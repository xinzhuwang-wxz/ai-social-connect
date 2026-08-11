# 共域 CoField

以共同事件为核心的校园社交连接器。后端 FastAPI + PostgreSQL 18，前端 Next.js 15。

**这一页是给开局的人和开局的 agent 看的。**它不重复 README，只回答一件事：
接手这个仓库的头十分钟该读什么、该守什么、跑什么命令能知道自己有没有搞砸。

---

## 开工前必读

按顺序，不要跳。每一条后面写的是**什么时候**必须读它——不是"建议读"。

| 文档 | 什么时候 |
|---|---|
| [`CONTEXT.md`](./CONTEXT.md) | **写任何代码或文档之前。** 领域语言 + 11 条不变量 |
| [`docs/GOAL.md`](./docs/GOAL.md) | **每次开工前。** 交付物、里程碑、完成的定义 |
| [`docs/07-产品语言与界面原则.md`](./docs/07-产品语言与界面原则.md) | **写任何用户可见文案之前。** 领域词→用户词映射表 |
| [`docs/03-技术架构.md`](./docs/03-技术架构.md) | 动后端实现之前 |
| [`docs/08-前端规格.md`](./docs/08-前端规格.md) | 动前端之前。每屏读什么接口、有哪些状态 |
| [`docs/06-仿真与测试人口.md`](./docs/06-仿真与测试人口.md) | 写测试之前。六个维度为什么不能随机 |
| [`HANDOFF.md`](./HANDOFF.md) 「别重开」一节 | **提议任何架构改动之前。** 这些判断已经被推翻过至少一次 |

写测试时照着 `apps/api/tests/test_funnel.py` 的风格：断言的是**筛得对**而不是**能筛**，
注释解释判断而不复述代码。

---

## 工程红线

八条，完整版在 [README](./README.md#工程红线)。最容易被违反的四条：

1. **不用 mock/stub。** 真 Postgres、真 pgvector、真 CP-SAT、真本地 Ollama。
   **唯一被替换的是「人」**（`is_synthetic` + 仿真租户）。
   例外只有一处：模拟**外部服务宕机**（如嵌入服务不可用）——被替换的不是我们自己的层。
2. **领域核心不得调 `now()`，不得 import 第三方 SDK 类型。**
   时间走注入的 `Clock` 端口，否则仿真无法快进。`scripts/check_domain_purity.py` 守着这条。
3. **不手写类型。** Pydantic → OpenAPI 3.1 → 前端类型自动派生。
   一个概念在 DB / API / 前端同名，命名来源是 `CONTEXT.md`。
4. **领域词汇不得出现在界面上。** "同意凭证""记忆切面""成局证明"是代码的语言。

三条无论进度多紧都不可越过（见 `docs/GOAL.md`）：

- AI 可以代为表达，**但不能代为承诺**。承诺状态只接受真人签名的命令
- 未获真人确认的提案不创建事件、共域或关系边
- **稳定性检查未通过的分区不得成为提案**

---

## 命令

```bash
pnpm test                  # 后端 pytest + 前端 vitest
pnpm typecheck             # mypy strict + tsc --noEmit
pnpm lint:domain-purity    # 领域核心纯度（AST 检查）
pnpm gen:api               # Pydantic → OpenAPI → TS 类型
pnpm check:contract        # 重新生成并断言无 diff
docker compose up          # 一条命令起全套
```

数据库镜像是 `pgvector/pgvector:pg18`，**不是** `postgres:18-alpine`——后者不含 `vector` 扩展。

后端测试默认起 testcontainer；已有实例时设 `COFIELD_TEST_DATABASE_URL` 跳过。
环境里的 `http_proxy` 会干扰 pnpm 与本地 Ollama，遇到网络问题先 `unset http_proxy https_proxy`。

---

## 派子智能体时

这个仓库的并行工作靠**文件边界**而不是靠约定。派活之前先划清楚：

- 共享文件——`schema.py`、`app.py`、`deps.py`、`conftest.py`、`migrations/`、
  `pyproject.toml`、`http/` 下任何文件、`apps/web/lib/api-types.ts`（自动生成）——
  **一次只能有一个人动**，通常是主会话
- 并行的活各自限定在自己的两三个新文件里，通过一份**先写好的契约**通信
  （范例：`apps/api/src/cofield/matching/contracts.py`）
- 契约本身不许被并行的任何一方修改。发现契约有缺陷就报回来，不要就地改

---

## Agent skills

### Issue tracker

GitHub，仓库 `xinzhuwang-wxz/ai-social-connect`，用 `gh` CLI 读写 issue。
外部 PR **不**作为请求面纳入 triage 队列。

### Triage labels

五个标准角色，标签名即角色名：
`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。

仓库另有一个非 triage 标签 `tracer-bullet`（端到端垂直切片），与状态机无关，别当成角色。

### Domain docs

单上下文。领域语言在根 `CONTEXT.md`，架构决策在 `docs/adr/`（按 `NNNN-kebab-title.md` 编号）。

`apps/api`（uv）与 `apps/web`（pnpm）是两个包但**同一个领域**——
pnpm workspace 只含 `apps/web`，不要因此当成多上下文仓库。

改动如果推翻了一条已写下的判断，**先加 ADR 再动代码**，并在 `docs/05` §5 追加一条评审记录。
