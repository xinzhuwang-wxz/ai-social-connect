"""招募相关的端点。

学生侧只看到还能报名的；组织者侧看到全貌。两侧看到的候选信息也不同——
组织者只能看到完成这件事必须让他知道的部分。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cofield.adapters.persistence.opportunities import (
    OpportunityRepository,
    OrganizationRepository,
)
from cofield.domain.model.opportunity import ActionOpportunity, Seat, publishable
from cofield.http.deps import CampusDep, ClockDep, ConnDep, KindsDep, PrincipalDep

router = APIRouter(tags=["opportunities"])


class SeatIn(BaseModel):
    role: str = Field(min_length=1, max_length=40)
    capacity: int = Field(ge=1, le=50)


class SeatOut(BaseModel):
    role: str
    capacity: int
    filled: int
    gap: int


class OpportunityOut(BaseModel):
    id: UUID
    organization_id: UUID
    organization_name: str
    #: 学生要靠它判断这不是一个用来收集信息的假项目。
    organization_verified: bool
    kind_key: str
    title: str
    goal: str
    seats: list[SeatOut]
    total_gap: int
    deadline: datetime
    location_scope: str | None
    qualifications: list[str]
    state: str


class CreateOpportunityRequest(BaseModel):
    organization_id: UUID
    kind_key: str
    title: str = Field(min_length=1, max_length=100)
    goal: str = Field(min_length=1, max_length=500)
    seats: list[SeatIn] = Field(min_length=1)
    deadline: datetime
    location_scope: str | None = None
    qualifications: list[str] = []


def _out(
    opportunity: ActionOpportunity, org_name: str, org_verified: bool
) -> OpportunityOut:
    return OpportunityOut(
        id=opportunity.id,
        organization_id=opportunity.organization_id,
        organization_name=org_name,
        organization_verified=org_verified,
        kind_key=opportunity.kind_key,
        title=opportunity.title,
        goal=opportunity.goal,
        seats=[
            SeatOut(role=s.role, capacity=s.capacity, filled=s.filled, gap=s.gap)
            for s in opportunity.seats
        ],
        total_gap=opportunity.total_gap,
        deadline=opportunity.deadline,
        location_scope=opportunity.location_scope,
        qualifications=list(opportunity.qualifications),
        state=opportunity.state,
    )


@router.get("/opportunities", response_model=list[OpportunityOut])
def list_opportunities(
    conn: ConnDep, clock: ClockDep, campus: CampusDep
) -> list[OpportunityOut]:
    """还能报名的招募。已满和已过期的不出现——列表上每一条都该能点。"""
    orgs = {o.id: o for o in OrganizationRepository(conn, clock, campus).list_all()}
    found = OpportunityRepository(conn, clock, campus).list_open()
    return [
        _out(
            o,
            orgs[o.organization_id].name if o.organization_id in orgs else "未知组织",
            orgs[o.organization_id].verified if o.organization_id in orgs else False,
        )
        for o in found
    ]


@router.post("/opportunities", response_model=OpportunityOut, status_code=201)
def create_opportunity(
    payload: CreateOpportunityRequest,
    conn: ConnDep,
    clock: ClockDep,
    campus: CampusDep,
    kinds: KindsDep,
    principal_id: PrincipalDep,
) -> OpportunityOut:
    """发布招募。发布者即负责人——没有负责人的成局会导致责任分散。"""
    org = OrganizationRepository(conn, clock, campus).get(payload.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="找不到这个组织")

    allowed, reason = publishable(org)
    if not allowed:
        raise HTTPException(status_code=403, detail=reason)

    try:
        kinds.get(payload.kind_key)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        opportunity = ActionOpportunity(
            id=uuid4(),
            organization_id=org.id,
            kind_key=payload.kind_key,
            title=payload.title,
            goal=payload.goal,
            seats=tuple(
                Seat(role=s.role, capacity=s.capacity) for s in payload.seats
            ),
            steward_id=principal_id,
            deadline=payload.deadline,
            created_at=clock.now(),
            qualifications=tuple(payload.qualifications),
            location_scope=payload.location_scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    OpportunityRepository(conn, clock, campus).add(opportunity)
    return _out(opportunity, org.name, org.verified)


@router.get("/organizations/{organization_id}/opportunities", response_model=list[OpportunityOut])
def list_for_organization(
    organization_id: UUID, conn: ConnDep, clock: ClockDep, campus: CampusDep
) -> list[OpportunityOut]:
    """组织者侧：含已满与已关闭的，他们要看全貌才知道要不要补推。"""
    org = OrganizationRepository(conn, clock, campus).get(organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="找不到这个组织")
    found = OpportunityRepository(conn, clock, campus).list_for_organization(
        organization_id
    )
    return [_out(o, org.name, org.verified) for o in found]
