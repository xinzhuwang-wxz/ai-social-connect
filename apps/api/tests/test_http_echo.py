"""「这次你会得到什么」与「这次留下了什么」的 HTTP 面。

这两屏是闭环的两端。这里断言的是两条产品判断，不是接口能不能通：

1. **邀请的主语是「我」**，不是"你被选中了"——单向推荐会让接收方
   觉得自己是被挑的商品
2. **证据只存事实不存评价**——这里没有任何字段能放"谁表现好"，
   一旦有了，它就变成打分系统，而打分系统会让人不敢参加自己不擅长的事
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from cofield.adapters.persistence.engine import campus_connection, owner_connection
from cofield.adapters.persistence.schema import (
    event_members,
    formation_proposals,
    shared_events,
)

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
CAMPUS = "demo-campus"


@pytest.fixture(autouse=True)
def _clean(engine: Engine):  # type: ignore[no-untyped-def]
    yield
    with owner_connection(engine) as conn:
        conn.execute(
            sa.text(
                "TRUNCATE formation_proposals, shared_events, event_members, "
                "evidence, memory_facets CASCADE"
            )
        )


def _seed_event(engine: Engine, *, me: UUID, mate: UUID) -> UUID:
    event_id = uuid4()
    with campus_connection(engine, CAMPUS) as conn:
        conn.execute(
            sa.insert(shared_events).values(
                id=event_id,
                campus_id=CAMPUS,
                proposal_id=uuid4(),
                action_kind="creative_work",
                title="拍一支 60 秒短片",
                goal="拍一支 60 秒短片",
                steward_id=me,
                formed_at=NOW,
                state="active",
            )
        )
        conn.execute(
            sa.insert(event_members),
            [
                {
                    "event_id": event_id,
                    "principal_id": person,
                    "campus_id": CAMPUS,
                    "joined_at": NOW,
                }
                for person in (me, mate)
            ],
        )
    return event_id


def _seed_proposal(engine: Engine, *, members: tuple[UUID, ...], intent_id: UUID) -> UUID:
    proposal_id = uuid4()
    with campus_connection(engine, CAMPUS) as conn:
        conn.execute(
            sa.insert(formation_proposals).values(
                id=proposal_id,
                campus_id=CAMPUS,
                intent_id=intent_id,
                action_kind="creative_work",
                cleared_at=NOW,
                member_ids=list(members),
                proof={},
                stability_passed=True,
                expires_at=datetime(2026, 9, 1, tzinfo=UTC),
                terms_digest="d0",
                version=1,
            )
        )
    return proposal_id


def _make_intent(client: TestClient) -> str:
    response = client.post(
        "/api/intents",
        json={
            "expression": "想拍支短片，缺个会剪辑的",
            "action_kind": "creative_work",
            "content": {
                "goal": "拍一支 60 秒短片",
                "offers": ["写脚本"],
                "needs": ["剪辑"],
                "team_size": {"minimum": 2, "maximum": 3},
            },
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


# --- 这次你会得到什么 ---


def test_the_invitation_speaks_in_the_first_person(
    engine: Engine, client: TestClient, me, seed_principal
) -> None:  # type: ignore[no-untyped-def]
    """**不是「你被选中了」。**

    单向推荐会让接收方觉得自己是被挑的商品，而互惠推荐的成功必须以
    多方接受为条件——单边相关度会系统性高估真实匹配。
    """
    mate = seed_principal(name="周雨")
    intent_id = UUID(_make_intent(client))
    proposal_id = _seed_proposal(engine, members=(me.id, mate.id), intent_id=intent_id)

    body = client.get(f"/api/proposals/{proposal_id}/invitation").json()

    assert body["i_get"], "说不出对方能得到什么的邀请不该被发出去"
    assert body["about"] == "拍一支 60 秒短片"
    assert "周雨" in body["with_others"]
    assert body["answer_by"], "没说什么时候要答复，等于逼人立刻决定"


def test_you_cannot_peek_at_an_invitation_that_is_not_yours(
    engine: Engine, client: TestClient, seed_principal
) -> None:  # type: ignore[no-untyped-def]
    """404 而不是 403——403 等于确认了这个邀请存在。"""
    others = (seed_principal(name="甲").id, seed_principal(name="乙").id)
    proposal_id = _seed_proposal(engine, members=others, intent_id=uuid4())

    assert client.get(f"/api/proposals/{proposal_id}/invitation").status_code == 404


def test_what_i_give_comes_after_what_i_get(client: TestClient) -> None:
    """先说代价的邀请没人会读完。

    这条查的是响应模型的字段顺序——它决定了界面默认的呈现顺序。
    """
    schema = client.get("/openapi.json").json()["components"]["schemas"]["InvitationOut"]
    fields = list(schema["properties"])

    assert fields.index("i_get") < fields.index("i_give")


# --- 这次留下了什么 ---


def test_evidence_records_facts_and_has_nowhere_to_put_a_score(
    engine: Engine, client: TestClient, me, seed_principal
) -> None:  # type: ignore[no-untyped-def]
    """**只存事实不存评价。**

    这里没有任何字段能放"谁表现好"，表里也没有——不是暂时没实现，
    是它不该存在。一旦开始存，它就变成打分系统，而打分系统会让人
    不敢参加自己不擅长的事。
    """
    mate = seed_principal(name="周雨")
    event_id = _seed_event(engine, me=me.id, mate=mate.id)

    created = client.post(
        f"/api/events/{event_id}/evidence",
        json={"kind": "note", "title": "片子剪完了，周四交的"},
    )
    assert created.status_code == 201

    schema = client.get("/openapi.json").json()["components"]["schemas"]["EvidenceIn"]
    fields = set(schema["properties"])
    assert not fields & {"rating", "score", "stars", "contribution", "performance"}


def test_only_people_who_were_there_can_leave_something(
    engine: Engine, client: TestClient, seed_principal
) -> None:  # type: ignore[no-untyped-def]
    strangers = (seed_principal(name="甲").id, seed_principal(name="乙").id)
    event_id = _seed_event(engine, me=strangers[0], mate=strangers[1])

    response = client.post(
        f"/api/events/{event_id}/evidence", json={"title": "我随便传的"}
    )

    assert response.status_code == 404


def test_a_record_i_wrote_myself_still_needs_me_to_confirm_it(
    engine: Engine, client: TestClient, me, seed_principal
) -> None:  # type: ignore[no-untyped-def]
    """本人写的东西为什么还要本人再点一次？

    因为**只留一条通往「算数」的路**：两条路意味着"哪些记录算数"
    这个问题有两个答案。
    """
    mate = seed_principal(name="周雨")
    event_id = _seed_event(engine, me=me.id, mate=mate.id)

    written = client.post(
        f"/api/events/{event_id}/records", json={"text": "我负责剪辑，片子按时交了"}
    )
    assert written.status_code == 201
    facet_id = written.json()["facet_id"]

    with campus_connection(engine, CAMPUS) as conn:
        state = conn.execute(
            sa.text("SELECT state FROM memory_facets WHERE id = :i"), {"i": facet_id}
        ).scalar_one()

    assert state == "draft", "自己写的直接就算数的话，「点头」这个动作就没有意义了"


def test_the_echo_screen_survives_the_drafting_service_being_down(
    engine: Engine, client: TestClient, me, seed_principal
) -> None:  # type: ignore[no-untyped-def]
    """抽不出草稿不是错误。

    这次没证据就没什么可抽的，起草服务挂了就闭嘴。两种情况下这一屏
    都照常——用户仍然能看证据、能自己写一条。
    """
    mate = seed_principal(name="周雨")
    event_id = _seed_event(engine, me=me.id, mate=mate.id)

    body = client.get(f"/api/events/{event_id}/echo").json()

    assert body["event_title"] == "拍一支 60 秒短片"
    assert body["evidence"] == []
    assert body["to_confirm"] == []


def test_my_invitations_only_lists_live_ones(
    engine: Engine, client: TestClient, me, seed_principal
) -> None:  # type: ignore[no-untyped-def]
    """过期的邀请不该还挂在那里——它会让人白跑一趟。"""
    mate = seed_principal(name="周雨")
    live = _seed_proposal(engine, members=(me.id, mate.id), intent_id=uuid4())
    with campus_connection(engine, CAMPUS) as conn:
        conn.execute(
            sa.update(formation_proposals)
            .where(formation_proposals.c.id != live)
            .values(withdrawn_at=NOW)
        )

    body = client.get("/api/me/proposals").json()

    # 回的是整屏而不是一串 id：只回 id 的话，N 条邀请就是 1+N 次请求，
    # 每张卡再单独问一次"我答过没有"就是 1+2N。
    assert [str(x["proposal_id"]) for x in body] == [str(live)]
    assert body[0]["my_answer"] == "pending", "没答和拒绝是两件事"


# --- 文案 ---


def _domain_terms() -> set[str]:
    text = (Path(__file__).resolve().parents[3] / "CONTEXT.md").read_text("utf-8")
    terms = set(re.findall(r"^\*\*([^*（\n]+)（", text, re.M))
    assert len(terms) > 20
    return terms


_EXTRA = ("切面", "主体", "共域", "漏斗", "召回", "求解", "提案", "智能体", "凭证")


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def test_both_screens_speak_the_users_language(
    engine: Engine, client: TestClient, me, seed_principal
) -> None:  # type: ignore[no-untyped-def]
    mate = seed_principal(name="周雨")
    event_id = _seed_event(engine, me=me.id, mate=mate.id)
    intent_id = UUID(_make_intent(client))
    proposal_id = _seed_proposal(engine, members=(me.id, mate.id), intent_id=intent_id)
    banned = _domain_terms() | set(_EXTRA)

    for path in (
        f"/api/proposals/{proposal_id}/invitation",
        f"/api/events/{event_id}/echo",
    ):
        for line in _strings(client.get(path).json()):
            leaked = [t for t in banned if t in line]
            assert not leaked, f"{path} 的「{line}」里漏了领域词汇：{leaked}"
