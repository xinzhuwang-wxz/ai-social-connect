"""数据库连接、应用角色与租户上下文。

两条设计，都是为了让"忘记过滤"在结构上发生不了：

1. **业务查询以 `cofield_app` 角色执行。** 超级用户和表属主都会绕过行级安全，
   开发环境里应用连的往往正是属主——不切角色的话，隔离测试会变成一场表演。
   角色是 NOLOGIN 的，靠事务内 `SET LOCAL ROLE` 切入，因此不需要第二套连接串。
2. **租户是连接的属性，不是查询里的 WHERE。** 走这里拿到的连接都已绑定 campus。

`SET LOCAL` 的作用域是事务：连接归还池子时上下文自动失效，不会把上一个
租户或角色带给下一个请求。
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy import Connection, Engine, create_engine

from cofield.adapters.persistence.schema import APP_ROLE, CAMPUS_SETTING


def build_engine(url: str) -> Engine:
    return create_engine(url, future=True, pool_pre_ping=True)


@contextmanager
def app_connection(engine: Engine) -> Generator[Connection, None, None]:
    """切到应用角色但**不设**租户。

    此时策略求值为 NULL，读不到任何行——默认拒绝。留这个入口是为了能测出
    "忘记设租户"时系统是沉默地返回空集，而不是沉默地返回全部。
    """
    with engine.begin() as conn:
        conn.execute(sa.text(f"SET LOCAL ROLE {APP_ROLE}"))
        yield conn


@contextmanager
def campus_connection(engine: Engine, campus_id: str) -> Generator[Connection, None, None]:
    """开一个绑定到指定 campus、以应用角色执行的事务连接。"""
    if not campus_id or not campus_id.strip():
        raise ValueError("campus_id 不能为空——不允许在无租户上下文下访问数据")

    with engine.begin() as conn:
        conn.execute(sa.text(f"SET LOCAL ROLE {APP_ROLE}"))
        conn.execute(
            sa.text(f"SELECT set_config('{CAMPUS_SETTING}', :campus, true)"),
            {"campus": campus_id},
        )
        yield conn


@contextmanager
def owner_connection(engine: Engine) -> Generator[Connection, None, None]:
    """以属主身份连接，绕过 RLS。

    只允许迁移、种子数据装载和测试清理使用。业务代码用它就是绕过了隔离，
    这一点由代码审查把关——没有静态检查能替代它。
    """
    with engine.begin() as conn:
        yield conn
