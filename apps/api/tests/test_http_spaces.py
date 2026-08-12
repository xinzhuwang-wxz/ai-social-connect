"""共域的 HTTP 面。

断言的不是"端点返回 200"，而是五件在这一层最容易被做没的事：

1. 身份只从请求头来——请求体里塞别人的 id 一律不算数
2. 关掉助手是**正常状态**不是故障：建议端点返回空列表，HTTP 200
3. 要真人点头的事，走 HTTP 也一样关不掉，助手也拿不到那一票
4. 别的租户的空间表现为"不存在"，不是"存在但没权限"
5. 响应里那几段给人看的话不出现领域词汇

真 PostgreSQL、真行级安全、真磁带回放。空间由测试直接写一行占位——
建空间是确认门的活（不变量 3），这一层没有那个入口是刻意的。
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from cofield.adapters.persistence.engine import campus_connection, owner_connection
from cofield.adapters.persistence.schema import spaces as spaces_table
from cofield.space import field_agent

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
CAMPUS = "demo-campus"
OTHER_CAMPUS = "simulation"

#: 这条事实在磁带里有一次真模型的真回答（见 tests/cassettes）。
#: 助手拿到的事实就是画布上算数的条目标题，所以标题必须原样是它。
RECORDED_FACT = "周雨能补上缺的剪辑"

#: 不得出现在任何用户可见文案里的词（07 §2，清单源自 CONTEXT.md 术语表）。
#:
#: 只查**值**不查键：字段名用领域词是对的（三层同名），给人看的字符串用
#: 领域词才是错的。两者是两套东西，08 §1③ 说得很清楚。
DOMAIN_WORDS = (
    "共域",
    "切面",
    "意图",
    "求解",
    "约束",
    "提案",
    "漏斗",
    "召回",
    "智能体",
    "代理",
    "成局",
    "撮合",
    "信封",
    "凭证",
    "主体",
    "回声",
    "素材",
    "稳定分区",
    "纪元",
    "超边",
    "共同事件",
    "行动类别",
)


@pytest.fixture(autouse=True)
def _clear_spaces(engine: Engine) -> Generator[None, None, None]:
    """空间与条目不在 conftest 的清理清单里，自己收。"""
    yield
    with owner_connection(engine) as conn:
        conn.execute(sa.text("TRUNCATE spaces, space_items CASCADE"))


def open_space(
    engine: Engine, *, campus: str = CAMPUS, agent_enabled: bool = True
) -> UUID:
    """写一行空间。

    **这是确认门的活，不是这一层的接口。** 共域随共同事件在确认门里诞生，
    所以没有"建空间"的端点可以调——测试里手写这一行是占位。
    """
    space_id = uuid4()
    with campus_connection(engine, campus) as conn:
        conn.execute(
            sa.insert(spaces_table).values(
                id=space_id,
                campus_id=campus,
                event_id=uuid4(),
                name="流浪猫短片",
                agent_enabled=agent_enabled,
                created_at=NOW,
            )
        )
    return space_id


@pytest.fixture
def space_id(engine: Engine) -> UUID:
    return open_space(engine)


@pytest.fixture
def chen_mu(seed_principal: Any) -> Any:
    """第二个真人。决策门要两个人点头才有"还差谁"这回事。"""
    return seed_principal(name="陈牧")


def add_task(client: TestClient, space_id: UUID, title: str, **rest: Any) -> dict:
    res = client.post(
        f"/api/spaces/{space_id}/items",
        json={"kind": "task", "title": title, **rest},
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


def open_gate(client: TestClient, space_id: UUID, deciders: list[UUID]) -> dict:
    res = client.post(
        f"/api/spaces/{space_id}/items",
        json={
            "kind": "decision_gate",
            "title": "署名怎么写",
            "extras": {"deciders": [str(u) for u in deciders]},
        },
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


def strings(value: Any) -> Iterator[str]:
    """遍历一份 JSON 里的全部字符串**值**。"""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from strings(nested)


# --- 一屏 -------------------------------------------------------------------


def test_a_brand_new_space_opens_as_a_usable_empty_screen(
    client: TestClient, space_id: UUID
) -> None:
    """空态是**可用的一屏**，不是错误，也不是一片空白。

    五态里的「空」最容易被做成 404 或者一个转圈——两者都会让用户以为
    出了问题，而这里什么问题都没有：这件事刚开始而已。
    """
    res = client.get(f"/api/spaces/{space_id}")

    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "流浪猫短片"
    assert body["cards"] == []
    assert body["progress"] == {"done": 0, "total": 0}
    assert body["summary"] == "还没有要做的事"


def test_the_screen_says_what_is_stuck_and_what_is_still_open(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    """一屏要能同时回答四句话：做什么、谁负责、卡在哪、还有哪些决定没关。"""
    add_task(client, space_id, "借设备", assignee_id=str(me.id))
    add_task(client, space_id, "先定下碰面地点")  # 没人认领 = 卡住
    open_gate(client, space_id, [me.id, chen_mu.id])

    body = client.get(f"/api/spaces/{space_id}").json()

    assert [c["title"] for c in body["stuck"]] == ["先定下碰面地点"]
    assert [c["title"] for c in body["open_gates"]] == ["署名怎么写"]
    assert body["progress"] == {"done": 0, "total": 2}
    assert "2 件事做完 0 件" in body["summary"]


def test_item_kinds_come_from_the_registry(client: TestClient) -> None:
    """能放哪几类东西由注册表说了算。

    新增一种条目时这里自动多一项，前端不改代码——这是那个扩展点的
    可见证据。`label` 那一列已经是用户词了。
    """
    kinds = {k["key"]: k for k in client.get("/api/item-kinds").json()}

    assert kinds["task"]["label"] == "要做的事"
    assert kinds["decision_gate"]["needs_human_decision"] is True
    assert kinds["task"]["needs_human_decision"] is False


# --- 身份 -------------------------------------------------------------------


def test_who_put_it_there_comes_from_the_header_not_the_body(
    client: TestClient, space_id: UUID, me: Any
) -> None:
    """请求体里塞别人的 id 不算数。

    身份可以由请求体决定的话，任何人都能冒充任何人——这是一个默认敞开的
    洞，不是一次失误。所以这条断的是"塞了也没用"，不是"塞了会报错"。
    """
    someone_else = uuid4()

    item = add_task(
        client,
        space_id,
        "借设备",
        created_by=str(someone_else),
        principal_id=str(someone_else),
    )

    assert item["created_by"] == str(me.id)


def test_a_body_borne_identity_does_not_buy_a_nod(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    """不是该点头的人，请求体里写上该点头的人也没用。"""
    gate = open_gate(client, space_id, [me.id, chen_mu.id])
    outsider = uuid4()

    res = client.post(
        f"/api/spaces/{space_id}/items/{gate['id']}:confirm",
        json={"principal_id": str(me.id)},
        headers={"X-Principal-Id": str(outsider)},
    )

    assert res.status_code == 403
    assert client.get(f"/api/spaces/{space_id}").json()["open_gates"]


def test_another_campus_sees_nothing_rather_than_a_refusal(
    client: TestClient, space_id: UUID
) -> None:
    """跨租户是 404 不是 403。

    403 等于确认了这个 id 存在——那本身就是一次泄漏。这里连接已绑定租户，
    行级安全把那行过滤掉了，所以"看不见"和"不存在"在这一层就是同一件事。
    """
    res = client.get(
        f"/api/spaces/{space_id}", headers={"X-Campus-Id": OTHER_CAMPUS}
    )

    assert res.status_code == 404


def test_a_missing_item_is_not_found_rather_than_a_conflict(
    client: TestClient, space_id: UUID
) -> None:
    """打错一个 id 是 404。

    画布把"这个空间里没有它"抛成一次非法操作；混成 409 的话，前端会把
    一次打错的 id 当成状态冲突去重试。
    """
    res = client.patch(
        f"/api/spaces/{space_id}/items/{uuid4()}", json={"state": "doing"}
    )

    assert res.status_code == 404


# --- 推进与指派 -------------------------------------------------------------


def test_advancing_and_handing_work_over(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    task = add_task(client, space_id, "借设备", assignee_id=str(me.id))
    url = f"/api/spaces/{space_id}/items/{task['id']}"

    moved = client.patch(url, json={"state": "doing", "assignee_id": str(chen_mu.id)})

    assert moved.status_code == 200
    assert moved.json()["state"] == "doing"
    assert moved.json()["assignee_id"] == str(chen_mu.id)

    # 做完了的那一件才计入进度。空间因真实行动生长，不因写了几条生长（不变量 6）。
    client.patch(url, json={"state": "done"})
    assert client.get(f"/api/spaces/{space_id}").json()["progress"] == {
        "done": 1,
        "total": 1,
    }


def test_putting_work_back_is_telling_it_apart_from_not_touching_it(
    client: TestClient, space_id: UUID, me: Any
) -> None:
    """显式给 null 是"把活放回去"，不给这个字段才是"不动它"。

    两者混成一个可选字段的话，改状态会顺手把负责人抹掉——而"没人负责"
    正是这块画布判断卡住的依据。
    """
    task = add_task(client, space_id, "借设备", assignee_id=str(me.id))
    url = f"/api/spaces/{space_id}/items/{task['id']}"

    assert client.patch(url, json={"state": "doing"}).json()["assignee_id"] == str(me.id)
    assert client.patch(url, json={"assignee_id": None}).json()["assignee_id"] is None
    assert [c["title"] for c in client.get(f"/api/spaces/{space_id}").json()["stuck"]] == [
        "借设备"
    ]


def test_what_a_kind_requires_is_refused_at_the_edge(
    client: TestClient, space_id: UUID
) -> None:
    """没有来源和可见范围的东西不许进来（不变量 5）。

    先收下再补是不行的：补不上的那一条已经在库里了。
    """
    res = client.post(
        f"/api/spaces/{space_id}/items",
        json={"kind": "material", "title": "第一版粗剪"},
    )

    assert res.status_code == 422


def test_an_unknown_kind_is_a_bad_request_not_a_silent_default(
    client: TestClient, space_id: UUID
) -> None:
    res = client.post(
        f"/api/spaces/{space_id}/items", json={"kind": "poll", "title": "投个票"}
    )

    assert res.status_code == 422


def test_sending_it_outside_needs_a_settled_decision_first(
    client: TestClient, space_id: UUID
) -> None:
    """放宽可见范围要先有一次点齐的点头，收窄不用。

    这不是对称性的疏忽：发出去是相关人共同的事，收回自己的东西是权利，
    而要走流程才能行使的权利等于没有（07 原则三）。
    """
    res = client.post(
        f"/api/spaces/{space_id}/items",
        json={
            "kind": "material",
            "title": "第一版粗剪",
            "extras": {"source": "周雨的相机", "reach": "ours"},
        },
    )
    item_id = res.json()["id"]

    widened = client.patch(
        f"/api/spaces/{space_id}/items/{item_id}", json={"reach": "outside"}
    )

    assert widened.status_code == 403


# --- 决策门 -----------------------------------------------------------------


def test_a_gate_closes_only_when_everyone_has_nodded(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    """少一个人就关上等于"没读的人默认被代表"，那正是群聊做错的事。

    中间那一步还要说得出**还差谁**——说得出名字的人知道该去戳谁，
    这比"还差 1 个人"多的不是礼貌，是可行动性。
    """
    gate = open_gate(client, space_id, [me.id, chen_mu.id])
    url = f"/api/spaces/{space_id}/items/{gate['id']}:confirm"

    half = client.post(url).json()
    assert half["state"] == "open"
    assert half["confirmed_by"] == [str(me.id)]

    waiting = client.get(f"/api/spaces/{space_id}").json()["open_gates"][0]
    assert waiting["notice"] == "还差陈牧点头"

    done = client.post(url, headers={"X-Principal-Id": str(chen_mu.id)}).json()
    assert done["state"] == "settled"
    assert client.get(f"/api/spaces/{space_id}").json()["open_gates"] == []


def test_a_gate_cannot_be_closed_by_advancing_it(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    """`PATCH state=settled` 是最好走的那条后门，走 HTTP 也一样不通。

    留着它的话，"要真人逐个点头"就只是 `:confirm` 那一个端点上的自觉。
    """
    gate = open_gate(client, space_id, [me.id, chen_mu.id])

    res = client.patch(
        f"/api/spaces/{space_id}/items/{gate['id']}", json={"state": "settled"}
    )

    assert res.status_code == 403
    assert client.get(f"/api/spaces/{space_id}").json()["open_gates"]


def test_the_assistant_cannot_nod_even_when_it_is_on_the_list(
    client: TestClient, space_id: UUID, me: Any
) -> None:
    """助手拿不到那一票，**哪怕有人把它写进了名单**。

    它的 id 由 space_id 派生，知道 space_id 的人都算得出来。不在这一层
    挡住的话，"AI 不能代为承诺"在 HTTP 面上就只剩"它没办法发请求"这一句
    自觉——而那句自觉挡不住任何一个知道 space_id 的人。
    """
    assistant = field_agent(space_id).id
    gate = open_gate(client, space_id, [me.id, assistant])

    res = client.post(
        f"/api/spaces/{space_id}/items/{gate['id']}:confirm",
        headers={"X-Principal-Id": str(assistant)},
    )

    assert res.status_code == 403
    assert client.get(f"/api/spaces/{space_id}").json()["open_gates"]


# --- 助手 -------------------------------------------------------------------


def test_switching_the_assistant_off_leaves_everything_else_intact(
    client: TestClient, space_id: UUID, me: Any
) -> None:
    """助手是画布上的一张卡片，不是画布的运行时。

    关掉之后人工那几栏一条都不少——这是 M3 的判据之一。
    """
    add_task(client, space_id, "借设备", assignee_id=str(me.id))

    off = client.post(f"/api/spaces/{space_id}/agent:toggle", json={"enabled": False})

    assert off.status_code == 200
    assert off.json()["agent_enabled"] is False
    assert [c["title"] for c in off.json()["cards"]] == ["借设备"]
    # 关着也照常放东西、照常推进。
    later = add_task(client, space_id, "先定下碰面地点")
    assert (
        client.patch(
            f"/api/spaces/{space_id}/items/{later['id']}", json={"state": "doing"}
        ).status_code
        == 200
    )

    # 再打开也是一步的事——要走流程才能关掉的助手，等于关不掉（07 原则三）。
    back = client.post(f"/api/spaces/{space_id}/agent:toggle", json={"enabled": True})
    assert back.json()["agent_enabled"] is True
    assert len(back.json()["cards"]) == 2


def test_suggestions_are_empty_when_the_assistant_is_off(
    client: TestClient, engine: Engine, me: Any
) -> None:
    """**关掉助手时建议端点返回空列表，HTTP 200。**

    关掉助手是一个正常状态，不是一次故障。回 4xx 会让界面弹一个红框，
    等于把用户自己的选择显示成出了问题。
    """
    space_id = open_space(engine, agent_enabled=False)
    add_task(client, space_id, RECORDED_FACT)

    res = client.get(f"/api/spaces/{space_id}/suggestions")

    assert res.status_code == 200
    assert res.json() == []


def test_an_empty_space_makes_it_shut_up_rather_than_invent(
    client: TestClient, space_id: UUID
) -> None:
    """空空的空间里助手无话可说。

    这时候闭嘴比编一条"欢迎开始协作"好——后者是纯粹的噪音，而且会让
    用户学会忽略它说的所有话。
    """
    assert client.get(f"/api/spaces/{space_id}/suggestions").json() == []


def test_a_suggestion_always_says_what_it_was_written_from(
    client: TestClient, space_id: UUID
) -> None:
    """看不到依据的建议，"人类决定"就只是点一下按钮。"""
    add_task(client, space_id, RECORDED_FACT)

    suggestions = client.get(f"/api/spaces/{space_id}/suggestions").json()

    assert suggestions, "磁带该命中却没命中，这条用例什么都没验证"
    for suggestion in suggestions:
        assert suggestion["grounded_in"] == [RECORDED_FACT]


def test_an_accepted_suggestion_keeps_both_signatures(
    client: TestClient, space_id: UUID, me: Any
) -> None:
    """助手写的、真人认的——**两个署名都要留着**。

    分不清谁写的，"AI 起草、人类决定"就只是一句话。认过之后它才算数：
    进完成度、能落到人头上。
    """
    add_task(client, space_id, RECORDED_FACT)
    suggestion = client.get(f"/api/spaces/{space_id}/suggestions").json()[0]

    res = client.post(f"/api/spaces/{space_id}/suggestions:accept", json=suggestion)

    assert res.status_code == 201
    item = res.json()
    assert item["drafted_by_agent"] is True
    assert item["accepted_by"] == str(me.id)
    assert item["awaiting_a_person"] is False
    screen = client.get(f"/api/spaces/{space_id}").json()
    assert item["id"] in [c["id"] for c in screen["cards"]]


def test_a_suggestion_without_grounds_never_reaches_the_canvas(
    client: TestClient, space_id: UUID
) -> None:
    """「点开看依据」这个承诺要么永远成立，要么就不成立。"""
    res = client.post(
        f"/api/spaces/{space_id}/suggestions:accept",
        json={"kind": "task", "title": "随便做点什么", "grounded_in": []},
    )

    assert res.status_code == 403


def test_nothing_can_be_accepted_while_the_assistant_is_off(
    client: TestClient, engine: Engine
) -> None:
    """关掉它，它的写入路径整条不通——包括这一条。

    这里是 409 而不是空列表：读一屏时"没有建议"是正常的，而按下采纳
    却什么都没发生，界面就只能说"点了没反应"。
    """
    space_id = open_space(engine, agent_enabled=False)

    res = client.post(
        f"/api/spaces/{space_id}/suggestions:accept",
        json={"kind": "task", "title": "约周四下午", "grounded_in": [RECORDED_FACT]},
    )

    assert res.status_code == 409


# --- 语言 -------------------------------------------------------------------


def test_no_domain_vocabulary_reaches_the_screen(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    """响应里给人看的字符串不出现领域词汇（07 §2）。

    严谨性应该被**感受到**，不应该被**阅读到**。这条检查只看值不看键——
    字段名用领域词是对的，那是三层同名那条红线要的。
    """
    add_task(client, space_id, RECORDED_FACT)
    add_task(client, space_id, "先定下碰面地点")
    gate = open_gate(client, space_id, [me.id, chen_mu.id])

    bodies = [
        client.get(f"/api/spaces/{space_id}").json(),
        client.get("/api/item-kinds").json(),
        client.get(f"/api/spaces/{space_id}/suggestions").json(),
        # 拒绝的话也是用户读的。它们最容易漏，因为没人会去设计错误文案。
        client.patch(
            f"/api/spaces/{space_id}/items/{gate['id']}", json={"state": "settled"}
        ).json(),
        client.post(
            f"/api/spaces/{space_id}/items", json={"kind": "material", "title": "粗剪"}
        ).json(),
        client.get(f"/api/spaces/{uuid4()}").json(),
    ]

    for body in bodies:
        for text in strings(body):
            for word in DOMAIN_WORDS:
                assert word not in text, f"用户读得到的这句话里有领域词「{word}」：{text}"


# --- 投票：把「还没定的事」变成一次能收敛的选择 ---


def _a_poll(
    client: TestClient, space_id: UUID, deciders: list[str], **rest: Any
) -> dict:
    res = client.post(
        f"/api/spaces/{space_id}/items",
        json={
            "kind": "poll",
            "title": "周六去东湖还是磨山？",
            "extras": {"options": ["东湖", "磨山"], "deciders": deciders},
            **rest,
        },
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


def test_a_poll_shows_the_count_to_everyone(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    """票数实时可见。

    藏着计票会让人觉得系统在操纵，而这是一个五六个人的组——
    他们本来就看得见彼此。
    """
    item = _a_poll(client, space_id, [str(me.id), str(chen_mu.id)])

    body = client.post(
        f"/api/spaces/{space_id}/items/{item['id']}:vote", json={"choice": 0}
    ).json()

    assert body["tally"][0]["votes"] == 1
    assert body["my_choice"] == 0
    assert body["waiting_on"], "说不出还差谁投"


def test_changing_my_mind_replaces_my_vote_not_adds_one(
    client: TestClient, space_id: UUID, me: Any
) -> None:
    """一个人只能改自己那一票。"""
    item = _a_poll(client, space_id, [str(me.id)])
    client.post(f"/api/spaces/{space_id}/items/{item['id']}:vote", json={"choice": 0})

    body = client.post(
        f"/api/spaces/{space_id}/items/{item['id']}:vote", json={"choice": 1}
    ).json()

    assert [t["votes"] for t in body["tally"]] == [0, 1]


def test_a_tie_is_reported_as_a_tie(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    """平票就是平票。**替人破局等于替人做决定**，而这一步的全部意义
    正是把决定交回给人。"""
    item = _a_poll(client, space_id, [str(me.id), str(chen_mu.id)])
    client.post(f"/api/spaces/{space_id}/items/{item['id']}:vote", json={"choice": 0})
    body = client.post(
        f"/api/spaces/{space_id}/items/{item['id']}:vote",
        json={"choice": 1},
        headers={"X-Principal-Id": str(chen_mu.id), "X-Campus-Id": CAMPUS},
    ).json()

    assert body["leading"] is None


def test_the_most_votes_does_not_close_it(
    client: TestClient, space_id: UUID, me: Any
) -> None:
    """票最多的那个不会自己变成"定了"。

    一次投票是**表达**，不是承诺（不变量 11）。把它直接当成承诺，
    "谁同意了什么"就没有可查的答案了。
    """
    item = _a_poll(client, space_id, [str(me.id)])

    body = client.post(
        f"/api/spaces/{space_id}/items/{item['id']}:vote", json={"choice": 0}
    ).json()

    assert body["leading"] == "东湖"
    assert body["settled"] is False, "票一多就自己关上了"
    # 关上它仍然要有人点头，走的是和别的要定的事同一条路。
    assert (
        client.post(f"/api/spaces/{space_id}/items/{item['id']}:confirm").status_code
        == 200
    )
    assert client.get(f"/api/spaces/{space_id}/polls").json()[0]["settled"] is True


def test_there_is_no_such_option(client: TestClient, space_id: UUID, me: Any) -> None:
    """投一个不存在的选项要被拦住，不是静默记下一个越界的数字。"""
    item = _a_poll(client, space_id, [str(me.id)])

    res = client.post(
        f"/api/spaces/{space_id}/items/{item['id']}:vote", json={"choice": 7}
    )

    assert res.status_code == 422


def test_a_poll_without_options_cannot_be_created(
    client: TestClient, space_id: UUID, me: Any
) -> None:
    """没有选项的投票不是投票。"""
    res = client.post(
        f"/api/spaces/{space_id}/items",
        json={
            "kind": "poll",
            "title": "去哪？",
            "extras": {"deciders": [str(me.id)]},
        },
    )

    assert res.status_code == 422
