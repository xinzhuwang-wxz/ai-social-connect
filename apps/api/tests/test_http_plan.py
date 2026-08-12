"""行动确认卡：从"有空一起"变成"确定一起"。

PRD 把它称作**最重要的中间转化节点**，而在这之前它整个不存在——
成局那道门问的是「要不要和这几个人组队」，之后就直接掉进一堆待办里，
中间没有任何东西钉死"我们要做的到底是什么"。

这里断言的核心只有一条：**改了计划，所有人的点头一起失效。**
少了它，"我点头的时候集合在北门"和"现在写着南门"可以同时成立。
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from cofield.adapters.persistence.engine import campus_connection, owner_connection
from cofield.adapters.persistence.schema import event_members, shared_events
from cofield.adapters.persistence.schema import spaces as spaces_table

CAMPUS = "demo-campus"
NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
SATURDAY = (NOW + timedelta(days=3)).isoformat()


@pytest.fixture(autouse=True)
def _clear(engine: Engine) -> Generator[None, None, None]:
    yield
    with owner_connection(engine) as conn:
        conn.execute(
            sa.text(
                "TRUNCATE spaces, space_items, action_plans, plan_nods, "
                "day_of_states, done_marks, shared_events, event_members CASCADE"
            )
        )


@pytest.fixture
def space_with_two(engine: Engine, me: Any, seed_principal: Any) -> tuple[UUID, Any]:
    """一个已经成局的空间，两个成员。

    手写这几行是占位：共域随共同事件在确认门里诞生，没有"建空间"的端点。
    """
    mate = seed_principal(name="陈牧")
    space_id, event_id = uuid4(), uuid4()
    with campus_connection(engine, CAMPUS) as conn:
        conn.execute(
            sa.insert(shared_events).values(
                id=event_id,
                campus_id=CAMPUS,
                proposal_id=uuid4(),
                title="流浪猫短片",
                goal="拍一支 60 秒短片",
                steward_id=me.id,
                formed_at=NOW,
            )
        )
        conn.execute(
            sa.insert(event_members),
            [
                {"event_id": event_id, "principal_id": p, "campus_id": CAMPUS,
                 "joined_at": NOW}
                for p in (me.id, mate.id)
            ],
        )
        conn.execute(
            sa.insert(spaces_table).values(
                id=space_id,
                campus_id=CAMPUS,
                event_id=event_id,
                name="流浪猫短片",
                created_at=NOW,
            )
        )
    return space_id, mate


def _write(client: TestClient, space_id: UUID, **fields: Any) -> dict[str, Any]:
    body = {"title": "周六拍流浪猫", "starts_at": SATURDAY, "place": "北门", **fields}
    res = client.put(f"/api/spaces/{space_id}/plan", json=body)
    assert res.status_code == 200, res.text
    return dict(res.json())


# --- 这张卡本身 ---


def test_no_plan_yet_is_a_state_not_a_404(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """还没人建过卡，是"这件事还没定下来"，不是出错。"""
    space_id, _ = space_with_two
    res = client.get(f"/api/spaces/{space_id}/plan")

    assert res.status_code == 200
    body = res.json()
    assert body["exists"] is False
    assert body["missing"], "说不出还缺什么"


def test_it_says_what_is_still_missing_not_just_incomplete(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """「信息不全」等于让人自己去找。要说得出缺的是哪一样。"""
    space_id, _ = space_with_two
    body = _write(client, space_id, starts_at=None, place=None)

    assert body["missing"] == ["什么时候", "在哪集合"]
    assert body["confirmed"] is False


def test_a_wish_cannot_be_confirmed(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """一张没写什么时候、在哪的卡不是计划，是一个愿望。

    让人对着愿望点头，等于让"确认"这个动作贬值。
    """
    space_id, _ = space_with_two
    _write(client, space_id, starts_at=None, place=None)

    res = client.post(f"/api/spaces/{space_id}/plan:confirm")

    assert res.status_code == 422
    assert "时间和地点" in res.json()["detail"]


# --- 这个文件存在的理由 ---


def test_changing_the_plan_undoes_everyones_nod(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """改了集合地点，所有人的点头一起失效。

    **这是这张卡的全部意义。** 少了它，"我点头的时候集合在北门"和
    "现在写着南门"可以同时成立——而那正是线下行动最常见的翻车方式。
    """
    space_id, mate = space_with_two
    _write(client, space_id)
    client.post(f"/api/spaces/{space_id}/plan:confirm")
    client.post(
        f"/api/spaces/{space_id}/plan:confirm",
        headers={"X-Principal-Id": str(mate.id), "X-Campus-Id": CAMPUS},
    )
    assert client.get(f"/api/spaces/{space_id}/plan").json()["confirmed"] is True

    after = _write(client, space_id, place="南门")

    assert after["confirmed"] is False, "改了地点，之前的点头还算数"
    assert after["nodded"] == []
    assert len(after["waiting_on"]) == 2


def test_saving_the_same_thing_again_does_not_reset_anyone(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """内容没变的一次重新保存不该让所有人重点一遍头。

    摘要只算内容，不算 id 和时间戳——否则用户每点一次"保存"，
    队友就要被叫回来重新确认一次。
    """
    space_id, _ = space_with_two
    _write(client, space_id)
    client.post(f"/api/spaces/{space_id}/plan:confirm")

    again = _write(client, space_id)

    assert len(again["nodded"]) == 1
    assert again["i_nodded"] is True


def test_it_names_who_is_still_missing(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """指名道姓。"还差 2 个人"催不动任何人。"""
    space_id, mate = space_with_two
    _write(client, space_id)
    client.post(f"/api/spaces/{space_id}/plan:confirm")

    body = client.get(f"/api/spaces/{space_id}/plan").json()

    assert body["waiting_on"] == [str(mate.id)]
    assert body["confirmed"] is False


def test_someone_outside_this_thing_cannot_confirm_it(
    client: TestClient, space_with_two: tuple[UUID, Any], seed_principal: Any
) -> None:
    """不在这件事里的人点不了头。承诺只接受这件事里的人签的名。"""
    space_id, _ = space_with_two
    _write(client, space_id)
    outsider = seed_principal(name="路人")

    res = client.post(
        f"/api/spaces/{space_id}/plan:confirm",
        headers={"X-Principal-Id": str(outsider.id), "X-Campus-Id": CAMPUS},
    )

    assert res.status_code == 403


# --- 它让植物结花苞 ---


def test_confirming_the_plan_is_what_makes_it_bud(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """全员确认之后，这件事才从「长叶」走到「花苞」。

    阶段是**派生**的：它由这张卡的状态决定，不由聊了多少句决定
    （不变量 6）。
    """
    space_id, mate = space_with_two
    assert client.get(f"/api/spaces/{space_id}").json()["growth"] == "sprout"

    _write(client, space_id)
    client.post(f"/api/spaces/{space_id}/plan:confirm")
    assert client.get(f"/api/spaces/{space_id}").json()["growth"] != "bud", (
        "只有一个人点头就结花苞了"
    )

    client.post(
        f"/api/spaces/{space_id}/plan:confirm",
        headers={"X-Principal-Id": str(mate.id), "X-Campus-Id": CAMPUS},
    )

    screen = client.get(f"/api/spaces/{space_id}").json()
    assert screen["growth"] == "bud"
    assert screen["growth_word"] == "结了花苞"
    assert screen["growth_why"], "说不出凭什么是这一档"


# --- 到那天了 ---


def test_day_of_stays_quiet_until_the_day_is_near(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """事情还没定下来的时候，「我出发了」只是噪音。

    而噪音会让人学会忽略这一整块——所以它在行动前一天才出现。
    """
    space_id, _ = space_with_two
    assert client.get(f"/api/spaces/{space_id}/day-of").json()["active"] is False

    _write(client, space_id, starts_at=(NOW + timedelta(days=30)).isoformat())
    assert client.get(f"/api/spaces/{space_id}/day-of").json()["active"] is False


def test_a_change_has_to_say_what_happened(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """一个不说原因的「临时有变」只会让所有人干着急。"""
    space_id, _ = space_with_two
    _write(client, space_id)

    res = client.put(f"/api/spaces/{space_id}/day-of", json={"state": "changed"})

    assert res.status_code == 422
    assert "说一句" in res.json()["detail"]


def test_my_standing_is_a_state_not_a_history(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """从"准备好了"改成"出发了"是覆盖，不是又记一条。"""
    space_id, _ = space_with_two
    _write(client, space_id)

    client.put(f"/api/spaces/{space_id}/day-of", json={"state": "ready"})
    body = client.put(f"/api/spaces/{space_id}/day-of", json={"state": "leaving"}).json()

    assert body["my_state"] == "leaving"
    assert len(body["standings"]) == 1
    assert body["standings"][0]["word"] == "出发了"


def test_it_takes_everyone_to_call_it_done(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """一个人说做完了就标记完成，等于让他替所有人宣布。

    而这件事会写进每个人的森林。
    """
    space_id, mate = space_with_two
    _write(client, space_id)

    mine = client.post(f"/api/spaces/{space_id}/done").json()
    assert mine["all_done"] is False
    assert mine["done_waiting_on"] == [str(mate.id)]

    both = client.post(
        f"/api/spaces/{space_id}/done",
        headers={"X-Principal-Id": str(mate.id), "X-Campus-Id": CAMPUS},
    ).json()
    assert both["all_done"] is True


def test_everyone_calling_it_done_is_what_makes_it_bloom(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """开花靠全员点「做完了」，**不靠"条目都打了勾"**。

    一堆勾选完的待办不等于那件事真的发生过——而这个产品的终点是
    真的一起完成了一次行动，不是一个清空的清单。
    """
    space_id, mate = space_with_two
    _write(client, space_id)
    client.post(f"/api/spaces/{space_id}/done")
    assert client.get(f"/api/spaces/{space_id}").json()["growth"] != "bloom"

    client.post(
        f"/api/spaces/{space_id}/done",
        headers={"X-Principal-Id": str(mate.id), "X-Campus-Id": CAMPUS},
    )

    screen = client.get(f"/api/spaces/{space_id}").json()
    assert screen["growth"] == "bloom"
    assert screen["growth_word"] == "开花了"


def test_marking_done_can_be_taken_back(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """不给收回的路，人就不敢点——而不敢点会让这一步整个失效。"""
    space_id, _ = space_with_two
    _write(client, space_id)
    client.post(f"/api/spaces/{space_id}/done")

    body = client.request("DELETE", f"/api/spaces/{space_id}/done").json()

    assert body["i_marked_done"] is False


# --- 明天要出发的事 ---


def test_something_without_a_time_is_not_coming_up(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """没定时间的事不该出现在"快到了"里。

    它不是"快到了"，它是"还没定"——而那一句在别处说。
    """
    space_id, _ = space_with_two
    _write(client, space_id, starts_at=None)

    assert client.get("/api/me/coming-up").json() == []


def test_next_week_is_not_tomorrow(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """提前太多的提醒和不提醒一样，人会学会忽略它。"""
    space_id, _ = space_with_two
    _write(client, space_id, starts_at=(NOW + timedelta(days=8)).isoformat())

    assert client.get("/api/me/coming-up").json() == []


def test_tomorrow_says_when_where_and_what_to_bring(
    client: TestClient, space_with_two: tuple[UUID, Any], sim_clock: Any
) -> None:
    """到点了得有东西主动找人，而且说得出带什么、几点、在哪。"""
    space_id, _ = space_with_two
    _write(
        client,
        space_id,
        starts_at=(NOW + timedelta(days=1)).isoformat(),
        place="北门地铁口",
        bring="录音笔",
    )

    rows = client.get("/api/me/coming-up").json()

    assert len(rows) == 1
    assert rows[0]["where"] == "北门地铁口"
    assert rows[0]["bring"] == "录音笔"
    assert rows[0]["space_id"], "点不进那件事的地方"


def test_it_knows_i_already_said_where_i_am(
    client: TestClient, space_with_two: tuple[UUID, Any]
) -> None:
    """说过状态的人不该再被当成"还没准备"催一次。"""
    space_id, _ = space_with_two
    _write(client, space_id, starts_at=(NOW + timedelta(days=1)).isoformat())
    client.put(f"/api/spaces/{space_id}/day-of", json={"state": "ready"})

    assert client.get("/api/me/coming-up").json()[0]["my_state"] == "ready"


# --- 做完了 -----------------------------------------------------------------


def test_one_person_saying_done_does_not_finish_it_for_everyone(
    client: TestClient, space_with_two: tuple[UUID, Any], engine: Engine
) -> None:
    """一个人说做完了，这件事还没完。

    这件事会写进**每个人**的森林。让一个人替所有人宣布，等于让他替别人
    在自己的经历上签字。
    """
    space_id, _ = space_with_two

    body = client.post(f"/api/spaces/{space_id}/done").json()

    assert body["i_marked_done"] is True
    assert body["all_done"] is False
    assert _state_of(engine, space_id) == "active"


def test_when_everyone_says_done_the_thing_is_really_finished(
    client: TestClient, space_with_two: tuple[UUID, Any], engine: Engine
) -> None:
    """全员点完，事件真的落到 completed。

    **在这条断言之前，没有任何代码写过这个状态。** 「做完了」只落在
    `done_marks` 上，而森林里的「这件事做成了」、成长档到「开花了」、
    「这次留下了什么」、「照这个再来一次」全都在等它——一整条下游建好了，
    源头那一笔从没落过，而每一层看起来都正常。
    """
    space_id, mate = space_with_two
    client.post(f"/api/spaces/{space_id}/done")

    body = client.post(
        f"/api/spaces/{space_id}/done",
        headers={"X-Principal-Id": str(mate.id), "X-Campus-Id": CAMPUS},
    ).json()

    assert body["all_done"] is True
    assert _state_of(engine, space_id) == "completed"


def test_taking_it_back_is_still_possible_before_the_last_person(
    client: TestClient, space_with_two: tuple[UUID, Any], engine: Engine
) -> None:
    """还没齐之前点错了能收回。不给收回的路，人就不敢点。"""
    space_id, _ = space_with_two
    client.post(f"/api/spaces/{space_id}/done")

    body = client.delete(f"/api/spaces/{space_id}/done").json()

    assert body["i_marked_done"] is False
    assert _state_of(engine, space_id) == "active"


def _state_of(engine: Engine, space_id: UUID) -> str:
    with campus_connection(engine, CAMPUS) as conn:
        return str(
            conn.execute(
                sa.select(shared_events.c.state)
                .select_from(
                    shared_events.join(
                        spaces_table, spaces_table.c.event_id == shared_events.c.id
                    )
                )
                .where(spaces_table.c.id == space_id)
            ).scalar_one()
        )
