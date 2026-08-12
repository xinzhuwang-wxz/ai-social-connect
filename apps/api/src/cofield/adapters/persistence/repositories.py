"""绑定到同一连接与租户的仓储集合。

在这之前，每个端点都要写 `XRepository(conn, clock, campus)` 三个参数，
出现了二十多次。它们从来不会不一致——一致性是靠人记住的，而不是靠结构
保证的。这里把三个参数收成一个依赖：端点依赖一件东西，而且新增一个仓储
不改任何端点签名。
"""

from __future__ import annotations

from functools import cached_property

from sqlalchemy import Connection

from cofield.domain.ports.clock import Clock

from .consent import ConsentRepository, EnvelopeRepository
from .events import EventRepository
from .intents import IntentRepository
from .opportunities import OpportunityRepository, OrganizationRepository
from .principals import PrincipalRepository


class Repositories:
    """同一事务、同一租户下的全部仓储。

    懒创建：一个端点通常只用其中一两个，没必要为其余的付出构造成本。
    """

    def __init__(self, conn: Connection, clock: Clock, campus_id: str) -> None:
        self._conn = conn
        self._clock = clock
        self._campus = campus_id

    @property
    def campus_id(self) -> str:
        return self._campus

    @cached_property
    def principals(self) -> PrincipalRepository:
        return PrincipalRepository(self._conn, self._clock)

    @cached_property
    def intents(self) -> IntentRepository:
        return IntentRepository(self._conn, self._clock, self._campus)

    @cached_property
    def events(self) -> EventRepository:
        return EventRepository(self._conn, self._campus)

    @cached_property
    def organizations(self) -> OrganizationRepository:
        return OrganizationRepository(self._conn, self._clock, self._campus)

    @cached_property
    def opportunities(self) -> OpportunityRepository:
        return OpportunityRepository(self._conn, self._clock, self._campus)

    @cached_property
    def envelopes(self) -> EnvelopeRepository:
        return EnvelopeRepository(self._conn, self._clock, self._campus)

    @cached_property
    def consent(self) -> ConsentRepository:
        return ConsentRepository(self._conn, self._clock, self._campus)
