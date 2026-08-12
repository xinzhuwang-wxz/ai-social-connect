"""一件事长到哪一步了。

## 它是派生值，不是一个可以被写的字段

不变量 6：**共域因真实行动证据生长，不因聊天量、签到或 Agent 活跃度生长。**

所以这里没有 `set_stage()`，也没有对应的列。每一档都由**可查的事实**决定：
聊了两百条而一件事都没定，它就停在「发芽了」——这不是惩罚，是诚实。

## 为什么用生命周期而不是百分比

一个百分比会立刻引出"凭什么是 40%"。而这件事本来就不是可以精确到百分点
的东西：定了时间但没定地点，和定了地点没定时间，谁更"完成"？

生命周期的模糊性在这里是优点。它在**承诺**那一栏才是缺陷——所以承诺永远
用朴素词说（ADR 0009）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Stage(StrEnum):
    """七档，对着 PRD v2 的事件状态表。

    每一档都对应一个**真实跨过的阶段**，不对应消息数量。
    """

    #: 种子已投递，等参与意向。
    SEED = "seed"
    #: 成局了——发起人挑中、候选说过愿意，共域建出来了。
    SPROUT = "sprout"
    #: 幼苗：开始有人认领要做的事。
    SEEDLING = "seedling"
    #: 生长：事情在推进，条目有人在做。
    GROWING = "growing"
    #: 花苞：行动约定全员确认，时间地点分工都定了。
    BUD = "bud"
    #: 开花：双方确认真实行动完成。
    BLOOM = "bloom"
    #: 结果：它结出了下一颗种子（再次发起）。
    FRUIT = "fruit"


#: 界面上的说法。**这是世界观词汇，允许出现在界面上**——
#: 它和领域词汇的区别是：用户凭常识就理解它（ADR 0009）。
WORDS: dict[Stage, str] = {
    Stage.SEED: "还没发芽",
    Stage.SPROUT: "发芽了",
    Stage.SEEDLING: "长出幼苗",
    Stage.GROWING: "在长了",
    Stage.BUD: "结了花苞",
    Stage.BLOOM: "开花了",
    Stage.FRUIT: "结了果",
}

#: 一句话说清"凭什么是这一档"。**每一档都要说得出判据**——
#: 说不出判据的进度条会被当成系统在评价你。
WHY: dict[Stage, str] = {
    Stage.SEED: "投出去了，等人答复",
    Stage.SPROUT: "人齐了，还没开始定事情",
    Stage.SEEDLING: "有人开始认领要做的事了",
    Stage.GROWING: "事情在往前走",
    Stage.BUD: "时间地点分工都定了，等那天到",
    Stage.BLOOM: "做完了，东西留下来了",
    Stage.FRUIT: "从这件事又长出了下一件",
}


@dataclass(frozen=True, slots=True)
class Growth:
    stage: Stage

    @property
    def word(self) -> str:
        return WORDS[self.stage]

    @property
    def why(self) -> str:
        return WHY[self.stage]

    @property
    def rank(self) -> int:
        """第几档，从 0 起。界面画进度用它，**不要用它算百分比**。"""
        return list(Stage).index(self.stage)


def of(
    *,
    formed: bool,
    has_claimed_items: bool,
    plan_confirmed: bool,
    completed: bool,
    has_evidence: bool,
    in_progress: bool = False,
    seeded_again: bool = False,
) -> Growth:
    """由事实定档。参数全都是"发生了没有"，没有一个是分数。

    倒着判：**只有更靠后的那一档不成立，才退回前一档**。正着判的话，
    一个已经开花的事件会因为"有条目还没做完"被算成长叶。
    """
    if seeded_again:
        return Growth(Stage.FRUIT)
    if completed and has_evidence:
        return Growth(Stage.BLOOM)
    if plan_confirmed:
        return Growth(Stage.BUD)
    if in_progress:
        return Growth(Stage.GROWING)
    if has_claimed_items:
        return Growth(Stage.SEEDLING)
    if formed:
        return Growth(Stage.SPROUT)
    return Growth(Stage.SEED)
