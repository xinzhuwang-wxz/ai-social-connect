"""共域里说过的话。

## 和成局前的受限协商是两回事

`negotiation_messages` 的每一句都是一次披露事件——那时候两个人还不认识，
说错一句就泄漏一次。所以那边只有七种结构化类型、没有一种构成同意。

这里的人**已经在同一个组里了**。他们本来就该能自由说话。
**约束的理由消失了，约束就该消失。**

## 也不塞进 `space_items`

条目有状态、有负责人、有截止时刻、进不进度；消息一样都没有。混在一起，
"做完了多少"会被聊天量冲淡——而不变量 6 说的正是**空间因真实行动证据
生长，不因聊天量生长**。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Connection, Row

from .schema import space_messages


class Kind(StrEnum):
    #: 一句话。
    SAID = "said"
    #: 一张待聊的话题卡。**只能来自还没定的事**，不能凭空造。
    TOPIC = "topic"


@dataclass(frozen=True, slots=True)
class Message:
    id: UUID
    space_id: UUID
    author_id: UUID
    kind: Kind
    text: str
    created_at: datetime
    #: 是不是助手说的。**一眼可辨**——分不清谁说的，
    #: "AI 起草、人类决定"就只是一句话。
    is_agent: bool = False
    #: 挂在哪张话题卡下面。空 = 主线。
    replies_to: UUID | None = None
    #: 这张话题卡关于哪条待定的事。助手发的话题**必须**指得回去。
    about_item_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Thread:
    """一张话题卡，连同它下面的回复。

    只有一层。两层以上的嵌套在手机上没人读得下去，而读不下去的讨论
    等于没发生。
    """

    topic: Message
    replies: tuple[Message, ...]

    @property
    def answered(self) -> bool:
        """有没有人回过。

        **没人回的话题不是失败，是信号**：它说明这张卡问得不对，
        或者这件事大家其实不在意。助手据此少发同类的。
        """
        return bool(self.replies)


def _to_domain(row: Row[tuple[object, ...]]) -> Message:
    return Message(
        id=row.id,
        space_id=row.space_id,
        author_id=row.author_id,
        kind=Kind(row.kind),
        text=row.text,
        created_at=row.created_at,
        is_agent=row.is_agent,
        replies_to=row.replies_to,
        about_item_id=row.about_item_id,
    )


class MessageRepository:
    def __init__(self, conn: Connection, campus_id: str) -> None:
        self._conn = conn
        self._campus = campus_id

    def say(
        self,
        space_id: UUID,
        *,
        author_id: UUID,
        text: str,
        now: datetime,
        kind: Kind = Kind.SAID,
        is_agent: bool = False,
        replies_to: UUID | None = None,
        about_item_id: UUID | None = None,
    ) -> Message:
        """说一句话，或者发一张话题卡。

        空话不落库：一条只有空格的消息在界面上是一个占位的气泡，
        它唯一的作用是让人以为有人说了什么。
        """
        if not text.strip():
            raise ValueError("空消息不落库")
        if kind is Kind.TOPIC and is_agent and about_item_id is None:
            # 助手凭空造的话题会很快被所有人忽略，而一旦被忽略，
            # 之后它说什么都没人看了。指不回去就不许发。
            raise ValueError("助手发的话题必须指得回一件还没定的事")

        if replies_to is not None:
            # **回复只能挂在这个空间里的一张话题卡下面。**
            #
            # 不校验的话，回给一条普通消息、或者指向一个随机 id 的回复
            # 会被接受，然后在 `threads()` 里**消失**——只在平铺列表里出现。
            # 「只有一层」原本是组装时保证的，代价是消息被静默吞掉。
            # 而静默地少一条，比明确地拒一条糟得多。
            parent = self._conn.execute(
                sa.select(space_messages.c.kind, space_messages.c.space_id).where(
                    space_messages.c.id == replies_to
                )
            ).one_or_none()
            if parent is None or parent.space_id != space_id:
                raise ValueError("回的那条不在这里")
            if Kind(parent.kind) is not Kind.TOPIC:
                raise ValueError("只能回在话题卡下面")

        message = Message(
            id=uuid4(),
            space_id=space_id,
            author_id=author_id,
            kind=kind,
            text=text.strip(),
            created_at=now,
            is_agent=is_agent,
            replies_to=replies_to,
            about_item_id=about_item_id,
        )
        self._conn.execute(
            sa.insert(space_messages).values(
                id=message.id,
                campus_id=self._campus,
                space_id=space_id,
                author_id=author_id,
                is_agent=is_agent,
                kind=kind.value,
                text=message.text,
                replies_to=replies_to,
                about_item_id=about_item_id,
                created_at=now,
            )
        )
        return message

    def history(self, space_id: UUID) -> tuple[Message, ...]:
        """全部说过的话，按时间。

        **不分页、不截断。** 「大家也可以看到整体的聊天记录」是这一层的
        承诺；一个默认只给最近五十条的接口会让"看看当时怎么说的"
        变成一件做不到的事。真到了需要分页的量级再加，那是一个
        可以被观测到的时刻。
        """
        rows = self._conn.execute(
            sa.select(space_messages)
            .where(space_messages.c.space_id == space_id)
            # 兜底键必须**单调**。原来用的是 `id`（随机 UUID），于是助手
            # 一次落的两张话题卡每读一次顺序都可能不一样。
            .order_by(space_messages.c.created_at.asc(), space_messages.c.seq.asc())
        ).all()
        return tuple(_to_domain(r) for r in rows)

    def threads(self, space_id: UUID) -> tuple[Thread, ...]:
        """话题卡，连同各自的回复。"""
        everything = self.history(space_id)
        replies: dict[UUID, list[Message]] = {}
        for message in everything:
            if message.replies_to is not None:
                replies.setdefault(message.replies_to, []).append(message)
        return tuple(
            Thread(topic=m, replies=tuple(replies.get(m.id, ())))
            for m in everything
            if m.kind is Kind.TOPIC
        )

    def already_asked_about(self, space_id: UUID) -> frozenset[UUID]:
        """助手已经就哪些事发过话题了。

        同一件事问第二遍最伤——它说明这个助手没在听。
        """
        rows = self._conn.execute(
            sa.select(space_messages.c.about_item_id)
            .where(space_messages.c.space_id == space_id)
            .where(space_messages.c.is_agent.is_(True))
            .where(space_messages.c.about_item_id.isnot(None))
        ).all()
        return frozenset(r.about_item_id for r in rows)
