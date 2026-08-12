"""用户主体仓储。

行与领域对象之间的转换只在这一处发生。领域层拿到的永远是 `Principal`，
永远不是一行 `Row`——这样换掉持久化实现不会波及领域测试。
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection, Row
from sqlalchemy.dialects.postgresql import ARRAY as PgArray
from sqlalchemy.dialects.postgresql import insert as pg_insert

from cofield.domain.model.principal import (
    CampusId,
    Principal,
    placeholder_name,
)
from cofield.domain.ports.clock import Clock

from .schema import principals


def _to_domain(row: Row[tuple[UUID, str, str, bool]]) -> Principal:
    """行 → 领域对象。

    **每一个领域字段都要在这里出现。** 原先这里只搬了四个字段，于是
    `Principal.self_intro` 和 `major` 读出来永远是 `None`——领域对象上
    有这个字段、库里也有这一列，中间这一步把它丢了。这种丢法不会报错，
    只会让下游看到一个"这个人什么都没写"。
    """
    return Principal(
        id=row.id,
        campus_id=CampusId(row.campus_id),
        display_name=row.display_name,
        is_synthetic=row.is_synthetic,
        self_intro=row.self_intro,
        major=row.major,
        skills=tuple(row.skills or ()),
        open_to=tuple(row.open_to or ()),
        zone=row.zone,
    )


class PrincipalRepository:
    """连接已绑定租户，因此这里没有一个方法接受 campus_id 参数。"""

    def __init__(self, conn: Connection, clock: Clock) -> None:
        self._conn = conn
        self._clock = clock

    def ensure(self, principal_id: UUID, campus_id: str) -> None:
        """第一次见到这个身份，就把它的行建出来。

        ## 为什么必须有这一步

        身份是外部给的（现在是请求头，将来是校园 OIDC 的声明），而
        `intent_signals.principal_id` 有外键指向这张表。少了这一步，
        **一个刚打开这个网页的人第一次点「开始找人」就会失败**——
        而那正是他对这个产品的第一印象。

        这个洞躲过了几百个后端测试：它们的 fixture 都先把人建好了。
        只有真浏览器带着一个全新身份打真栈才碰得到。

        ## 这是 JIT 供给，不是"谁都能建账号"

        真实系统里也是这么做的：校园 OIDC 认证通过之后，第一次登录才
        创建本地账号。这里的请求头是那个声明的临时替身——**换成真身份
        接入时，换掉的是"声明从哪来"，不是这一步本身。**

        名字先给一个能区分彼此的占位。真名来自校园身份，不该由用户
        随手填——但在那之前，两个人在群聊里长得一模一样比占位名更糟。

        原来用的是「同学」加 id 后四位，而它**会撞**：一支队里出现三个
        「同学0002」的时候，"要不要和这几个人一起做事"这个问题就问不成了。
        """
        self._conn.execute(
            pg_insert(principals)
            .values(
                id=principal_id,
                campus_id=campus_id,
                display_name=placeholder_name(principal_id),
                is_synthetic=False,
                created_at=self._clock.now(),
            )
            .on_conflict_do_nothing(index_elements=[principals.c.id])
        )

    def name_self(self, principal_id: UUID, display_name: str) -> Principal:
        """本人给自己起个名。

        ## 为什么这一步必须有

        没有它，第一次打开的人被静默分配一个占位名，队友在群里看到的是
        「同学f2a1」——**而这个产品的第一件事是让两个人愿意一起做点事**。
        一个连名字都没有的人提出的邀请，收到的人先要判断这是不是真人。

        真名将来来自校园身份。在那之前它由本人填——**占位名不是"还没接
        身份系统"的临时方案，它是一个真实存在的产品缺口**。
        """
        row = self._conn.execute(
            sa.update(principals)
            .where(principals.c.id == principal_id)
            .values(display_name=display_name)
            .returning(principals)
        ).one()
        return _to_domain(row)

    def has_named_self(self, principal_id: UUID) -> bool:
        """他自己起过名没有。

        判据是"名字还是不是那个占位"——**不加一列 `named_at`**：
        多一列就多一个可能和事实不一致的地方，而占位名本身就是事实。
        """
        current = self._conn.execute(
            sa.select(principals.c.display_name).where(principals.c.id == principal_id)
        ).scalar_one_or_none()
        return current is not None and current != placeholder_name(principal_id)

    def describe(
        self,
        principal_id: UUID,
        *,
        skills: Sequence[str],
        open_to: Sequence[str],
        self_intro: str | None,
        zone: str | None,
        major: str | None = None,
    ) -> Principal:
        """本人改写自己这一面。

        ## 为什么这是一次覆盖而不是一次追加

        这四项都是**当前状态**，不是历史。"我不再想参与拍摄了"必须能表达，
        而只能追加的接口表达不了取消——用户会发现自己被一件早就不想干的事
        反复找上门，然后再也不填这一面。

        ## 词表校验不在这里

        归一和拒绝发生在 HTTP 那一层，因为**要告诉用户哪一项没被认出来**。
        仓储只负责写；一个默默把不认识的词丢掉的仓储，会让"我明明填了"
        变成一个查不出原因的问题。
        """
        row = self._conn.execute(
            sa.update(principals)
            .where(principals.c.id == principal_id)
            .values(
                skills=list(skills),
                open_to=list(open_to),
                self_intro=self_intro,
                zone=zone,
                major=major,
            )
            .returning(principals)
        ).one()
        return _to_domain(row)

    def learned(self, principal_id: UUID, skills: Sequence[str]) -> None:
        """他刚刚在一件具体的事情里说了自己能出什么——记下来。

        ## 为什么必须有这条回流

        没有它，产品的前提就是"你得先跟软件交代自己"：只有那一屏写过
        `skills` 的人才可能被别人找到。而人真正说清自己的时刻不在表单里，
        **在他发需求那一刻的「我能出」**——那是有具体语境的一句话，
        比对着一张技能表打勾可靠得多，也是他本来就要说的话。

        ## 为什么是合并不是覆盖

        「我这边」那一屏是覆盖（他在那里说"我不再想干这个了"）。这里是
        追加：一次说过的话不因为下一次没提就作废。取消永远只能由本人
        在那一屏上做——**系统学得到，但只有他删得掉。**

        ## 为什么不走"你看对不对"那一步

        因为这不是系统猜的，是他自己写在需求卡上、并且亲手点了确认的。
        再问一遍"你会剪辑吗"是把他刚说过的话当没听见。
        系统**猜**出来的东西走的是另一条路（记忆切面，逐条确认）。
        """
        wanted = [s for s in dict.fromkeys(skills) if s]
        if not wanted:
            return
        self._conn.execute(
            sa.update(principals)
            .where(principals.c.id == principal_id)
            .values(
                skills=sa.func.array(
                    sa.select(sa.distinct(sa.func.unnest(
                        sa.func.array_cat(
                            principals.c.skills, sa.cast(wanted, PgArray(sa.Text))
                        )
                    ))).scalar_subquery()
                )
            )
        )

    def remind_about(self, principal_id: UUID, skills: Sequence[str]) -> None:
        """「以后有类似的叫我」。

        和 `learned()` 是两件事：那一条记的是**我能做什么**（会进求解器的
        角色覆盖），这一条记的是**我想被叫上**（只放宽召回）。
        一个刚拒绝了这次的人不是"会做这个"，他是"这次不行，下次问我"。
        """
        wanted = [s for s in dict.fromkeys(skills) if s]
        if not wanted:
            return
        self._conn.execute(
            sa.update(principals)
            .where(principals.c.id == principal_id)
            .values(
                open_to=sa.func.array(
                    sa.select(
                        sa.distinct(
                            sa.func.unnest(
                                sa.func.array_cat(
                                    principals.c.open_to,
                                    sa.cast(wanted, PgArray(sa.Text)),
                                )
                            )
                        )
                    ).scalar_subquery()
                )
            )
        )

    def add(self, principal: Principal) -> None:
        self._conn.execute(
            sa.insert(principals).values(
                id=principal.id,
                campus_id=principal.campus_id.value,
                display_name=principal.display_name,
                is_synthetic=principal.is_synthetic,
                self_intro=principal.self_intro,
                major=principal.major,
                skills=list(principal.skills),
                open_to=list(principal.open_to),
                zone=principal.zone,
                created_at=self._clock.now(),
            )
        )

    def add_many(self, batch: Sequence[Principal]) -> None:
        if not batch:
            return
        created_at = self._clock.now()
        self._conn.execute(
            sa.insert(principals),
            [
                {
                    "id": p.id,
                    "campus_id": p.campus_id.value,
                    "display_name": p.display_name,
                    "self_intro": p.self_intro,
                    "major": p.major,
                    "skills": list(p.skills),
                    "open_to": list(p.open_to),
                    "zone": p.zone,
                    "is_synthetic": p.is_synthetic,
                    "created_at": created_at,
                }
                for p in batch
            ],
        )

    def get(self, principal_id: UUID) -> Principal | None:
        row = self._conn.execute(
            sa.select(principals).where(principals.c.id == principal_id)
        ).one_or_none()
        return _to_domain(row) if row is not None else None

    def list_all(self) -> list[Principal]:
        """列出当前租户下的全部主体。过滤由行级安全完成，不靠这里加 WHERE。"""
        rows = self._conn.execute(sa.select(principals).order_by(principals.c.id)).all()
        return [_to_domain(r) for r in rows]

    def count(self, *, is_synthetic: bool | None = None) -> int:
        stmt = sa.select(sa.func.count()).select_from(principals)
        if is_synthetic is not None:
            stmt = stmt.where(principals.c.is_synthetic == is_synthetic)
        return self._conn.execute(stmt).scalar_one()
