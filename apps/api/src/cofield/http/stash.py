"""念头的被动提示。

漏斗最前面缺的那一段：还没想清楚的人也能先说一句。念头只对本人可见、
不参与撮合、无过期压力；当出现语义相关的招募时，在**本人的入口页**
提示一下。

被动是这条的关键——不推送、不通知、不打扰。念头不是内容流，
系统里没有任何端点会返回别人的念头。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from cofield.adapters.persistence.intents import IntentRepository
from cofield.adapters.persistence.opportunities import (
    OpportunityRepository,
    OrganizationRepository,
)
from cofield.domain.model.intent import IntentState
from cofield.domain.model.opportunity import ActionOpportunity
from cofield.http.deps import CampusDep, ClockDep, ConnDep, PrincipalDep

router = APIRouter(tags=["stash"])


class HintOut(BaseModel):
    opportunity_id: UUID
    title: str
    organization_name: str
    organization_verified: bool
    #: 为什么提示这一条。说清楚，不是"猜你喜欢"。
    because: str
    total_gap: int


class StashHintOut(BaseModel):
    intent_id: UUID
    note: str
    hints: list[HintOut]


def _overlap(stash_terms: set[str], opportunity: ActionOpportunity) -> str | None:
    """念头和招募有没有对上，以及**对在哪**。

    先看角色缺口——那是最硬的信号：招募明确说缺这个角色，而念头里提到了它。
    其次看目标文字里的重合。匹配不上就返回 None，不硬凑。
    """
    roles = {s.role for s in opportunity.gaps}
    hit_roles = sorted(roles & stash_terms)
    if hit_roles:
        return f"这条招募正缺{('、'.join(hit_roles))}"

    haystack = f"{opportunity.title}{opportunity.goal}"
    hit_words = sorted(t for t in stash_terms if len(t) >= 2 and t in haystack)
    if hit_words:
        return f"和你说的「{hit_words[0]}」对得上"
    return None


def _terms(goal: str, needs: tuple[str, ...], offers: tuple[str, ...]) -> set[str]:
    terms = {*needs, *offers}
    # 目标里取足够长的连续片段做粗匹配。这一步在 #5 会被语义召回取代。
    terms.update(w for w in goal.replace("，", " ").split() if len(w) >= 2)
    if len(goal) >= 6:
        terms.add(goal[:6])
    return {t.strip() for t in terms if t.strip()}


@router.get("/me/stash-hints", response_model=list[StashHintOut])
def stash_hints(
    conn: ConnDep, clock: ClockDep, campus: CampusDep, principal_id: PrincipalDep
) -> list[StashHintOut]:
    """我记下的念头，以及现在有哪些招募对得上。

    出现在本人的入口页，不产生推送。
    """
    stashed = IntentRepository(conn, clock, campus).list_for_principal(
        principal_id, states={IntentState.STASHED}
    )
    if not stashed:
        return []

    opportunities = OpportunityRepository(conn, clock, campus).list_open()
    if not opportunities:
        return [
            StashHintOut(intent_id=s.id, note=s.content.goal, hints=[])
            for s in stashed
        ]

    orgs = {o.id: o for o in OrganizationRepository(conn, clock, campus).list_all()}

    result: list[StashHintOut] = []
    for signal in stashed:
        terms = _terms(
            signal.content.goal, signal.content.needs, signal.content.offers
        )
        hints: list[HintOut] = []
        for opportunity in opportunities:
            reason = _overlap(terms, opportunity)
            if reason is None:
                continue
            org = orgs.get(opportunity.organization_id)
            hints.append(
                HintOut(
                    opportunity_id=opportunity.id,
                    title=opportunity.title,
                    organization_name=org.name if org else "未知组织",
                    organization_verified=org.verified if org else False,
                    because=reason,
                    total_gap=opportunity.total_gap,
                )
            )
        result.append(
            StashHintOut(intent_id=signal.id, note=signal.content.goal, hints=hints[:3])
        )
    return result
