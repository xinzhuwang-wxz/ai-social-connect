"""一次受限协商。状态机是 A2A 的 Task 生命周期，不是我们自研的（见 ADR 0004）。

复用它的**全部理由**是那两个非终止的中断态：

| 状态 | 语义 |
|---|---|
| `TASK_STATE_INPUT_REQUIRED` | 需要更多输入才能继续。暂停但不结束 |
| `TASK_STATE_AUTH_REQUIRED` | 需要凭证才能继续。同样是暂停不结束 |

"交还给真人"是协议的一等状态，不是我们的发明。自研一个语义相同的状态机，
既是重复造轮子，也会让将来接第三方个人代理时多一层翻译。

**这一层负责"怎么谈"，不负责"谈的结果算不算数"。** 它谈完之后产出的是一份
结构化差异清单；事件、关系边和行动承诺一律不在这里发生——那是确认门的事。
这不是靠自觉：这一层的类型里没有"接受""拒绝"这样的取值，仓储也只对两张
协商表发语句。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from a2a.server.agent_execution.active_task import (
    INTERRUPTED_TASK_STATES,
    TERMINAL_TASK_STATES,
)
from a2a.types import Role, Task, TaskState

# protobuf 不带类型存根，见 `messages.py` 里同一处注释。
from google.protobuf.json_format import MessageToDict  # type: ignore[import-untyped]

from cofield.domain.model.action_kind import AgentReplyPolicy
from cofield.negotiation.messages import (
    EvidenceCitation,
    HumanOnlyDecision,
    MessageKind,
    RestrictedMessage,
    SpeakerMode,
    Utterance,
    disclosed,
    from_a2a,
    to_a2a,
)

#: 每次协商的轮次上限。协议安全基线要求每个 Task 有最大轮次（03 §9.6），
#: 而 N×N 规模下开放式对话的 token 消耗会直接爆炸——受限协商谈不完十几轮，
#: 谈不完就该把问题交给人，不是接着谈。
MAX_ROUNDS = 12


class NegotiationClosed(RuntimeError):
    """任务已进终止态。终止之后还能补一句，"谈完了"就没有意义。"""


class HandedBackToHuman(RuntimeError):
    """已经交还给真人。在人回来之前，代理不能替他往下走。"""


class TooManyRounds(RuntimeError):
    """轮次用尽。"""


class NotCitable(RuntimeError):
    """引用了本人没勾选过的那段经历。"""


class Standing(StrEnum):
    """对方在这一次里的处境。

    **这里没有"接受"也没有"拒绝"。** 超时的外部代理标成 `UNKNOWN`——
    把沉默读成拒绝，等于让一次网络抖动替一个人做了决定，而这个人对此
    毫不知情。未知就是未知，它的下一步是问人，不是替人下结论。
    """

    WAITING = "waiting"
    RESPONDING = "responding"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ReciprocalView:
    """被邀请的一侧看到的那一屏：**这次我会得到什么**。

    不是"你被选中了"。单向推荐会让接收方觉得自己是被挑的商品，而互惠推荐的
    成功必须以多方接受为条件——单边相关度会系统性高估真实匹配（05 §研究依据）。

    `gets` 为空就构造不出来：说不出对方能得到什么的邀请，不该被发出去。
    这条在构造函数里拦，而不是在界面上提醒。
    """

    inviter_name: str
    inviter_verified: bool
    time_cost: str
    gets: tuple[str, ...]
    gives: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.gets:
            raise ValueError("说不出对方这次能得到什么，就不该发出这次邀请")
        if not self.time_cost.strip():
            raise ValueError("要花多少时间说不清楚，接收方没法判断值不值得")

    def lines(self) -> tuple[str, ...]:
        """给人看的几句。得到写在最前面——这一屏的第一句决定它是邀请还是通知。"""
        first = f"这次你会得到：{'、'.join(self.gets)}"
        cost = f"你要花的是：{self.time_cost}"
        if self.gives:
            cost += f"，还有{'、'.join(self.gives)}"
        who = (
            f"找你的是{self.inviter_name}，学校核实过他的身份。"
            if self.inviter_verified
            else f"找你的是{self.inviter_name}，学校还没核实过他的身份。"
        )
        return (first, cost, who)


@dataclass(frozen=True, slots=True)
class Difference:
    """结构化差异清单里的一条。

    协商结果是一份可逐条查看的清单，不是一段供人观赏的代理对话——所以每条
    都带上"谁说的""是不是 AI 接的""要不要挂标识""哪件事必须你自己定"。
    自由文本单独一栏：界面上那句 `text` 只由结构化字段生成，别人写进 `note`
    的内容永远不会被读成系统的结论。
    """

    kind: MessageKind
    text: str
    author_id: UUID
    by_agent: bool
    show_agent_label: bool
    note: str | None = None
    needs_human: HumanOnlyDecision | None = None


class NegotiationSession:
    """驱动一个 A2A Task 的受限协商。

    `open()` 必须给出互惠视角：一次谈判从"对方能得到什么"开始，而不是从
    "我们挑中了你"开始。视角本身不入库——它随提案版本变化，存快照会让人
    看到一份已经过期的"你会得到什么"。
    """

    def __init__(
        self,
        task: Task,
        *,
        view: ReciprocalView,
        policy: AgentReplyPolicy,
        counterparts: tuple[UUID, ...] = (),
        citable: frozenset[UUID] = frozenset(),
    ) -> None:
        self._task = task
        self._view = view
        self._policy = policy
        self._citable = citable
        self._standings: dict[UUID, Standing] = dict.fromkeys(counterparts, Standing.WAITING)
        for utterance in self._utterances():
            if utterance.author_id in self._standings:
                self._standings[utterance.author_id] = Standing.RESPONDING

    @classmethod
    def open(
        cls,
        *,
        proposal_id: UUID,
        view: ReciprocalView,
        policy: AgentReplyPolicy,
        now: datetime,
        counterparts: tuple[UUID, ...] = (),
        citable: frozenset[UUID] = frozenset(),
        task_id: str | None = None,
        context_id: str | None = None,
    ) -> NegotiationSession:
        """开一次协商。

        `task_id` 与 `context_id` 用文本而不是 UUID：协议里它们是字符串，
        将来对接外部代理时不该由我们规定它们长什么样。同一次成局的多轮协商
        共享 `context_id`。
        """
        task = Task(id=task_id or str(uuid4()), context_id=context_id or str(uuid4()))
        task.metadata.update({"proposal_id": str(proposal_id)})
        task.status.state = TaskState.TASK_STATE_SUBMITTED
        task.status.timestamp.FromDatetime(now)
        return cls(task, view=view, policy=policy, counterparts=counterparts, citable=citable)

    # --- 只读 ---------------------------------------------------------------

    @property
    def task(self) -> Task:
        """底下那个 A2A Task。仓储存的就是它，不是我们翻译过的副本。"""
        return self._task

    @property
    def task_id(self) -> str:
        return self._task.id

    @property
    def context_id(self) -> str:
        return self._task.context_id

    @property
    def proposal_id(self) -> UUID:
        meta: dict[str, Any] = MessageToDict(self._task.metadata)
        return UUID(str(meta["proposal_id"]))

    @property
    def state(self) -> TaskState:
        return self._task.status.state

    @property
    def invitation(self) -> ReciprocalView:
        return self._view

    @property
    def rounds(self) -> int:
        return len(self._task.history)

    def suspended(self) -> bool:
        """是不是停在"等真人"上。**中断不是结束**——这正是复用 A2A 的理由。"""
        return self._task.status.state in INTERRUPTED_TASK_STATES

    def finished(self) -> bool:
        return self._task.status.state in TERMINAL_TASK_STATES

    def standings(self) -> Mapping[UUID, Standing]:
        return dict(self._standings)

    def differences(self) -> tuple[Difference, ...]:
        """协商产出。界面上逐条查看的就是这个。"""
        return tuple(self._difference(u) for u in self._utterances())

    def pending_decision(self) -> HumanOnlyDecision | None:
        """还等着真人拍板的那件事。没停在中断态就是 `None`。"""
        if not self.suspended():
            return None
        for utterance in reversed(self._utterances()):
            handed = utterance.payload.hands_back()
            if handed is not None:
                return handed
        return None

    # --- 说话 ---------------------------------------------------------------

    def say(
        self,
        payload: RestrictedMessage,
        *,
        author_id: UUID,
        mode: SpeakerMode,
        now: datetime,
    ) -> Difference:
        """记下一条受限消息，并按它的性质推进 Task 状态。

        三道闸，顺序是有讲究的：先看任务还活着吗、再看还能不能谈、最后才看
        这条消息本身允不允许。把"引用没获准的经历"放在最后，是因为它是**这条
        消息**的问题，不是这次协商的问题。
        """
        if self.finished():
            raise NegotiationClosed(f"任务已是 {TaskState.Name(self.state)}，不再接受新消息")
        utterance = Utterance(payload=payload, author_id=author_id, mode=mode, said_at=now)
        if self.suspended() and utterance.role == Role.ROLE_AGENT:
            # 交还给真人之后只认 ROLE_USER。前两档发出的都是本人，可以继续；
            # 第三档不能替人拍板——这一条不可配置。
            raise HandedBackToHuman(
                f"已交还给真人（{TaskState.Name(self.state)}），AI 代答不能替他往下走"
            )
        if self.rounds >= MAX_ROUNDS:
            raise TooManyRounds(f"这次已经谈了 {self.rounds} 轮，该把问题交给人")
        if isinstance(payload, EvidenceCitation) and payload.facet_id not in self._citable:
            raise NotCitable("这段经历本人没有勾选允许被引用")

        message = to_a2a(
            utterance,
            message_id=uuid4(),
            task_id=self._task.id,
            context_id=self._task.context_id,
        )
        self._task.history.append(message)
        if author_id in self._standings:
            self._standings[author_id] = Standing.RESPONDING
        self._advance(payload, now=now)
        return self._difference(utterance)

    def note_silence(self, counterpart_id: UUID, *, now: datetime) -> None:
        """外部代理超时或不可达。

        标成**未知**，并把这次交还给真人。不标成拒绝：一次超时不是一个人的决定，
        而一旦写成拒绝，后面所有基于它的重解都建立在一个没人做过的决定上。
        """
        if self.finished():
            raise NegotiationClosed("任务已终止，不再改动谁的处境")
        self._standings[counterpart_id] = Standing.UNKNOWN
        self._set_state(TaskState.TASK_STATE_INPUT_REQUIRED, now=now)

    def close(self, *, now: datetime) -> None:
        """谈完了。

        **这不等于任何人答应了什么。** `COMPLETED` 在这里的意思只有一个：
        差异清单已经齐了，可以交给确认门。要求最后一句出自 `ROLE_USER`，
        是因为一次协商不该由 AI 收尾——收尾的那句话必须是人的。
        """
        if self.finished():
            raise NegotiationClosed("已经结束过一次")
        if self.suspended():
            raise HandedBackToHuman("还有事等着真人处理，不能就这么收尾")
        if not self._task.history or self._task.history[-1].role != Role.ROLE_USER:
            raise HandedBackToHuman("最后一句得是本人说的")
        self._set_state(TaskState.TASK_STATE_COMPLETED, now=now)

    # --- 内部 ---------------------------------------------------------------

    def _advance(self, payload: RestrictedMessage, *, now: datetime) -> None:
        handed = payload.hands_back()
        if handed is HumanOnlyDecision.IDENTITY:
            # 让对方多知道一些关于自己的事，等于当场扩大一次授权范围——
            # 协议里"需要凭证才能继续"说的正是这件事。
            self._set_state(TaskState.TASK_STATE_AUTH_REQUIRED, now=now)
        elif handed is not None:
            self._set_state(TaskState.TASK_STATE_INPUT_REQUIRED, now=now)
        else:
            self._set_state(TaskState.TASK_STATE_WORKING, now=now)

    def _set_state(self, state: TaskState, *, now: datetime) -> None:
        self._task.status.state = state
        self._task.status.timestamp.FromDatetime(now)

    def _utterances(self) -> tuple[Utterance, ...]:
        return tuple(from_a2a(m) for m in self._task.history)

    def _difference(self, utterance: Utterance) -> Difference:
        return Difference(
            kind=utterance.payload.kind,
            text=utterance.payload.summary(),
            author_id=utterance.author_id,
            by_agent=utterance.mode is SpeakerMode.AI_SPOKE,
            show_agent_label=disclosed(self._policy, utterance),
            note=utterance.payload.note,
            needs_human=utterance.payload.hands_back(),
        )
