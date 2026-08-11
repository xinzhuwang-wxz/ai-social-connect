"""受限协商的仓储：A2A Task 与七种消息落到我们自己的两张表上。

## 为什么不直接用 `a2a.server.tasks.DatabaseTaskStore`

复用优先是这个仓库的红线，所以先评估了它。**结论是不能直接用**，四条理由，
前两条各自就足以否决：

1. **它绕开行级安全。** 它自己 `async_sessionmaker(engine)` 开会话，从不执行
   `SET LOCAL ROLE cofield_app`，也不 `set_config('app.current_campus', …)`。
   我们的租户隔离是**连接的属性**而不是查询里的 WHERE（见 `engine.py`）：
   它这样连上来，要么以属主身份连接从而 BYPASSRLS，要么策略求值为 NULL
   一行都读不到。它自己的隔离手段是 `owner` 列上的 `WHERE owner = …`——
   application-level filtering，正是我们刻意不依赖的那种。
2. **它在运行时 `create_all` 建自己的 `tasks` 表。** 我们的表由迁移 0009 建，
   并在同一次迁移里挂上 `ENABLE/FORCE ROW LEVEL SECURITY` 与 campus 策略。
   一张被 SDK 在运行时建出来的表不会有这些策略，也不在 `RLS_TABLES` 清单里，
   隔离测试因此测不到它。
3. **它是 `AsyncEngine`。** 本项目持久化层整个是同步的（`sqlalchemy.Engine` +
   事务作用域的 `SET LOCAL`）。为它引一套异步引擎，等于多一个连接池、
   多一套事务边界，而 `SET LOCAL ROLE` 的语义正依赖"一个事务一个连接"。
4. 它的 `owner` 语义是"哪个用户的任务"，我们要的是"哪个校园 + 哪个提案"。

所以这里实现我们自己的 TaskStore。它**不继承** `a2a.server.tasks.TaskStore`：
那个 ABC 的四个方法都是 `async` 且要求 `ServerCallContext`，在同步栈里实现它
只能用阻塞事件循环的假异步，比诚实地写一个同步类更糟。存进去、读出来的
仍然是原样的 `a2a.types.Task`——**协议类型没有被翻译成我们自己的词**，
复用的是 Task 生命周期本身，这才是 ADR 0004 要的东西。

## 这里写不了承诺

这个模块只对 `negotiation_tasks` 与 `negotiation_messages` 两张表发语句。
"AI 可以代为表达，但不能代为承诺"在这一层的落实方式就是这么朴素：
没有任何一条通往 `commitments` 的路径。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from a2a.types import Message, Role, Task, TaskState

# protobuf 不带类型存根，见 `negotiation/messages.py` 里同一处注释。
from google.protobuf.json_format import MessageToDict  # type: ignore[import-untyped]
from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert as pg_insert

from cofield.negotiation.messages import (
    MessageKind,
    SpeakerMode,
    Utterance,
    decode_payload,
    from_a2a,
    to_a2a,
)

from .schema import negotiation_messages, negotiation_tasks


class NegotiationTaskStore:
    """一次协商的持久化。租户绑在连接上，这里的语句一律不提 campus 过滤。"""

    def __init__(self, conn: Connection, campus_id: str) -> None:
        self._conn = conn
        self._campus = campus_id

    def save(self, task: Task, *, proposal_id: UUID, now: datetime) -> None:
        """写任务当前状态，并追加还没落库的消息。

        状态原样存 A2A 的名字（`TASK_STATE_INPUT_REQUIRED` 这种），不翻译成
        我们自己的词——一旦翻译，"中断态是协议的一等状态"这件事就只剩注释了。

        消息按 `message_id` 幂等追加：重复 `save()` 是安全的，因为一条已经说过的
        话不该因为多存一次就变成两条。
        """
        state_name = TaskState.Name(task.status.state)
        self._conn.execute(
            pg_insert(negotiation_tasks)
            .values(
                task_id=task.id,
                campus_id=self._campus,
                context_id=task.context_id,
                proposal_id=proposal_id,
                state=state_name,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[negotiation_tasks.c.task_id],
                set_={"state": state_name, "updated_at": now},
            )
        )
        for message in task.history:
            self._append(message, task_id=task.id)

    def get(self, task_id: str) -> Task | None:
        """读回一个 Task，含完整历史。读不到就是 `None`——包括跨租户读。"""
        row = self._conn.execute(
            sa.select(negotiation_tasks).where(negotiation_tasks.c.task_id == task_id)
        ).one_or_none()
        if row is None:
            return None
        return self._rebuild(row)

    def list_for_proposal(self, proposal_id: UUID) -> list[Task]:
        rows = self._conn.execute(
            sa.select(negotiation_tasks)
            .where(negotiation_tasks.c.proposal_id == proposal_id)
            .order_by(negotiation_tasks.c.created_at)
        ).all()
        return [self._rebuild(r) for r in rows]

    def contexts_of(self, proposal_id: UUID) -> list[str]:
        """这个提案下出现过几个 `contextId`。

        同一次成局的多轮协商共享 contextId——它多出一个，就说明有人在"补充输入"
        的时候另开了一次，而不是接着原来那次谈。
        """
        rows = self._conn.execute(
            sa.select(negotiation_tasks.c.context_id)
            .where(negotiation_tasks.c.proposal_id == proposal_id)
            .distinct()
        ).all()
        return [r.context_id for r in rows]

    def delete(self, task_id: str) -> None:
        """协商过程不产生长期记忆，所以它整体是可丢弃的。"""
        self._conn.execute(
            sa.delete(negotiation_messages).where(negotiation_messages.c.task_id == task_id)
        )
        self._conn.execute(
            sa.delete(negotiation_tasks).where(negotiation_tasks.c.task_id == task_id)
        )

    # --- 内部 ---------------------------------------------------------------

    def _append(self, message: Message, *, task_id: str) -> None:
        # 先解一遍再存：第八种消息在**写库这一步**也过不去。
        # 校验只放在会话层的话，任何绕过会话的写入路径都能把它带进来。
        utterance = from_a2a(message)
        data = cast(dict[str, Any], MessageToDict(message.parts[0].data))
        kind = MessageKind(data["kind"])
        payload = {k: v for k, v in data.items() if k != "kind"}
        self._conn.execute(
            pg_insert(negotiation_messages)
            .values(
                id=UUID(message.message_id),
                campus_id=self._campus,
                task_id=task_id,
                author_id=utterance.author_id,
                role=Role.Name(utterance.role),
                kind=kind.value,
                payload=payload,
                speaker_mode=utterance.mode.value,
                created_at=utterance.said_at,
            )
            .on_conflict_do_nothing(index_elements=[negotiation_messages.c.id])
        )

    def _rebuild(self, task_row: sa.Row[Any]) -> Task:
        task_id: str = task_row.task_id
        context_id: str = task_row.context_id
        task = Task(id=task_id, context_id=context_id)
        task.metadata.update({"proposal_id": str(task_row.proposal_id)})
        task.status.state = TaskState.Value(task_row.state)
        for row in self._conn.execute(
            sa.select(negotiation_messages)
            .where(negotiation_messages.c.task_id == task_id)
            .order_by(negotiation_messages.c.created_at, negotiation_messages.c.id)
        ).all():
            task.history.append(self._message(row, task_id=task_id, context_id=context_id))
        return task

    def _message(self, row: sa.Row[Any], *, task_id: str, context_id: str) -> Message:
        utterance = Utterance(
            payload=decode_payload(MessageKind(row.kind), cast(dict[str, Any], row.payload)),
            author_id=row.author_id,
            mode=SpeakerMode(row.speaker_mode),
            said_at=row.created_at,
        )
        return to_a2a(
            utterance, message_id=row.id, task_id=task_id, context_id=context_id
        )
