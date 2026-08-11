"""凑不出队的时候说什么。

## 为什么这是产品的一部分，不是错误处理

匹配失败是常态，不是异常。稀缺角色本来就只有几十个人会，时间本来就常常
对不上。**系统在这里最容易犯的错是伪造候选**——凑几个不合适的人交差，
比说"凑不出来"伤害大得多：用户会花时间去联系他们，然后发现全是浪费。

所以这一层只做一件事：把挫败换成一个**具体的下一步**。

## 两种凑不出来是两回事

```
连符合条件的人都没有   →  RECALL 阶段。缺的是供给
有人，但凑不成一个组   →  FORMATION 阶段。供给在，组合不成立
```

对用户是完全不同的两句话，也是完全不同的下一步：前者要么等新人来、
要么放宽条件，后者往往只差一个时间段。把它们混成一句"没找到合适的人"
会让第二种情况的用户白白放弃——他们其实很接近成功。

## 数字必须是真的

"可以试试放宽条件"等于什么都没说。每一个可放宽项都带**实测的增量**：
放开校区多出 137 个人，还是多出 2 个，用户的决定完全不同。
数字来自真的重新查询，不是估的。

## 不是所有条件都该被建议放宽

高风险的线下场景里，"少几个人也行""换个远点的地方"正是出事的形状。
这类放宽仍然**列出来**——不列等于替用户做决定——但明确标记不建议，
并说清担心的是什么。见 04-治理与安全 §2.1 与 §3。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cofield.domain.model.action_kind import ActionKind, RiskTier
from cofield.domain.model.intent import IntentSignal
from cofield.matching.contracts import ConstraintKind, SolveResult
from cofield.matching.funnel import Funnel


class Stage(StrEnum):
    """卡在哪一段。决定了对用户说哪句话。"""

    #: 连符合硬条件的人都没有。缺的是供给。
    RECALL = "recall"
    #: 人有，但凑不成一个组。往往只差一个共同的时间段。
    FORMATION = "formation"


class StepKind(StrEnum):
    """下一步能做什么。**每一种都必须真的能点**——
    列一个做不了的选项比不列更让人挫败。"""

    #: 有人发出符合条件的需求时通知我。
    WAIT_FOR_SUPPLY = "wait_for_supply"
    #: 直接拉一个自己认识的人进来。
    INVITE_SOMEONE = "invite_someone"
    #: 把这件事交给社团或学院去凑人。
    ASK_ORGANIZERS = "ask_organizers"
    #: 改一改需求本身再试。
    REVISE = "revise"


@dataclass(frozen=True, slots=True)
class Relaxation:
    """放宽某一项能换来什么。"""

    field_name: str
    #: 给用户看的一句话，祈使句：「先不限校区」。
    invitation: str
    #: 放宽之后多出多少人。真查出来的，不是估的。
    gains: int
    #: 是否建议。不建议的项**照样列出来**——不列等于替用户做决定。
    advisable: bool = True
    #: 不建议的理由。说清担心的是什么，不说"出于安全考虑"这种废话。
    caution: str = ""


@dataclass(frozen=True, slots=True)
class NextStep:
    kind: StepKind
    #: 按钮上的话。
    invitation: str


@dataclass(frozen=True, slots=True)
class BlockingProof:
    stage: Stage
    #: 一句平静具体的话。不安慰，也不冷冰冰。
    statement: str
    #: 是哪几条共同导致的。**共同**——单独任何一条都还有人。
    causes: tuple[str, ...]
    relaxations: tuple[Relaxation, ...]
    next_steps: tuple[NextStep, ...]

    @property
    def best_relaxation(self) -> Relaxation | None:
        """建议里收益最大的那一个。界面上默认高亮它。"""
        advisable = [r for r in self.relaxations if r.advisable and r.gains > 0]
        return max(advisable, key=lambda r: r.gains, default=None)


#: 领域词汇到用户词汇。这一层的输出直接进界面，
#: 所以这里不能出现"意图""硬约束""召回"这类说法（见 07 §1）。
_FIELD_WORDS: dict[str, str] = {
    "needs": "会做这几件事的人",
    "location_scope": "限定在这个校区",
    "time_window": "这个时间范围",
    "team_size": "这个人数",
}

_RELAX_WORDS: dict[str, str] = {
    "needs": "少要一样本事，自己补上其中一件",
    "location_scope": "先不限校区",
    "time_window": "把时间放宽几天",
    "team_size": "少一个人也开始",
}

_CONSTRAINT_WORDS: dict[ConstraintKind, str] = {
    ConstraintKind.ROLE_COVERAGE: "缺的本事没人能补上",
    ConstraintKind.TEAM_SIZE: "凑不够你要的人数",
    ConstraintKind.COMMON_TIME: "大家没有一段连着的共同空闲",
    ConstraintKind.ZONE: "他们不在同一个校区",
    ConstraintKind.CONCURRENCY: "合适的人手上都已经排满了",
    ConstraintKind.EXCLUSION: "你排除掉的人正好是能补上的那几个",
}


def explain_recall(
    funnel: Funnel,
    intent: IntentSignal,
    blocked_by: tuple[str, ...],
    *,
    kind: ActionKind | None = None,
) -> BlockingProof:
    """一个符合条件的人都没有时说什么。

    `blocked_by` 来自漏斗的诊断——它已经逐条卸掉约束试过了，
    知道是哪几条**共同**把人筛没的。
    """
    relaxations = tuple(
        _relaxation(field_name, funnel.relaxation_gain(intent, field_name), kind)
        for field_name in blocked_by
    )
    causes = tuple(_FIELD_WORDS.get(f, f) for f in blocked_by)

    return BlockingProof(
        stage=Stage.RECALL,
        statement=_recall_statement(causes, relaxations),
        causes=causes,
        relaxations=relaxations,
        next_steps=_next_steps(Stage.RECALL),
    )


#: 求解器的每条硬约束对应用户可以松开哪一项。
#: `EXCLUSION` 不在这里——"要不要把拉黑的人放回来"不该由系统建议。
_CONSTRAINT_TO_FIELD: dict[ConstraintKind, str] = {
    ConstraintKind.ROLE_COVERAGE: "needs",
    ConstraintKind.TEAM_SIZE: "team_size",
    ConstraintKind.COMMON_TIME: "time_window",
    ConstraintKind.ZONE: "location_scope",
}


def explain_formation(
    result: SolveResult,
    *,
    funnel: Funnel | None = None,
    intent: IntentSignal | None = None,
    kind: ActionKind | None = None,
) -> BlockingProof:
    """人有，但凑不成一个组的时候说什么。

    这一种往往只差一个时间段，用户其实很接近成功——
    说成"没找到合适的人"会让他们白白放弃。

    这里也是**地点与人数**两项放宽真正出现的地方。召回段几乎见不到它们：
    两万人的校园里，全校有人会的技能每个校区都有人会（实测确实如此），
    所以单独放开校区在召回段一个人都多不出来。真正卡在地点上的是**成局**——
    人都在，但不在同一个校区。高风险类别的安全提醒因此也挂在这一段。

    `funnel` 与 `intent` 给得出时，地点那一项带上真数字；给不出时仍然列出，
    只是没有增量——**没有数字也好过不提这条路**。
    """
    causes = tuple(
        _CONSTRAINT_WORDS.get(c.kind, c.detail) for c in result.blocked_by
    )
    kinds = {c.kind for c in result.blocked_by}

    relaxations = tuple(
        _relaxation(
            field_name,
            _gain_for(field_name, funnel, intent),
            kind,
        )
        for constraint_kind in result.blocked_by
        if (field_name := _CONSTRAINT_TO_FIELD.get(constraint_kind.kind)) is not None
    )

    if kinds == {ConstraintKind.COMMON_TIME}:
        statement = "合适的人都在，但你们凑不出一段连着的共同空闲。"
    elif causes:
        statement = "这几个人凑不成一个组：" + "；".join(causes) + "。"
    else:
        statement = "这次没能凑成一个组。"

    return BlockingProof(
        stage=Stage.FORMATION,
        statement=statement,
        causes=causes,
        relaxations=relaxations,
        next_steps=_next_steps(Stage.FORMATION),
    )


def _gain_for(
    field_name: str, funnel: Funnel | None, intent: IntentSignal | None
) -> int:
    """能算就算真数字，算不出就给 0。

    **不估。** 一个编出来的"大概能多几十个人"会被用户当真去改需求，
    比不给数字伤害大。漏斗只管得了它自己施加的那几条，
    时间与人数是求解器的约束，这里算不出来。
    """
    if funnel is None or intent is None:
        return 0
    if field_name not in ("needs", "location_scope"):
        return 0
    return funnel.relaxation_gain(intent, field_name)


def _relaxation(
    field_name: str, gains: int, kind: ActionKind | None
) -> Relaxation:
    advisable, caution = _safety(field_name, kind)
    return Relaxation(
        field_name=field_name,
        invitation=_RELAX_WORDS.get(field_name, f"放宽{field_name}"),
        gains=gains,
        advisable=advisable,
        caution=caution,
    )


def _safety(field_name: str, kind: ActionKind | None) -> tuple[bool, str]:
    """哪些放宽不该被建议。

    只针对高风险类别，而且只针对**真的会让它更危险**的两项。
    把所有放宽都标成"注意安全"等于没有标记——用户会一律忽略。
    """
    if kind is None or kind.risk_tier is not RiskTier.HIGH:
        return True, ""

    if field_name == "location_scope":
        return False, "这类活动换到更远、更不熟的地方，风险会明显变高。"
    if field_name == "team_size":
        return False, "这类活动人少的时候最容易出事，建议宁可等等。"
    return True, ""


def _recall_statement(
    causes: tuple[str, ...], relaxations: tuple[Relaxation, ...]
) -> str:
    """平静、具体、直接说下一步。

    不写"很遗憾"，也不写"未找到匹配结果"。前者是安慰，后者是报错，
    两种都没告诉用户接下来能做什么。
    """
    if not causes:
        return "现在还没有人能接上这件事。"

    head = "这个组暂时凑不出来：" + "，同时".join(causes) + "。"
    best = max(
        (r for r in relaxations if r.advisable and r.gains > 0),
        key=lambda r: r.gains,
        default=None,
    )
    if best is None:
        return head + "先记着，等有人发出对得上的需求，我告诉你。"
    return f"{head}{best.invitation}的话，能多出 {best.gains} 个人。"


def _next_steps(stage: Stage) -> tuple[NextStep, ...]:
    """每一种都必须真的能点。

    「等」放在第一个不是凑数：意图自带截止期，用户明确告诉了我们他什么时候
    退出——在还有时间的前提下，等着市场变厚往往比现在勉强凑一队更划算。
    """
    common = (
        NextStep(StepKind.WAIT_FOR_SUPPLY, "有人对上了就通知我"),
        NextStep(StepKind.INVITE_SOMEONE, "我自己拉一个人进来"),
    )
    if stage is Stage.RECALL:
        return (
            *common,
            NextStep(StepKind.ASK_ORGANIZERS, "让社团帮忙找找"),
            NextStep(StepKind.REVISE, "改一改再试"),
        )
    return (*common, NextStep(StepKind.REVISE, "改一改再试"))
