"""稳定性检查：求解器算出的最优分区，未必是稳定分区。

组队的正式模型是 **hedonic coalition formation game**：每个人对「自己在哪个组」
有偏好，输出是一个分区。它的基本结论是**最优 ≠ 稳定**——为了让整体目标最大化，
求解器完全可能把某个人塞进他并不想去的组；他会在第一次线下见面之前退出，整组
随之崩掉。所以这一层是**门不是分**：`passed` 是布尔值，不通过的分区不得成为
提案（CONTEXT.md 不变量 9）。

## 选了哪个稳定性概念：individual stability

判据是「不存在这样一对（人, 组）：他更想去那个组，**并且**那个组接纳他」。
两个条件缺一不可，这也正是 CONTEXT.md 里「稳定分区」的字面定义。

- 比 **Nash 稳定弱**。Nash 允许单方面跳槽，不问对方要不要他。在这个产品里那不
  成立：一个组接不接得下一个人是有硬约束管着的（人数上限、整组共同空闲），而且
  那是一群要一起干活的真人。「他想去、那边不要他」并不会让当前分区散架。
- 比 **core 稳定弱得多**。core 允许任意一群人自己另起炉灶；我们只能在求解器给出
  的这几个候选组之间比较，表达不了「这五个人自己重组一个新组」。
- **不是 contractual individual stability**：不检查他走了之后原来那组会不会塌。
  这是产品判断——「留下的人会受损」不是挽留他的理由，只说明那一组本来就脆。

`docs/03-技术架构.md` §8.6 把它叫作「Nash 稳定的近似」，但那里写下来的判据
（更偏好 + 被接纳）就是 individual stability。这里按判据实现，不按名字实现。

## 「更愿意」是怎么定义的

个体偏好**不看整组 `score`**——那是全局量，是求解器为了整体最优给出的排序，
不是任何一个人的视角。这里从 `CandidateGroup.contributions` 里挑出确实能用
第一人称说出口的三项，并把整组的 `raw` 换成**这个人自己的那一份**：

| 目标项 | 他自己的那一份 | 为什么算第一人称 |
|---|---|---|
| `TIME_SLACK` | 这一组还剩几段连续共同空闲 | 段数越少，一次调课就散，代价落在他身上 |
| `RECIPROCITY` | 队友会、而他不会的本事有几样 | 「我来这一趟能得到什么」，与发起人的需求无关 |
| `CROSS_MAJOR` | 组里和他不同专业的有几个人 | 见到多少不一样的人，是他自己的收益 |

另外三项**不进入**个体偏好，理由分别是：

- `ROLE_FIT`：`role_assignment` 是**发起者**视角的「谁补我的缺」，不是候选人视角
  的「我更想去哪」；而且它在假设组里没法对称计算——一个可行组的缺口本来就已经补
  满，新来的人角色恒为 0，把它放进来会系统性偏袒现状，让这道门形同虚设。
- `EXPOSURE_FAIRNESS` / `NEWCOMER_PROTECTION`：平台级公平量，是**人的属性**而不是
  组的属性，对同一个人在所有组里取值相同，放进来只是给每个组加同一个常数。

权重不自己发明。`check()` 拿不到 `SolveRequest.objectives`，但每条 contribution
同时带着 `raw` 与 `weighted`，两者相除就是求解器实际用的权重；反解出来用，
「他更想去」才和求解器的「分数更高」是同一套单位。反解不出来时退回
`DEFAULT_OBJECTIVES`。

## 规模

复杂度是 O(人数 × 组数 × 组内人数 × 21)：每个人对每个他不在的组试一次，试一次要
把那组在座的每个人重算一遍福利，重算的底层是 21 位掩码上的按位与。
`group_count=6`、每组 6 人（19 个不同的人、136 次真正跑完的接纳判定）实测 **5.4 ms**，
离容量护栏里那个 1 秒有两个数量级余量。真要撑不住时的降级方向是只比较得分最高的
top-K 组——**代价是那句承诺得改口**，从「没有人有更好的去处」退成「在这 K 个组里
没有」，所以那是产品与工程一起做的决定，不是这一层可以自己降的。

## 这个概念漏掉了什么

1. **只在给定的候选组之间比较。** 不是完整的 individual stability（定义域应是所有
   可行联盟），更不是 core。求解器没生成的那个组，我们看不见。
2. **不覆盖「那边更需要我」这类以角色为动机的跳槽。** 见上面 `ROLE_FIT` 的理由。
3. **偏好是推断的，不是本人说的。** 三项都从结构化属性算出来；一个真的不在乎跨专业
   的人，我们仍会按 0.8 的权重替他在乎。
4. **只算一轮，不追连锁反应。** A 走了之后 B 所在的组变了，B 可能因此也想走——这
   一轮看不到。重求解后需要再跑一次。
5. **不管他走后原组会不会塌**（非 contractual）。
6. **同一个人出现在多个候选组时**，取他所在各组里最好的那一个当作「他现在过得多
   好」：候选组是并列的备选，用户最终从中挑，只有当某个他不在的组比他已有的全部
   都好，他才真的想走。
"""

from __future__ import annotations

from uuid import UUID

from cofield.matching.contracts import (
    DEFAULT_OBJECTIVES,
    WEEK_SLOTS,
    CandidateGroup,
    Defection,
    Member,
    ObjectiveKind,
    Requirement,
    StabilityVerdict,
)

#: 只用来挡浮点噪声，不是「容忍度」。门要宁可误判不稳定，也不能放过一个真会走的人，
#: 所以这里没有可调的松弛量——两边差一点点就算差，只是不算差 1e-9。
_NOISE = 1e-9

#: 进入个体偏好的三项。另外三项为什么不在这里，见模块 docstring。
_PERSONAL: tuple[ObjectiveKind, ...] = (
    ObjectiveKind.TIME_SLACK,
    ObjectiveKind.RECIPROCITY,
    ObjectiveKind.CROSS_MAJOR,
)

#: 每一项在「他为什么想走」里怎么说给人听。数字直接给两边的取值，可以自己核。
_PHRASING: dict[ObjectiveKind, str] = {
    ObjectiveKind.TIME_SLACK: "整组能一起动的时间从 {here:g} 段变成 {there:g} 段",
    ObjectiveKind.RECIPROCITY: "队友会而他不会的本事从 {here:g} 样变成 {there:g} 样",
    ObjectiveKind.CROSS_MAJOR: "同组不同专业的人从 {here:g} 个变成 {there:g} 个",
}


def check(
    groups: tuple[CandidateGroup, ...], requirement: Requirement
) -> StabilityVerdict:
    """这个分区里有没有人既更想去别的组、那个组又接得下他。

    有一个就不通过。`defections` 精确指认是谁、想去第几组、为什么。
    """
    if len(groups) <= 1:
        # 没有第二个组，就没有「别处」——通过是必然的，所以这句话必须说清它没在承诺什么。
        return StabilityVerdict(passed=True, statement=_nothing_to_compare(groups))

    run = max(1, requirement.contiguous_run)
    weights = _solver_weights(groups)

    # 每个人在他现在所在的每个组里过得多好。算一次存下来：接纳判定要反复用它。
    baselines: list[dict[UUID, float]] = [
        {m.principal_id: _appeal(_shares(m, g.members, run), weights) for m in g.members}
        for g in groups
    ]

    people: dict[UUID, Member] = {}
    here: dict[UUID, tuple[float, int]] = {}
    for index, group in enumerate(groups):
        for who in group.members:
            people[who.principal_id] = who
            standing = baselines[index][who.principal_id]
            known = here.get(who.principal_id)
            if known is None or standing > known[0]:
                here[who.principal_id] = (standing, index)

    defections: list[Defection] = []
    for pid, (here_appeal, here_index) in here.items():
        who = people[pid]
        target: tuple[float, int, tuple[Member, ...]] | None = None
        for index, group in enumerate(groups):
            if pid in group.member_ids:
                continue
            joined = group.members + (who,)
            if not _would_accept(group, who, joined, requirement, run, weights, baselines[index]):
                continue
            appeal = _appeal(_shares(who, joined, run), weights)
            if appeal <= here_appeal + _NOISE:
                continue
            # 他不止一个更好的去处时，指认最好的那个——那才是他真会走的方向。
            if target is None or appeal > target[0]:
                target = (appeal, index, joined)
        if target is not None:
            defections.append(
                Defection(
                    principal_id=pid,
                    prefers_group_index=target[1],
                    reason=_reason(
                        who, here_index, groups[here_index].members, target[1], target[2], run
                    ),
                )
            )

    if defections:
        return StabilityVerdict(
            passed=False,
            defections=tuple(defections),
            statement=_broken(defections, people),
        )
    return StabilityVerdict(passed=True, statement=_promise(len(groups), len(people)))


# --- 个体视角 ---------------------------------------------------------------


def _solver_weights(groups: tuple[CandidateGroup, ...]) -> dict[ObjectiveKind, float]:
    """把求解器实际用的权重从 contributions 里反解出来。

    `raw` 与 `weighted` 相除就是那一项的权重。这样个体偏好和求解器的目标函数
    用同一套单位——差别只在**主语**是人还是组，而不是我另发明了一套刻度。
    """
    recovered: dict[ObjectiveKind, float] = {}
    for group in groups:
        for item in group.contributions:
            if item.kind in recovered or abs(item.raw) < _NOISE:
                continue
            recovered[item.kind] = item.weighted / item.raw

    default = {objective.kind: objective.weight for objective in DEFAULT_OBJECTIVES}
    return {kind: recovered.get(kind, default.get(kind, 1.0)) for kind in _PERSONAL}


def _shares(
    who: Member, members: tuple[Member, ...], run: int
) -> dict[ObjectiveKind, float]:
    """这个人在这一组里，三项各自摊到他头上是多少。

    `members` 既可以是一个真实候选组，也可以是「加进一个人之后」的假设组——
    两边必须用同一个函数算，否则差值没有意义。
    """
    others = tuple(m for m in members if m.principal_id != who.principal_id)
    theirs: set[str] = set()
    for other in others:
        theirs |= other.skills

    return {
        ObjectiveKind.TIME_SLACK: float(_common_runs(members, run)),
        ObjectiveKind.RECIPROCITY: float(len(theirs - who.skills)),
        ObjectiveKind.CROSS_MAJOR: float(
            sum(1 for m in others if m.major and who.major and m.major != who.major)
        ),
    }


def _appeal(shares: dict[ObjectiveKind, float], weights: dict[ObjectiveKind, float]) -> float:
    return sum(weights[kind] * shares[kind] for kind in _PERSONAL)


def _common_runs(members: tuple[Member, ...], run: int) -> int:
    """整组有多少个「连续 run 段」的共同空闲。

    与 `funnel.contiguous_common_slots` 同一口径，但不从那里 import：那个模块连着
    SQLAlchemy 与 schema，而这一层是纯计算，必须能在没有数据库的地方跑。
    """
    if not members:
        return 0
    masks = [_mask(m) for m in members]
    common = [all(mask[i] == "1" for mask in masks) for i in range(WEEK_SLOTS)]
    return sum(
        all(common[i + k] for k in range(run)) for i in range(WEEK_SLOTS - run + 1)
    )


def _mask(member: Member) -> str:
    """缺失的位按空闲处理，与漏斗一致——时间约束的收紧交给求解器，不在这里加码。"""
    return member.availability.ljust(WEEK_SLOTS, "1")[:WEEK_SLOTS]


# --- 那一组要不要他 ---------------------------------------------------------


def _would_accept(
    group: CandidateGroup,
    newcomer: Member,
    joined: tuple[Member, ...],
    requirement: Requirement,
    run: int,
    weights: dict[ObjectiveKind, float],
    baseline: dict[UUID, float],
) -> bool:
    """那一组接不接得下他。「他想去」和「那边要他」是两件事。

    只查会因为「多一个人」而翻脸的硬约束：`TEAM_SIZE`（满员就是满员）、
    `EXCLUSION`（被点名排除的人哪个组都不能收）、`COMMON_TIME`（真正咬人的那条——
    多一个人，整组的共同空闲只会更少）。

    `CONCURRENCY` 与 `ZONE` 不查：跳槽是「离开一组、加入一组」，他的并发承诺数不变；
    校区是他自己的属性，在他现在这一组里已经成立过一次。`ROLE_COVERAGE` 不查：
    多一个人只会多覆盖，不会少覆盖。
    """
    if len(joined) > requirement.team_max:
        return False
    if newcomer.principal_id in requirement.excluded:
        return False
    if _common_runs(joined, run) == 0:
        return False

    # individual stability 的另一半：组里现有的人不能因为接纳他而变差。
    # 多一个人常常把整组的共同空闲砍掉一大截——那笔账要记在原来那几个人头上。
    return all(
        _appeal(_shares(sitting, joined, run), weights) >= baseline[sitting.principal_id] - _NOISE
        for sitting in group.members
    )


# --- 说给人听 ---------------------------------------------------------------


def _reason(
    who: Member,
    here_index: int,
    here_members: tuple[Member, ...],
    there_index: int,
    there_members: tuple[Member, ...],
    run: int,
) -> str:
    """他为什么想走。给用户看的，所以给的是两边的具体数字，不是「匹配度更高」。"""
    here = _shares(who, here_members, run)
    there = _shares(who, there_members, run)
    gains = [
        _PHRASING[kind].format(here=here[kind], there=there[kind])
        for kind in _PERSONAL
        if there[kind] > here[kind] + _NOISE
    ]
    better = "；".join(gains) if gains else "整体上更合得来"

    return (
        f"{who.display_name}现在在第 {here_index} 组，但第 {there_index} 组对他更划算："
        f"{better}。第 {there_index} 组加上他之后仍然凑得出连续 {run} 段共同空闲、"
        f"人数也没超上限，组里原有的人不会因此变差——所以这一步他走得成。"
    )


def _promise(group_count: int, head_count: int) -> str:
    """通过时那句话必须可证伪：指名道姓挑一个人、一个组，就能自己复核。"""
    return (
        f"这 {group_count} 个候选组、{head_count} 个人里，没有任何一个人存在"
        f"「他更想去、且那一组接纳他之后仍然成立」的其他组——任指一人一组都可以逐条核。"
    )


def _broken(defections: list[Defection], people: dict[UUID, Member]) -> str:
    named = "、".join(people[d.principal_id].display_name for d in defections[:3])
    if len(defections) == 1:
        head = f"{named}更想去第 {defections[0].prefers_group_index} 组，而那一组接得下他"
    else:
        more = "等" if len(defections) > 3 else ""
        head = f"{named}{more}共 {len(defections)} 个人更想去别的组，而那些组接得下他们"
    return f"{head}。这不是稳定分区，不能作为提案。"


def _nothing_to_compare(groups: tuple[CandidateGroup, ...]) -> str:
    if not groups:
        return "没有候选组，稳定性无从谈起。"
    return (
        "只有一个候选组，没有别处可去，所以它必然通过。"
        "这是「没有比较对象」，不是「组里每个人都满意」。"
    )
