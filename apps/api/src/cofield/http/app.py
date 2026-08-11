"""FastAPI 应用。

它是 OpenAPI 3.1 的产出点——前端类型由这里导出的契约自动派生，
任何一层都不手写类型。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from cofield.adapters.clock import SimulatedClock
from cofield.config import settings
from cofield.http import (
    echo,
    envelopes,
    intents,
    memory,
    opportunities,
    proposals,
    spaces,
    stash,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="共域 CoField API",
        version="0.1.0",
        description=(
            "以共同事件为核心的校园社交连接器。\n\n"
            "领域词汇见 CONTEXT.md；用户可见文案不使用这些词汇，映射见 docs/07。"
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(intents.router, prefix="/api")
    app.include_router(opportunities.router, prefix="/api")
    app.include_router(envelopes.router, prefix="/api")
    app.include_router(stash.router, prefix="/api")
    app.include_router(proposals.router, prefix="/api")
    app.include_router(spaces.router, prefix="/api")
    app.include_router(memory.router, prefix="/api")
    app.include_router(echo.router, prefix="/api")

    @app.get("/api/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok", "demo_mode": str(settings.demo_mode).lower()}

    if settings.demo_mode:
        # 演示模式下时钟可以被推着走。**关掉时这条路由根本不注册**——
        # 一个能改系统时间的接口在生产里不该只是"权限不够"，
        # 而应该探测不到。
        app.state.clock = SimulatedClock(datetime.now(UTC))

        @app.post("/api/clock:advance", tags=["ops"])
        def advance(seconds: int = 3600) -> dict[str, str]:
            """把时钟往前推。

            核心循环里有两处要等：撮合窗口六小时、记忆回流两周。
            演示不该真等——这正是 `Clock` 端口从第一天就注入的理由。
            """
            clock = getattr(app.state, "clock", None)
            if not isinstance(clock, SimulatedClock):
                raise HTTPException(status_code=404, detail="没开演示模式")
            clock.advance(timedelta(seconds=seconds))
            return {"now": clock.now().isoformat()}

    return app


app = create_app()
