"""匹配信封的端点。

一条规则贯穿：**未授权字段不出现在任何对外输出**。过滤在服务端做，
按信封求出可见字段集合再投影——不是"前端记得别显示"。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cofield.adapters.persistence.consent import ConsentRepository, EnvelopeRepository
from cofield.adapters.persistence.intents import IntentRepository
from cofield.domain.model.consent import (
    GRANTABLE_FIELDS,
    Audience,
    ConsentEvent,
    ConsentEventKind,
    ConsentRecord,
    FieldGrant,
    MatchEnvelope,
    Purpose,
)
from cofield.domain.model.intent import IntentContent
from cofield.http.deps import CampusDep, ClockDep, ConnDep, PrincipalDep

router = APIRouter(tags=["envelopes"])

#: 信封的默认有效期。用户界面上会常驻显示它。
DEFAULT_ENVELOPE_TTL = timedelta(hours=72)


class GrantIn(BaseModel):
    field_name: str
    #: solver_only = 参与求解但不对候选展示；candidates = 可在提案里看到。
    audience: str = Audience.SOLVER_ONLY.value


class GrantOut(BaseModel):
    field_name: str
    audience: str
    purposes: list[str]
    #: 这一项用来干什么，给人看的一句话。界面直接显示它。
    purpose_label: str


class EnvelopeOut(BaseModel):
    id: UUID
    intent_id: UUID
    grants: list[GrantOut]
    cited_facet_ids: list[UUID]
    state: str
    expires_at: datetime
    consent_record_id: UUID | None = None


class PutEnvelopeRequest(BaseModel):
    grants: list[GrantIn] = Field(default_factory=list)
    cited_facet_ids: list[UUID] = Field(default_factory=list)


class GrantableFieldOut(BaseModel):
    field_name: str
    label: str
    #: 这条目前有没有内容。空的字段不该出现在授权列表上让人困惑。
    present: bool


class PreviewOut(BaseModel):
    """「别人眼中的我」。

    这一屏让"最小披露"从一句承诺变成用户可以自己检查的东西。
    """

    visible: dict[str, object]
    withheld: list[str]


_PURPOSE_LABELS = {
    Audience.SOLVER_ONLY: "只给系统算，不展示给对方",
    Audience.CANDIDATES: "对方能在小队说明里看到",
}

_FIELD_LABELS = {
    "goal": "要做什么",
    "offers": "我能出",
    "needs": "我缺",
    "time_window": "什么时候",
    "location_scope": "在哪",
    "team_size": "几个人",
    "boundaries": "我的底线",
    "open_questions": "还没定的事",
    "portfolio_link": "作品链接",
}


def _content_field(content: IntentContent, name: str) -> object:
    mapping: dict[str, object] = {
        "goal": content.goal,
        "offers": list(content.offers),
        "needs": list(content.needs),
        "time_window": (
            {
                "earliest": content.time_window.earliest.isoformat(),
                "deadline": content.time_window.deadline.isoformat(),
            }
            if content.time_window
            else None
        ),
        "location_scope": content.location_scope,
        "team_size": (
            {"minimum": content.team_size.minimum, "maximum": content.team_size.maximum}
            if content.team_size
            else None
        ),
        "boundaries": list(content.boundaries),
        "open_questions": list(content.open_questions),
        "portfolio_link": None,
    }
    return mapping.get(name)


def _out(envelope: MatchEnvelope, consent_id: UUID | None = None) -> EnvelopeOut:
    return EnvelopeOut(
        id=envelope.id,
        intent_id=envelope.intent_id,
        grants=[
            GrantOut(
                field_name=g.field_name,
                audience=g.audience.value,
                purposes=sorted(p.value for p in g.purposes),
                purpose_label=_PURPOSE_LABELS[g.audience],
            )
            for g in envelope.grants
        ],
        cited_facet_ids=list(envelope.cited_facet_ids),
        state=envelope.state.value,
        expires_at=envelope.expires_at,
        consent_record_id=consent_id,
    )


@router.get("/intents/{intent_id}/grantable-fields", response_model=list[GrantableFieldOut])
def grantable_fields(
    intent_id: UUID, conn: ConnDep, clock: ClockDep, campus: CampusDep
) -> list[GrantableFieldOut]:
    """这次可以逐项授权的字段。

    空字段也列出来但标 `present=false`——界面据此把它们灰掉，
    而不是让用户对着一个没内容的开关犹豫。
    """
    signal = IntentRepository(conn, clock, campus).get(intent_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="找不到这条需求")
    return [
        GrantableFieldOut(
            field_name=name,
            label=_FIELD_LABELS.get(name, name),
            present=_content_field(signal.content, name) not in (None, [], ""),
        )
        for name in sorted(GRANTABLE_FIELDS)
    ]


@router.put("/intents/{intent_id}/envelope", response_model=EnvelopeOut)
def put_envelope(
    intent_id: UUID,
    payload: PutEnvelopeRequest,
    conn: ConnDep,
    clock: ClockDep,
    campus: CampusDep,
    principal_id: PrincipalDep,
) -> EnvelopeOut:
    """保存这次的授权，并留下一条同意记录。

    信封会被撤销和过期；同意记录只追加不修改——申诉和导出看的是后者。
    """
    signal = IntentRepository(conn, clock, campus).get(intent_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="找不到这条需求")
    if signal.principal_id != principal_id:
        raise HTTPException(status_code=403, detail="只能给自己的需求授权")

    now = clock.now()
    try:
        grants = tuple(
            FieldGrant(
                field_name=g.field_name,
                audience=Audience(g.audience),
                purposes=frozenset(
                    {Purpose.FORMATION_FEASIBILITY, Purpose.FORMATION_PROOF}
                    if Audience(g.audience) is Audience.CANDIDATES
                    else {Purpose.FORMATION_FEASIBILITY}
                ),
            )
            for g in payload.grants
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    envelopes = EnvelopeRepository(conn, clock, campus)
    existing = envelopes.for_intent(intent_id)
    envelope = MatchEnvelope(
        id=existing.id if existing else uuid4(),
        principal_id=principal_id,
        intent_id=intent_id,
        grants=grants,
        created_at=existing.created_at if existing else now,
        expires_at=now + DEFAULT_ENVELOPE_TTL,
        cited_facet_ids=tuple(payload.cited_facet_ids),
    )
    envelopes.save(envelope)

    record = ConsentRecord(
        record_id=uuid4(),
        created_at=now,
        pii_principal_id=principal_id,
        purposes=(Purpose.FORMATION_FEASIBILITY, Purpose.FORMATION_PROOF),
        pii_categories=tuple(sorted(g.field_name for g in grants)),
        audience=(
            Audience.CANDIDATES
            if any(g.audience is Audience.CANDIDATES for g in grants)
            else Audience.SOLVER_ONLY
        ),
        retention_until=envelope.expires_at,
        events=(ConsentEvent(ConsentEventKind.GIVEN, now),),
    )
    ConsentRepository(conn, clock, campus).append(record)

    return _out(envelope, record.record_id)


@router.post("/envelopes/{envelope_id}:revoke", response_model=EnvelopeOut)
def revoke_envelope(
    envelope_id: UUID,
    conn: ConnDep,
    clock: ClockDep,
    campus: CampusDep,
    principal_id: PrincipalDep,
) -> EnvelopeOut:
    """收回授权。撤销后新请求立刻被拒，不用等任何异步清理。"""
    envelopes = EnvelopeRepository(conn, clock, campus)
    envelope = envelopes.get(envelope_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail="找不到这次授权")
    if envelope.principal_id != principal_id:
        raise HTTPException(status_code=403, detail="只能收回自己的授权")
    revoked = envelope.revoke()
    envelopes.save(revoked)
    return _out(revoked)


@router.get("/me/grants", response_model=list[EnvelopeOut])
def my_grants(
    conn: ConnDep, clock: ClockDep, campus: CampusDep, principal_id: PrincipalDep
) -> list[EnvelopeOut]:
    """「谁能看到我」。仍在生效的授权，可一键收回。"""
    found = EnvelopeRepository(conn, clock, campus).list_active(principal_id)
    return [_out(e) for e in found]


@router.get("/intents/{intent_id}/preview", response_model=PreviewOut)
def preview(
    intent_id: UUID, conn: ConnDep, clock: ClockDep, campus: CampusDep
) -> PreviewOut:
    """别人在小队说明里会看到我的什么。

    投影按信封求出的可见字段集合做——和真正对外输出走的是同一条路径，
    所以这一屏显示什么，对方就真的只看到什么。
    """
    signal = IntentRepository(conn, clock, campus).get(intent_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="找不到这条需求")

    envelope = EnvelopeRepository(conn, clock, campus).for_intent(intent_id)
    if envelope is None:
        # 还没授权 = 什么都不给看。默认拒绝。
        return PreviewOut(visible={}, withheld=sorted(_FIELD_LABELS.values()))

    allowed = envelope.visible_fields(
        audience=Audience.CANDIDATES,
        purpose=Purpose.FORMATION_PROOF,
        now=clock.now(),
    )
    visible = {
        _FIELD_LABELS[name]: _content_field(signal.content, name)
        for name in sorted(allowed)
        if _content_field(signal.content, name) not in (None, [], "")
    }
    withheld = sorted(
        label for name, label in _FIELD_LABELS.items() if name not in allowed
    )
    return PreviewOut(visible=visible, withheld=withheld)
