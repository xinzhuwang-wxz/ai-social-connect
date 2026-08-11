"""七种受限消息。**没有一种构成同意。**

为什么是七种固定类型而不是自由对话，理由有三条，缺一不可（见 ADR 0004 末尾
与 `docs/03-技术架构.md` §8.10）：

1. **选择过载**：微软 Magentic Marketplace 的实证里，搜索上限从 3 放到 100，
   福利反而下降。谈得越多越好这件事没有证据支持。
2. **首提案偏差**：所有被测模型都严重偏向第一个提案，响应速度相对质量的优势
   达 10–30 倍。自由格式下赢的是回得快的代理，不是最合适的人。
3. **提示注入**：自由文本是攻击面。这里的做法是——**界面上那句话由结构化字段
   生成，自由文本另存一栏**，所以别人写进 `note` 的内容永远不会被读成系统的结论。

伦理上还有一条：挡住"两个 AI 越聊越熟，真人见面只剩嗯嗯哈哈"。

它们是 A2A `Message.parts` 里的结构化载荷，不是替代 A2A 的另一套协议。
"""

from __future__ import annotations

import abc
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar
from uuid import UUID

from a2a.types import Message, Role

# protobuf 自己不带类型存根，`types-protobuf` 不在依赖里——为了一个 JSON
# 编解码函数多装一个包不划算，这里就地忽略这一条。
from google.protobuf.json_format import (  # type: ignore[import-untyped]
    MessageToDict,
    ParseDict,
)

from cofield.domain.model.action_kind import AgentReplyPolicy

#: 自由文本的长度上限。它只是字段补充——一条能装下一整段说辞的 `note`
#: 就等于把受限协商偷偷改回自由对话。
MAX_NOTE_CHARS = 140


class MessageKind(StrEnum):
    """封闭集合。第八种在解析处就被拒绝，进不到这一层里面来。

    取值用协议里的驼峰原名，不翻译成我们自己的词——将来对接第三方个人代理时，
    线上跑的是这几个字符串。
    """

    CONSTRAINT_INTERSECTION = "ConstraintIntersection"
    EVIDENCE_CITATION = "EvidenceCitation"
    CONDITIONAL_RESPONSE = "ConditionalResponse"
    CONFLICT = "Conflict"
    PROPOSAL_REVISION = "ProposalRevision"
    DISCLOSURE_DENIED = "DisclosureDenied"
    CONSENT_REQUEST = "ConsentRequest"


class SpeakerMode(StrEnum):
    """代聊三档。用户自己选，可按会话切换。

    前两档发出的都**是本人**，所以在协议层是 `ROLE_USER`；只有第三档是
    `ROLE_AGENT`。是否向对方披露由 `agent_reply_policy` 决定，是可配置策略；
    但**如实记下来是不变量**——申诉时必须查得出这句话到底是谁说的。
    """

    SELF = "self"
    AI_DRAFTED = "ai_drafted"
    AI_SPOKE = "ai_spoke"


class HumanOnlyDecision(StrEnum):
    """只能由真人拍板的三件事。**这一条不可配置**（见 07 §4）。

    它们不是"敏感话题"的例子，是一份穷举表：AI 在任何档位下碰到这三件事
    都必须停下来把决定交回去。
    """

    JOINING = "joining"
    MEETING = "meeting"
    IDENTITY = "identity"


class Topic(StrEnum):
    """交集与冲突谈的是哪一维。用枚举而不是自由字符串，是为了让"谈了什么"可聚合。"""

    TIME = "time"
    PLACE = "place"
    ROLE = "role"


#: 内部字段名到用户词的唯一一处翻译。两边各自拼字符串迟早对不上。
FIELD_LABELS: dict[str, str] = {
    "skills": "他会做什么",
    "availability": "他哪些时间有空",
    "zone": "他常在哪个校区",
    "major": "他的专业",
    "self_intro": "他写的那段自我介绍",
    "contact": "他的联系方式",
    "identity": "更多关于他本人的事",
}

#: 常态化轻标识。**不弹窗、不打断**——关键在于它是常态：
#: 当所有人都知道 AI 可以帮忙接话，用 AI 就不再是丢人的事。
DISCLOSURE_LABEL = "帮他接的"


class UnsupportedMessageKind(ValueError):
    """第八种消息。协议边界上直接拒绝，不做"尽力理解"。"""


class RestrictedMessage(abc.ABC):
    """一条受限消息。

    子类只有七个，且 `MessageKind` 是封闭枚举——"没有一种构成同意"因此不是
    一句约定，而是这一层**根本没有表达同意的词**：这些类型里既没有
    accepted/declined 这样的取值，也没有任何方法能写承诺表。
    """

    kind: ClassVar[MessageKind]

    @abc.abstractmethod
    def fields(self) -> dict[str, Any]:
        """结构化载荷。进 `Message.parts[0].data`。"""

    @abc.abstractmethod
    def summary(self) -> str:
        """给人看的那一句。**只由结构化字段生成**，不掺自由文本。"""

    def hands_back(self) -> HumanOnlyDecision | None:
        """这条消息触及了哪件只能由真人拍板的事。七种里只有 `ConsentRequest` 有值。"""
        return None

    def sensitive(self) -> bool:
        """涉不涉及本人的事。`disclose_on_sensitive` 那一档按它判断。"""
        return False

    @property
    def note(self) -> str | None:
        """自由文本。只作字段补充，不进 `summary()`。"""
        return None


def _check_note(note: str | None) -> None:
    if note is not None and len(note) > MAX_NOTE_CHARS:
        raise ValueError(
            f"自由文本超过 {MAX_NOTE_CHARS} 字——它只是字段补充，不是另开一条对话"
        )


@dataclass(frozen=True, slots=True)
class ConstraintIntersection(RestrictedMessage):
    """报告时间、地点、角色等交集。"""

    kind: ClassVar[MessageKind] = MessageKind.CONSTRAINT_INTERSECTION

    topic: Topic
    shared: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.shared:
            raise ValueError("交集为空就不是交集，该发的是 Conflict")

    def fields(self) -> dict[str, Any]:
        return {"topic": self.topic.value, "shared": list(self.shared)}

    def summary(self) -> str:
        joined = "、".join(self.shared)
        if self.topic is Topic.TIME:
            return f"{joined}，几个人都有空。"
        if self.topic is Topic.PLACE:
            return f"{joined}，几个人都能去。"
        return f"{joined}，都有人能做。"


@dataclass(frozen=True, slots=True)
class EvidenceCitation(RestrictedMessage):
    """提供获准的经历证据摘要与来源。

    `facet_id` 指向本人**逐条勾选过**的那段经历——候选人控制自己的哪条经历
    允许被引用，所以引用必须指得着一个具体的授权项，不能是一句泛泛的"他有经验"。
    """

    kind: ClassVar[MessageKind] = MessageKind.EVIDENCE_CITATION

    facet_id: UUID
    claim: str
    source: str
    occurrences: int

    def fields(self) -> dict[str, Any]:
        return {
            "facet_id": str(self.facet_id),
            "claim": self.claim,
            "source": self.source,
            "occurrences": self.occurrences,
        }

    def summary(self) -> str:
        return f"{self.claim}，以前做过 {self.occurrences} 次，能看到{self.source}。"

    def sensitive(self) -> bool:
        # 引的是这个人过去做过什么，属于他本人的事。
        return True


@dataclass(frozen=True, slots=True)
class ConditionalResponse(RestrictedMessage):
    """"若满足 X，则可进入真人确认"。

    七种里最像接受的一条，也正因如此要说清楚：它到此为止。
    `applies_to` 记的是这个条件挂在哪一项上，让它能进差异清单被逐条查看。
    """

    kind: ClassVar[MessageKind] = MessageKind.CONDITIONAL_RESPONSE

    applies_to: str
    condition: str
    supplement: str | None = None

    def __post_init__(self) -> None:
        _check_note(self.supplement)
        if not self.condition.strip():
            raise ValueError("没有条件的条件响应等于一句空话")

    def fields(self) -> dict[str, Any]:
        return {
            "applies_to": self.applies_to,
            "condition": self.condition,
            "supplement": self.supplement,
        }

    def summary(self) -> str:
        return f"可以，但要{self.condition}。"

    @property
    def note(self) -> str | None:
        return self.supplement


@dataclass(frozen=True, slots=True)
class Conflict(RestrictedMessage):
    """指出不可行约束及受影响字段。"""

    kind: ClassVar[MessageKind] = MessageKind.CONFLICT

    topic: Topic
    detail: str
    affected: tuple[str, ...] = ()

    def fields(self) -> dict[str, Any]:
        return {
            "topic": self.topic.value,
            "detail": self.detail,
            "affected": list(self.affected),
        }

    def summary(self) -> str:
        return f"{self.detail}，这里对不上。"


@dataclass(frozen=True, slots=True)
class ProposalRevision(RestrictedMessage):
    """提议修改团队或条件。

    改了什么要单独存一栏：任一实质变更之后受影响的人要重新确认，
    而"改了哪里"如果只活在一段话里，界面就没法把它逐条列出来。
    """

    kind: ClassVar[MessageKind] = MessageKind.PROPOSAL_REVISION

    changes: tuple[str, ...]
    supplement: str | None = None

    def __post_init__(self) -> None:
        _check_note(self.supplement)
        if not self.changes:
            raise ValueError("没有改动的修改提议是一条噪音")

    def fields(self) -> dict[str, Any]:
        return {"changes": list(self.changes), "supplement": self.supplement}

    def summary(self) -> str:
        return f"有人想改一处：{'；'.join(self.changes)}。"

    @property
    def note(self) -> str | None:
        return self.supplement


@dataclass(frozen=True, slots=True)
class DisclosureDenied(RestrictedMessage):
    """拒绝披露某字段。

    它必须是一条**正经消息**而不是沉默：对方要知道这里问不出来，
    才不会反复来问；而不给理由是这条消息的设计，不是它的缺陷。
    """

    kind: ClassVar[MessageKind] = MessageKind.DISCLOSURE_DENIED

    field_name: str

    def fields(self) -> dict[str, Any]:
        return {"field_name": self.field_name}

    def summary(self) -> str:
        label = FIELD_LABELS.get(self.field_name, "有些事")
        return f"有人暂时不想让别人看到{label}。"

    def sensitive(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class ConsentRequest(RestrictedMessage):
    """请求对应真人处理特定决定。

    **这是七种里唯一会改变任务状态的消息**，而它改成的是非终止的中断态——
    "交还给真人"。它请求的是人来决定，它本身什么都没决定。
    """

    kind: ClassVar[MessageKind] = MessageKind.CONSENT_REQUEST

    decision: HumanOnlyDecision

    def fields(self) -> dict[str, Any]:
        return {"decision": self.decision.value}

    def summary(self) -> str:
        if self.decision is HumanOnlyDecision.JOINING:
            return "要不要加入，只能你自己定。"
        if self.decision is HumanOnlyDecision.MEETING:
            return "要不要见面，只能你自己定。"
        return "要不要让对方多知道一些关于你的事，只能你自己定。"

    def hands_back(self) -> HumanOnlyDecision:
        return self.decision

    def sensitive(self) -> bool:
        return True


# --- 与 A2A 的编解码 --------------------------------------------------------


def _decode_constraint(data: dict[str, Any]) -> RestrictedMessage:
    return ConstraintIntersection(
        topic=Topic(data["topic"]), shared=tuple(str(s) for s in data["shared"])
    )


def _decode_evidence(data: dict[str, Any]) -> RestrictedMessage:
    return EvidenceCitation(
        facet_id=UUID(str(data["facet_id"])),
        claim=str(data["claim"]),
        source=str(data["source"]),
        occurrences=int(data["occurrences"]),
    )


def _decode_conditional(data: dict[str, Any]) -> RestrictedMessage:
    return ConditionalResponse(
        applies_to=str(data["applies_to"]),
        condition=str(data["condition"]),
        supplement=_optional_text(data.get("supplement")),
    )


def _decode_conflict(data: dict[str, Any]) -> RestrictedMessage:
    return Conflict(
        topic=Topic(data["topic"]),
        detail=str(data["detail"]),
        affected=tuple(str(a) for a in data.get("affected", ())),
    )


def _decode_revision(data: dict[str, Any]) -> RestrictedMessage:
    return ProposalRevision(
        changes=tuple(str(c) for c in data["changes"]),
        supplement=_optional_text(data.get("supplement")),
    )


def _decode_denied(data: dict[str, Any]) -> RestrictedMessage:
    return DisclosureDenied(field_name=str(data["field_name"]))


def _decode_consent(data: dict[str, Any]) -> RestrictedMessage:
    return ConsentRequest(decision=HumanOnlyDecision(data["decision"]))


def _optional_text(value: Any) -> str | None:
    return None if value is None else str(value)


_DECODERS: dict[MessageKind, Callable[[dict[str, Any]], RestrictedMessage]] = {
    MessageKind.CONSTRAINT_INTERSECTION: _decode_constraint,
    MessageKind.EVIDENCE_CITATION: _decode_evidence,
    MessageKind.CONDITIONAL_RESPONSE: _decode_conditional,
    MessageKind.CONFLICT: _decode_conflict,
    MessageKind.PROPOSAL_REVISION: _decode_revision,
    MessageKind.DISCLOSURE_DENIED: _decode_denied,
    MessageKind.CONSENT_REQUEST: _decode_consent,
}

# 少写一个解码器，那一种就会在运行时静默失败；多写一个，封闭集合就破了。
# 这个断言在导入时跑，让两边只能同时改。
if set(_DECODERS) != set(MessageKind):
    raise RuntimeError("受限消息类型与解码器对不上——七种是封闭集合")


def decode_payload(kind: MessageKind, data: Mapping[str, Any]) -> RestrictedMessage:
    """从结构化载荷还原一条受限消息。

    仓储读回一行时走这里，而不是自己认字段——认字段的地方多一处，
    "七种是封闭集合"就多一个能被绕开的入口。
    """
    return _DECODERS[kind](dict(data))


@dataclass(frozen=True, slots=True)
class Utterance:
    """一条消息说出去时的完整事实。

    `mode` 与 `author_id` 一起回答"这句话到底是谁说的"。协议层的 `role` 由
    `mode` 推出来，不另存——`ROLE_USER` / `ROLE_AGENT` 在 A2A 里就有位置。
    """

    payload: RestrictedMessage
    author_id: UUID
    mode: SpeakerMode
    said_at: datetime

    @property
    def role(self) -> Role:
        return Role.ROLE_AGENT if self.mode is SpeakerMode.AI_SPOKE else Role.ROLE_USER


def to_a2a(
    utterance: Utterance, *, message_id: UUID, task_id: str, context_id: str
) -> Message:
    """打包成 A2A 的 `Message`。

    结构化载荷进 `parts[0].data`，"谁说的"进 `metadata`——两者都是协议里现成的
    位置。自由文本跟着载荷走，不单独开一个 text part：单开一个 part 之后，
    "这条消息在说什么"就有了两个来源。
    """
    raw: dict[str, Any] = {
        "messageId": str(message_id),
        "contextId": context_id,
        "taskId": task_id,
        "role": Role.Name(utterance.role),
        "parts": [{"data": {"kind": utterance.payload.kind.value, **utterance.payload.fields()}}],
        "metadata": {
            "author_id": str(utterance.author_id),
            "speaker_mode": utterance.mode.value,
            "said_at": utterance.said_at.isoformat(),
        },
    }
    message: Message = ParseDict(raw, Message())
    return message


def from_a2a(message: Message) -> Utterance:
    """还原一条消息。**不认识的一律拒绝，不做"尽力理解"。**

    这是"代理间只出现七种消息"的执行点：既拦第八种 `kind`，也拦只有自由文本、
    没有结构化载荷的消息——后者正是提示注入最想走的那条路。
    """
    if len(message.parts) != 1:
        raise UnsupportedMessageKind(
            f"一条受限消息只带一个结构化载荷，收到 {len(message.parts)} 个"
        )
    part = message.parts[0]
    if part.WhichOneof("content") != "data":
        raise UnsupportedMessageKind("只有自由文本的消息不是受限消息")

    decoded: Any = MessageToDict(part.data)
    if not isinstance(decoded, dict) or "kind" not in decoded:
        raise UnsupportedMessageKind("载荷没有声明自己是七种里的哪一种")
    data: dict[str, Any] = {str(k): v for k, v in decoded.items()}
    try:
        kind = MessageKind(data["kind"])
    except ValueError as exc:
        raise UnsupportedMessageKind(f"{data['kind']!r} 不在七种受限消息里") from exc

    meta = MessageToDict(message.metadata)
    return Utterance(
        payload=_DECODERS[kind](data),
        author_id=UUID(str(meta["author_id"])),
        mode=SpeakerMode(meta["speaker_mode"]),
        said_at=datetime.fromisoformat(str(meta["said_at"])),
    )


def disclosed(policy: AgentReplyPolicy, utterance: Utterance) -> bool:
    """这句话要不要挂上"帮他接的"这个标。

    只有第三档才有东西可披露——前两档发出的是本人，没有"其实是 AI 说的"
    这件事需要告诉对方。三种策略都得能跑：这是产品与合规决定，不焊死在领域层。
    """
    if utterance.mode is not SpeakerMode.AI_SPOKE:
        return False
    if policy is AgentReplyPolicy.ALWAYS_DISCLOSE:
        return True
    if policy is AgentReplyPolicy.DISCLOSE_ON_SENSITIVE:
        return utterance.payload.sensitive()
    return False
