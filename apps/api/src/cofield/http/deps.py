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
from cofield.adapters.embedding.ollama import OllamaEmbedder
from cofield.adapters.extraction import RuleIntentExtractor
from cofield.adapters.persistence.engine import build_engine, campus_connection
from cofield.adapters.persistence.repositories import Repositories
from cofield.adapters.persistence.semantic import SemanticIndexWriter
from cofield.catalog import registry as action_kinds
from cofield.config import settings
from cofield.domain.model.action_kind import ActionKindRegistry
from cofield.domain.ports.clock import Clock
from cofield.domain.ports.embedder import Embedder
from cofield.domain.ports.intent_extractor import IntentExtractor
from cofield.matching.semantic import SemanticRetriever

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


def get_optional_principal_id(
    x_principal_id: Annotated[str | None, Header()] = None,
) -> UUID | None:
    """带了身份就给，没带就 `None`。

    和 `get_principal_id` 分开：有些端点不需要身份（健康检查、行动类别），
    而它们不该因为没带头就 401。
    """
    if not x_principal_id:
        return None
    try:
        return UUID(x_principal_id)
    except ValueError:
        return None


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


def get_embedder(request: Request) -> Embedder | None:
    """嵌入服务，没配就是 `None`。

    先看 app.state——测试和仿真在那里放一个替身；否则按配置装一个本地的。
    **没配等于没有**，不是"装一个连不上的"：每次匹配都先等一个超时，
    比明说这台机器上没有语义那一路糟得多。
    """
    injected: Embedder | None = getattr(request.app.state, "embedder", None)
    if injected is not None:
        return injected
    if not settings.embedding_endpoint:
        return None
    return OllamaEmbedder(
        endpoint=settings.embedding_endpoint,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )


def get_index_writer(
    conn: Annotated[Connection, Depends(get_connection)],
    embedder: Annotated[Embedder | None, Depends(get_embedder)],
) -> SemanticIndexWriter | None:
    """写语义索引的那一头。没有嵌入服务就是 `None`，调用方跳过索引。"""
    return SemanticIndexWriter(conn, embedder) if embedder is not None else None


def get_retriever(
    conn: Annotated[Connection, Depends(get_connection)],
    embedder: Annotated[Embedder | None, Depends(get_embedder)],
) -> SemanticRetriever | None:
    """读语义索引的那一头。

    **它必须真的被装到匹配路径上。** 在这之前，语义召回被实测过、被
    基准过、被写进文档（6.4 倍富集），却从来没有出现在一次真实的匹配里——
    HTTP 层构造漏斗时没传 retriever，所以线上永远是 `STRUCTURED`。
    量过的东西没接上，和没量过一样。
    """
    return SemanticRetriever(conn, embedder) if embedder is not None else None


def get_repositories(
    conn: Annotated[Connection, Depends(get_connection)],
    clock: Annotated[Clock, Depends(get_clock)],
    campus: Annotated[str, Depends(get_campus)],
    principal_id: Annotated[UUID | None, Depends(get_optional_principal_id)] = None,
) -> Repositories:
    """端点依赖这一件东西，而不是连接、时钟、租户三件。

    顺手把身份落实：外部给的身份第一次出现时，这张表里还没有它的行，
    而好几张表的外键都指向它。少了这一步，**一个刚打开这个网页的人
    第一次保存就会失败**——那是他对这个产品的第一印象。

    放在这里而不是每个写端点各自记得做：漏掉一个就是一个洞，
    而"每个人都记得"从来不是一种机制。
    """
    repos = Repositories(conn, clock, campus)
    if principal_id is not None:
        repos.principals.ensure(principal_id, campus)
    return repos


CampusDep = Annotated[str, Depends(get_campus)]
ClockDep = Annotated[Clock, Depends(get_clock)]
ConnDep = Annotated[Connection, Depends(get_connection)]
ExtractorDep = Annotated[IntentExtractor, Depends(get_extractor)]
IndexWriterDep = Annotated[SemanticIndexWriter | None, Depends(get_index_writer)]
RetrieverDep = Annotated[SemanticRetriever | None, Depends(get_retriever)]
KindsDep = Annotated[ActionKindRegistry, Depends(get_action_kinds)]
PrincipalDep = Annotated[UUID, Depends(get_principal_id)]
ReposDep = Annotated[Repositories, Depends(get_repositories)]
