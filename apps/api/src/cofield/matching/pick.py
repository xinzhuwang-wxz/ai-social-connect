"""为什么是这个人。

## 它是成局证明的那一半

旧链路里证明回答的是"为什么是这几个人"——一支队的理由。投递制之后
（ADR 0010）发起人是**逐个**挑，所以问题变成"为什么是这个人"。

**这一层整个保留下来了，只是主语变了。** 它是这套东西里最值钱的部分：
界面上没有分数、没有百分比，只有几句能逐条追回事实的话。

## 三条不能动

**每一句都要指得回一个可查的事实。** "他看起来很合适"不是理由，
"他会剪辑，而你缺剪辑"是。

**不引用相似度。** 0.71 不是用户能判断的东西；"他自己写的『文风比较冲』"是。

**说不出来就不说。** 编一条理由比不给理由伤害大——用户会照着它去联系人，
然后发现全是浪费。
"""

from __future__ import annotations

from dataclasses import dataclass

from cofield.domain.model.intent import IntentContent
from cofield.matching.funnel import Candidate, contiguous_common_slots


@dataclass(frozen=True, slots=True)
class Why:
    """为什么把这颗种子投给他。"""

    lines: tuple[str, ...]
    #: 排序用。**不出现在界面上**——它是内部的先后，不是给人打的分。
    weight: int


def explain(
    candidate: Candidate,
    content: IntentContent,
    *,
    my_availability: str | None = None,
    together_before: int = 0,
) -> Why:
    """一个候选的理由与位次。

    位次只用来决定谁排在前面。**它不进界面**：一旦露出来，"87 分"和
    "62 分"之间那点差别就会被当成对人的判断，而它其实只是几条事实的加总。
    """
    lines: list[str] = []
    weight = 0

    covers = [need for need in content.needs if need in candidate.skills]
    if covers:
        lines.append(f"你缺{'、'.join(covers)}，他会。")
        weight += 40 * len(covers)

    open_to = [need for need in content.needs if need not in candidate.skills]
    if not covers and open_to:
        # 只说过"想参与"的人：**放宽召回，不放宽承诺**——所以这句话
        # 要说清楚他是想参与，不是会做。
        lines.append(f"他说过想参与{'、'.join(open_to)}这类事。")
        weight += 10

    if my_availability and candidate.availability:
        slots = contiguous_common_slots([my_availability, candidate.availability], run=2)
        if slots:
            lines.append(f"你们有 {slots} 段连着的共同空闲。")
            weight += min(slots, 6) * 3

    if content.location_scope and candidate.zone:
        if candidate.zone in content.location_scope:
            lines.append(f"他常在{candidate.zone}。")
            weight += 8

    if together_before > 0:
        # 闭环靠这一句合上：上次一起完成过，是这个产品独有的、
        # 别处拿不到的信息。
        lines.append(f"你们一起做成过 {together_before} 件事。")
        weight += 25 * min(together_before, 3)

    if candidate.matched_text:
        # 语义命中的**原话**，不是相似度。
        lines.append(f"他自己写的：「{candidate.matched_text}」")
        weight += 12

    if not lines:
        # 说不出来就说不出来。编一条比不给伤害大。
        lines.append("说不出特别的理由，你自己看看合不合适。")

    return Why(lines=tuple(lines), weight=weight)
