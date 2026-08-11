"""组织与行动机会仓储。

席位缺口在 SQL 里聚合而不是取回来算——机会列表是学生侧的常看页面，
每次都把全部席位拉回来再求和是错的。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection, Row

from cofield.domain.model.opportunity import (
    ActionOpportunity,
    OpportunityState,
    Organization,
    Seat,
)
from cofield.domain.model.principal import CampusId
from cofield.domain.ports.clock import Clock

from .schema import action_opportunities, opportunity_seats, organizations


def _org(row: Row[tuple[object, ...]]) -> Organization:
    return Organization(
        id=row.id,
        campus_id=CampusId(row.campus_id),
        name=row.name,
        verified=row.verified,
    )


class OrganizationRepository:
    def __init__(self, conn: Connection, clock: Clock, campus_id: str) -> None:
        self._conn = conn
        self._clock = clock
        self._campus = campus_id

    def add(self, organization: Organization) -> None:
        self._conn.execute(
            sa.insert(organizations).values(
                id=organization.id,
                campus_id=self._campus,
                name=organization.name,
                verified=organization.verified,
                created_at=self._clock.now(),
            )
        )

    def get(self, organization_id: UUID) -> Organization | None:
        row = self._conn.execute(
            sa.select(organizations).where(organizations.c.id == organization_id)
        ).one_or_none()
        return _org(row) if row is not None else None

    def list_all(self) -> list[Organization]:
        rows = self._conn.execute(
            sa.select(organizations).order_by(organizations.c.name)
        ).all()
        return [_org(r) for r in rows]


class OpportunityRepository:
    def __init__(self, conn: Connection, clock: Clock, campus_id: str) -> None:
        self._conn = conn
        self._clock = clock
        self._campus = campus_id

    def add(self, opportunity: ActionOpportunity) -> None:
        self._conn.execute(
            sa.insert(action_opportunities).values(
                id=opportunity.id,
                campus_id=self._campus,
                organization_id=opportunity.organization_id,
                kind_key=opportunity.kind_key,
                title=opportunity.title,
                goal=opportunity.goal,
                steward_id=opportunity.steward_id,
                deadline=opportunity.deadline,
                location_scope=opportunity.location_scope,
                qualifications=list(opportunity.qualifications),
                state=opportunity.state,
                created_at=opportunity.created_at,
            )
        )
        self._conn.execute(
            sa.insert(opportunity_seats),
            [
                {
                    "opportunity_id": opportunity.id,
                    "campus_id": self._campus,
                    "role": seat.role,
                    "capacity": seat.capacity,
                    "filled": seat.filled,
                }
                for seat in opportunity.seats
            ],
        )

    def get(self, opportunity_id: UUID) -> ActionOpportunity | None:
        row = self._conn.execute(
            sa.select(action_opportunities).where(
                action_opportunities.c.id == opportunity_id
            )
        ).one_or_none()
        if row is None:
            return None
        return self._hydrate(row, self._seats_of([opportunity_id]))

    def list_open(self, *, now: datetime | None = None) -> list[ActionOpportunity]:
        """学生侧看到的招募。已满和已过期的不出现——列表上的每一条都该能报名。"""
        instant = now or self._clock.now()
        rows = self._conn.execute(
            sa.select(action_opportunities)
            .where(action_opportunities.c.state == OpportunityState.OPEN)
            .where(action_opportunities.c.deadline > instant)
            .order_by(action_opportunities.c.deadline.asc())
        ).all()
        if not rows:
            return []
        seats = self._seats_of([r.id for r in rows])
        found = [self._hydrate(r, seats) for r in rows]
        return [o for o in found if o.total_gap > 0]

    def list_for_organization(self, organization_id: UUID) -> list[ActionOpportunity]:
        """组织者侧：含已满和已关闭的，他们要看全貌。"""
        rows = self._conn.execute(
            sa.select(action_opportunities)
            .where(action_opportunities.c.organization_id == organization_id)
            .order_by(action_opportunities.c.created_at.desc())
        ).all()
        if not rows:
            return []
        seats = self._seats_of([r.id for r in rows])
        return [self._hydrate(r, seats) for r in rows]


    def _seats_of(self, ids: list[UUID]) -> dict[UUID, list[Seat]]:
        rows = self._conn.execute(
            sa.select(opportunity_seats)
            .where(opportunity_seats.c.opportunity_id.in_(ids))
            .order_by(opportunity_seats.c.role)
        ).all()
        grouped: dict[UUID, list[Seat]] = {}
        for row in rows:
            grouped.setdefault(row.opportunity_id, []).append(
                Seat(role=row.role, capacity=row.capacity, filled=row.filled)
            )
        return grouped

    @staticmethod
    def _hydrate(
        row: Row[tuple[object, ...]], seats: dict[UUID, list[Seat]]
    ) -> ActionOpportunity:
        return ActionOpportunity(
            id=row.id,
            organization_id=row.organization_id,
            kind_key=row.kind_key,
            title=row.title,
            goal=row.goal,
            seats=tuple(seats.get(row.id, ())),
            steward_id=row.steward_id,
            deadline=row.deadline,
            created_at=row.created_at,
            qualifications=tuple(row.qualifications),
            location_scope=row.location_scope,
            state=row.state,
        )
