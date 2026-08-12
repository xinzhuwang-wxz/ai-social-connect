# 架构决策记录

一条 ADR 记的是**一个被推翻过或反复被问起的判断**，不是每次改动的流水账。
写它的门槛是：这条判断如果不写下来，下一个人（或下一个 agent）会重新提一遍。

命名 `NNNN-kebab-title.md`。**编号不回收**——代码注释按号引用它们
（`# … 见 ADR 0010`），把旧号让给新决策会让同一个号在两个时期指向两件事。

| 号 | 判断 | 状态 |
|---|---|---|
| [0001](./0001-stack-and-workspace.md) | 技术栈与工作区布局 | 已采纳 |
| [0002](./0002-tenant-isolation-via-rls.md) | 租户隔离用行级安全 + `SET LOCAL ROLE` | 已采纳 |
| [0003](./0003-where-ai-is-load-bearing.md) | AI 承重的位置，以及由此重排的顺序 | 已采纳 |
| [0004](./0004-reuse-a2a-task-lifecycle.md) | 协商复用 A2A 的 Task 生命周期，不自研状态机 | 已采纳 |
| [0005](./0005-generative-llm-behind-one-port.md) | 生成式 LLM 走一个端口，用 litellm 做适配 | 已采纳 |
| [0006](./0006-time-is-not-a-hard-constraint.md) | 时间不再是硬约束 | 已采纳 |
| [0007](./0007-one-assistant-per-event-not-per-person.md) | 助手属于「事」不属于「人」，但「我的助手」这个概念要有 | 已采纳 |
| [0008](./0008-record-lost.md) | *（记录在 2026-08-12 的目录事故里丢了，编号保留不补写）* | 已作废 |
| [0009](./0009-worldview-words-carry-state-not-promises.md) | 世界观词汇承担状态，承诺永远用朴素词 | 已采纳 |
| [0010](./0010-delivery-instead-of-group-solving.md) | 投递制：种子投给多人，候选表态，发起人挑到收满 | 已采纳 |
| [0011](./0011-private-rating-is-a-pairing-preference.md) | 私密评价是配对偏好不是评分；回忆门控分层 | 已采纳，实现延后 |
| [0012](./0012-completion-needs-everyone-to-say-so.md) | 一件事完成，必须每个成员各自说过 | 已采纳 |
| [0013](./0013-reach-and-consent-are-two-axes.md) | 投递范围与逐项授权是两个轴 | 已采纳 |

## 写完就推

0008 那一号是这么丢的：判断写在了一个从未推送的提交里，目录一没，
论证就只剩结论。**一条 ADR 的成本是一次 `git push`。**
