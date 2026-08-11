"""把求解结果写成一个人能逐条追溯的成局证明。

纯转换：不碰数据库、不碰 LLM、不重算任何约束。输入是 `contracts` 里的
结构化对象，输出还是结构化对象——界面上看到的是它的**转写**，不是它的替代品。

四条不能动的判断：

**不给总分。** `CandidateGroup.score` 和每个目标项的 `raw`/`weighted` 在这一层
一律不外发。用户要看的是「周雨补上了缺的剪辑」，不是「匹配度 87%」。一个总分
无法被检查，也无法被反驳；逐条依据可以。

**结论可以说，别人的切面内容要获准才能说。** 「你们凑得出连着的两段都有空的
时间」是求解器的结论，永远说得出口；「周四下午」是别人日程里的内容，只有
`visible_fields` 里有 `availability` 时才写得出来。降级的是具体，不是诚实。

**求解器的措辞不上界面。** `ObjectiveContribution.explanation` 是工程语言，
原样搬到屏幕上就是术语泄漏。原文进 `notes`（申诉与审计读那里，用领域词汇
是合法的），用户看到的句子由这一层自己写。

**`for_humans` 不是缺失项。** 合不合得来、那天到底能不能来、署名怎么算——
这些即使有数据也不该由系统替人定。它们是刻意留下的，所以永远非空。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from cofield.domain.model.consent import GRANTABLE_FIELDS
from cofield.matching.contracts import (
    WEEK_SLOTS,
    CandidateGroup,
    EvidenceSource,
    FormationProof,
    Member,
    ObjectiveKind,
    ProofLine,
    Requirement,
    StabilityVerdict,
)

#: 一份证明能活多久。72 小时不是拍脑袋：证明里引用的内容由匹配信封授权露出，
#: 而信封默认 72 小时失效——**证明不能比授权它的那份授权活得久**。
#: 真正的失效时刻还要和 `Requirement.deadline` 取较早者：截止之后再说「能行动」
#: 已经没有意义，而人在这段时间里很可能已经答应了别的事。
PROOF_TTL = timedelta(hours=72)

#: 离截止多近算「快来不及了」。取两天是因为提案要留出对方看到、回话、
#: 再各自安排的余量；不到两天时这三步很可能排不下。
NEAR_DEADLINE = timedelta(days=2)

#: 证明可能引用到的 `Member` 属性 ↔ 匹配信封里的授权字段名。
#: 两套词表**不重合**，所以调用方从 `MatchEnvelope.visible_fields()` 拿到的集合
#: 必须先用 `attributes_visible_under` 翻译，再传进 `build`。
GRANT_NAMES: Mapping[str, str] = {
    "skills": "offers",
    "availability": "time_window",
    "zone": "location_scope",
    "major": "major",
    "confirmed_events": "confirmed_events",
    "active_commitments": "active_commitments",
}

#: 白名单里**没有**对应项的属性：在有人把它们显式加进 `GRANTABLE_FIELDS`
#: 并说明用途之前，它们永远引用不到。列出来是为了让「引用不到」成为一个
#: 被记录的事实，而不是某天加字段时才发现的意外——默认拒绝，不是忘了排除。
UNGRANTABLE: frozenset[str] = frozenset(
    attribute for attribute, name in GRANT_NAMES.items() if name not in GRANTABLE_FIELDS
)

# 名字（`display_name`）不在逐项授权范围内：同意被放进一个小队，本身就包含了
# 同意在这份证明里被指名，否则「为什么是这几个人」根本无法呈现。
# 需要遮的是这个人的**切面内容**，不是他叫什么。

_DAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
_PARTS = ("上午", "下午", "晚上")
# 7 天 × 3 段 = 21，与 `WEEK_SLOTS` 同源。

_COUNT = ("零", "一", "两", "三", "四", "五", "六", "七", "八", "九", "十")


def attributes_visible_under(granted: frozenset[str]) -> frozenset[str]:
    """把匹配信封给出的字段名，翻成这一层引用的属性名。

    信封说的是「offers 可以给候选看」，证明问的是「能不能说周雨会剪辑」。
    中间这一次翻译必须存在且只有一处，否则两边各自拼字符串迟早对不上。
    """
    return frozenset(
        attribute for attribute, name in GRANT_NAMES.items() if name in granted
    )


def build(
    group: CandidateGroup,
    requirement: Requirement,
    verdict: StabilityVerdict,
    *,
    now: datetime,
    visible_fields: frozenset[str],
) -> FormationProof:
    """把一个候选组写成成局证明。

    `visible_fields` 是**对方已授权露出**的属性名集合（见
    `attributes_visible_under`）。传空集就等于什么都没获准：证明仍然成立，
    但只剩下求解器的结论，一句别人的切面内容都不会出现。
    """
    scene = _Scene(
        group=group,
        requirement=requirement,
        verdict=verdict,
        now=now,
        visible=visible_fields,
    )
    withheld = _withheld(scene)
    conflicts = _conflicts(scene)

    return FormationProof(
        satisfied=(
            *_roles(scene),
            *_time(scene),
            *_place(scene),
            *_slack(scene),
            *_cross_major(scene),
            *_stable(scene),
        ),
        for_humans=tuple(_for_humans(scene, withheld=withheld)),
        uncertainties=(*conflicts, *_doubts(scene)),
        # 稳定性如实带上。没通过的分区不该被提交为提案，但那是调用方的决定，
        # 不是靠在这里把结论吞掉来实现的。
        stability=verdict,
        expires_at=min(requirement.deadline, now + PROOF_TTL),
        generated_at=now,
        notes=_notes(scene, withheld=withheld),
    )


# --- 场景 -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Scene:
    """一次转写要用到的全部输入。避免每个私有函数都重复接五个参数。"""

    group: CandidateGroup
    requirement: Requirement
    verdict: StabilityVerdict
    now: datetime
    visible: frozenset[str]

    def may_cite(self, attribute: str) -> bool:
        return attribute in self.visible

    def member(self, principal_id: UUID) -> Member | None:
        for candidate in self.group.members:
            if candidate.principal_id == principal_id:
                return candidate
        return None

    def objective(self, kind: ObjectiveKind) -> bool:
        return any(c.kind is kind for c in self.group.contributions)

    @property
    def head_count(self) -> str:
        return _count(len(self.group.members))

    @property
    def everyone(self) -> tuple[str, ...]:
        return tuple(_who(m) for m in self.group.members)


def _who(member: Member) -> str:
    return f"principal:{member.principal_id}"


def _count(number: int) -> str:
    """写给人看的量词。「三个人」不写成「3 个人」。"""
    return _COUNT[number] if 0 <= number <= 10 else str(number)


def _slot_name(index: int) -> str:
    return f"{_DAYS[index // len(_PARTS)]}{_PARTS[index % len(_PARTS)]}"


def _valid_slots(scene: _Scene) -> tuple[int, ...]:
    return tuple(s for s in scene.group.common_slots if 0 <= s < WEEK_SLOTS)


# --- 已满足：为什么是这几个人、为什么是现在 ---------------------------------


def _roles(scene: _Scene) -> list[ProofLine]:
    """每个缺口由谁补。这是「为什么是这几个人」最直接的答案。

    说不出「谁」的时候（对方没让你看他会什么）也要说出「补上了」——
    被满足的是一条硬约束，这个结论属于求解器，不属于任何人的切面。
    """
    named: list[ProofLine] = []
    anonymous: list[str] = []
    extra = sorted(set(scene.group.role_assignment) - set(scene.requirement.needs))

    for need in (*scene.requirement.needs, *extra):
        holder_id = scene.group.role_assignment.get(need)
        if holder_id is None:
            continue  # 没人认领——不在「已满足」里假装满足，交给 _conflicts
        holder = scene.member(holder_id)
        if holder is None:
            continue  # 指到组外的人，同样交给 _conflicts
        if scene.may_cite("skills"):
            named.append(
                ProofLine(
                    source=EvidenceSource.SOLVER_CONSTRAINT,
                    text=f"{holder.display_name}补上了缺的{need}。",
                    refers_to=(_who(holder), f"need:{need}"),
                )
            )
        else:
            anonymous.append(need)

    if anonymous:
        named.append(
            ProofLine(
                source=EvidenceSource.SOLVER_CONSTRAINT,
                text=f"缺的{'、'.join(anonymous)}都有人补上了。",
                refers_to=tuple(f"need:{n}" for n in anonymous),
            )
        )
    return named


def _time(scene: _Scene) -> list[ProofLine]:
    """为什么是现在。

    `common_slots` 是连续段的**起点**，段长由 `contiguous_slots` 决定，
    所以 `refers_to` 指起点就够——指到段内每一格反而会指出输入里没有的东西。
    """
    slots = _valid_slots(scene)
    if not slots:
        return []  # 根本没有都空着的时间，那是冲突，不是依据

    run = max(1, scene.requirement.contiguous_slots)
    if not scene.may_cite("availability"):
        return [
            ProofLine(
                source=EvidenceSource.SOLVER_CONSTRAINT,
                text=f"你们{scene.head_count}个凑得出连着的{_count(run)}段都有空的时间。",
                refers_to=scene.everyone,
            )
        ]

    start = min(slots)
    span = [_slot_name(i) for i in range(start, min(start + run, WEEK_SLOTS))]
    text = f"{'、'.join(span)}，你们{scene.head_count}个都空着。"
    if len(slots) > 1:
        text += f"另外还有{_count(len(slots) - 1)}段这样的时间。"
    return [
        ProofLine(
            source=EvidenceSource.SOLVER_CONSTRAINT,
            text=text,
            refers_to=(f"slot:{start}",),
        )
    ]


def _place(scene: _Scene) -> list[ProofLine]:
    zone = scene.requirement.zone
    if not zone or not scene.may_cite("zone"):
        return []
    if any(m.zone != zone for m in scene.group.members):
        return []  # 有人对不上或者没写，交给 _conflicts / _doubts
    return [
        ProofLine(
            source=EvidenceSource.SOLVER_CONSTRAINT,
            text=f"你们都在{zone}。",
            refers_to=(*scene.everyone, f"zone:{zone}"),
        )
    ]


def _slack(scene: _Scene) -> list[ProofLine]:
    """时间宽裕度。只在真有富余时说——只有一段的时候说「有余地」是撒谎。"""
    if not scene.objective(ObjectiveKind.TIME_SLACK):
        return []
    if len(_valid_slots(scene)) < 2 or not scene.may_cite("availability"):
        return []
    return [
        ProofLine(
            source=EvidenceSource.OBJECTIVE_CONTRIBUTION,
            text="时间上还有余地，不是只卡着这一段。",
            refers_to=(f"objective:{ObjectiveKind.TIME_SLACK.value}",),
        )
    ]


def _cross_major(scene: _Scene) -> list[ProofLine]:
    """专业不同这件事，只有在对方允许露出时才说得出口。

    `major` 目前不在 `GRANTABLE_FIELDS` 里（见 `UNGRANTABLE`），也就是说
    这条现在写不出来。留着它不是死代码：它是这个字段被授权那天的落点，
    也是「未获准就不许引用」这条规则唯一能被测出来的地方。
    """
    if not scene.objective(ObjectiveKind.CROSS_MAJOR) or not scene.may_cite("major"):
        return []
    majors = [m.major for m in scene.group.members if m.major]
    if len(set(majors)) < 2:
        return []
    return [
        ProofLine(
            source=EvidenceSource.APPROVED_FACET,
            # 只说事实，不替人下"你们会互补"这种判断——那是见了面才知道的事。
            text=f"你们来自不同的方向：{'、'.join(dict.fromkeys(majors))}。",
            refers_to=(*scene.everyone, f"objective:{ObjectiveKind.CROSS_MAJOR.value}"),
        )
    ]


def _stable(scene: _Scene) -> list[ProofLine]:
    """通过时的那句可证伪的承诺。措辞照 07 §6 的对照表，不另起炉灶。"""
    if not scene.verdict.passed:
        return []
    return [
        ProofLine(
            source=EvidenceSource.SOLVER_CONSTRAINT,
            text="这几个人现在都没有更想去的组。",
            refers_to=scene.everyone,
        )
    ]


# --- 冲突与不确定 -----------------------------------------------------------


def _conflicts(scene: _Scene) -> list[ProofLine]:
    """系统没能解决的事。说出来的代价永远小于藏起来。"""
    lines: list[ProofLine] = []
    requirement = scene.requirement
    members = scene.group.members

    for member in members:
        if member.principal_id in requirement.excluded:
            lines.append(
                ProofLine(
                    source=EvidenceSource.UNRESOLVED_CONFLICT,
                    text=f"你说过不想和{member.display_name}一起，他还在这份名单里。",
                    refers_to=(_who(member), f"intent:{requirement.intent_id}"),
                )
            )

    size = len(members)
    if size < requirement.team_min:
        lines.append(
            ProofLine(
                source=EvidenceSource.UNRESOLVED_CONFLICT,
                text=(
                    f"这组只凑到{_count(size)}个人，"
                    f"你要的是至少{_count(requirement.team_min)}个。"
                ),
                refers_to=(f"intent:{requirement.intent_id}",),
            )
        )
    elif size > requirement.team_max:
        lines.append(
            ProofLine(
                source=EvidenceSource.UNRESOLVED_CONFLICT,
                text=(
                    f"这组有{_count(size)}个人，"
                    f"比你要的{_count(requirement.team_max)}个多。"
                ),
                refers_to=(f"intent:{requirement.intent_id}",),
            )
        )

    missing = [
        need for need in requirement.needs if need not in scene.group.role_assignment
    ]
    if missing:
        lines.append(
            ProofLine(
                source=EvidenceSource.UNRESOLVED_CONFLICT,
                text=f"缺的{'、'.join(missing)}还没人认领。",
                refers_to=tuple(f"need:{n}" for n in missing),
            )
        )

    if not _valid_slots(scene):
        lines.append(
            ProofLine(
                source=EvidenceSource.UNRESOLVED_CONFLICT,
                text="你们几个没有都空着的时间，得有人挪。",
                refers_to=scene.everyone,
            )
        )

    if requirement.zone:
        elsewhere = [m for m in members if m.zone is not None and m.zone != requirement.zone]
        if elsewhere:
            # 名字可以说，但「他在哪个校区」是他的切面，没获准就只说有这么个人。
            names = "、".join(m.display_name for m in elsewhere)
            text = (
                f"{names}不在{requirement.zone}，路上要算时间。"
                if scene.may_cite("zone")
                else f"有人不在{requirement.zone}，路上要算时间。"
            )
            lines.append(
                ProofLine(
                    source=EvidenceSource.UNRESOLVED_CONFLICT,
                    text=text,
                    refers_to=tuple(_who(m) for m in elsewhere),
                )
            )

    loaded = [m for m in members if m.active_commitments >= requirement.max_concurrent]
    if loaded:
        names = "、".join(m.display_name for m in loaded)
        text = (
            f"{names}手上的事已经排满了，再加这件会挤。"
            if scene.may_cite("active_commitments")
            else "有人手上的事已经排满了，再加这件会挤。"
        )
        lines.append(
            ProofLine(
                source=EvidenceSource.UNRESOLVED_CONFLICT,
                text=text,
                refers_to=tuple(_who(m) for m in loaded),
            )
        )

    if not scene.verdict.passed:
        for defection in scene.verdict.defections:
            defector = scene.member(defection.principal_id)
            name = defector.display_name if defector else "有人"
            lines.append(
                ProofLine(
                    source=EvidenceSource.UNRESOLVED_CONFLICT,
                    text=f"{name}现在更想去别的组，这组不一定拢得住。",
                    refers_to=(_who(defector),) if defector else (),
                )
            )
        if not scene.verdict.defections:
            lines.append(
                ProofLine(
                    source=EvidenceSource.UNRESOLVED_CONFLICT,
                    text="这几个人里还有人更想去别的组，这组不一定拢得住。",
                    refers_to=scene.everyone,
                )
            )

    return lines


def _doubts(scene: _Scene) -> list[ProofLine]:
    """系统自己承认的不确定。"""
    lines: list[ProofLine] = []
    requirement = scene.requirement

    # 没做完过一件事的人，他的技能只是他自己写的。这句话的依据是对方
    # 已授权露出的经历本身，所以没获准就一句都不写——不能靠「说出缺失」
    # 把没获准的东西带出去。
    if scene.may_cite("confirmed_events"):
        for need, holder_id in scene.group.role_assignment.items():
            holder = scene.member(holder_id)
            if holder is None or holder.confirmed_events > 0:
                continue
            lines.append(
                ProofLine(
                    source=EvidenceSource.APPROVED_FACET,
                    text=f"{holder.display_name}的{need}还没被任何一件做完的事验证过。",
                    refers_to=(_who(holder), f"need:{need}"),
                )
            )

    if scene.may_cite("zone") and requirement.zone:
        unstated = [m for m in scene.group.members if m.zone is None]
        if unstated:
            names = "、".join(m.display_name for m in unstated)
            lines.append(
                ProofLine(
                    source=EvidenceSource.APPROVED_FACET,
                    text=f"{names}没写常在哪个校区，地点还得对一次。",
                    refers_to=tuple(_who(m) for m in unstated),
                )
            )

    remaining = requirement.deadline - scene.now
    if remaining <= NEAR_DEADLINE:
        window = "一天" if remaining <= timedelta(days=1) else "两天"
        lines.append(
            ProofLine(
                source=EvidenceSource.USER_STATEMENT,
                text=f"离你写的截止不到{window}了，他们不一定来得及回。",
                refers_to=(f"intent:{requirement.intent_id}",),
            )
        )

    return lines


# --- 留给人的 ---------------------------------------------------------------


def _for_humans(scene: _Scene, *, withheld: tuple[str, ...]) -> list[ProofLine]:
    """刻意不判断的部分。

    每条的 `source` 指的是**系统在这件事上到底知道什么**，不是这条属于哪一类。
    比如「那天能不能来」的依据是求解器算出的时间重合——它只知道大家勾了空，
    勾了不等于去得了，所以这条挂在 `SOLVER_CONSTRAINT` 上。
    """
    requirement = scene.requirement
    lines: list[ProofLine] = [
        # 无条件的三条：任何一次成局都必然有留给人的判断，空的就是错的。
        ProofLine(
            source=EvidenceSource.USER_STATEMENT,
            text="署名、发到哪、要不要露脸——你没说，这些也不该替你们定。",
            refers_to=(f"intent:{requirement.intent_id}",),
        ),
        ProofLine(
            source=EvidenceSource.USER_STATEMENT,
            text="你们合不合得来，见一面才知道。",
            refers_to=(f"intent:{requirement.intent_id}",),
        ),
        ProofLine(
            source=EvidenceSource.SOLVER_CONSTRAINT,
            text="都标了有空，不等于那天真能来。约之前问一句。",
            refers_to=scene.everyone,
        ),
    ]

    if scene.objective(ObjectiveKind.RECIPROCITY):
        # 互惠是个软目标，但「这次对他到底值不值」只有他自己能回答——
        # 契约里也确实没有任何字段承载「谁从这次里得到什么」。
        lines.append(
            ProofLine(
                source=EvidenceSource.OBJECTIVE_CONTRIBUTION,
                text="他们各自图什么，这里猜不准。见面问一句更快。",
                refers_to=(f"objective:{ObjectiveKind.RECIPROCITY.value}",),
            )
        )

    if withheld:
        lines.append(
            ProofLine(
                source=EvidenceSource.APPROVED_FACET,
                text="他们愿意让你看到的就这些。想知道更多，得他们自己说。",
                refers_to=scene.everyone,
            )
        )

    if not scene.verdict.passed:
        lines.append(
            ProofLine(
                source=EvidenceSource.UNRESOLVED_CONFLICT,
                text="先别急着约——有人现在更想去别的组。要不要等下一轮，你定。",
                refers_to=scene.everyone,
            )
        )

    return lines


# --- 工程面 -----------------------------------------------------------------


def _withheld(scene: _Scene) -> tuple[str, ...]:
    """这次因为没获准露出而写不出来的东西。

    不静静吞掉：进 `notes`，申诉和导出时看得到（07 §7）。
    """
    wanted = ["skills", "availability"]
    if scene.requirement.zone:
        wanted.append("zone")
    if scene.objective(ObjectiveKind.CROSS_MAJOR):
        wanted.append("major")
    wanted.append("confirmed_events")
    if any(
        m.active_commitments >= scene.requirement.max_concurrent
        for m in scene.group.members
    ):
        wanted.append("active_commitments")
    return tuple(a for a in wanted if a not in scene.visible)


def _notes(scene: _Scene, *, withheld: tuple[str, ...]) -> tuple[str, ...]:
    """给申诉、审计和运营看的那一面。

    这里用领域词汇是合法的（07 §2.1 例外一与例外三）——它不是用户可见文案。
    求解器和稳定性检查写的原话都留在这里：屏幕上不给它们位置，但追责时要找得到。
    """
    notes = [
        f"目标项 {c.kind.value}：{c.explanation}" for c in scene.group.contributions
    ]
    notes += [f"未获准露出，已略去：{a}" for a in withheld]
    if scene.verdict.statement:
        notes.append(f"稳定性结论原文：{scene.verdict.statement}")
    # 契约里拿不到的东西也记一笔：`Member.availability` 没有采集时间，
    # 所以「这份空闲是三周前填的」这类不确定性目前写不出来。
    notes.append("无法给出：可用时间的采集时间——Member 上没有这个字段")
    return tuple(notes)
