# ADR 0001 · 技术栈与工作区布局

- 状态：已采纳
- 日期：2026-08-12
- 相关：[`03-技术架构`](../03-技术架构.md) §12.1.1

## 背景

需要选一套栈，且要满足两条已定的红线：领域核心不依赖第三方 SDK 类型，
契约先行且三层不手写类型。

## 决定

**Python 3.12 + FastAPI + Pydantic v2 + PostgreSQL 18；前端 Next.js；
根部 pnpm 工作区统一 `test` / `typecheck` 入口；Python 依赖用 uv。**

目录：

```
apps/api/src/cofield/
  domain/     领域核心。禁止 import 第三方库与外圈（静态检查强制）
  adapters/   外圈：clock / persistence / …
  app/        用例编排
  http/       FastAPI
apps/web/     Next.js
scripts/      跨语言的检查脚本
```

## 理由

求解层**必须**是 Python——OR-Tools、sentence-transformers、Mesa 都没有等价的
TS 方案。而 Pydantic 已经是领域 schema 层，FastAPI 从 Pydantic 直接导出
OpenAPI 3.1，于是"单一事实源"不需要额外工程就成立。

选 uv 而不是 poetry：装 Python 与解依赖都快一个数量级，且能自己管解释器版本，
本机 3.10 不必污染。

根部用 pnpm 而非 make：目标里写死了 `pnpm test && pnpm typecheck`，
让它真的是入口，而不是又一层转发。

## 后果

- 跨语言 schema 契约暂时不需要 BAML——只有 Python 一侧产出契约。将来若出现
  必须用 TS 写的服务，再引入。
- `apps/api` 不在 pnpm 工作区里（它不是 node 包），根 `package.json` 用
  `cd apps/api && uv run …` 转发。多一层间接，换来两套包管理器互不干扰。
