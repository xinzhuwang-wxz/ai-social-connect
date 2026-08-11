"""等配队 / 给你找的人 / 还差这几件事 的 HTTP 面。

这里断言的重点只有两条：

1. **没有一屏是空白页。** 没在等的时候、凑不出队的时候，返回的都得是
   一个能渲染出有用界面的结构，不是 404 也不是一句"暂无结果"。
2. **身份取自请求头，不取自请求体。** 承诺只接受真人签名的命令，
   请求体里带 id 等于任何人都能替任何人承诺。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from cofield.adapters.persistence.engine import owner_connection

CAMPUS = "demo-campus"


@pytest.fixture(autouse=True)
def _clear(engine: Engine):  # type: ignore[no-untyped-def]
    yield
    with owner_connection(engine) as conn:
        conn.execute(
            sa.text("TRUNCATE formation_proposals, commitments CASCADE")
        )


def _make_intent(client: TestClient, needs: list[str], place: str | None = None) -> str:
    response = client.post(
        "/api/intents",
        json={
            "expression": "想拍支短片，缺个会剪的",
            "content": {
                "goal": "拍一支 60 秒短片",
                "offers": ["写脚本"],
                "needs": needs,
                "location_scope": place,
                "team_size": {"minimum": 2, "maximum": 4},
            },
            "action_kind": "creative_work",
        },
    )
    assert response.status_code == 201, response.text
    intent_id: str = response.json()["id"]
    client.post(f"/api/intents/{intent_id}:confirm")
    return intent_id


# --- 没有一屏是空白页 ---


def test_waiting_says_something_useful_even_with_nobody_waiting(
    client: TestClient,
) -> None:
    """一个人都没在等的时候，也得说得出下次什么时候配队。

    这一屏返回 404 或者一句"暂无数据"，用户就只能盯着白屏。
    """
    response = client.get("/api/me/waiting")

    assert response.status_code == 200
    body = response.json()
    assert body["next_round_at"], "说不出下次什么时候配队"
    assert body["waiting_count"] == 0
    assert body["can_still_revise"] is True, "等待期间必须还能改需求"


def test_being_unable_to_form_a_team_is_not_an_error(client: TestClient) -> None:
    """凑不出队是常态，不是异常。

    这一屏最容易被做成一句"暂无结果"，而那正是用户流失的地方。
    """
    intent_id = _make_intent(client, ["焊接"])
    response = client.get(f"/api/intents/{intent_id}/blocked")

    assert response.status_code == 200
    body = response.json()
    assert body["statement"], "说不出卡在哪"
    assert body["next_steps"], "没有任何下一步可以点"


def test_no_teams_yet_is_an_empty_list_not_a_404(client: TestClient) -> None:
    """还没配到队 ≠ 这条需求不存在。"""
    intent_id = _make_intent(client, ["剪辑"])
    response = client.get(f"/api/intents/{intent_id}/teams")

    assert response.status_code == 200
    assert response.json() == []


def test_the_clearing_can_be_triggered_so_a_demo_does_not_wait_six_hours(
    client: TestClient,
) -> None:
    """推进时钟就能看到配队发生，不用真等一个窗口。"""
    response = client.post("/api/clearing:run")

    assert response.status_code == 200
    assert set(response.json()) == {"considered", "proposed", "blocked", "early"}


# --- 身份 ---


def test_you_cannot_read_someone_elses_teams(client: TestClient) -> None:
    """404 而不是 403——403 等于确认了这个 id 存在。"""
    response = client.get(f"/api/intents/{uuid4()}/teams")

    assert response.status_code == 404


def test_deciding_uses_the_header_identity_not_the_body(client: TestClient) -> None:
    """请求体里带 principal_id 等于任何人都能替任何人承诺。

    这里断言的是**请求体里根本没有这个字段**——多传的字段被忽略掉，
    而不是被采纳。
    """
    response = client.post(
        f"/api/proposals/{uuid4()}:decide",
        json={"answer": "accepted", "principal_id": str(uuid4())},
    )

    # 提案不存在，所以 404；重点是它没有因为请求体里那个 id 而做任何事。
    assert response.status_code in (404, 422)
    schema = client.get("/openapi.json").json()
    body_schema = schema["components"]["schemas"]["DecideRequest"]
    assert "principal_id" not in body_schema["properties"], (
        "请求体里出现了身份字段——任何人都能冒充任何人"
    )


def test_an_unknown_answer_is_refused_clearly(client: TestClient) -> None:
    """422 而不是 500：用户能理解并改正的情况不是服务出错。"""
    response = client.post(
        f"/api/proposals/{uuid4()}:decide", json={"answer": "maybe"}
    )

    assert response.status_code == 422


# --- 文案 ---


def _domain_terms() -> set[str]:
    text = (Path(__file__).resolve().parents[3] / "CONTEXT.md").read_text("utf-8")
    terms = set(re.findall(r"^\*\*([^*（\n]+)（", text, re.M))
    assert len(terms) > 20, "没抓到术语表，路径大概写错了"
    return terms


_EXTRA = (
    "意图", "主体", "切面", "共域", "漏斗", "召回", "求解", "提案",
    "稳定性", "智能体", "代理", "凭证", "信封", "撮合",
)


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for value in node.values() for s in _strings(value)]
    if isinstance(node, list):
        return [s for value in node for s in _strings(value)]
    return []


def test_the_words_users_see_are_users_words(client: TestClient) -> None:
    """响应体里不出现领域词汇。

    这条能被机器检查，不该靠 review 时凭感觉抓。
    """
    intent_id = _make_intent(client, ["焊接"], "南校区")
    banned = _domain_terms() | set(_EXTRA)

    for path in (
        "/api/me/waiting",
        f"/api/intents/{intent_id}/blocked",
        f"/api/intents/{intent_id}/teams",
    ):
        for line in _strings(client.get(path).json()):
            leaked = [t for t in banned if t in line]
            assert not leaked, f"{path} 的「{line}」里漏了领域词汇：{leaked}"


def test_the_blocked_screen_gives_real_numbers(client: TestClient) -> None:
    """「可以试试放宽条件」等于什么都没说。

    放开校区多出 137 个人还是多出 2 个，用户的决定完全不同。
    """
    intent_id = _make_intent(client, ["焊接"], "南校区")
    body = client.get(f"/api/intents/{intent_id}/blocked").json()

    for relaxation in body["relaxations"]:
        assert isinstance(relaxation["gains"], int)


def test_a_team_card_never_carries_a_score(engine: Engine, client: TestClient) -> None:
    """成局理由是逐条的，**没有分数也没有百分比**。

    一个 87% 用户无从判断，也无从反驳。
    """
    schema = client.get("/openapi.json").json()["components"]["schemas"]["TeamOut"]
    fields = set(schema["properties"])

    assert not fields & {"score", "match_rate", "confidence", "percentage"}
    assert "why_these_people" in fields
