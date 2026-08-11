"""招募相关的端点。

学生侧只看到还能报名的；组织者侧看到全貌。两侧看到的候选信息也不同——
组织者只能看到完成这件事必须让他知道的部分。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cofield.domain.model.opportunity import ActionOpportunity, Seat, publishable
from cofield.http.deps import ClockDep, KindsDep, PrincipalDep, ReposDep

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
    #: 真人负责人。
    #:
    #: 领域模型里它是必填的（"没有负责人的自动成局会导致责任分散——
    #: 匿名聚合能降低发起压力，但没人承担下一步时事情就烂在那里"），
    #: 而这一层曾经不透出它，于是界面上每一条招募都显示"没写谁负责"。
    #: **领域里守住的东西，接口不透出等于没守住。**
    steward_id: UUID
    steward_name: str


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
    opportunity: ActionOpportunity,
    org_name: str,
    org_verified: bool,
    steward_name: str = "这位同学",
) -> OpportunityOut:
    return OpportunityOut(
        steward_id=opportunity.steward_id,
        steward_name=steward_name,
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
def list_opportunities(repos: ReposDep) -> list[OpportunityOut]:
    """还能报名的招募。已满和已过期的不出现——列表上每一条都该能点。"""
    orgs = {o.id: o for o in repos.organizations.list_all()}
    found = repos.opportunities.list_open()
    stewards = {
        o.steward_id: person.display_name
        for o in found
        if (person := repos.principals.get(o.steward_id)) is not None
    }
    return [
        _out(
            o,
            orgs[o.organization_id].name if o.organization_id in orgs else "未知组织",
            orgs[o.organization_id].verified if o.organization_id in orgs else False,
            stewards.get(o.steward_id, "这位同学"),
        )
        for o in found
    ]


class OrganizationOut(BaseModel):
    id: UUID
    name: str
    #: 没被核过的组织**发不了招募**。列出来但标清楚，
    #: 比直接过滤掉好——组织者要知道自己为什么发不出去。
    verified: bool


@router.get("/organizations", response_model=list[OrganizationOut])
def list_organizations(repos: ReposDep) -> list[OrganizationOut]:
    """能代表哪些组织发招募。

    没有这个端点时，界面只能从"已经发过招募的组织"里反推可选项——
    于是一个**全新的、刚被核过的组织发不出第一份招募**，
    而那正是它最需要这个功能的时候。
    """
    return [
        OrganizationOut(id=o.id, name=o.name, verified=o.verified)
        for o in repos.organizations.list_all()
    ]


@router.post("/opportunities", response_model=OpportunityOut, status_code=201)
def create_opportunity(
    payload: CreateOpportunityRequest,
    repos: ReposDep,
    clock: ClockDep,
    kinds: KindsDep,
    principal_id: PrincipalDep,
) -> OpportunityOut:
    """发布招募。发布者即负责人——没有负责人的成局会导致责任分散。"""
    org = repos.organizations.get(payload.organization_id)
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

    repos.opportunities.add(opportunity)
    return _out(opportunity, org.name, org.verified)


@router.get("/organizations/{organization_id}/opportunities", response_model=list[OpportunityOut])
def list_for_organization(
    organization_id: UUID, repos: ReposDep
) -> list[OpportunityOut]:
    """组织者侧：含已满与已关闭的，他们要看全貌才知道要不要补推。"""
    org = repos.organizations.get(organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="找不到这个组织")
    found = repos.opportunities.list_for_organization(organization_id)
    return [_out(o, org.name, org.verified) for o in found]
