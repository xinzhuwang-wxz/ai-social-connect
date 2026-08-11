"""谁可以出现在同一个成局提案里。

这里只回答一个问题：**这组人能不能被放进同一个提案**。
它不回答他们该不该组队——那是求解器和稳定性检查的事。
返回判定而不是抛异常：求解阶段要廉价地大量筛选，靠捕获异常筛选是错的。
写入边界的断言等到真有写入边界时再加（#9），由那个调用点决定它的形状。

两条规则合放在一起，因为它们是同一个判断的两面：一个提案的成员必须处在
同一个策略边界内，且不得混合真人与合成主体。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from cofield.domain.model.principal import Principal


@dataclass(frozen=True, slots=True)
class Eligibility:
    ok: bool
    reason: str | None = None

    @staticmethod
    def allowed() -> Eligibility:
        return Eligibility(ok=True)

    @staticmethod
    def refused(reason: str) -> Eligibility:
        return Eligibility(ok=False, reason=reason)


def eligibility(members: Sequence[Principal]) -> Eligibility:
    """判断这组主体能否共处一个成局提案。用于求解阶段筛选候选。"""
    if not members:
        return Eligibility.refused("成局提案不能为空")

    campuses = {m.campus_id.value for m in members}
    if len(campuses) > 1:
        return Eligibility.refused(f"跨校园成局需要单独授权：{sorted(campuses)}")

    kinds = {m.is_synthetic for m in members}
    if len(kinds) > 1:
        return Eligibility.refused("合成主体不能与真人出现在同一个成局提案中")

    return Eligibility.allowed()
