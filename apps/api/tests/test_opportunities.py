"""招募：供给侧的最小闭环。

冷启动策略是供给先行。这些用例守的是三件事：未验证的组织发不了招募、
学生侧只看到还能报名的、组织者看得到缺口。
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
from cofield.adapters.persistence.opportunities import OrganizationRepository
from cofield.adapters.persistence.principals import PrincipalRepository
from cofield.domain.model.opportunity import Organization
from cofield.domain.model.principal import CampusId, Principal
from cofield.http import deps
from cofield.http.app import create_app

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
CAMPUS = "demo-campus"


@pytest.fixture
def steward(engine: Engine) -> Principal:
    person = Principal(id=uuid4(), campus_id=CampusId(CAMPUS), display_name="社长")
    with campus_connection(engine, CAMPUS) as conn:
        PrincipalRepository(conn, SimulatedClock(NOW)).add(person)
    return person


def _org(engine: Engine, *, verified: bool) -> Organization:
    org = Organization(
        id=uuid4(),
        campus_id=CampusId(CAMPUS),
        name="影像协会" if verified else "来路不明工作室",
        verified=verified,
    )
    with campus_connection(engine, CAMPUS) as conn:
        OrganizationRepository(conn, SimulatedClock(NOW), CAMPUS).add(org)
    return org


@pytest.fixture
def client(
    engine: Engine, steward: Principal
) -> Generator[TestClient, None, None]:
    app = create_app()
    app.state.clock = SimulatedClock(NOW)
    app.dependency_overrides[deps.get_engine] = lambda: engine
    with TestClient(app) as c:
        c.headers.update({"X-Principal-Id": str(steward.id), "X-Campus-Id": CAMPUS})
        yield c


def _payload(org: Organization, **over: object) -> dict:
    body: dict = {
        "organization_id": str(org.id),
        "kind_key": "creative_work",
        "title": "校园影像大赛 · 短片组",
        "goal": "周五前交一支 60 秒短片",
        "seats": [
            {"role": "拍摄", "capacity": 2},
            {"role": "剪辑", "capacity": 1},
        ],
        "deadline": (NOW + timedelta(days=7)).isoformat(),
        "location_scope": "传媒楼",
        "qualifications": ["限大二以上"],
    }
    body.update(over)
    return body


def test_a_verified_organization_can_publish(client: TestClient, engine: Engine) -> None:
    org = _org(engine, verified=True)

    res = client.post("/api/opportunities", json=_payload(org))

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["total_gap"] == 3
    assert body["organization_verified"] is True


def test_an_unverified_organization_cannot(client: TestClient, engine: Engine) -> None:
    """学生要靠"已验证"判断这不是骗局，所以这条不能有例外。"""
    org = _org(engine, verified=False)

    res = client.post("/api/opportunities", json=_payload(org))

    assert res.status_code == 403
    assert "未验证" in res.json()["detail"]


def test_students_see_the_verification_badge(client: TestClient, engine: Engine) -> None:
    org = _org(engine, verified=True)
    client.post("/api/opportunities", json=_payload(org))

    listed = client.get("/api/opportunities").json()

    assert listed[0]["organization_verified"] is True
    assert listed[0]["organization_name"] == "影像协会"


def test_the_student_list_only_shows_what_can_still_be_joined(
    client: TestClient, engine: Engine
) -> None:
    """列表上的每一条都该能点。已过期的不出现。"""
    org = _org(engine, verified=True)
    client.post("/api/opportunities", json=_payload(org))
    client.post(
        "/api/opportunities",
        json=_payload(org, title="已经过期的", deadline=(NOW - timedelta(days=1)).isoformat()),
    )

    listed = client.get("/api/opportunities").json()

    assert [o["title"] for o in listed] == ["校园影像大赛 · 短片组"]


def test_gaps_are_reported_per_role(client: TestClient, engine: Engine) -> None:
    """组织者要知道哪个角色最缺，不是只知道"还差几个人"。"""
    org = _org(engine, verified=True)
    client.post("/api/opportunities", json=_payload(org))

    listed = client.get("/api/opportunities").json()

    gaps = {s["role"]: s["gap"] for s in listed[0]["seats"]}
    assert gaps == {"拍摄": 2, "剪辑": 1}


def test_the_publisher_becomes_the_steward(client: TestClient, engine: Engine, steward: Principal) -> None:
    """没有负责人的成局会导致责任分散，所以发布者即负责人。"""
    org = _org(engine, verified=True)
    client.post("/api/opportunities", json=_payload(org))

    with campus_connection(engine, CAMPUS) as conn:
        from cofield.adapters.persistence.opportunities import OpportunityRepository

        found = OpportunityRepository(conn, SimulatedClock(NOW), CAMPUS).list_open()

    assert found[0].steward_id == steward.id


def test_an_unregistered_action_kind_is_refused(client: TestClient, engine: Engine) -> None:
    """静默回退到某个默认类别，会让"新场景没注册"这种错误藏到线上。"""
    org = _org(engine, verified=True)

    res = client.post("/api/opportunities", json=_payload(org, kind_key="没注册的"))

    assert res.status_code == 422
    assert "未注册" in str(res.json()["detail"])


def test_duplicate_roles_are_refused(client: TestClient, engine: Engine) -> None:
    org = _org(engine, verified=True)

    res = client.post(
        "/api/opportunities",
        json=_payload(
            org, seats=[{"role": "剪辑", "capacity": 1}, {"role": "剪辑", "capacity": 2}]
        ),
    )

    assert res.status_code == 422


def test_an_opportunity_without_seats_is_refused(
    client: TestClient, engine: Engine
) -> None:
    """没有席位的招募，学生不知道该来干什么。"""
    org = _org(engine, verified=True)

    res = client.post("/api/opportunities", json=_payload(org, seats=[]))

    assert res.status_code == 422


def test_the_organizer_view_includes_what_students_no_longer_see(
    client: TestClient, engine: Engine
) -> None:
    """组织者要看全貌才知道要不要补推。"""
    org = _org(engine, verified=True)
    client.post("/api/opportunities", json=_payload(org))
    client.post(
        "/api/opportunities",
        json=_payload(org, title="已经过期的", deadline=(NOW - timedelta(days=1)).isoformat()),
    )

    mine = client.get(f"/api/organizations/{org.id}/opportunities").json()

    assert len(mine) == 2


def test_opportunities_do_not_leak_across_campuses(
    client: TestClient, engine: Engine
) -> None:
    org = _org(engine, verified=True)
    client.post("/api/opportunities", json=_payload(org))

    other = client.get("/api/opportunities", headers={"X-Campus-Id": "simulation"})

    assert other.json() == []
