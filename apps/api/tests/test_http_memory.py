"""三个自我管理面的 HTTP 面：我参加过的 / 关于我的记录 / 谁能看到我。

断言的是**权利真的落地了**，不是"端点能返回 200"：

- 收回之后，那条**立刻**不再被任何地方引用——用 SQL 直接查，
  不是断言"我们没写那行代码"
- 没点过头的和点过头的分开返回，界面没有把两堆混起来的机会
- 别人的记录确认不了也收不回，而且失败之后那一行**没变**
- 系统里不存在能读到别人的路径

真 PostgreSQL，真迁移。唯一被替换的是"人"。
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from cofield.adapters.persistence.engine import campus_connection, owner_connection
from cofield.adapters.persistence.events import EventRepository
from cofield.adapters.persistence.memory import (
    EvidenceItem,
    FacetState,
    MemoryFacet,
    MemoryRepository,
)
from cofield.adapters.persistence.schema import event_members, memory_facets

CAMPUS = "demo-campus"

#: 和 conftest 的 FIXED_NOW 对齐。测试里的时刻必须和应用时钟同源，
#: 否则"还没过期"这类断言会随真实时间漂移。
NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)

FILM = "檐下"
GOAL = "拍一支 60 秒短片"


@pytest.fixture(autouse=True)
def _clear(engine: Engine) -> Iterator[None]:
    """事件、成员、来源材料、记录都不在 conftest 的清理清单里。

    不清的话，上一个用例留下的行会被下一个用例的断言数进去。
    """
    yield
    with owner_connection(engine) as conn:
        conn.execute(
            sa.text(
                "TRUNCATE shared_events, event_members, evidence, memory_facets, "
                "spaces, space_items, formation_proposals, commitments CASCADE"
            )
        )


# --- 装配 -------------------------------------------------------------------


def an_event(
    engine: Engine,
    members: Sequence[UUID],
    *,
    state: str = "completed",
    title: str = FILM,
) -> UUID:
    """一件真的发生过的事。

    走 `EventRepository`，不直接塞行——共同事件只有一个诞生入口，
    测试也不该给自己开第二个。
    """
    with campus_connection(engine, CAMPUS) as conn:
        formed = EventRepository(conn, CAMPUS).form(
            proposal_id=uuid4(),
            action_kind="creative_work",
            title=title,
            goal=GOAL,
            steward_id=members[0],
            member_ids=tuple(members),
            role_assignment={},
            deadline=None,
            first_action=None,
            now=NOW,
        )
        conn.execute(
            sa.text("UPDATE shared_events SET state = :s WHERE id = :i"),
            {"s": state, "i": formed.event_id},
        )
    return formed.event_id


def left_halfway(engine: Engine, event_id: UUID, who: UUID) -> None:
    with campus_connection(engine, CAMPUS) as conn:
        conn.execute(
            sa.text(
                "UPDATE event_members SET left_at = :t "
                "WHERE event_id = :e AND principal_id = :p"
            ),
            {"t": NOW + timedelta(days=1), "e": event_id, "p": who},
        )


def some_evidence(
    engine: Engine, event_id: UUID, uploader: UUID, title: str = "分镜脚本第 3 版"
) -> UUID:
    item = EvidenceItem(
        id=uuid4(),
        event_id=event_id,
        kind="note",
        title=title,
        uploaded_by=uploader,
        created_at=NOW,
    )
    with campus_connection(engine, CAMPUS) as conn:
        MemoryRepository(conn, CAMPUS).add_evidence(item)
    return item.id


def a_record(
    engine: Engine,
    who: UUID,
    *,
    text: str = "他做完过一支 60 秒短片，负责剪辑",
    event_id: UUID | None = None,
    evidence_ids: tuple[UUID, ...] = (),
    state: FacetState = FacetState.DRAFT,
    by_agent: bool = True,
) -> UUID:
    facet = MemoryFacet(
        id=uuid4(),
        principal_id=who,
        text=text,
        state=state,
        created_at=NOW,
        event_id=event_id,
        evidence_ids=evidence_ids,
        drafted_by_agent=by_agent,
        confirmed_at=NOW if state is FacetState.CONFIRMED else None,
    )
    with campus_connection(engine, CAMPUS) as conn:
        MemoryRepository(conn, CAMPUS).add_facet(facet)
    return facet.id


def an_intent(client: TestClient) -> str:
    response = client.post(
        "/api/intents",
        json={
            "expression": "想拍支短片，缺个会剪的",
            "content": {
                "goal": GOAL,
                "offers": ["写脚本"],
                "needs": ["剪辑"],
                "team_size": {"minimum": 2, "maximum": 4},
            },
            "action_kind": "creative_work",
        },
    )
    assert response.status_code == 201, response.text
    intent_id: str = response.json()["id"]
    client.post(f"/api/intents/{intent_id}:confirm")
    return intent_id


def show_to_others(client: TestClient, intent_id: str, records: list[UUID]) -> str:
    """给这条需求留下一次仍在生效的对外披露。"""
    response = client.put(
        f"/api/intents/{intent_id}/envelope",
        json={
            "grants": [
                {"field_name": "goal", "audience": "candidates"},
                {"field_name": "major", "audience": "solver_only"},
            ],
            "cited_facet_ids": [str(r) for r in records],
        },
    )
    assert response.status_code == 200, response.text
    envelope_id: str = response.json()["id"]
    return envelope_id


def row_of(engine: Engine, facet_id: UUID) -> Any:
    """直接查权威表。界面说什么不算数，这一行说了算。"""
    with campus_connection(engine, CAMPUS) as conn:
        return conn.execute(
            sa.select(memory_facets).where(memory_facets.c.id == facet_id)
        ).one()


def still_citable(engine: Engine, who: UUID, facet_id: UUID) -> bool:
    """这条现在还能不能被任何一份证明引用。

    走 `citable()`——它是切面被引用的**唯一**入口，所以这个断言问的
    就是"它现在还会不会被用出去"，而不是"某张表里还有没有这一行"。
    """
    with campus_connection(engine, CAMPUS) as conn:
        found = MemoryRepository(conn, CAMPUS).citable(
            [who], permitted=frozenset({facet_id})
        )
    return bool(found)


# --- 我参加过的 -------------------------------------------------------------


def test_an_event_shows_what_was_done_and_with_whom(
    engine: Engine, client: TestClient, me: Any, seed_principal: Any
) -> None:
    """每条是一次做成的事，不是一个头衔。

    所以「和谁做的」必须在：一个人独自完成的清单和一起做成的清单，
    对读它的人是两回事。
    """
    su = seed_principal(name="苏晚")
    an_event(engine, [me.id, su.id])

    body = client.get("/api/me/events").json()

    assert len(body) == 1
    assert body[0]["title"] == FILM
    assert body[0]["with_others"] == ["苏晚"]
    assert body[0]["counts_as_done"] is True


def test_a_cancelled_event_is_still_mine_but_is_not_a_success(
    engine: Engine, client: TestClient, me: Any
) -> None:
    """取消的事在这里可见——它属于本人的真实经历。

    但它**不产生成功记录**。藏起来等于系统替人修饰了历史；
    算成成功则等于说了假话。两者都不行，所以是"在，但不算"。
    """
    an_event(engine, [me.id], state="abandoned", title="没做成的那次")

    body = client.get("/api/me/events").json()

    assert [e["title"] for e in body] == ["没做成的那次"]
    assert body[0]["counts_as_done"] is False


def test_leaving_halfway_keeps_the_event_but_not_the_success(
    engine: Engine, client: TestClient, me: Any, seed_principal: Any
) -> None:
    """中途退出的人留在名单里，但"我们一起做完过"这句话对他不成立。"""
    su = seed_principal(name="苏晚")
    event_id = an_event(engine, [me.id, su.id])
    left_halfway(engine, event_id, me.id)

    body = client.get("/api/me/events").json()

    assert len(body) == 1, "退出过就从自己的经历里消失，等于系统替他改了历史"
    assert body[0]["left_at"] is not None
    assert body[0]["counts_as_done"] is False


def test_i_do_not_see_events_i_was_not_in(
    engine: Engine, client: TestClient, seed_principal: Any
) -> None:
    """身份来自请求头。别人的事不会因为它存在就出现在我这儿。"""
    su = seed_principal(name="苏晚")
    an_event(engine, [su.id])

    assert client.get("/api/me/events").json() == []


# --- 关于我的记录 -----------------------------------------------------------


def test_drafts_and_confirmed_come_back_apart(
    engine: Engine, client: TestClient, me: Any
) -> None:
    """没点过头的和点过头的分开返回，不是一个列表加一个状态字段。

    分组在服务端做，界面就没有把两堆混起来显示的机会——
    而"没点过的永远不出现在任何人的证明里"最怕的正是混起来。
    """
    a_record(engine, me.id, text="他剪过两支短片")
    a_record(engine, me.id, text="他写过分镜", state=FacetState.CONFIRMED)

    body = client.get("/api/me/facets").json()

    assert [r["text"] for r in body["to_confirm"]] == ["他剪过两支短片"]
    assert [r["text"] for r in body["confirmed"]] == ["他写过分镜"]
    assert body["revoked"] == []


def test_every_record_points_back_and_says_who_wrote_it(
    engine: Engine, client: TestClient, me: Any
) -> None:
    """说不出来源的记录，本人无从判断该不该留着它。

    看不出是谁写的，"AI 起草、人类决定"就只是一句话——
    所以来源与作者两样都必须在同一条卡片上。
    """
    event_id = an_event(engine, [me.id])
    source_id = some_evidence(engine, event_id, me.id)
    a_record(engine, me.id, event_id=event_id, evidence_ids=(source_id,))

    card = client.get("/api/me/facets").json()["to_confirm"][0]

    assert card["event_title"] == FILM, "指不回是哪件事留下的"
    assert [s["title"] for s in card["sources"]] == ["分镜脚本第 3 版"]
    assert card["drafted_by_agent"] is True, "看不出这句话是系统猜的"


def test_confirming_is_what_makes_a_record_usable(
    engine: Engine, client: TestClient, me: Any
) -> None:
    """点头之前它进不了任何一份证明，点头之后才能。"""
    facet_id = a_record(engine, me.id)
    assert not still_citable(engine, me.id, facet_id), "没点头就已经能被引用"

    response = client.post(f"/api/facets/{facet_id}:confirm")

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "confirmed"
    assert row_of(engine, facet_id).confirmed_at is not None
    assert still_citable(engine, me.id, facet_id)


def test_revoking_stops_it_being_used_immediately(
    engine: Engine, client: TestClient, me: Any
) -> None:
    """收回之后**下一次查询就读不到**，不是"标记为已删除但还在用"。

    三处一起验：权威表那一行、引用入口 `citable()`、以及仍在生效的
    那次对外披露现在还带不带这句话。三处不一致，撤销权就是假的。
    """
    facet_id = a_record(engine, me.id, state=FacetState.CONFIRMED)
    intent_id = an_intent(client)
    show_to_others(client, intent_id, [facet_id])

    before = client.get("/api/me/visibility").json()
    assert before[0]["shows_records"] == ["他做完过一支 60 秒短片，负责剪辑"]
    assert client.get("/api/me/facets").json()["confirmed"][0]["in_use"] == 1

    response = client.post(f"/api/facets/{facet_id}:revoke")

    assert response.status_code == 200, response.text
    row = row_of(engine, facet_id)
    assert row.state == "revoked"
    assert row.revoked_at is not None
    assert not still_citable(engine, me.id, facet_id)
    # 那次披露还在生效，但它现在带不出这句话了——不用等任何异步清理。
    after = client.get("/api/me/visibility").json()
    assert after[0]["shows_records"] == []
    assert client.get("/api/me/facets").json()["revoked"][0]["in_use"] == 0


def test_a_record_you_revoked_cannot_come_back(
    engine: Engine, client: TestClient, me: Any
) -> None:
    """收回就是收回。少了这一条，撤销退化成"暂时不用"。"""
    facet_id = a_record(engine, me.id, state=FacetState.CONFIRMED)
    client.post(f"/api/facets/{facet_id}:revoke")

    response = client.post(f"/api/facets/{facet_id}:confirm")

    assert response.status_code == 422
    assert row_of(engine, facet_id).state == "revoked"


def test_revoking_twice_is_not_an_error(
    engine: Engine, client: TestClient, me: Any
) -> None:
    """第二次点击不该报错，也不该把收回时刻改成现在。"""
    facet_id = a_record(engine, me.id, state=FacetState.CONFIRMED)
    client.post(f"/api/facets/{facet_id}:revoke")
    first = row_of(engine, facet_id).revoked_at

    again = client.post(f"/api/facets/{facet_id}:revoke")

    assert again.status_code == 200
    assert row_of(engine, facet_id).revoked_at == first


def test_you_cannot_confirm_someone_elses_record(
    engine: Engine, client: TestClient, seed_principal: Any
) -> None:
    """替别人背书这件事不该成立——而且失败之后那一行必须没变。

    404 而不是 403：403 等于告诉调用方"这条记录存在，只是不归你"。
    """
    su = seed_principal(name="苏晚")
    hers = a_record(engine, su.id, text="她拍过夜景")

    response = client.post(f"/api/facets/{hers}:confirm")

    assert response.status_code == 404
    row = row_of(engine, hers)
    assert row.state == "draft"
    assert row.confirmed_at is None


def test_you_cannot_revoke_someone_elses_record(
    engine: Engine, client: TestClient, seed_principal: Any
) -> None:
    """替别人删东西同样不成立。"""
    su = seed_principal(name="苏晚")
    hers = a_record(engine, su.id, text="她拍过夜景", state=FacetState.CONFIRMED)

    response = client.post(f"/api/facets/{hers}:revoke")

    assert response.status_code == 404
    assert row_of(engine, hers).revoked_at is None
    assert still_citable(engine, su.id, hers), "她的那条被别人弄没了"


# --- 谁能看到我 -------------------------------------------------------------


def test_visibility_says_what_it_was_for_and_when_it_lapses(
    client: TestClient, me: Any
) -> None:
    """一排"两项，72 小时后失效"分辨不出哪条是哪条，也就收不回想收的那条。

    收不回的权利等于没有这项权利，所以"这是给哪件事的"必须在。
    """
    intent_id = an_intent(client)
    show_to_others(client, intent_id, [])

    body = client.get("/api/me/visibility").json()

    assert len(body) == 1
    assert body[0]["for_what"] == GOAL
    assert body[0]["expires_at"]
    shown = {s["field_name"]: s["seen_by_others"] for s in body[0]["shows"]}
    assert shown == {"goal": True, "major": False}, (
        "分不出哪几项对方看得到、哪几项只用来配队"
    )


def test_taking_it_back_removes_it_from_the_list(
    client: TestClient, me: Any
) -> None:
    """收回之后这一屏立刻不再列它——这一屏问的是"现在谁还能看到我"。"""
    intent_id = an_intent(client)
    envelope_id = show_to_others(client, intent_id, [])

    assert client.post(f"/api/envelopes/{envelope_id}:revoke").status_code == 200

    assert client.get("/api/me/visibility").json() == []


def test_i_do_not_see_what_other_people_gave_out(
    client: TestClient, seed_principal: Any
) -> None:
    su = seed_principal(name="苏晚")
    intent_id = an_intent(client)
    show_to_others(client, intent_id, [])

    mine = client.get(
        "/api/me/visibility", headers={"X-Principal-Id": str(su.id)}
    ).json()

    assert mine == []


# --- 身份 -------------------------------------------------------------------


def test_no_endpoint_lets_anyone_browse_anyone(client: TestClient) -> None:
    """系统里不存在供他人浏览的个人主页端点。

    一旦出现 `/principals/{id}/facets` 这样的路径，冷启动用户就天然吃亏——
    产品退回"看人卡决定要不要连接"。这条靠契约本身来守，不靠记得别写。
    """
    spec = client.get("/openapi.json").json()

    assert not [p for p in spec["paths"] if p.startswith("/api/principals")]
    for path, operations in spec["paths"].items():
        if "/me/" not in path and "/facets/" not in path:
            continue
        for operation in operations.values():
            named = [
                p["name"]
                for p in operation.get("parameters", [])
                # 请求头是身份**唯一**的来源，所以它不在这条断言的范围里。
                if p.get("in") != "header" and "principal" in p["name"].lower()
            ]
            assert not named, f"{path} 从路径或查询串里取身份：{named}"


def test_the_request_body_never_carries_an_identity(client: TestClient) -> None:
    """请求体里带 principal_id 等于任何人都能替任何人收回记录。"""
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    for name in ("MyRecordOut", "MyRecordsOut", "VisibilityOut", "MyEventOut"):
        assert name in schemas, f"{name} 不在契约里，前端类型无从派生"
    # 确认与收回都是无请求体的命令：身份只能来自请求头。
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/api/facets/{facet_id}:confirm", "/api/facets/{facet_id}:revoke"):
        assert "requestBody" not in paths[path]["post"]


# --- 空、错误、降级 ---------------------------------------------------------


def test_a_brand_new_person_gets_nothing_not_an_error(client: TestClient) -> None:
    """零历史的人占人口 45%，这是他们的第一印象。

    三个面都必须是"空"而不是 404——404 会让界面显示成"出错了"，
    而事实是他刚来，什么都还没做。
    """
    assert client.get("/api/me/events").json() == []
    assert client.get("/api/me/facets").json() == {
        "to_confirm": [],
        "confirmed": [],
        "revoked": [],
    }
    assert client.get("/api/me/visibility").json() == []


def test_an_unknown_record_says_so_instead_of_failing(client: TestClient) -> None:
    response = client.post(f"/api/facets/{uuid4()}:revoke")

    assert response.status_code == 404
    assert response.json()["detail"]


def test_a_record_whose_source_is_gone_is_still_returned(
    engine: Engine, client: TestClient, me: Any
) -> None:
    """降级：来源材料被清掉之后，这条记录仍然看得见、收得回。

    整条 500 或者干脆不返回，用户就连"把它收回"都做不到——
    而那恰恰是他看到一条来源不明的记录时最想做的事。
    """
    event_id = an_event(engine, [me.id])
    source_id = some_evidence(engine, event_id, me.id)
    facet_id = a_record(engine, me.id, event_id=event_id, evidence_ids=(source_id,))
    with owner_connection(engine) as conn:
        conn.execute(sa.text("DELETE FROM evidence WHERE id = :i"), {"i": source_id})

    card = client.get("/api/me/facets").json()["to_confirm"][0]

    assert card["sources"] == []
    assert card["event_title"] == FILM
    assert client.post(f"/api/facets/{facet_id}:revoke").status_code == 200


# --- 文案 -------------------------------------------------------------------


def _domain_terms() -> set[str]:
    text = (Path(__file__).resolve().parents[3] / "CONTEXT.md").read_text("utf-8")
    terms = set(re.findall(r"^\*\*([^*（\n]+)（", text, re.M))
    assert len(terms) > 20, "没抓到术语表，路径大概写错了"
    return terms


_EXTRA = (
    "意图", "主体", "切面", "共域", "漏斗", "召回", "求解", "提案", "约束",
    "稳定性", "智能体", "代理", "凭证", "信封", "撮合", "授权", "回声", "素材",
)


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for value in node.values() for s in _strings(value)]
    if isinstance(node, list):
        return [s for value in node for s in _strings(value)]
    return []


def test_the_words_users_see_are_users_words(
    engine: Engine, client: TestClient, me: Any
) -> None:
    """响应体里不出现领域词汇。

    这三个面全是"我的"，用户会逐条读它们——术语泄漏在这里最刺眼。
    """
    event_id = an_event(engine, [me.id])
    source_id = some_evidence(engine, event_id, me.id)
    facet_id = a_record(
        engine, me.id, event_id=event_id, evidence_ids=(source_id,),
        state=FacetState.CONFIRMED,
    )
    intent_id = an_intent(client)
    show_to_others(client, intent_id, [facet_id])
    banned = _domain_terms() | set(_EXTRA)

    for path in ("/api/me/events", "/api/me/facets", "/api/me/visibility"):
        for line in _strings(client.get(path).json()):
            leaked = [t for t in banned if t in line]
            assert not leaked, f"{path} 的「{line}」里漏了领域词汇：{leaked}"


def test_a_record_card_never_carries_a_score(client: TestClient) -> None:
    """记录是可核验的事实，不是分数。

    这里没有一列能放评价——不是暂时没实现，是它不该存在。
    """
    schema = client.get("/openapi.json").json()["components"]["schemas"]["MyRecordOut"]
    fields = set(schema["properties"])

    assert not fields & {"score", "rating", "reliability", "confidence", "level"}
    assert {"sources", "drafted_by_agent"} <= fields


# --- 做过的事变成"我会什么" ---


def test_a_record_i_nodded_at_becomes_something_i_can_do(
    engine: Engine, client: TestClient, me: Any
) -> None:
    """他点头承认的这句话说到一样本事，那就是他会的。

    这是「一个人由什么表达」的第三条来源，也是唯一一条来自**做过的事**
    而不是说过的话的：做完一件事，系统从留下的东西里写出一句
    「这次的片子是他剪的」，他看过、点了头——到这一步，"会剪辑"已经比
    任何一张勾选表都更实在。

    在这条回流之前，这句话只能被引用进证明，**不参与找人**：
    做过十次剪辑的人，下一次仍然不出现在任何缺剪辑的人的候选里。
    """
    facet_id = a_record(engine, me.id)  # 「他做完过一支 60 秒短片，负责剪辑」
    assert "剪辑" not in client.get("/api/me/profile").json()["skills"]

    client.post(f"/api/facets/{facet_id}:confirm")

    assert "剪辑" in client.get("/api/me/profile").json()["skills"]


def test_a_guess_i_have_not_nodded_at_counts_for_nothing(
    engine: Engine, client: TestClient, me: Any
) -> None:
    """系统猜的那一版什么都不算——这正是那道门存在的意义。"""
    a_record(engine, me.id)

    assert client.get("/api/me/profile").json()["skills"] == []


# --- 照上次再来一次 ---


def test_doing_it_again_starts_from_a_draft_not_a_new_thing(
    engine: Engine, client: TestClient, me: Any, seed_principal: Any
) -> None:
    """带过来的东西要让本人过目。

    **尤其是时间和地点——它们必然是新的。** 抽取只产出草稿这条规矩在这里
    同样成立：直接建一条新需求，等于替他决定了这次要做的和上次一模一样。
    """
    mate = seed_principal(name="苏晚")
    event_id = an_event(engine, [me.id, mate.id])

    body = client.get(f"/api/events/{event_id}/again").json()

    assert body["goal"], "说不出上次做的是什么"
    assert body["last_time_with"], "不知道上次和谁一起"
    # 缺什么由本人重填：上次缺的这次未必缺，带过来一个错的比空着糟。
    assert body["needs"] == []


def test_someone_who_was_not_there_cannot_reuse_it(
    engine: Engine, client: TestClient, me: Any, seed_principal: Any
) -> None:
    """不在那件事里的人翻不出它。404 而不是 403——403 等于确认了它存在。"""
    other = seed_principal(name="路人")
    event_id = an_event(engine, [other.id])

    assert client.get(f"/api/events/{event_id}/again").status_code == 404


def test_asking_them_again_makes_a_proposal_not_a_membership(
    engine: Engine, client: TestClient, me: Any, seed_principal: Any
) -> None:
    """「一键重新邀请」邀的是**答复**，不是人。

    不变量 3：成局前只有提案，没有关系。所以按完之后那几个人各自多了
    一条待答复，而这件事的成员一个没变——把他们直接算进去，等于系统
    替他们答应了。
    """
    mate = seed_principal(name="苏晚")
    _can(engine, mate.id, ["拍摄", "剪辑"])
    event_id = an_event(engine, [me.id, mate.id])
    intent_id = _a_confirmed_intent(client)

    before = _members_of(engine, event_id)
    res = client.post(
        f"/api/events/{event_id}:again",
        json={"intent_id": str(intent_id), "invite": [str(mate.id)]},
    )

    assert res.status_code == 200, res.text
    assert _members_of(engine, event_id) == before, "把人直接算进了旧事件"


def test_pressing_ask_them_again_twice_does_not_ask_twice(
    engine: Engine, client: TestClient, me: Any, seed_principal: Any
) -> None:
    """按第二次问不出去。

    清算那条路一直守着"同一件事不问第二遍"，而这条路是**人主动按的**，
    没有清算边界可依——挡在界面上的"按过了"刷新一下就没了，于是同一批
    人会收到第二条待答复。

    边界只能画在"上一份还活着"上：还有人等着答复，就不再发。
    """
    mate = seed_principal(name="苏晚")
    _can(engine, mate.id, ["拍摄", "剪辑"])
    event_id = an_event(engine, [me.id, mate.id])
    intent_id = _a_confirmed_intent(client)
    body = {"intent_id": str(intent_id), "invite": [str(mate.id)]}

    first = client.post(f"/api/events/{event_id}:again", json=body).json()["asked"]
    second = client.post(f"/api/events/{event_id}:again", json=body).json()["asked"]

    # 第一次问没问出去（比如这几个人这次凑不成组）时，这条断言什么也
    # 证明不了——那种情况下两次都是 0，测试会假绿。
    assert first == 1, "第一次就没问出去，后面这条断言证明不了幂等"
    assert second == 0, "按第二次又问了一遍同一批人"


def _a_confirmed_intent(client: TestClient) -> UUID:
    """一条真的能拿去找人的需求。草稿不行——那道门是这个产品的地基。

    **只缺一个人。** 抽取那句话得到的是"三四个人"，而这两条测试的校园里
    只有两个真人——凑不成组的时候两次都返回 0，幂等那条断言会假绿。
    要验的是"问过第二遍没有"，就不能让它先倒在"根本没问出去"上。
    """
    compiled = client.post(
        "/api/intents:compile",
        json={"expression": "想再做一支一分钟的校园短片，这周内完成。我会写脚本，缺剪辑"},
    ).json()
    content = {k: v for k, v in compiled["content"].items() if k != "uncertain_fields"}
    content["needs"] = ["剪辑"]
    content["team_size"] = {"minimum": 2, "maximum": 2}
    created = client.post(
        "/api/intents", json={"expression": "再做一支短片", "content": content}
    ).json()
    client.post(f"/api/intents/{created['id']}:confirm")
    return UUID(created["id"])


def _can(engine: Engine, principal_id: UUID, skills: list[str]) -> None:
    """让这个人真的会点什么。**走本人那一面的写入口**，不直接塞列——
    "谁写这一列"正是这个产品曾经整体缺过的那一环。"""
    from cofield.adapters.clock import SimulatedClock
    from cofield.adapters.persistence.principals import PrincipalRepository

    with campus_connection(engine, CAMPUS) as conn:
        PrincipalRepository(conn, SimulatedClock(NOW)).describe(
            principal_id, skills=skills, open_to=[], self_intro=None, zone=None
        )


def _members_of(engine: Engine, event_id: UUID) -> set[UUID]:
    with campus_connection(engine, CAMPUS) as conn:
        rows = conn.execute(
            sa.select(event_members.c.principal_id).where(
                event_members.c.event_id == event_id
            )
        ).all()
    return {r.principal_id for r in rows}
