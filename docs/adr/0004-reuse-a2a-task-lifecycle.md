# ADR 0004 · 协商复用 A2A 的 Task 生命周期，不自研状态机

- 状态：已采纳
- 日期：2026-08-12
- 相关：issue #8，[`03-技术架构`](../03-技术架构.md) §9

## 背景

受限协商需要一个状态机：提案发出、对方处理、需要真人拍板、达成或谈崩。
原计划自研。

## 决定

**用官方 `a2a-sdk` 的 Task 生命周期承载协商，不自己写状态机。**

关键是 A2A 有两个**非终止的中断态**，语义正是我们要的"交还给真人"：

| 状态 | 语义 |
|---|---|
| `TASK_STATE_INPUT_REQUIRED` | 需要更多输入才能继续。暂停但不结束，客户端用同一个 `taskId` + `contextId` 补充后继续 |
| `TASK_STATE_AUTH_REQUIRED` | 需要凭证才能继续。同样是暂停不结束 |
| `COMPLETED` / `FAILED` / `CANCELED` / `REJECTED` | 终止态 |

一并复用：`AgentCard.securitySchemes`、§7.6 的 in-task authorization、
`Message.role`（`ROLE_USER` / `ROLE_AGENT`）、`parts` 结构、
`AgentExecutor` / `TaskStore` / `DefaultRequestHandler` / `ClientFactory`。

## 理由

**"交还给真人"是协议的一等状态，不是我们的发明。** 自研一个语义相同的状态机，
既是重复造轮子，也会让将来接第三方个人代理时多一层翻译。

`ROLE_USER` / `ROLE_AGENT` 也直接对上「代聊三档」——消息作者是人还是 agent
在协议层就有位置，不需要另加字段（见 07 §4）。

## 边界不变

A2A 表达不了授权范围、同意、委托边界、可撤销性与可审计性（见
[Governance Gaps 论文](https://arxiv.org/pdf/2606.31498)）。这五样仍然自建，
落在领域核心。协议管**怎么谈**，领域管**谈的结果算不算数**。

七种受限消息类型仍然保留，它们是 `Message.parts` 里的结构化载荷，
不是替代 A2A 的另一套协议。

## 附带证据：为什么协商必须受限

微软 Magentic Marketplace 在双边 agent 市场上的实证：

- **选择过载**：搜索上限 3 → 100，福利反而下降（Claude Sonnet 4 从 1800 掉到 600）
- **首提案偏差**：所有模型都严重偏向第一个提案，**响应速度比质量的优势达 10–30 倍**
- agent 易受心理操纵与提示注入

前两条分别给"只给 2–3 个提案"和"窗口清算而非即时撮合"提供了**独立于
JPE 2020 之外的第二条依据**：即时撮合下赢的是回得快的 agent，不是最合适的人。
第三条说明自由格式协商是攻击面。
