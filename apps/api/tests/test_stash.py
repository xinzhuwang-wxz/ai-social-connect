"""念头：漏斗最前面缺的那一段。

守三件事：念头不参与撮合、只有本人看得到、提示是被动的且说得清为什么。
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
from cofield.domain.model.opportunity import Organization
from cofield.domain.model.principal import CampusId, Principal
from cofield.http import deps
from cofield.http.app import create_app

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
CAMPUS = "demo-campus"


@pytest.fixture
def client(engine: Engine, me: Principal) -> Generator[TestClient, None, None]:
    app = create_app()
    app.state.clock = SimulatedClock(NOW)
    app.dependency_overrides[deps.get_engine] = lambda: engine
    with TestClient(app) as c:
        c.headers.update({"X-Principal-Id": str(me.id), "X-Campus-Id": CAMPUS})
        yield c


def _stash(client: TestClient, text: str) -> str:
    compiled = client.post("/api/intents:compile", json={"expression": text}).json()
    content = {k: v for k, v in compiled["content"].items() if k != "uncertain_fields"}
    return str(
        client.post(
            "/api/intents", json={"expression": text, "content": content, "stash": True}
        ).json()["id"]
    )


def _opportunity(client: TestClient, engine: Engine, *, roles: list[str], title: str) -> None:
    org = Organization(
        id=uuid4(), campus_id=CampusId(CAMPUS), name="影像协会", verified=True
    )
    with campus_connection(engine, CAMPUS) as conn:
        OrganizationRepository(conn, SimulatedClock(NOW), CAMPUS).add(org)
    client.post(
        "/api/opportunities",
        json={
            "organization_id": str(org.id),
            "kind_key": "creative_work",
            "title": title,
            "goal": "周五前交一支短片",
            "seats": [{"role": r, "capacity": 1} for r in roles],
            "deadline": (NOW + timedelta(days=7)).isoformat(),
        },
    )


def test_a_half_formed_thought_can_be_saved_without_being_completed(
    client: TestClient,
) -> None:
    """想不清楚就放弃，是漏斗最前面的流失。这里允许只说半句。"""
    stash_id = _stash(client, "最近想搞个短片")

    mine = client.get("/api/me/intents").json()

    assert [i["id"] for i in mine] == [stash_id]
    assert mine[0]["state"] == "stashed"
    assert mine[0]["is_matchable"] is False


def test_a_stash_shows_up_with_no_hints_when_nothing_matches(
    client: TestClient,
) -> None:
    _stash(client, "最近想搞个短片")

    hints = client.get("/api/me/stash-hints").json()

    assert len(hints) == 1
    assert hints[0]["hints"] == []


def test_a_matching_recruitment_says_why_it_matched(
    client: TestClient, engine: Engine
) -> None:
    """说清为什么，不是"猜你喜欢"。"""
    _stash(client, "想拍个短片，缺剪辑")
    _opportunity(client, engine, roles=["剪辑", "拍摄"], title="校园影像大赛")

    hints = client.get("/api/me/stash-hints").json()[0]["hints"]

    assert len(hints) == 1
    assert "剪辑" in hints[0]["because"]
    assert hints[0]["organization_verified"] is True


def test_an_unrelated_recruitment_is_not_forced_into_a_match(
    client: TestClient, engine: Engine
) -> None:
    """匹配不上就不提示，不硬凑。"""
    _stash(client, "想找人一起备考六级")
    _opportunity(client, engine, roles=["焊接"], title="机器人硬件组")

    assert client.get("/api/me/stash-hints").json()[0]["hints"] == []


def test_nobody_else_can_see_my_stash(client: TestClient) -> None:
    """念头不是内容流——系统里没有任何端点返回别人的念头。"""
    _stash(client, "最近想搞个短片")

    stranger = client.get(
        "/api/me/stash-hints", headers={"X-Principal-Id": str(uuid4())}
    )

    assert stranger.json() == []


def test_a_stash_never_enters_the_matching_pool(
    client: TestClient, engine: Engine
) -> None:
    from cofield.adapters.persistence.intents import IntentRepository

    _stash(client, "想拍个短片，缺剪辑")

    with campus_connection(engine, CAMPUS) as conn:
        pool = IntentRepository(conn, SimulatedClock(NOW), CAMPUS).list_matchable()

    assert pool == []


def test_hints_are_capped_so_the_page_stays_calm(
    client: TestClient, engine: Engine
) -> None:
    _stash(client, "想拍个短片，缺剪辑")
    for i in range(5):
        _opportunity(client, engine, roles=["剪辑"], title=f"招募 {i}")

    assert len(client.get("/api/me/stash-hints").json()[0]["hints"]) <= 3
