"""回流：已确认的记忆改变下一次成局。

**这是 M4 的判据，也是整个产品的论点。** 前面十三片都在铺路：如果同一条
需求在有已确认切面和没有时得到的成局证明一模一样，那么"真实行动沉淀为
可控、可追溯、可撤销的关系记忆"就只是一句宣传语——闭环看起来合上了，
实际上没有。所以这一层存在的全部理由，是让那个差别**可被测出来**。

## 差别长什么样：多出来的是可核验，不是分数

有历史的人拿到的是**几行多出来的、指得回具体事件与素材的句子**：

    你们上次一起完成过《檐下》。
    这是你们第 2 次一起做事。
    周雨剪过一支 60 秒短片。

没有一个数字被改动。`stability` 原样带出，`satisfied` 里原有的每一行
一条不少也不重排——历史只做加法。这条不是修辞：冷启动公平要求零历史
用户的首次成局时间与老用户没有系统性差距，老用户的优势必须体现为
「更可核验」而不是「排得更前」。如果历史能改动求解结果或删掉原有依据，
那就成了一个隐性的社会信用分。

## 关系强度不是一个字段

「第 2 次一起做事」是 `co_completed()` 从 `event_members` 这条超边上数出来的，
不是某处维护的熟悉度。不变量 7：关系图谱是共同事件的可重建投影。

## 为什么这一层不修改 `matching.proof`

`proof.build` 是纯转换：不碰数据库、不碰 LLM。历史要从库里读，塞进去
它就不纯了，"换持久化不触及领域测试"也就不成立。所以这里在它外面
包一层——它照常产出那份证明，这一层往 `satisfied` 后面接几行。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from cofield.adapters.persistence.memory import (
    CitedFacet,
    MemoryRepository,
    TogetherBefore,
)
from cofield.domain.model.consent import MatchEnvelope
from cofield.matching import proof as proof_module
from cofield.matching.contracts import (
    CandidateGroup,
    EvidenceSource,
    FormationProof,
    ProofLine,
    Requirement,
    StabilityVerdict,
)


@dataclass(frozen=True, slots=True)
class SharedHistory:
    """这次成局能引用的全部历史。

    两块合起来才是"你们之前一起做过什么"：`together` 是这批人共同的，
    `facets` 是某个人自己的。分开是因为它们的确认规则不同——
    共同经历由那件事本身作证，个人切面要本人逐项点头。
    """

    facets: tuple[CitedFacet, ...] = ()
    together: tuple[TogetherBefore, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.facets and not self.together


#: 零历史。一个人第一次用这个产品时手上就是这个——**不是缺失，是起点**。
#: 它是不可变值，所以可以当默认参数用，也不会有人不小心往里加东西。
NO_HISTORY = SharedHistory()


def permitted_facet_ids(
    envelopes: Sequence[MatchEnvelope], *, now: datetime
) -> frozenset[UUID]:
    """这次允许引用哪几条切面。

    只取**还生效**的信封里的 `cited_facet_ids`：信封过期或被撤销时
    `is_usable` 为假，那份授权里的切面立刻不再可引用——「已授权用于匹配、
    且未过期」这句话的两个条件在这里合成一个判断。

    没有信封、或信封里一条都没勾，返回空集。空集在 `citable()` 那边
    等于什么都读不到——**默认拒绝**。
    """
    permitted: set[UUID] = set()
    for envelope in envelopes:
        if envelope.is_usable(now=now):
            permitted.update(envelope.cited_facet_ids)
    return frozenset(permitted)


def recall(
    repo: MemoryRepository,
    *,
    member_ids: Sequence[UUID],
    permitted: frozenset[UUID],
) -> SharedHistory:
    """按权限检索这批人身上还能被说出口的东西。

    **每次都重新读权威行。** 没有缓存、没有快照、没有把切面文本抄进别处的
    派生表——所以一次撤销之后紧接着的这一次调用就已经读不到它了，
    不需要等任何清理任务。这就是"撤销即时生效"的全部机制。
    """
    return SharedHistory(
        facets=tuple(repo.citable(member_ids, permitted=permitted)),
        together=tuple(repo.co_completed(member_ids)),
    )


def history_lines(
    history: SharedHistory, *, member_ids: frozenset[UUID]
) -> tuple[ProofLine, ...]:
    """把历史写成几行能逐条追溯的句子。

    `member_ids` 再过滤一道：`history` 是调用方传进来的，而一条不属于
    这个组里任何人的切面绝不该出现在这份证明里。默认拒绝要在每一道门上
    都成立，不是只在第一道门上成立。
    """
    lines: list[ProofLine] = []

    if history.together:
        latest = history.together[0]
        lines.append(
            ProofLine(
                source=EvidenceSource.APPROVED_FACET,
                text=f"你们上次一起完成过《{latest.title}》。",
                refers_to=(f"event:{latest.event_id}",),
            )
        )
        # 用阿拉伯数字：这是一个可以被数出来的次数，不是一个评价。
        # 「第 2 次」读起来像事实，「熟悉度 0.7」读起来像判决。
        lines.append(
            ProofLine(
                source=EvidenceSource.APPROVED_FACET,
                text=f"这是你们第 {len(history.together) + 1} 次一起做事。",
                refers_to=tuple(f"event:{t.event_id}" for t in history.together),
            )
        )

    for facet in history.facets:
        if facet.principal_id not in member_ids:
            continue
        # 名字由这一层加上，不由切面文本自带——说不说名字是这一次的
        # 披露判断，不该在抽切面那一刻就被写死（见 echo.FACET_INSTRUCTION）。
        refers_to = [f"principal:{facet.principal_id}", f"facet:{facet.facet_id}"]
        if facet.event_id is not None:
            refers_to.append(f"event:{facet.event_id}")
        refers_to.extend(f"evidence:{e}" for e in facet.evidence_ids)
        lines.append(
            ProofLine(
                source=EvidenceSource.APPROVED_FACET,
                text=f"{facet.display_name}{facet.text}",
                refers_to=tuple(refers_to),
            )
        )

    return tuple(lines)


def build(
    group: CandidateGroup,
    requirement: Requirement,
    verdict: StabilityVerdict,
    *,
    now: datetime,
    visible_fields: frozenset[str],
    history: SharedHistory = NO_HISTORY,
) -> FormationProof:
    """成局证明，接上这批人已确认的历史。

    `history` 为空时**逐字等于** `matching.proof.build` 的输出——零历史的人
    不因为缺历史而少任何一条依据，只是少了那几行"上次一起做过什么"。

    历史只往 `satisfied` 后面接行，不改 `stability`、不动 `expires_at`、
    不删任何已有的行。差别因此是可枚举的：两份证明的差集恰好就是
    `history_lines` 返回的那几条。
    """
    base = proof_module.build(
        group, requirement, verdict, now=now, visible_fields=visible_fields
    )
    lines = history_lines(history, member_ids=group.member_ids)
    if not lines:
        return base

    # notes 是给申诉、导出与运营看的那一面，用领域词汇是合法的（07 §2.1）。
    # 记下引用了哪几条，是为了让"这份证明当时凭什么这么说"在切面被撤销之后
    # 仍然查得出来——撤销阻止的是新的使用，不是抹掉已经发生过的事。
    cited = [f.facet_id for f in history.facets if f.principal_id in group.member_ids]
    notes = (
        *base.notes,
        f"引用了 {len(cited)} 条已确认的记忆切面：{[str(i) for i in cited]}",
        f"共同完成过的事件数：{len(history.together)}",
    )
    return replace(base, satisfied=(*base.satisfied, *lines), notes=notes)
