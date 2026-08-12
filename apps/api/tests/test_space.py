"""共域：结构化画布，不是群聊。

这里断言的不是"能存条目"，而是**这块画布守得住三件事**：

1. 把助手关掉之后，人工流程一步都不少——助手是画布上的一张卡片，
   不是画布的运行时。这是 M3 的判据之一，所以它是这个文件里最长的一个用例。
2. 助手起草而没人认的东西**不算数**，而"不算数"是四条可断言的行为，
   不是一句宣言。
3. 要真人点头的事，助手关不掉；被拒时明确失败，不是静默忽略。

真 PostgreSQL、真迁移、真行级安全。空间由测试直接写一行占位——
**建空间不归这一层**，它在确认门里随共同事件一起、在同一个事务内诞生。
"""

from __future__ import annotations

import re
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from cofield.adapters.persistence.engine import campus_connection, owner_connection
from cofield.adapters.persistence.schema import spaces as spaces_table
from cofield.adapters.persistence.spaces import SpaceRepository
from cofield.space import (
    ABOUT,
    CONFIRMED_BY,
    DECIDERS,
    DISCARDED,
    REACH,
    SHIPPED_ITEM_KINDS,
    SOURCE,
    AgentCannotDecide,
    AgentIsOff,
    Canvas,
    CanvasRefused,
    DraftDoesNotCount,
    ItemKind,
    ItemKindRegistry,
    MissingProvenance,
    NotYoursToDecide,
    Progress,
    ItemReach,
    field_agent,
    item_kinds,
    person,
)

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
CAMPUS = "demo-campus"
OTHER = "simulation"

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "apps/api/src/cofield"

#: 三个人。共域里不需要他们在 `principals` 里有行——画布不读那张表，
#: 它只认 id。真造几个人反而会让这些用例看起来在测别的东西。
ME = uuid4()
CHEN_MU = uuid4()
SU_WAN = uuid4()
NAMES = {ME: "林知遥", CHEN_MU: "陈牧", SU_WAN: "苏晚"}


@pytest.fixture(autouse=True)
def _clear_spaces(engine: Engine) -> Generator[None, None, None]:
    yield
    with owner_connection(engine) as conn:
        conn.execute(sa.text("TRUNCATE spaces, space_items CASCADE"))


def open_space(
    engine: Engine,
    *,
    campus: str = CAMPUS,
    name: str = "流浪猫短片",
    agent_enabled: bool = True,
) -> UUID:
    """写一行空间。

    **这是 #9 的活，不是这一层的接口。** 共域随共同事件在确认门里诞生，
    仓储里没有 `create_space` 是刻意的——留一个凭空建空间的入口，
    就等于留了一条绕过确认门的路。测试里手写这一行是占位。
    """
    space_id = uuid4()
    with campus_connection(engine, campus) as conn:
        conn.execute(
            sa.insert(spaces_table).values(
                id=space_id,
                campus_id=campus,
                event_id=uuid4(),
                name=name,
                agent_enabled=agent_enabled,
                created_at=NOW,
            )
        )
    return space_id


@contextmanager
def canvas(
    engine: Engine,
    space_id: UUID,
    *,
    campus: str = CAMPUS,
    kinds: ItemKindRegistry = item_kinds,
) -> Generator[Canvas, None, None]:
    with campus_connection(engine, campus) as conn:
        repo = SpaceRepository(conn, campus)
        space = repo.get(space_id)
        assert space is not None, "空间没建起来"
        yield Canvas(repo, space, kinds)


def switch_agent(engine: Engine, space_id: UUID, *, on: bool) -> None:
    with campus_connection(engine, CAMPUS) as conn:
        SpaceRepository(conn, CAMPUS).set_agent_enabled(space_id, enabled=on)


# --- 关掉助手之后 -----------------------------------------------------------


def test_the_whole_human_flow_survives_the_assistant_being_off(engine: Engine) -> None:
    """把助手关掉，再跑一遍完整的人工流程：建、指派、推进到完成、开门、结门。

    这是 M3 的判据之一。助手在这个产品里是画布上的一张卡片，
    不是画布的运行时——所以它缺席时，共域不该少任何一样东西。

    同时验的是关掉那一刻的两种遗留：**已经被采纳的草稿留下**
    （它们已经是真人的决定了），**没被采纳的从画布上撤下但行还在**。
    """
    space_id = open_space(engine)
    agent = field_agent(space_id)

    # 助手还开着的时候，它起草了两条：一条被人认了，一条没有。
    with canvas(engine, space_id) as c:
        adopted = c.add("task", "把脚本发到群里", by=agent, now=NOW)
        shelved = c.add("task", "周四去南门试拍", by=agent, now=NOW)
        c.accept(adopted.id, by=person(ME), now=NOW)

    switch_agent(engine, space_id, on=False)

    # --- 一步一步走完，每一步都要真的落地 ---
    with canvas(engine, space_id) as c:
        step = c.add("task", "写完 60 秒的脚本", by=person(ME), now=NOW)
        assert step.state == "todo"

        step = c.assign(step.id, to=CHEN_MU, by=person(ME), now=NOW)
        assert step.assignee_id == CHEN_MU
        assert c.assigned_to(CHEN_MU) == (step,)

        step = c.advance(step.id, to="doing", by=person(CHEN_MU), now=NOW)
        assert step.state == "doing"
        step = c.advance(step.id, to="done", by=person(CHEN_MU), now=NOW)
        assert step.state == "done"

        gate = c.add(
            "decision_gate",
            "片尾署名怎么写",
            by=person(ME),
            now=NOW,
            extras={DECIDERS: [ME, CHEN_MU]},
        )
        assert gate.state == "open"

        gate = c.confirm(gate.id, by=person(ME), now=NOW)
        assert gate.state == "open", "一个人点头就关上，等于没读的人被代表了"
        gate = c.confirm(gate.id, by=person(CHEN_MU), now=NOW)
        assert gate.state == "settled"

        # 被采纳的那条草稿在这里和别的卡片没有任何区别。
        c.advance(adopted.id, to="done", by=person(ME), now=NOW)

    with canvas(engine, space_id) as c:
        view = c.view(now=NOW, names=NAMES)

    titles = {card.item.title for card in view.cards}
    assert "写完 60 秒的脚本" in titles
    assert "把脚本发到群里" in titles, "已经被真人认下的草稿不该跟着开关一起消失"
    assert "周四去南门试拍" not in titles
    assert view.progress.done == 2
    assert view.progress.total == 2, "没人认的那条不该进分母"
    assert view.open_gates == ()
    assert view.drafts == (), "助手关掉之后，等你过目的那一栏是空的"

    # 撤下不是删除：申诉时要查得到当时都提过什么。
    with canvas(engine, space_id) as c:
        assert c.item(shelved.id).title == "周四去南门试拍"

    # 而助手这一侧整条不通。
    with canvas(engine, space_id) as c:
        with pytest.raises(AgentIsOff):
            c.add("task", "我再提一个", by=agent, now=NOW)
        with pytest.raises(AgentIsOff):
            c.accept(shelved.id, by=person(ME), now=NOW)


def test_turning_the_assistant_back_on_brings_the_shelved_drafts_back(
    engine: Engine,
) -> None:
    """撤下是视图上的事，不是数据上的事。

    没被采纳的草稿本来就不算数——删掉它换不来任何正确性，只会让"关掉助手"
    变成一个需要二次确认的破坏性动作。而要二次确认的开关，用户就不敢关。
    真要清掉是逐条丢弃，那是人的决定，不是开关的副作用。
    """
    space_id = open_space(engine)
    agent = field_agent(space_id)
    with canvas(engine, space_id) as c:
        draft = c.add("task", "周四去南门试拍", by=agent, now=NOW)

    switch_agent(engine, space_id, on=False)
    with canvas(engine, space_id) as c:
        assert c.view(now=NOW).drafts == ()

    switch_agent(engine, space_id, on=True)
    with canvas(engine, space_id) as c:
        assert [card.item.id for card in c.view(now=NOW).drafts] == [draft.id]
        # 丢弃之后才是真的不回来了。
        c.discard(draft.id, by=person(ME), now=NOW)
        assert c.view(now=NOW).drafts == ()
        assert c.item(draft.id).state == DISCARDED


# --- 没人认的草稿不算数 -----------------------------------------------------


def test_an_unadopted_draft_counts_for_nothing(engine: Engine) -> None:
    """"不算数"是四条行为，不是一句宣言：

    不计入做完了多少、不落到任何人的待办里、不能被推进、做不了决定的结论。
    少任何一条，"AI 起草，人类决定"都只是一句好听的话。
    """
    space_id = open_space(engine)
    agent = field_agent(space_id)

    with canvas(engine, space_id) as c:
        drafted = c.add(
            "task", "周四去南门试拍", by=agent, now=NOW, assignee_id=CHEN_MU
        )
        gate = c.add(
            "decision_gate",
            "要不要拍人的正脸",
            by=agent,
            now=NOW,
            extras={DECIDERS: [ME, CHEN_MU]},
        )
        view = c.view(now=NOW)

        assert view.progress.total == 0, "没人认的草稿把分母撑大了"
        assert c.assigned_to(CHEN_MU) == (), "助手写的负责人是建议，不是落到人头上的事"
        assert view.cards == ()
        assert {card.item.id for card in view.drafts} == {drafted.id, gate.id}

        with pytest.raises(DraftDoesNotCount):
            c.advance(drafted.id, to="done", by=person(ME), now=NOW)
        with pytest.raises(DraftDoesNotCount):
            c.assign(drafted.id, to=SU_WAN, by=person(ME), now=NOW)
        with pytest.raises(DraftDoesNotCount):
            c.confirm(gate.id, by=person(ME), now=NOW)


def test_an_adopted_draft_becomes_that_persons_own_decision(engine: Engine) -> None:
    """采纳之后它就是真人的东西了——计入进度、进待办、能推进。

    这条和上一条是一对：只测"不算数"而不测"采纳之后算数"，
    代码可以靠"永远不算数"骗过去。
    """
    space_id = open_space(engine)
    agent = field_agent(space_id)

    with canvas(engine, space_id) as c:
        drafted = c.add(
            "task", "周四去南门试拍", by=agent, now=NOW, assignee_id=CHEN_MU
        )
        c.accept(drafted.id, by=person(ME), now=NOW)

        assert c.view(now=NOW).progress.total == 1
        assert [i.id for i in c.assigned_to(CHEN_MU)] == [drafted.id]
        assert c.advance(drafted.id, to="done", by=person(CHEN_MU), now=NOW).state == (
            "done"
        )
        # 采纳过的条目助手再也动不了：那已经是真人的决定，改它就是替人改主意。
        with pytest.raises(AgentCannotDecide):
            c.assign(drafted.id, to=SU_WAN, by=agent, now=NOW)


def test_the_assistant_cannot_adopt_its_own_draft(engine: Engine) -> None:
    """采纳必须是真人的动作。助手能自己认，前面那道门就等于没关。"""
    space_id = open_space(engine)
    agent = field_agent(space_id)
    with canvas(engine, space_id) as c:
        drafted = c.add("task", "周四去南门试拍", by=agent, now=NOW)
        with pytest.raises(AgentCannotDecide):
            c.accept(drafted.id, by=agent, now=NOW)


# --- 决策门 -----------------------------------------------------------------


def test_the_assistant_can_never_close_a_gate(engine: Engine) -> None:
    """这一条是硬的。

    而且拒绝的理由必须是"你是助手"，不是"你不在名单上"——所以这里
    故意把助手的 id 写进了需要点头的名单。写进名单也一样过不去，
    才说明这条不变量挂在身份上，不挂在一份可以被改的名单上。
    """
    space_id = open_space(engine)
    agent = field_agent(space_id)

    with canvas(engine, space_id) as c:
        gate = c.add(
            "decision_gate",
            "片尾署名怎么写",
            by=person(ME),
            now=NOW,
            extras={DECIDERS: [ME, agent.id]},
        )

        with pytest.raises(AgentCannotDecide):
            c.confirm(gate.id, by=agent, now=NOW)
        # 绕道也不行：推进状态这条路上，终态对谁都是关着的。
        with pytest.raises(CanvasRefused):
            c.advance(gate.id, to="settled", by=agent, now=NOW)
        with pytest.raises(NotYoursToDecide):
            c.advance(gate.id, to="settled", by=person(ME), now=NOW)

        # 明确失败，不是静默忽略——门还开着。
        assert c.item(gate.id).state == "open"


def test_a_gate_names_who_has_to_nod_and_waits_for_all_of_them(
    engine: Engine,
) -> None:
    """"需要谁确认"是明写的，不是猜的；不在名单上的人点不动它。"""
    space_id = open_space(engine)
    with canvas(engine, space_id) as c:
        gate = c.add(
            "decision_gate",
            "片尾署名怎么写",
            by=person(ME),
            now=NOW,
            extras={DECIDERS: [CHEN_MU, SU_WAN]},
        )

        with pytest.raises(NotYoursToDecide):
            c.confirm(gate.id, by=person(ME), now=NOW)

        c.confirm(gate.id, by=person(CHEN_MU), now=NOW)
        # 同一个人点两次不算两个人。
        gate = c.confirm(gate.id, by=person(CHEN_MU), now=NOW)
        assert gate.state == "open"
        assert len(gate.extras[CONFIRMED_BY]) == 1

        gate = c.confirm(gate.id, by=person(SU_WAN), now=NOW)
        assert gate.state == "settled"
        with pytest.raises(CanvasRefused):
            c.confirm(gate.id, by=person(SU_WAN), now=NOW)


def test_a_gate_without_names_is_refused_at_the_door(engine: Engine) -> None:
    """没写清楚谁点头的门，永远关不上，也没人知道该等谁。"""
    space_id = open_space(engine)
    with canvas(engine, space_id) as c:
        with pytest.raises(MissingProvenance):
            c.add("decision_gate", "片尾署名怎么写", by=person(ME), now=NOW)


# --- 素材：来源、上传者、可见范围 -------------------------------------------


def test_something_without_a_source_or_a_reach_never_gets_in(engine: Engine) -> None:
    """没有来源和可见范围的东西不能成为权威长期记忆（不变量 5）。

    所以缺了就不许写进来，而不是先收下再补——先收下的，永远补不上。
    """
    space_id = open_space(engine)
    with canvas(engine, space_id) as c:
        with pytest.raises(MissingProvenance):
            c.add("material", "试拍的第一条", by=person(ME), now=NOW)
        with pytest.raises(MissingProvenance):
            c.add(
                "material",
                "试拍的第一条",
                by=person(ME),
                now=NOW,
                extras={SOURCE: "陈牧手机直传"},
            )

        kept = c.add(
            "material",
            "试拍的第一条",
            by=person(CHEN_MU),
            now=NOW,
            extras={SOURCE: "陈牧手机直传", REACH: ItemReach.OURS},
        )
        assert kept.created_by == CHEN_MU, "上传者必须留得住"
        assert kept.extras[SOURCE] == "陈牧手机直传"
        assert kept.extras[REACH] == ItemReach.OURS.value


def test_sending_something_outside_needs_everyone_to_have_nodded(
    engine: Engine,
) -> None:
    """共同素材是否发布由相关人决定（04 §1 权利矩阵）。

    收回则不用：权利必须顺手，要走流程才能收回的权利等于没有（07 原则三）。
    """
    space_id = open_space(engine)
    agent = field_agent(space_id)

    with canvas(engine, space_id) as c:
        thing = c.add(
            "material",
            "试拍的第一条",
            by=person(CHEN_MU),
            now=NOW,
            extras={SOURCE: "陈牧手机直传", REACH: ItemReach.OURS},
        )

        with pytest.raises(NotYoursToDecide):
            c.change_reach(thing.id, to=ItemReach.OUTSIDE, by=person(ME), now=NOW)
        with pytest.raises(AgentCannotDecide):
            c.change_reach(thing.id, to=ItemReach.OUTSIDE, by=agent, now=NOW)

        gate = c.add(
            "decision_gate",
            "这条要不要发到外面",
            by=person(ME),
            now=NOW,
            extras={DECIDERS: [ME, CHEN_MU], ABOUT: str(thing.id)},
        )
        c.confirm(gate.id, by=person(ME), now=NOW)
        # 还差一个人点头的时候，仍然发不出去。
        with pytest.raises(NotYoursToDecide):
            c.change_reach(thing.id, to=ItemReach.OUTSIDE, by=person(ME), now=NOW)

        c.confirm(gate.id, by=person(CHEN_MU), now=NOW)
        sent = c.change_reach(thing.id, to=ItemReach.OUTSIDE, by=person(ME), now=NOW)
        assert sent.extras[REACH] == ItemReach.OUTSIDE.value

        # 收回不用再点一次头。
        back = c.change_reach(thing.id, to=ItemReach.OURS, by=person(CHEN_MU), now=NOW)
        assert back.extras[REACH] == ItemReach.OURS.value


# --- 一屏看见什么 -----------------------------------------------------------


def test_the_view_says_what_is_stuck_and_what_is_still_open(engine: Engine) -> None:
    """一屏可见：要做什么、谁负责什么、卡在哪、还有哪些决定没关。

    "卡住"有两种，都不需要谁来汇报：没有名字挂在上面的，
    和过了说好的时间还没完的。一件事只要没有负责人，它就不会自己往前走。
    """
    space_id = open_space(engine)
    with canvas(engine, space_id) as c:
        nobody = c.add("task", "找配乐", by=person(ME), now=NOW)
        late = c.add(
            "task",
            "剪出初版",
            by=person(ME),
            now=NOW,
            assignee_id=SU_WAN,
            due_at=NOW - timedelta(days=1),
        )
        moving = c.add("task", "写脚本", by=person(ME), now=NOW, assignee_id=ME)
        c.advance(moving.id, to="doing", by=person(ME), now=NOW)
        c.add(
            "decision_gate",
            "片尾署名怎么写",
            by=person(ME),
            now=NOW,
            extras={DECIDERS: [ME, CHEN_MU]},
        )

        view = c.view(now=NOW, names=NAMES)

    assert {card.item.id for card in view.stuck} == {nobody.id, late.id}
    assert [card.item.title for card in view.open_gates] == ["片尾署名怎么写"]
    assert view.progress == Progress(done=0, total=3)
    assert view.summary == "3 件事做完 0 件，1 件事等着定，2 件卡住了"


def test_a_pending_gate_says_who_it_is_still_waiting_for(engine: Engine) -> None:
    """"还差陈牧和苏晚点头"——名字给了就说名字，没给就只说人数。

    人数那一档不是降级凑数：不认识的人名对读的人没有意义，
    而"还差 2 个人"至少是真的。
    """
    space_id = open_space(engine)
    with canvas(engine, space_id) as c:
        gate = c.add(
            "decision_gate",
            "片尾署名怎么写",
            by=person(ME),
            now=NOW,
            extras={DECIDERS: [CHEN_MU, SU_WAN]},
        )
        assert _notice_of(c, gate.id, names=NAMES) == "还差陈牧和苏晚点头"
        assert _notice_of(c, gate.id, names=None) == "还差 2 个人点头"

        c.confirm(gate.id, by=person(CHEN_MU), now=NOW)
        assert _notice_of(c, gate.id, names=NAMES) == "还差苏晚点头"


def _notice_of(
    c: Canvas, item_id: UUID, *, names: dict[UUID, str] | None
) -> str | None:
    view = c.view(now=NOW, names=names)
    for card in (*view.cards, *view.drafts):
        if card.item.id == item_id:
            return card.notice
    raise AssertionError("这张卡片不在画布上")


# --- 扩展点 -----------------------------------------------------------------


def test_a_new_kind_of_item_needs_no_existing_file_changed(engine: Engine) -> None:
    """新增一种条目 = 新增一条声明。

    证明分两半。一半是机械的：画布和仓储这两份文件里**不出现任何一种条目的
    名字**——出现了就说明清单被写死在了代码里，那个扩展点是假的。
    另一半是行为的：现场声明两种没人见过的条目，它们各自的生命周期、
    进度口径和"要真人点头"全都照常生效，一行既有代码都没改。

    尤其是最后这条：不变量跟着**声明的属性**走，不跟着名字走。
    所以任何人新注册一种要真人点头的条目，助手一样关不掉它——
    这是"决策门不能被助手结掉"能够长期成立的原因。
    """
    for path in (SRC / "space/canvas.py", SRC / "adapters/persistence/spaces.py"):
        source = path.read_text(encoding="utf-8")
        for shipped in SHIPPED_ITEM_KINDS:
            assert shipped.key not in source, f"{path.name} 里写死了 {shipped.key}"

    risk = ItemKind(
        key="risk",
        label="要当心的",
        states=("watching", "cleared"),
        done_states=frozenset({"cleared"}),
        counts_toward_progress=True,
    )
    signoff = ItemKind(
        key="signoff",
        label="要签的字",
        states=("open", "signed"),
        done_states=frozenset({"signed"}),
        needs_human_decision=True,
        required_extras=(DECIDERS,),
    )
    kinds = ItemKindRegistry((*SHIPPED_ITEM_KINDS, risk, signoff))

    space_id = open_space(engine)
    agent = field_agent(space_id)
    with canvas(engine, space_id, kinds=kinds) as c:
        watched = c.add("risk", "夜里拍要有人同行", by=person(ME), now=NOW)
        assert watched.state == "watching"
        assert c.view(now=NOW).progress.total == 1

        signing = c.add(
            "signoff",
            "外联要用的名字",
            by=person(ME),
            now=NOW,
            extras={DECIDERS: [ME]},
        )
        with pytest.raises(AgentCannotDecide):
            c.confirm(signing.id, by=agent, now=NOW)
        assert c.confirm(signing.id, by=person(ME), now=NOW).state == "signed"

        c.advance(watched.id, to="cleared", by=person(ME), now=NOW)
        view = c.view(now=NOW)

    assert view.progress == Progress(done=1, total=1)
    assert {card.label for card in view.cards} == {"要当心的", "要签的字"}


# --- 租户 -------------------------------------------------------------------


def test_another_campus_reads_nothing(engine: Engine) -> None:
    """知道空间的主键也读不到——隔离不依赖 ID 不可猜。

    这里读的是空间本身和它的条目两条路径：只挡住其中一条，
    另一条就是一个能翻出别人协作内容的洞。
    """
    space_id = open_space(engine)
    with canvas(engine, space_id) as c:
        c.add("task", "写完 60 秒的脚本", by=person(ME), now=NOW)

    with campus_connection(engine, OTHER) as conn:
        repo = SpaceRepository(conn, OTHER)
        assert repo.get(space_id) is None
        assert repo.list_items(space_id) == []


# --- 界面上不许出现领域词汇 -------------------------------------------------

#: 词根黑名单。完整术语从 CONTEXT.md 读（见 `_domain_terms`），
#: 这里补的是那份表里拆不出来的部分。做法照 `test_proof.py`：
#: 术语泄漏是可测的，不该靠 review 时凭感觉抓。
STEMS = (
    "意图",
    "主体",
    "切面",
    "共域",
    "求解",
    "约束",
    "提案",
    "证明",
    "授权",
    "撮合",
    "稳定",
    "代理",
    "智能体",
    "凭证",
    "信封",
    "回声",
    "素材",
    "草稿",
    "决策门",
    "确认门",
    "可见范围",
)
SCORES = ("%", "百分比", "匹配度", "评分", "得分", "分数", "契合度")


def _domain_terms() -> frozenset[str]:
    text = (REPO_ROOT / "CONTEXT.md").read_text(encoding="utf-8")
    terms = frozenset(re.findall(r"^\*\*([^*（]+)（", text, flags=re.MULTILINE))
    assert len(terms) > 20, "没读到术语表，黑名单是空的"
    return terms


def test_nothing_a_person_reads_is_written_in_the_engineering_vocabulary(
    engine: Engine,
) -> None:
    """卡片上的每一句都要过这一关。

    后端严谨 ≠ 前端严谨。屏幕上出现"共域""素材""决策门"，一个大二学生
    会立刻关掉——而这一段代码正好是最容易把内部词直接印上去的地方，
    因为它离表结构只有一层。
    """
    space_id = open_space(engine)
    agent = field_agent(space_id)
    with canvas(engine, space_id) as c:
        c.add("task", "找配乐", by=person(ME), now=NOW)
        c.add(
            "task",
            "剪出初版",
            by=person(ME),
            now=NOW,
            assignee_id=SU_WAN,
            due_at=NOW - timedelta(days=1),
        )
        c.add(
            "material",
            "试拍的第一条",
            by=person(CHEN_MU),
            now=NOW,
            extras={SOURCE: "陈牧手机直传", REACH: ItemReach.OURS},
        )
        c.add(
            "decision_gate",
            "片尾署名怎么写",
            by=person(ME),
            now=NOW,
            extras={DECIDERS: [ME, CHEN_MU]},
        )
        c.add("note", "南门保安说下午四点后人少", by=person(ME), now=NOW)
        c.add("task", "周四去南门试拍", by=agent, now=NOW)

        view = c.view(now=NOW, names=NAMES)

    visible = [view.title, view.summary]
    for card in (*view.cards, *view.drafts):
        visible.append(card.label)
        if card.notice is not None:
            visible.append(card.notice)

    assert len(visible) > 10, "没收集到几句话，这个用例测不到东西"
    banned = (*_domain_terms(), *STEMS, *SCORES)
    for line in visible:
        for word in banned:
            assert word not in line, f"{word!r} 出现在了给人看的句子里：{line}"

    # 反面：这几句确实是"有话说"的，不是靠全部返回空串过关的。
    assert "这是我猜的，你看对不对" in visible
    assert "还差林知遥和陈牧点头" in visible
    assert "还没人认领" in visible
