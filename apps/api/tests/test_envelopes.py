"""匹配信封与同意记录。

守的是同一件事的三面：未授权字段出不去、撤销立刻生效、预览和真正对外
输出走同一条路径（所以预览不会骗人）。
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from cofield.adapters.clock import SimulatedClock
from cofield.adapters.persistence.engine import campus_connection
from cofield.adapters.persistence.principals import PrincipalRepository
from cofield.domain.model.consent import (
    Audience,
    FieldGrant,
    MatchEnvelope,
    Purpose,
)
from cofield.domain.model.principal import CampusId, Principal
from cofield.http import deps
from cofield.http.app import create_app

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
CAMPUS = "demo-campus"
CANONICAL = (
    "我想做一个关于校园流浪猫的一分钟短片，周五前完成。"
    "我会写脚本，但不认识会拍摄和剪辑的人。"
)


@pytest.fixture
def me(engine: Engine) -> Principal:
    person = Principal(id=uuid4(), campus_id=CampusId(CAMPUS), display_name="林知遥")
    with campus_connection(engine, CAMPUS) as conn:
        PrincipalRepository(conn, SimulatedClock(NOW)).add(person)
    return person


@pytest.fixture
def sim_clock() -> SimulatedClock:
    return SimulatedClock(NOW)


@pytest.fixture
def client(
    engine: Engine, me: Principal, sim_clock: SimulatedClock
) -> Generator[TestClient, None, None]:
    app = create_app()
    app.state.clock = sim_clock
    app.dependency_overrides[deps.get_engine] = lambda: engine
    with TestClient(app) as c:
        c.headers.update({"X-Principal-Id": str(me.id), "X-Campus-Id": CAMPUS})
        yield c


@pytest.fixture
def intent_id(client: TestClient) -> str:
    compiled = client.post("/api/intents:compile", json={"expression": CANONICAL}).json()
    content = {k: v for k, v in compiled["content"].items() if k != "uncertain_fields"}
    return str(
        client.post(
            "/api/intents", json={"expression": CANONICAL, "content": content}
        ).json()["id"]
    )


# --- 领域规则 ---


def test_a_field_outside_the_whitelist_cannot_be_granted() -> None:
    """白名单是正向的：新字段要显式加入并说明用途，不能靠"忘了排除"漏出去。"""
    with pytest.raises(ValueError, match="白名单"):
        FieldGrant(
            field_name="真实姓名",
            audience=Audience.CANDIDATES,
            purposes=frozenset({Purpose.FORMATION_PROOF}),
        )


def test_solver_only_fields_never_reach_candidates() -> None:
    envelope = MatchEnvelope(
        id=uuid4(),
        principal_id=uuid4(),
        intent_id=uuid4(),
        grants=(
            FieldGrant("goal", Audience.CANDIDATES, frozenset({Purpose.FORMATION_PROOF})),
            FieldGrant(
                "location_scope",
                Audience.SOLVER_ONLY,
                frozenset({Purpose.FORMATION_FEASIBILITY}),
            ),
        ),
        created_at=NOW,
        expires_at=NOW + timedelta(hours=72),
    )

    visible = envelope.visible_fields(
        audience=Audience.CANDIDATES, purpose=Purpose.FORMATION_PROOF, now=NOW
    )

    assert visible == {"goal"}


def test_an_expired_envelope_shows_nothing() -> None:
    """失效即空集——默认拒绝，而不是"忘了检查就全发"。"""
    envelope = MatchEnvelope(
        id=uuid4(),
        principal_id=uuid4(),
        intent_id=uuid4(),
        grants=(
            FieldGrant("goal", Audience.CANDIDATES, frozenset({Purpose.FORMATION_PROOF})),
        ),
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    assert (
        envelope.visible_fields(
            audience=Audience.CANDIDATES,
            purpose=Purpose.FORMATION_PROOF,
            now=NOW + timedelta(hours=2),
        )
        == frozenset()
    )


def test_a_revoked_envelope_shows_nothing() -> None:
    envelope = MatchEnvelope(
        id=uuid4(),
        principal_id=uuid4(),
        intent_id=uuid4(),
        grants=(
            FieldGrant("goal", Audience.CANDIDATES, frozenset({Purpose.FORMATION_PROOF})),
        ),
        created_at=NOW,
        expires_at=NOW + timedelta(hours=72),
    ).revoke()

    assert (
        envelope.visible_fields(
            audience=Audience.CANDIDATES, purpose=Purpose.FORMATION_PROOF, now=NOW
        )
        == frozenset()
    )


# --- 端点 ---


def test_grantable_fields_mark_which_ones_are_empty(
    client: TestClient, intent_id: str
) -> None:
    """空字段列出来但标灰，别让用户对着没内容的开关犹豫。"""
    fields = client.get(f"/api/intents/{intent_id}/grantable-fields").json()

    by_name = {f["field_name"]: f for f in fields}
    assert by_name["goal"]["present"] is True
    assert by_name["portfolio_link"]["present"] is False
    assert by_name["goal"]["label"] == "要做什么"


def test_each_grant_says_what_it_is_for(client: TestClient, intent_id: str) -> None:
    """用途、接收范围、有效期——这三样缺一，最小披露就只是口号。"""
    body = client.put(
        f"/api/intents/{intent_id}/envelope",
        json={"grants": [{"field_name": "goal", "audience": "candidates"}]},
    ).json()

    grant = body["grants"][0]
    assert grant["purpose_label"] == "对方能在小队说明里看到"
    assert body["expires_at"] is not None
    assert body["consent_record_id"] is not None


def test_ungranted_fields_do_not_appear_in_the_preview(
    client: TestClient, intent_id: str
) -> None:
    client.put(
        f"/api/intents/{intent_id}/envelope",
        json={
            "grants": [
                {"field_name": "goal", "audience": "candidates"},
                {"field_name": "needs", "audience": "solver_only"},
            ]
        },
    )

    preview = client.get(f"/api/intents/{intent_id}/preview").json()

    assert "要做什么" in preview["visible"]
    assert "我缺" not in preview["visible"]
    assert "我缺" in preview["withheld"]


def test_without_an_envelope_nothing_is_visible(
    client: TestClient, intent_id: str
) -> None:
    """还没授权 = 什么都不给看。"""
    preview = client.get(f"/api/intents/{intent_id}/preview").json()

    assert preview["visible"] == {}


def test_revoking_takes_effect_immediately(client: TestClient, intent_id: str) -> None:
    """撤销后新请求立刻被拒，不用等任何异步清理。"""
    envelope = client.put(
        f"/api/intents/{intent_id}/envelope",
        json={"grants": [{"field_name": "goal", "audience": "candidates"}]},
    ).json()

    client.post(f"/api/envelopes/{envelope['id']}:revoke")

    assert client.get(f"/api/intents/{intent_id}/preview").json()["visible"] == {}


def test_revoked_envelopes_leave_my_grants_list(
    client: TestClient, intent_id: str
) -> None:
    envelope = client.put(
        f"/api/intents/{intent_id}/envelope",
        json={"grants": [{"field_name": "goal", "audience": "candidates"}]},
    ).json()
    assert len(client.get("/api/me/grants").json()) == 1

    client.post(f"/api/envelopes/{envelope['id']}:revoke")

    assert client.get("/api/me/grants").json() == []


def test_grants_expire_on_their_own(
    client: TestClient, intent_id: str, sim_clock: SimulatedClock
) -> None:
    client.put(
        f"/api/intents/{intent_id}/envelope",
        json={"grants": [{"field_name": "goal", "audience": "candidates"}]},
    )

    sim_clock.advance(timedelta(hours=73))

    assert client.get("/api/me/grants").json() == []
    assert client.get(f"/api/intents/{intent_id}/preview").json()["visible"] == {}


def test_only_the_owner_can_grant(client: TestClient, intent_id: str) -> None:
    res = client.put(
        f"/api/intents/{intent_id}/envelope",
        json={"grants": [{"field_name": "goal", "audience": "candidates"}]},
        headers={"X-Principal-Id": str(uuid4())},
    )

    assert res.status_code == 403


def test_a_field_outside_the_whitelist_is_refused_at_the_edge(
    client: TestClient, intent_id: str
) -> None:
    res = client.put(
        f"/api/intents/{intent_id}/envelope",
        json={"grants": [{"field_name": "真实姓名", "audience": "candidates"}]},
    )

    assert res.status_code == 422
    assert "白名单" in res.json()["detail"]


def test_updating_the_envelope_replaces_rather_than_accumulates(
    client: TestClient, intent_id: str
) -> None:
    """收回一项就是收回，不能因为"之前给过"而残留。"""
    client.put(
        f"/api/intents/{intent_id}/envelope",
        json={
            "grants": [
                {"field_name": "goal", "audience": "candidates"},
                {"field_name": "needs", "audience": "candidates"},
            ]
        },
    )

    client.put(
        f"/api/intents/{intent_id}/envelope",
        json={"grants": [{"field_name": "goal", "audience": "candidates"}]},
    )

    preview = client.get(f"/api/intents/{intent_id}/preview").json()
    assert "我缺" not in preview["visible"]


def test_a_consent_record_is_written_in_the_standard_shape(
    client: TestClient, intent_id: str, engine: Engine, sim_clock: SimulatedClock
) -> None:
    """结构对齐 ISO/IEC TS 27560:2023——自创同意 schema 属于重复造轮子。"""
    from cofield.adapters.persistence.consent import ConsentRepository

    body = client.put(
        f"/api/intents/{intent_id}/envelope",
        json={"grants": [{"field_name": "goal", "audience": "candidates"}]},
    ).json()

    with campus_connection(engine, CAMPUS) as conn:
        record = ConsentRepository(conn, sim_clock, CAMPUS).get(
            body["consent_record_id"]
        )

    assert record is not None
    assert record.schema_version == "ISO/IEC TS 27560:2023"
    assert record.pii_categories == ("goal",)
    assert [e.kind.value for e in record.events] == ["given"]
    assert record.retention_until is not None
