"""FastAPI 应用。

它是 OpenAPI 3.1 的产出点——前端类型由这里导出的契约自动派生，
任何一层都不手写类型。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cofield.http import envelopes, intents, opportunities


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

    @app.get("/api/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
