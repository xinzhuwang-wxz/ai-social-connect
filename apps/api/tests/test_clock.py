"""时钟端口的三个实现。

这些用例证明"仿真推进时间"不需要 sleep——整个测试套件里不允许出现 sleep。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cofield.adapters.clock import FrozenClock, SimulatedClock, SystemClock
from cofield.domain.ports.clock import Clock

AWARE = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "make",
    [lambda: SystemClock(), lambda: SimulatedClock(AWARE), lambda: FrozenClock(AWARE)],
    ids=["system", "simulated", "frozen"],
)
def test_all_implementations_satisfy_the_port(make) -> None:
    clock = make()
    assert isinstance(clock, Clock)
    assert clock.now().tzinfo is not None, "时刻必须带时区"


def test_simulated_clock_advances_without_sleeping() -> None:
    clock = SimulatedClock(AWARE)
    assert clock.now() == AWARE

    clock.advance(timedelta(days=14))

    assert clock.now() == AWARE + timedelta(days=14)



def test_simulated_clock_refuses_to_run_backwards() -> None:
    """时间倒流会让有效期与过期判断变得不可推理，所以直接禁掉。"""
    clock = SimulatedClock(AWARE)

    with pytest.raises(ValueError, match="不能倒流"):
        clock.advance(timedelta(seconds=-1))


def test_frozen_clock_never_moves() -> None:
    clock = FrozenClock(AWARE)
    assert clock.now() == clock.now() == AWARE
    assert not hasattr(clock, "advance"), "冻结时钟不该提供推进能力"


@pytest.mark.parametrize("naive", [datetime(2026, 8, 12, 9, 0)])
def test_naive_datetimes_are_rejected(naive: datetime) -> None:
    with pytest.raises(ValueError, match="时区"):
        SimulatedClock(naive)
    with pytest.raises(ValueError, match="时区"):
        FrozenClock(naive)
