"""我这边：我能做什么、我想参与什么。

## 这个文件存在的理由

在它之前，**两个真人从来没有可能被配到一起**：

- 漏斗第一段写死 `skills && needs`
- 没有任何接口能写 `skills`
- 真人这一列永远是空的，永远不进任何人的候选
- 合成主体又不能与真人同局

四百多个后端用例全绿，因为它们的夹具直接往库里写技能。仿真也全绿，
因为合成人口装载时就带着技能。**只有"两个真人，都只走 HTTP"这一种
写法碰得到它**——而这正是产品上线后每一个用户走的那条路。

所以这里的核心用例不是"字段能存下来"，是
`test_two_real_people_can_actually_end_up_in_the_same_team`。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

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
        conn.execute(sa.text("TRUNCATE formation_proposals, commitments CASCADE"))


def _profile(client: TestClient, **fields: Any) -> dict[str, Any]:
    response = client.put("/api/me/profile", json=fields)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- 这一面本身 ---


def test_a_brand_new_person_gets_an_empty_page_not_an_error(client: TestClient) -> None:
    """刚打开的人这一面是空的——空不是错。

    这里同时钉住 JIT 供给：身份第一次出现时行就该被建出来，
    否则读自己这一面会 404，而那是他能点到的第一批屏之一。
    """
    response = client.get("/api/me/profile")

    assert response.status_code == 200
    body = response.json()
    assert body["skills"] == []
    assert body["open_to"] == []
    assert body["display_name"], "连个能在群里认出他的名字都没有"


def test_what_i_can_do_survives_a_reload(client: TestClient) -> None:
    saved = _profile(client, skills=["剪辑", "拍摄"], self_intro="我拍东西比较野")

    assert saved["skills"] == ["剪辑", "拍摄"]
    again = client.get("/api/me/profile").json()
    assert again["skills"] == ["剪辑", "拍摄"]
    assert again["self_intro"] == "我拍东西比较野"


def test_saving_is_a_replacement_so_i_can_take_something_back(
    client: TestClient,
) -> None:
    """「我不想再参与拍摄了」必须说得出口。

    只能追加的接口表达不了取消，用户会被一件早就不想干的事反复找上门，
    然后再也不填这一面。
    """
    _profile(client, open_to=["拍摄", "剪辑"])
    after = _profile(client, open_to=["剪辑"])

    assert after["open_to"] == ["剪辑"]


def test_a_word_it_does_not_know_is_kept_visible_not_swallowed(
    client: TestClient,
) -> None:
    """「打杂」不在词表里。

    整条拒收，他填的其他东西一起丢；静默丢掉，他永远不知道为什么没人找他。
    两样都不做：收下能认的，**并且明说哪一项没认出来**。
    """
    saved = _profile(client, skills=["剪辑", "打杂"])

    assert saved["skills"] == ["剪辑"]
    assert saved["not_recognised"] == ["打杂"]


def test_it_understands_how_people_actually_talk(client: TestClient) -> None:
    """用户不会照着词表说话。「会剪片子的」得能落到「剪辑」上。"""
    saved = _profile(client, skills=["会剪片子的", "视频剪辑"])

    assert saved["skills"] == ["剪辑"], saved
    assert saved["not_recognised"] == []


def test_the_words_on_screen_come_from_the_server(client: TestClient) -> None:
    """界面上那些可点的词不能在前端硬编码。

    词表是封闭的：两处各写一份，界面上迟早出现一个匹配零个人的词，
    而用户看不出任何异常——他只是永远配不到人。
    """
    body = client.get("/api/vocabulary").json()

    assert "剪辑" in body["skills"]
    assert "东校区" in body["zones"]


# --- 这个产品最核心的那件事 ---


def test_two_real_people_can_actually_end_up_in_the_same_team(
    client: TestClient, seed_principal: Any, sim_clock: Any
) -> None:
    """一个人发起，另一个人说了自己会这个，配队之后他们在同一支队里。

    **这是这个产品的存在理由**，而在这个用例之前它对真实用户从来没成立过。
    """
    editor = seed_principal(name="沈迟")
    with_editor = {"X-Principal-Id": str(editor.id), "X-Campus-Id": CAMPUS}

    # 会剪辑的人先说清楚自己会什么——这是他唯一能被找到的方式。
    response = client.put(
        "/api/me/profile", json={"skills": ["剪辑"]}, headers=with_editor
    )
    assert response.status_code == 200, response.text

    intent_id = _post_need(client, ["剪辑"])
    sim_clock.advance(timedelta(hours=7))
    client.post("/api/clearing:run")

    # 投递制（ADR 0010）：种子先投到他信箱里，他表态，发起人再挑。
    inbox = client.get("/api/me/seeds", headers=with_editor).json()
    assert inbox, "配了一轮，会剪辑的真人连一颗种子都没收到"
    assert inbox[0]["why"], "投给他却说不出为什么"

    client.post(f"/api/seeds/{intent_id}:respond", json={"willing": True},
                headers=with_editor)
    screen = client.get(f"/api/intents/{intent_id}/candidates").json()
    assert [c["display_name"] for c in screen["willing"]] == ["沈迟"]


def test_wanting_to_join_is_enough_to_be_found(
    client: TestClient, seed_principal: Any, sim_clock: Any
) -> None:
    """他不会剪辑，但他说过想参与这类事——他仍然该被找到。

    一个刚做完一件事、想再接一个的人要的不是发起，是参与。
    只认「我会什么」的时候，这种人永远不出现在任何人的候选里。
    """
    editor = seed_principal(name="沈迟")
    helper = seed_principal(name="周未")
    client.put("/api/me/profile", json={"skills": ["剪辑"]},
               headers={"X-Principal-Id": str(editor.id), "X-Campus-Id": CAMPUS})
    client.put("/api/me/profile", json={"open_to": ["剪辑"]},
               headers={"X-Principal-Id": str(helper.id), "X-Campus-Id": CAMPUS})

    _post_need(client, ["剪辑"], team_max=4)
    sim_clock.advance(timedelta(hours=7))
    client.post("/api/clearing:run")

    got = client.get("/api/me/seeds",
                     headers={"X-Principal-Id": str(helper.id), "X-Campus-Id": CAMPUS}).json()
    assert got, "说过想参与的人没收到种子"


def test_wanting_to_join_does_not_make_me_the_one_who_can_do_it(
    client: TestClient, seed_principal: Any, sim_clock: Any
) -> None:
    """只有「想参与」的人，不能被当成会做这件事的人。

    **放宽召回，不放宽承诺。** 全校只有他一个人和这条需求沾边，而他
    只是想参与——这时候正确的结果是凑不出队，不是把他塞进那个坑里
    然后让发起人以为有人会剪辑。
    """
    hopeful = seed_principal(name="周未")
    client.put("/api/me/profile", json={"open_to": ["剪辑"]},
               headers={"X-Principal-Id": str(hopeful.id), "X-Campus-Id": CAMPUS})

    _post_need(client, ["剪辑"], team_max=2)
    sim_clock.advance(timedelta(hours=7))
    client.post("/api/clearing:run")

    # 他仍然会收到种子（放宽召回），但理由里说的是"想参与"不是"他会"——
    # **放宽召回，不放宽承诺**。
    got = client.get("/api/me/seeds",
                     headers={"X-Principal-Id": str(hopeful.id), "X-Campus-Id": CAMPUS}).json()
    assert got, "想参与的人应该收得到"
    assert any("想参与" in line for line in got[0]["why"]), got[0]["why"]
    assert not any("他会" in line for line in got[0]["why"]), "把想参与说成了会做"


def _post_need(
    client: TestClient, needs: list[str], *, team_min: int = 2, team_max: int = 3
) -> str:
    response = client.post(
        "/api/intents",
        json={
            "expression": "想拍支短片，缺个会剪的",
            "content": {
                "goal": "拍一支 60 秒短片",
                "offers": ["写脚本"],
                "needs": needs,
                "team_size": {"minimum": team_min, "maximum": team_max},
            },
            "action_kind": "creative_work",
        },
    )
    assert response.status_code == 201, response.text
    intent_id: str = response.json()["id"]
    client.post(f"/api/intents/{intent_id}:confirm")
    return intent_id


def test_it_does_not_say_nobody_can_when_somebody_can(
    client: TestClient, seed_principal: Any, sim_clock: Any
) -> None:
    """有人能接，只是凑不够人数——这时候不能说「还没有人能接上这件事」。

    这句话是假的，而用户会据此以为这个方向没人、然后放弃。正确的下一步
    是把人数改小，或者自己拉两个人进来——两条都在「还差这几件事」上，
    但前提是它说的是真话。

    这个洞的形状是：`explain_formation`（人有、凑不成组）从建好那天起就
    没有被走到过——接口只调另一个。**两条解释路径写好了一条从不执行。**
    """
    editor = seed_principal(name="沈迟")
    client.put("/api/me/profile", json={"skills": ["剪辑"]},
               headers={"X-Principal-Id": str(editor.id), "X-Campus-Id": CAMPUS})

    # 全校只有一个人能接，而他要四个人的队。
    intent_id = _post_need(client, ["剪辑"], team_min=4, team_max=4)
    sim_clock.advance(timedelta(hours=7))
    client.post("/api/clearing:run")

    body = client.get(f"/api/intents/{intent_id}/blocked").json()
    assert body["stage"] == "formation", body
    assert "还没有人能接" not in body["statement"], body["statement"]
    assert body["next_steps"], "没说下一步能做什么"


def test_it_still_says_nobody_can_when_truly_nobody_can(
    client: TestClient, sim_clock: Any
) -> None:
    """真的一个人都没有的时候，那句话仍然要说得出口。"""
    intent_id = _post_need(client, ["三维建模"])
    sim_clock.advance(timedelta(hours=7))
    client.post("/api/clearing:run")

    body = client.get(f"/api/intents/{intent_id}/blocked").json()
    assert body["stage"] == "recall", body


# --- 一个人是由什么表达的 ---


def test_saying_what_i_can_bring_makes_me_findable(
    client: TestClient, seed_principal: Any, sim_clock: Any
) -> None:
    """他从没打开过「我这边」，只是发过一条需求——他仍然该被找到。

    ## 这条回流是产品前提的分界线

    没有它，前提是"你得先跟软件交代自己"：只有去那一屏打过勾的人才可能
    出现在任何人的候选里。而人真正说清自己的时刻不在表单里，在他发需求
    那一刻的「我能出」——那是有具体语境的一句话，也是他本来就要写的。
    """
    writer = seed_principal(name="沈迟")
    as_writer = {"X-Principal-Id": str(writer.id), "X-Campus-Id": CAMPUS}

    # 他发自己的需求：我能出剪辑，我缺拍摄。**全程没碰过「我这边」。**
    response = client.post(
        "/api/intents",
        json={
            "expression": "想做个短片，我能剪，缺个会拍的",
            "content": {
                "goal": "做一个短片",
                "offers": ["剪辑"],
                "needs": ["拍摄"],
                "team_size": {"minimum": 2, "maximum": 3},
            },
            "action_kind": "creative_work",
        },
        headers=as_writer,
    )
    assert response.status_code == 201, response.text
    client.post(f"/api/intents/{response.json()['id']}:confirm", headers=as_writer)

    mine = client.get("/api/me/profile", headers=as_writer).json()
    assert "剪辑" in mine["skills"], f"他说过自己能剪，系统没记住：{mine}"

    # 而这正意味着别人缺剪辑的时候找得到他。
    _post_need(client, ["剪辑"])
    sim_clock.advance(timedelta(hours=7))
    client.post("/api/clearing:run")
    assert client.get("/api/me/seeds", headers=as_writer).json(), "从没填过表的人收不到种子"


def test_what_i_said_once_is_not_undone_by_the_next_thing_i_say(
    client: TestClient,
) -> None:
    """第二条需求没提剪辑，不代表他不会剪辑了。

    合并不是覆盖。取消永远只能由本人在「我这边」上做——
    **系统学得到，但只有他删得掉。**
    """
    for offers in (["剪辑"], ["写文案"]):
        created = client.post(
            "/api/intents",
            json={
                "expression": "又想做点事",
                "content": {
                    "goal": "做点事",
                    "offers": offers,
                    "needs": ["拍摄"],
                    "team_size": {"minimum": 2, "maximum": 3},
                },
                "action_kind": "creative_work",
            },
        ).json()
        client.post(f"/api/intents/{created['id']}:confirm")

    mine = client.get("/api/me/profile").json()
    assert set(mine["skills"]) == {"剪辑", "写文案"}, mine


def test_only_the_person_can_take_it_back(client: TestClient) -> None:
    """系统学到的，本人一句话就能删掉。"""
    created = client.post(
        "/api/intents",
        json={
            "expression": "想做点事",
            "content": {
                "goal": "做点事",
                "offers": ["剪辑"],
                "needs": ["拍摄"],
                "team_size": {"minimum": 2, "maximum": 3},
            },
            "action_kind": "creative_work",
        },
    ).json()
    client.post(f"/api/intents/{created['id']}:confirm")
    assert "剪辑" in client.get("/api/me/profile").json()["skills"]

    after = _profile(client, skills=[])
    assert after["skills"] == []


# --- 别再靠"有人正好问起"发现这类洞 ---


def test_every_input_the_matcher_reads_has_a_real_user_writer(
    client: TestClient,
) -> None:
    """匹配链路读的每一样东西，真人都得有办法把它写进去。

    ## 这个用例是一次根因修复，不是一条断言

    有四个洞是同一个原因冒出来的：真人没有 `skills`、新访客连
    `principals` 行都没有、演示租户一个组织都没有、真人的 `major` 永远为空。

    **设计是自顶向下的，但它是对着一个由生成器填好的校园写的。**
    `simulation/population.py` 给每个合成人写了技能、专业、校区、空闲，
    所以每一句"漏斗按会什么过滤"在任何环境里都是真的、都演示得出来。
    没有任何一份文档写过：**这些东西真人的那一份是谁写的**——因为在我们
    跑过的每个环境里，早就有人替他写好了。

    所以这里不再逐个补洞，而是把"谁写"变成一条必须回答的问题：一个
    从没被夹具碰过的真人，只走 HTTP，能不能把匹配要读的每一样都写进去。
    往漏斗里加一列而没有对应的入口时，这个用例会红。

    `availability` 不在名单里，理由写在 `window.py`：读不到就按"都有空"
    算，而时间早就不是硬约束（ADR 0006）。**这是一个写下来的决定，
    不是一个没人问起的空列。**
    """
    saved = _profile(
        client,
        skills=["剪辑"],
        open_to=["拍摄"],
        self_intro="拍东西比较野",
        zone="东校区",
        major="新闻传播",
    )

    # 漏斗与求解器读的每一样，这里都得能回读出来。
    assert saved["skills"] == ["剪辑"], "漏斗按它精确过滤，求解器补洞只认它"
    assert saved["open_to"] == ["拍摄"], "「我想参与」只放宽召回"
    assert saved["zone"] == "东校区", "校区是硬约束之一"
    assert saved["major"] == "新闻传播", "跨专业那条软目标只认它"
    assert saved["self_intro"] == "拍东西比较野", "语义召回读的是这一段"
    assert saved["display_name"], "证明里要指名道姓"


def test_the_words_on_screen_cover_everything_you_can_fill(
    client: TestClient,
) -> None:
    """能填的每一项都得有一份**服务端给的**可选值。

    前端硬编码一份的话，屏上迟早出现一个匹配零个人的词，
    而用户看不出任何异常——他只是永远配不到人。
    """
    body = client.get("/api/vocabulary").json()

    assert "剪辑" in body["skills"]
    assert "东校区" in body["zones"]
    assert "新闻传播" in body["majors"], "专业能填，却没有一份可选的清单"


def test_two_people_in_one_team_do_not_have_the_same_name(
    client: TestClient, seed_principal: Any
) -> None:
    """占位名要**能把人区分开**。

    原来是「同学」加 id 后四位。一支四个人的队里出现三个「同学0002」的
    时候，"要不要和这几个人一起做事"这个问题就问不成了——而那正是那一屏
    唯一要问的问题。
    """
    from uuid import uuid4

    from cofield.domain.model.principal import placeholder_name

    names = {placeholder_name(uuid4()) for _ in range(500)}
    assert len(names) > 480, f"五百个人里只有 {len(names)} 个不同的名字"

    # 而且同一个人每次都叫同一个名字：换名字比重名更让人不知道他是谁。
    someone = uuid4()
    assert placeholder_name(someone) == placeholder_name(someone)


def test_declining_but_asking_to_be_told_next_time_leaves_a_trace(
    client: TestClient, seed_principal: Any, sim_clock: Any
) -> None:
    """「这次不行，以后类似的叫我」——拒绝这一次，但留下一条线索。

    PRD 把它列为接收方的第四种回应。它**不是第四个承诺档位**：做成档位的话
    "他到底算不算同意了"就多出一种要解释的状态，而这件事的真实含义是
    **拒绝**加**一个偏好**，两者本来就该分开记。

    线索落在「我想参与的」上，所以下一次有人缺同样的东西，他会出现在候选里。
    """
    editor = seed_principal(name="沈迟")
    with_editor = {"X-Principal-Id": str(editor.id), "X-Campus-Id": CAMPUS}
    client.put("/api/me/profile", json={"skills": ["剪辑"]}, headers=with_editor)

    intent_id = _post_need(client, ["剪辑"])
    sim_clock.advance(timedelta(hours=7))
    client.post("/api/clearing:run")
    assert client.get("/api/me/seeds", headers=with_editor).json(), "先得收到种子"

    res = client.post(
        f"/api/seeds/{intent_id}:respond",
        json={"willing": False, "remind_me": True},
        headers=with_editor,
    )
    assert res.status_code == 200, res.text

    mine = client.get("/api/me/profile", headers=with_editor).json()
    assert "剪辑" in mine["open_to"], f"说了以后叫我，却没留下线索：{mine}"


def test_joining_does_not_quietly_add_things_to_what_i_want(
    client: TestClient, seed_principal: Any, sim_clock: Any
) -> None:
    """加入了就不需要"以后再叫我"。**只有拒绝的时候这条才有意义。**"""
    editor = seed_principal(name="沈迟")
    with_editor = {"X-Principal-Id": str(editor.id), "X-Campus-Id": CAMPUS}
    client.put("/api/me/profile", json={"skills": ["剪辑"]}, headers=with_editor)

    intent_id = _post_need(client, ["剪辑"])
    sim_clock.advance(timedelta(hours=7))
    client.post("/api/clearing:run")

    client.post(
        f"/api/seeds/{intent_id}:respond",
        json={"willing": True, "remind_me": True},
        headers=with_editor,
    )

    assert client.get("/api/me/profile", headers=with_editor).json()["open_to"] == []


# --- 这条需求问谁 ---


def test_asking_only_people_i_have_done_something_with(
    client: TestClient, seed_principal: Any, sim_clock: Any
) -> None:
    """「熟人」由**共同完成过的事**定义，不是好友列表。

    不变量 7：关系图谱是共同事件的可重建投影，不是平台对"熟不熟"的
    主观判定。
    """
    stranger = seed_principal(name="陌生人")
    client.put("/api/me/profile", json={"skills": ["剪辑"]},
               headers={"X-Principal-Id": str(stranger.id), "X-Campus-Id": CAMPUS})

    res = client.post(
        "/api/intents",
        json={
            "expression": "只想找一起做过事的人",
            "content": {
                "goal": "再做一支短片",
                "offers": ["写脚本"],
                "needs": ["剪辑"],
                "team_size": {"minimum": 2, "maximum": 2},
            },
            "action_kind": "creative_work",
            "reach": "known",
        },
    )
    assert res.status_code == 201, res.text
    intent_id = res.json()["id"]
    assert res.json()["reach"] == "known", "问谁这件事界面上要说得出来"
    client.post(f"/api/intents/{intent_id}:confirm")

    sim_clock.advance(timedelta(hours=7))
    client.post("/api/clearing:run")

    # 第一次用这个产品的人**没有熟人**。那不是 bug，是这一档的真实含义。
    assert client.get(f"/api/intents/{intent_id}/candidates").json()["willing"] == []
    blocked = client.get(f"/api/intents/{intent_id}/blocked").json()
    assert any("一起做成过事" in c for c in blocked["causes"]), blocked


def test_an_unknown_reach_falls_back_to_the_whole_campus(
    client: TestClient,
) -> None:
    """认不出来的范围按全校算。

    **冷启动时缩小范围等于没有匹配**，而一个打错字的参数不该让他的需求
    悄悄没人看见。
    """
    res = client.post(
        "/api/intents",
        json={
            "expression": "随便写的",
            "content": {"goal": "做点事", "offers": [], "needs": ["剪辑"]},
            "reach": "friends-of-friends",
        },
    )

    assert res.json()["reach"] == "campus"


# --- 我叫什么 ---------------------------------------------------------------


def test_a_new_person_has_not_named_themselves_yet(client: TestClient) -> None:
    """刚来的人顶着一个占位名，而系统**说得出**这件事。

    界面据此决定要不要先问他叫什么。让界面自己去猜（比如看名字里有没有
    「同学」两个字），猜法迟早和占位的生成规则对不上。

    **用一个真正第一次出现的身份**——fixture 里那个人是被造出来的，
    一出生就有名字，验不到这条路。
    """
    from uuid import uuid4

    body = client.get(
        "/api/me/profile",
        headers={"X-Principal-Id": str(uuid4()), "X-Campus-Id": CAMPUS},
    ).json()

    assert body["named_self"] is False
    assert body["display_name"], "连占位名都没有的话，队友那边会看到一片空白"


def test_naming_myself_sticks_and_shows_up_to_the_people_i_work_with(
    client: TestClient,
) -> None:
    """起过名之后就不再问了。"""
    client.put("/api/me/profile", json={"display_name": "林知遥", "skills": ["剪辑"]})

    body = client.get("/api/me/profile").json()

    assert body["display_name"] == "林知遥"
    assert body["named_self"] is True


def test_saving_the_rest_of_the_page_does_not_wipe_my_name(
    client: TestClient,
) -> None:
    """改「我能做的」不该把名字改没。

    这一页是整份覆盖，而名字**不在被覆盖的那一份里**：
    「我不想再参与拍摄了」要说得出口，「我不叫任何名字」不该说得出口。
    """
    client.put("/api/me/profile", json={"display_name": "林知遥", "skills": ["剪辑"]})

    client.put("/api/me/profile", json={"skills": ["拍摄"]})

    body = client.get("/api/me/profile").json()
    assert body["display_name"] == "林知遥"
    assert body["skills"] == ["拍摄"]
