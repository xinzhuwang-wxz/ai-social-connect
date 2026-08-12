"""群聊的 HTTP 面。

断言的不是"端点返回 200"，而是六件在这一层最容易被做没的事：

1. **说话的人来自请求头**，请求体里塞别人的 id、塞 `is_agent` 一律不算数
2. 空消息不落库——一条只有空格的消息在界面上是个占位气泡
3. **助手关掉时话题端点返回空数组 + 200，而群聊照常可用**
   （M3 判据「关掉助手后共域照常」在聊天上的延伸）
4. 起草说不出话时降级：发不出话题，人自己聊照常
5. **聊出共识不等于结门**：话题卡下面写满"同意"，决策门一动不动
6. 别的租户读不到、也写不进这个组的聊天

真 PostgreSQL、真行级安全、真磁带回放。空间由测试直接写一行占位——
建空间是确认门的活（不变量 3），这一层没有那个入口是刻意的。
"""

from __future__ import annotations

import re
from collections.abc import Generator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from cofield.adapters.clock import SimulatedClock
from cofield.adapters.persistence.engine import campus_connection, owner_connection
from cofield.adapters.persistence.schema import spaces as spaces_table
from cofield.space import field_agent

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
CAMPUS = "demo-campus"
OTHER_CAMPUS = "simulation"
REPO_ROOT = Path(__file__).resolve().parents[3]

#: 这两件事在磁带里有一次真模型的真回答（见 tests/cassettes）。
#: 助手拿到的事实就是决策门的标题，所以标题必须原样是它们。
SIGNING = "署名怎么写"
WHERE = "碰面地点定在哪"

#: 磁带里**没有**的一件事。它走的是和"起草服务挂了"完全同一条降级路径——
#: 起草说不出话就是说不出话，磁带缺一条和服务挂掉在调用方看来是同一件事。
UNRECORDED = "片尾音乐用谁的"

#: 领域词汇的词根。完整术语表从 CONTEXT.md 读（见 `_domain_terms`），
#: 这里补的是那份表里拆不出来的部分：07 §2 映射表左列的工程词。
STEMS = (
    "共域",
    "智能体",
    "代理",
    "切面",
    "凭证",
    "主体",
    "成局",
    "撮合",
    "信封",
    "提案",
    "求解",
    "约束",
    "回声",
    "素材",
    "纪元",
    "policy_epoch",
)


def _domain_terms() -> frozenset[str]:
    """黑名单直接从 CONTEXT.md 的术语表生成——07 §2.1 就是这么要求的。

    手抄一份清单会跟着文档漂移。读原文的代价是路径写错时测试会静默通过，
    所以下面那条数量断言不是保险，是这个做法能成立的前提。
    """
    text = (REPO_ROOT / "CONTEXT.md").read_text(encoding="utf-8")
    terms = frozenset(re.findall(r"^\*\*([^*（]+)（", text, flags=re.MULTILINE))
    assert len(terms) > 20, "没读到术语表，黑名单是空的"
    return terms


@pytest.fixture(autouse=True)
def _clear_spaces(engine: Engine) -> Generator[None, None, None]:
    """空间、条目与消息不在 conftest 的清理清单里，自己收。"""
    yield
    with owner_connection(engine) as conn:
        conn.execute(sa.text("TRUNCATE spaces, space_items, space_messages CASCADE"))


def open_space(
    engine: Engine, *, campus: str = CAMPUS, agent_enabled: bool = True
) -> UUID:
    """写一行空间。建空间是确认门的活，这里手写一行当占位。"""
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


def chat_url(space_id: UUID) -> str:
    return f"/api/spaces/{space_id}/chat"


def open_gate(
    client: TestClient, space_id: UUID, deciders: list[UUID], title: str = SIGNING
) -> dict:
    """一件还没定的事。它就是话题卡唯一合法的来源。"""
    res = client.post(
        f"/api/spaces/{space_id}/items",
        json={
            "kind": "decision_gate",
            "title": title,
            "extras": {"deciders": [str(u) for u in deciders]},
        },
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


def say(client: TestClient, space_id: UUID, text: str, **rest: Any) -> dict:
    res = client.post(chat_url(space_id), json={"text": text, **rest})
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


# --- 谁说的 -----------------------------------------------------------------


def test_who_said_it_comes_from_the_header_not_the_body(
    client: TestClient, space_id: UUID, me: Any
) -> None:
    """请求体里塞别人的 id 不算数，塞 `is_agent` 也不算数。

    聊天记录是这个组以后唯一能回去查的东西。作者可以由请求体决定的话，
    任何人都能以任何人的名义发言，而**冒充助手**更糟——那一栏是界面用来
    分辨"这句话没人负责"的唯一依据。

    所以断的是"塞了也没用"，不是"塞了会报错"。
    """
    someone_else = uuid4()

    said = say(
        client,
        space_id,
        "我借到相机了",
        author_id=str(someone_else),
        principal_id=str(someone_else),
        is_agent=True,
    )

    assert said["author_id"] == str(me.id)
    assert said["is_agent"] is False
    assert said["kind"] == "said"


def test_the_assistant_cannot_speak_as_a_person(
    client: TestClient, space_id: UUID
) -> None:
    """助手的 id 由 space_id 派生，知道 space_id 的人都算得出来。

    不在这一层挡住的话，任何人都能借它的名义在群里说一句话——
    而它说的话在界面上是另一种颜色，那种颜色的可信度是这个产品自己给的。
    """
    res = client.post(
        chat_url(space_id),
        json={"text": "我替大家定了，就周四"},
        headers={"X-Principal-Id": str(field_agent(space_id).id)},
    )

    assert res.status_code == 403
    assert client.get(chat_url(space_id)).json()["messages"] == []


def test_a_message_of_only_spaces_never_becomes_a_bubble(
    client: TestClient, space_id: UUID
) -> None:
    """一条只有空格的消息在界面上是一个占位气泡。

    它唯一的作用是让人以为有人说了什么。这里是 422 而不是 201——
    静默丢掉的话，发的人会以为自己说过了。
    """
    for blank in ("", "   ", "\n\t "):
        res = client.post(chat_url(space_id), json={"text": blank})
        assert res.status_code == 422, blank

    assert client.get(chat_url(space_id)).json()["messages"] == []


# --- 整条记录 ---------------------------------------------------------------


def test_the_whole_record_comes_back_unpaged(
    client: TestClient, space_id: UUID, sim_clock: SimulatedClock
) -> None:
    """「大家能看到整体的聊天记录」是这一层的承诺。

    一个默认只给最近五十条的接口会让"看看当时怎么说的"变成一件做不到的事。
    这里发 137 条：任何一个常见的默认页长（20/50/100）都会在这条断言上现形。
    """
    for i in range(137):
        say(client, space_id, f"第 {i} 句")
        # 逐条推进时刻。同一时刻的多条消息之间没有可靠的先后，
        # 而"当时怎么说的"这件事要的正是先后。
        sim_clock.advance(timedelta(seconds=1))

    body = client.get(chat_url(space_id)).json()

    assert len(body["messages"]) == 137
    assert [m["text"] for m in body["messages"]] == [f"第 {i} 句" for i in range(137)]


def test_another_campus_can_neither_read_this_chat_nor_speak_into_it(
    client: TestClient, space_id: UUID
) -> None:
    """跨租户是 404 不是 403，读和写都是。

    403 等于确认了这个 id 存在——那本身就是一次泄漏。只挡读不挡写更糟：
    别人仍然可以往这个组里塞一句话，而这个组会把它当成自己人说的。
    """
    say(client, space_id, "我先去问问场地")
    elsewhere = {"X-Campus-Id": OTHER_CAMPUS}

    read = client.get(chat_url(space_id), headers=elsewhere)
    wrote = client.post(chat_url(space_id), json={"text": "我是别的学校的"}, headers=elsewhere)

    assert read.status_code == 404
    assert wrote.status_code == 404
    assert [m["text"] for m in client.get(chat_url(space_id)).json()["messages"]] == [
        "我先去问问场地"
    ]


# --- 话题卡 -----------------------------------------------------------------


def test_a_topic_always_points_back_at_something_still_undecided(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    """助手挑不了话题，只能把一件**已经存在的**待定事项写得好回答一点。

    `about_item_id` 不是可选的元数据，是这张卡有没有资格存在的凭据——
    指不回去的话题就是它自己编的，而编出来的话题会让人学会忽略它说的所有话。
    """
    gate = open_gate(client, space_id, [me.id, chen_mu.id])

    res = client.post(f"{chat_url(space_id)}:topics")

    assert res.status_code == 200
    topics = res.json()
    assert topics, "磁带该命中却没命中，这条用例什么都没验证"
    for topic in topics:
        assert topic["about_item_id"] == gate["id"]
        assert topic["kind"] == "topic"
        # 一眼可辨。分不清谁说的，"AI 起草、人类决定"就只是一句话。
        assert topic["is_agent"] is True
        assert topic["author_id"] == str(field_agent(space_id).id)


def test_it_never_raises_the_same_thing_twice(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    """同一件事问第二遍最伤——它说明这个助手没在听。

    这件事没有任何进展（没人回、门也没关），它仍然不再问：
    「问过没有」记的是它自己说过什么，不是这件事有没有被解决。
    """
    open_gate(client, space_id, [me.id, chen_mu.id])

    first = client.post(f"{chat_url(space_id)}:topics").json()
    again = client.post(f"{chat_url(space_id)}:topics").json()

    assert len(first) == 1
    assert again == []
    # 第二次什么都没说，也就不该在记录里多出一条。
    assert len(client.get(chat_url(space_id)).json()["messages"]) == 1


def test_with_nothing_left_undecided_it_says_nothing(
    client: TestClient, space_id: UUID, me: Any
) -> None:
    """没有待定的事就闭嘴。

    这时候发话题只能是闲聊，而闲聊正是让人学会忽略它的那件事。
    空间里有东西（一件要做的事），但没有一件**要定**的事——
    这两者的区别正是这条判断的全部。
    """
    client.post(
        f"/api/spaces/{space_id}/items",
        json={"kind": "task", "title": "借设备", "assignee_id": str(me.id)},
    )

    res = client.post(f"{chat_url(space_id)}:topics")

    assert res.status_code == 200
    assert res.json() == []


def test_a_drafting_service_that_cannot_word_it_costs_the_topic_not_the_chat(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    """起草说不出话（这里是磁带里没有这一条）时，发不出话题，人自己聊照常。

    助手是增强不是前提。这里是空数组 + 200 而不是 5xx——
    界面弹一个红框，等于把一次"它这次没话说"显示成一次事故。
    """
    open_gate(client, space_id, [me.id, chen_mu.id], title=UNRECORDED)

    res = client.post(f"{chat_url(space_id)}:topics")

    assert res.status_code == 200
    assert res.json() == []
    # 人自己聊一句照常。
    say(client, space_id, "音乐我来找，明天给你们听")
    assert len(client.get(chat_url(space_id)).json()["messages"]) == 1


# --- 关掉助手，群聊照常 -----------------------------------------------------


def test_switching_the_assistant_off_costs_the_topics_and_nothing_else(
    client: TestClient, engine: Engine, me: Any, chen_mu: Any
) -> None:
    """**关掉助手时话题端点返回空数组 + 200，而群聊本身照常可用。**

    这是 M3 判据「关掉助手后共域照常」在聊天上的延伸，也是这个文件里
    最要紧的一条。关掉助手是一个正常选择，不是一次故障：

    - 话题：空数组 + 200，而且**一条都不写进记录**
    - 说话、看记录、在卡下面回复：一样都不少
    - 要真人点头的事照常关得上——它从来就不靠助手

    最后再打开：话题回来了。少了这一半，这条用例可能只是因为
    这个空间根本发不出话题而通过。
    """
    space_id = open_space(engine, agent_enabled=False)
    gate = open_gate(client, space_id, [me.id, chen_mu.id])

    quiet = client.post(f"{chat_url(space_id)}:topics")

    assert quiet.status_code == 200
    assert quiet.json() == []

    # 群聊照常：说得出、看得见。
    mine = say(client, space_id, "那我们自己在这儿定")
    body = client.get(chat_url(space_id)).json()
    assert [m["text"] for m in body["messages"]] == ["那我们自己在这儿定"]
    assert body["threads"] == []
    assert mine["is_agent"] is False

    # 要定的事照常关得上——助手关着，这条路一步都没变。
    confirm = f"/api/spaces/{space_id}/items/{gate['id']}:confirm"
    assert client.post(confirm).status_code == 200
    closed = client.post(confirm, headers={"X-Principal-Id": str(chen_mu.id)})
    assert closed.json()["state"] == "settled"

    # 再打开，它又说得出话了。
    client.post(f"/api/spaces/{space_id}/agent:toggle", json={"enabled": True})
    open_gate(client, space_id, [me.id, chen_mu.id], title=WHERE)
    assert client.post(f"{chat_url(space_id)}:topics").json()


# --- 聊天定不了任何事 -------------------------------------------------------


def test_agreeing_in_the_chat_never_closes_the_gate(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    """**聊出共识不等于结门。**

    该点头的两个人在话题卡下面各写了一句"同意"，那道门一动不动：
    还开着、一个签名都没有、卡片上仍然写着还差他们两个。

    这不是多此一举的一步。少了它，「没读的人默认被代表」就会从群聊
    原样搬进来——一句"没人反对吧"就把所有人算作同意了，而这正是
    群聊做错的那件事。

    最后各自点一次头，门关上了：证明这道门是关得上的，只是聊天关不上。
    """
    gate = open_gate(client, space_id, [me.id, chen_mu.id])
    topic = client.post(f"{chat_url(space_id)}:topics").json()[0]

    say(client, space_id, "同意，就写「我们四个」", replies_to=topic["id"])
    client.post(
        chat_url(space_id),
        json={"text": "我也同意，就这么定", "replies_to": topic["id"]},
        headers={"X-Principal-Id": str(chen_mu.id)},
    )

    chatted = client.get(f"/api/spaces/{space_id}").json()["open_gates"]
    assert [g["id"] for g in chatted] == [gate["id"]]
    assert chatted[0]["confirmed_by"] == []
    assert chatted[0]["notice"] == "还差林知遥和陈牧点头"

    confirm = f"/api/spaces/{space_id}/items/{gate['id']}:confirm"
    client.post(confirm)
    client.post(confirm, headers={"X-Principal-Id": str(chen_mu.id)})
    assert client.get(f"/api/spaces/{space_id}").json()["open_gates"] == []


def test_chatting_does_not_grow_the_space(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    """空间因真实行动证据生长，**不因聊天量生长**（不变量 6）。

    说了二十句、开了一张话题卡，"做完了多少"一个数都没动——
    消息进的是另一张表，不是画布。混在一起的话，一个话多的组会
    显得比一个真在做事的组更有进展。
    """
    client.post(
        f"/api/spaces/{space_id}/items",
        json={"kind": "task", "title": "借设备", "assignee_id": str(me.id)},
    )
    open_gate(client, space_id, [me.id, chen_mu.id])
    before = client.get(f"/api/spaces/{space_id}").json()

    client.post(f"{chat_url(space_id)}:topics")
    for i in range(20):
        say(client, space_id, f"第 {i} 句")

    after = client.get(f"/api/spaces/{space_id}").json()

    assert after["progress"] == before["progress"] == {"done": 0, "total": 1}
    assert [c["id"] for c in after["cards"]] == [c["id"] for c in before["cards"]]
    assert after["summary"] == before["summary"]


# --- 只有一层 ---------------------------------------------------------------


def test_a_reply_hangs_under_the_topic_card_and_the_mainline_stays_out(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any, sim_clock: SimulatedClock
) -> None:
    """回复挂在话题卡下面，主线上说的话不属于任何一张卡。

    两层以上的嵌套在手机上没人读得下去，而读不下去的讨论等于没发生。
    整条记录仍然给全部——分组是给眼睛的，不是给"看得到什么"的。
    """
    open_gate(client, space_id, [me.id, chen_mu.id])
    topic = client.post(f"{chat_url(space_id)}:topics").json()[0]
    sim_clock.advance(timedelta(seconds=1))

    say(client, space_id, "写「我们四个」就行", replies_to=topic["id"])
    sim_clock.advance(timedelta(seconds=1))
    say(client, space_id, "我也这么想")

    body = client.get(chat_url(space_id)).json()

    assert len(body["threads"]) == 1
    thread = body["threads"][0]
    assert thread["topic"]["id"] == topic["id"]
    assert [r["text"] for r in thread["replies"]] == ["写「我们四个」就行"]
    assert thread["answered"] is True
    assert [m["text"] for m in body["messages"]][1:] == [
        "写「我们四个」就行",
        "我也这么想",
    ]


def test_a_card_nobody_answered_says_so(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    """**没人回不是失败，是信号**——这张卡问得不对，或者这件事大家其实不在意。

    助手据此少发同类的。做成"待回复"红点的话，它就成了催促，
    而催促一个不想答的问题只会让人把整个功能关掉。
    """
    open_gate(client, space_id, [me.id, chen_mu.id])
    client.post(f"{chat_url(space_id)}:topics")

    thread = client.get(chat_url(space_id)).json()["threads"][0]

    assert thread["replies"] == []
    assert thread["answered"] is False


# --- 语言 -------------------------------------------------------------------


def test_no_domain_vocabulary_reaches_the_chat(
    client: TestClient, space_id: UUID, me: Any, chen_mu: Any
) -> None:
    """响应里给人看的字符串不出现领域词汇（07 §2）。

    严谨性应该被**感受到**，不应该被**阅读到**。这条检查只看值不看键——
    字段名用领域词是对的，那是三层同名那条红线要的。

    助手写的那句话也在检查范围里：它是这一层唯一不是我们写的文本，
    也就是唯一可能把领域词说出口的地方。
    """
    open_gate(client, space_id, [me.id, chen_mu.id])
    topic = client.post(f"{chat_url(space_id)}:topics").json()[0]
    say(client, space_id, "写「我们四个」就行", replies_to=topic["id"])

    bodies = [
        client.get(chat_url(space_id)).json(),
        client.post(f"{chat_url(space_id)}:topics").json(),
        # 拒绝的话也是用户读的。它们最容易漏，因为没人会去设计错误文案。
        client.post(chat_url(space_id), json={"text": "   "}).json(),
        client.post(
            chat_url(space_id),
            json={"text": "我替大家定了"},
            headers={"X-Principal-Id": str(field_agent(space_id).id)},
        ).json(),
        client.get(chat_url(uuid4())).json(),
    ]

    banned = (*_domain_terms(), *STEMS)
    for body in bodies:
        for text in strings(body):
            for word in banned:
                assert word not in text, f"用户读得到的这句话里有领域词「{word}」：{text}"
