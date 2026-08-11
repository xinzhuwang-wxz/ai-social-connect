"""依赖装配。

领域核心通过端口拿到能力，装配发生在这里——换掉任何一个实现都不该触及
领域测试，这是判断边界画得对不对的标准。
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import Connection, Engine

from cofield.adapters.clock import SystemClock
from cofield.adapters.extraction import RuleIntentExtractor
from cofield.adapters.persistence.engine import build_engine, campus_connection
from cofield.catalog import registry as action_kinds
from cofield.config import settings
from cofield.domain.model.action_kind import ActionKindRegistry
from cofield.domain.ports.clock import Clock
from cofield.domain.ports.intent_extractor import IntentExtractor

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = build_engine(settings.database_url)
    return _engine


def get_clock(request: Request) -> Clock:
    """时钟从应用状态取，不是新建。

    仿真运行时会把 `SimulatedClock` 放进 app.state，于是整条链路——TTL、
    撮合窗口、切面有效期——都跟着推进，不需要任何一处特判。
    """
    clock: Clock | None = getattr(request.app.state, "clock", None)
    return clock or SystemClock()


def get_extractor(request: Request) -> IntentExtractor:
    extractor: IntentExtractor | None = getattr(request.app.state, "extractor", None)
    return extractor or RuleIntentExtractor()


def get_action_kinds() -> ActionKindRegistry:
    return action_kinds


def get_campus(x_campus_id: Annotated[str | None, Header()] = None) -> str:
    return x_campus_id or settings.default_campus


def get_principal_id(
    x_principal_id: Annotated[str | None, Header()] = None,
) -> UUID:
    """当前用户。

    M1 阶段用请求头承载身份，真校园身份接入在后续里程碑。这不影响领域
    边界——所有下游只看到一个 `UUID`。
    """
    if not x_principal_id:
        raise HTTPException(status_code=401, detail="缺少身份")
    try:
        return UUID(x_principal_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="身份格式不对") from None


def get_connection(
    campus: Annotated[str, Depends(get_campus)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> Generator[Connection, None, None]:
    """已绑定租户、以应用角色执行的连接。业务代码拿不到别的连接。

    engine 必须**经依赖注入**取得而不是直接调 `get_engine()`——直接调会绕过
    依赖覆盖，测试就会静默连到另一个库上。
    """
    with campus_connection(engine, campus) as conn:
        yield conn


CampusDep = Annotated[str, Depends(get_campus)]
ClockDep = Annotated[Clock, Depends(get_clock)]
ConnDep = Annotated[Connection, Depends(get_connection)]
ExtractorDep = Annotated[IntentExtractor, Depends(get_extractor)]
KindsDep = Annotated[ActionKindRegistry, Depends(get_action_kinds)]
PrincipalDep = Annotated[UUID, Depends(get_principal_id)]
