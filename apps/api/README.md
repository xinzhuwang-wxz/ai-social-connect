# cofield-api

```bash
docker compose up -d db                 # 起数据库（仓库根目录）
cd apps/api
uv sync                                 # 装依赖
uv run alembic upgrade head             # 建表与策略
uv run pytest                           # 测试（自带 PostgreSQL 18 容器）
uv run mypy src                         # 类型
uv run python ../../scripts/check_domain_purity.py   # 领域纯度
```

`pytest` 默认自己起容器。若已有实例，设 `COFIELD_TEST_DATABASE_URL` 指过去。

## 边界

- `src/cofield/domain/` 是领域核心：**不得 import 第三方库，不得直接读时钟**。
  两条都由 `scripts/check_domain_purity.py` 静态强制。
- 业务查询一律经 `campus_connection`，它切到 `cofield_app` 角色并绑定租户。
  `owner_connection` 绕过行级安全，只给迁移、种子和测试清理用。

## 跑起来

```bash
uv run uvicorn cofield.http.app:app --reload --port 8000
# 契约：http://localhost:8000/openapi.json  ·  文档：/docs
```
