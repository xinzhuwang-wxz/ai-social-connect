"""时间端口。

领域核心永远不直接读系统时钟——所有 TTL、撮合窗口、切面有效期、提案过期
都经由这个端口取时间。这样仿真才能快进，测试才能不用 sleep。

违反这条的静态检查在 `scripts/check_domain_purity.py`。
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """取当前时刻。返回值必须带时区（UTC）。

    刻意只有一个方法。时间的复杂度属于实现，不属于接口。
    """

    def now(self) -> datetime: ...
