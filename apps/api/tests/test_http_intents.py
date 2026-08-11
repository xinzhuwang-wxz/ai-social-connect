"""意图端点的行为。

跑在真数据库上，走真路由。这里断言的是**产品行为**而不是实现细节——
换掉抽取器、换掉持久化，这些用例都不该改。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from cofield.adapters.clock import SimulatedClock
from cofield.http import deps
from cofield.http.app import create_app

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
CAMPUS = "demo-campus"
CANONICAL = (
    "我想做一个关于校园流浪猫的一分钟短片，周五前完成。"
    "我会写脚本，但不认识会拍摄和剪辑的人。"
)


def _create(client: TestClient, compiled: dict, expression: str = CANONICAL) -> dict:
    content = {k: v for k, v in compiled["content"].items() if k != "uncertain_fields"}
    res = client.post("/api/intents", json={"expression": expression, "content": content})
    assert res.status_code == 201, res.text
    return res.json()


# --- 首屏 ---


def test_the_first_screen_has_scene_starters_not_an_empty_box(client: TestClient) -> None:
    """冷启动用户面对空输入框会卡住，这是漏斗第一段最大的流失点。"""
    kinds = client.get("/api/action-kinds").json()

    assert len(kinds) >= 4
    for kind in kinds:
        example = kind["starter"]["example"]
        assert len(example) > 10, "示例必须是一句完整的好例子，不是占位符"
        assert "请输入" not in example


def test_high_risk_kinds_expose_coarser_locations(client: TestClient) -> None:
    """户外同行这类线下场景，地点只能到校区——服务端强制，客户端无权提升。"""
    kinds = {k["key"]: k for k in client.get("/api/action-kinds").json()}

    assert kinds["outdoor_trip"]["risk_tier"] == "high"
    assert kinds["outdoor_trip"]["place_precision"] == "campus"
    assert kinds["creative_work"]["place_precision"] == "building"


# --- 编译 ---


def test_compiling_reads_both_role_gaps_out_of_a_negation(client: TestClient) -> None:
    res = client.post("/api/intents:compile", json={"expression": CANONICAL})

    body = res.json()
    assert res.status_code == 200
    assert body["content"]["needs"] == ["拍摄", "剪辑"]
    assert body["content"]["offers"] == ["写脚本"]


def test_compiling_writes_nothing(client: TestClient) -> None:
    """抽取只产出草稿。它不该在库里留下任何东西。"""
    client.post("/api/intents:compile", json={"expression": CANONICAL})

    assert client.get("/api/me/intents").json() == []


def test_a_vague_expression_falls_back_to_a_form(client: TestClient) -> None:
    body = client.post("/api/intents:compile", json={"expression": "随便看看"}).json()

    assert body["fall_back_to_form"] is True
    assert body["confidence"] < 0.5


def test_no_more_than_two_follow_ups(client: TestClient) -> None:
    body = client.post("/api/intents:compile", json={"expression": "随便看看"}).json()

    assert len(body["follow_ups"]) <= 2


def test_uncertain_fields_are_surfaced_not_hidden(client: TestClient) -> None:
    body = client.post(
        "/api/intents:compile", json={"expression": "缺一个会剪辑的，明天要"}
    ).json()

    assert "team_size" in body["content"]["uncertain_fields"]


# --- 那道门 ---


def test_a_saved_draft_is_not_matchable(client: TestClient) -> None:
    compiled = client.post("/api/intents:compile", json={"expression": CANONICAL}).json()

    created = _create(client, compiled)

    assert created["state"] == "draft"
    assert created["is_matchable"] is False


def test_confirming_makes_it_matchable(client: TestClient) -> None:
    compiled = client.post("/api/intents:compile", json={"expression": CANONICAL}).json()
    created = _create(client, compiled)

    confirmed = client.post(f"/api/intents/{created['id']}:confirm").json()

    assert confirmed["state"] == "active"
    assert confirmed["is_matchable"] is True


def test_editing_a_confirmed_intent_requires_confirming_again(
    client: TestClient,
) -> None:
    compiled = client.post("/api/intents:compile", json={"expression": CANONICAL}).json()
    created = _create(client, compiled)
    client.post(f"/api/intents/{created['id']}:confirm")

    revised = client.patch(
        f"/api/intents/{created['id']}",
        json={"content": {**created["content"], "goal": "改成两分钟"}},
    ).json()

    assert revised["state"] == "draft"
    assert revised["is_matchable"] is False


def test_confirming_a_conflicted_intent_names_the_clash(client: TestClient) -> None:
    """不能只回一句"参数错误"——要说清是哪两条打架。"""
    compiled = client.post("/api/intents:compile", json={"expression": CANONICAL}).json()
    created = _create(client, compiled)
    client.patch(
        f"/api/intents/{created['id']}",
        json={"content": {**created["content"], "offers": ["剪辑"], "needs": ["剪辑"]}},
    )

    res = client.post(f"/api/intents/{created['id']}:confirm")

    assert res.status_code == 409
    detail = res.json()["detail"]
    assert any(c["field"] == "needs" for c in detail["conflicts"])


# --- 念头 ---


def test_a_stash_stays_private_and_out_of_matching(client: TestClient) -> None:
    compiled = client.post(
        "/api/intents:compile", json={"expression": "最近想搞个短片"}
    ).json()
    content = {k: v for k, v in compiled["content"].items() if k != "uncertain_fields"}

    created = client.post(
        "/api/intents",
        json={"expression": "最近想搞个短片", "content": content, "stash": True},
    ).json()

    assert created["state"] == "stashed"
    assert created["is_matchable"] is False


def test_no_endpoint_returns_someone_elses_intents(client: TestClient) -> None:
    """念头只对本人可见——系统里不该有任何端点能返回别人的。"""
    compiled = client.post("/api/intents:compile", json={"expression": CANONICAL}).json()
    _create(client, compiled)

    stranger = client.get("/api/me/intents", headers={"X-Principal-Id": str(uuid4())})

    assert stranger.json() == []


# --- 时间 ---


def test_expiry_is_capped_by_the_users_own_deadline(
    client: TestClient, sim_clock: SimulatedClock
) -> None:
    compiled = client.post("/api/intents:compile", json={"expression": CANONICAL}).json()
    created = _create(client, compiled)

    confirmed = client.post(f"/api/intents/{created['id']}:confirm").json()

    deadline = confirmed["content"]["time_window"]["deadline"]
    assert confirmed["expires_at"] == deadline


def test_withdrawing_takes_it_out_of_the_pool(client: TestClient) -> None:
    compiled = client.post("/api/intents:compile", json={"expression": CANONICAL}).json()
    created = _create(client, compiled)
    client.post(f"/api/intents/{created['id']}:confirm")

    withdrawn = client.post(f"/api/intents/{created['id']}:withdraw").json()

    assert withdrawn["state"] == "withdrawn"
    assert withdrawn["is_matchable"] is False


def test_requests_without_identity_are_refused(engine: Engine) -> None:
    app = create_app()
    app.dependency_overrides[deps.get_engine] = lambda: engine
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/me/intents").status_code == 401


def test_health_needs_no_identity(engine: Engine) -> None:
    app = create_app()
    app.dependency_overrides[deps.get_engine] = lambda: engine
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/health").json() == {"status": "ok"}


def test_the_clock_flows_all_the_way_through(
    client: TestClient, sim_clock: SimulatedClock
) -> None:
    """推进仿真时钟，写入的时间戳跟着走——整条链路用的是注入的时间。"""
    compiled = client.post("/api/intents:compile", json={"expression": CANONICAL}).json()
    first = _create(client, compiled)

    sim_clock.advance(timedelta(days=1))
    second = _create(client, compiled)

    assert (
        datetime.fromisoformat(second["created_at"])
        - datetime.fromisoformat(first["created_at"])
        == timedelta(days=1)
    )
