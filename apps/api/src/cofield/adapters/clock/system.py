"""生产时钟。"""

from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    """真实时间。这是唯一允许调用系统时钟的地方。"""

    def now(self) -> datetime:
        return datetime.now(UTC)
