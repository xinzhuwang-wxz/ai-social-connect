"""冻结时钟：单元测试用。

与 SimulatedClock 的区别不是命名而是保证——它**定义上**不会变，
所以被测代码即使误调 advance 也不会让断言随执行顺序漂移。
"""

from __future__ import annotations

from datetime import UTC, datetime


class FrozenClock:
    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("时刻必须带时区")
        self._instant = instant.astimezone(UTC)

    def now(self) -> datetime:
        return self._instant
