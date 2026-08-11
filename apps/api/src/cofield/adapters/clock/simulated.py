"""仿真时钟：可推进的真实现，不是 mock。

仿真推进它，所有 TTL、撮合窗口、切面有效期照常生效——被替换的是时间的
来源，不是时间的语义。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class SimulatedClock:
    """由仿真运行器驱动的时钟。线程内单调，只能向前。"""

    def __init__(self, start: datetime) -> None:
        self._instant = _require_aware(start)

    def now(self) -> datetime:
        return self._instant

    def advance(self, delta: timedelta) -> datetime:
        """向前推进。拒绝倒流——时间倒流会让有效期与过期判断变得不可推理。"""
        if delta < timedelta(0):
            raise ValueError("仿真时钟不能倒流")
        self._instant += delta
        return self._instant


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("时刻必须带时区")
    return value.astimezone(UTC)
