"""成局之后的群聊：仓储与助手这一层。

这些人**已经在同一个组里了**，所以他们本来就该能自由说话——成局前那七种
结构化消息的约束在这里没有理由存在。但"能自由说话"不等于"什么都能靠说话
定下来"，下面断言的正是这条界线上的六件事：

1. 助手发的话题**必须指得回一件还没定的事**，指不回去的一律不落库
2. 同一件事不问第二遍——问第二遍说明它没在听
3. 没有待定的事就闭嘴，不发闲聊
4. 聊天记录**不分页不截断**，`history()` 给全部
5. **聊出共识不等于结门**：话题卡下面写满"同意"，决策门一动不动
6. 起草说不出话时降级：发不出话题，人自己聊照常

真 PostgreSQL、真行级安全、真磁带回放。空间由测试直接写一行占位——
建空间是确认门的活（不变量 3），这一层没有那个入口是刻意的。
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from cofield.adapters.llm import Cassette, LiteLLMComposer
from cofield.adapters.persistence.engine import campus_connection, owner_connection
from cofield.adapters.persistence.messages import Kind, MessageRepository
from cofield.adapters.persistence.schema import spaces as spaces_table
from cofield.adapters.persistence.spaces import Item, SpaceRepository
from cofield.domain.ports.composer import ComposerUnavailable, Draft, DraftKind
from cofield.space import DECIDERS, Canvas, field_agent, item_kinds, person
from cofield.space.agent import CapabilityRefused, FieldAgent, Power, Suggestion
from cofield.space.canvas import AgentIsOff

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
CAMPUS = "demo-campus"
OTHER_CAMPUS = "simulation"
CASSETTES = Path(__file__).resolve().parent / "cassettes"

ME = uuid4()
CHEN_MU = uuid4()

#: 这两件事在磁带里有一次真模型的真回答（见 tests/cassettes）。
#: 助手拿到的事实就是决策门的标题，所以标题必须原样是它们。
SIGNING = "署名怎么写"
WHERE = "碰面地点定在哪"

#: 磁带里**没有**的一件事。它走的是和"起草服务挂了"完全同一条降级路径。
UNRECORDED = "片尾音乐用谁的"

ASK_ONLY = frozenset({Power.ASK})


@pytest.fixture(autouse=True)
def _clear(engine: Engine) -> Generator[None, None, None]:
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


class _SilentComposer:
    """模型挂了。**替换的是外部服务，不是我们自己的层**——
    而它挂掉是真实会发生的事，降级路径必须被真的走一遍。"""

    model = "silent"

    def draft(self, kind: DraftKind, **kwargs: object) -> Draft:
        raise ComposerUnavailable("这次说不出话")


@contextmanager
def chatting_in(
    engine: Engine,
    space_id: UUID,
    *,
    campus: str = CAMPUS,
    composer: object | None = None,
) -> Generator[tuple[FieldAgent, Canvas, MessageRepository], None, None]:
    """一个空间的助手、画布与聊天记录，三样挂在同一条连接上。

    同一条连接是刻意的：判断 5 要断言的是"聊天动了、画布没动"，
    两边读的必须是同一个事务看到的同一份事实。
    """
    with campus_connection(engine, campus) as conn:
        repo = SpaceRepository(conn, campus)
        space = repo.get(space_id)
        assert space is not None
        agent = FieldAgent(
            conn,
            Canvas(repo, space, item_kinds),
            composer=composer or Cassette(LiteLLMComposer(), directory=CASSETTES),  # type: ignore[arg-type]
            campus_id=campus,
        )
        yield agent, Canvas(repo, space, item_kinds), MessageRepository(conn, campus)


def a_gate(canvas: Canvas, title: str) -> Item:
    """一件还没定的事。两个人点头才算定下来。"""
    return canvas.add(
        "decision_gate",
        title,
        by=person(ME),
        now=NOW,
        extras={DECIDERS: [str(ME), str(CHEN_MU)]},
    )


def post_topics(
    repo: MessageRepository, space_id: UUID, topics: tuple, *, at: datetime = NOW
) -> None:
    """把助手起的话题落进聊天记录，作者是这个空间的助手。"""
    for i, topic in enumerate(topics):
        repo.say(
            space_id,
            author_id=field_agent(space_id).id,
            text=topic.text,
            # 逐条推进时刻。`history()` 同一时刻内按 id 兜底排序，而 id 是随机的，
            # 所以"同一刻发的两条"没有可靠的先后——测试自己控制时刻，不去赌它。
            now=at + timedelta(milliseconds=i),
            kind=Kind.TOPIC,
            is_agent=True,
            about_item_id=topic.about_item_id,
        )


# --- 话题必须指得回一件还没定的事 -------------------------------------------


def test_a_topic_the_assistant_cannot_point_back_to_never_lands(
    engine: Engine,
) -> None:
    """凭空造的话题连库都进不去。

    这条不是格式校验。助手一旦开始编话题，人会很快学会忽略它——
    而一旦被忽略，之后它说什么都没人看了。所以拒绝必须发生在**落库之前**：
    先收下再说不行，那一条已经在别人的屏幕上了。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id) as (_, _, repo):
        with pytest.raises(ValueError, match="指得回"):
            repo.say(
                space_id,
                author_id=field_agent(space_id).id,
                text="大家最近怎么样？",
                now=NOW,
                kind=Kind.TOPIC,
                is_agent=True,
            )

        assert repo.history(space_id) == ()


def test_a_person_starting_a_topic_owes_nobody_a_reference(engine: Engine) -> None:
    """人自己起的话题不受这条约束。

    约束的理由是"助手会编"，不是"话题得有出处"。把它加在所有人头上，
    这个组就连"我们聊点别的"都做不到了——那正是成局前那七种结构化消息
    存在的理由，而那个理由在这里已经消失了。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id) as (_, _, repo):
        mine = repo.say(
            space_id, author_id=ME, text="聊点别的：周末谁有空", now=NOW, kind=Kind.TOPIC
        )

        assert mine.about_item_id is None
        assert mine.is_agent is False
        assert len(repo.threads(space_id)) == 1


# --- 同一件事不问第二遍 -----------------------------------------------------


def test_it_never_raises_the_same_thing_twice(engine: Engine) -> None:
    """问第二遍说明它没在听。

    先证明这条守卫拦的不是"它根本发不出话题"：第一轮两件事都问了，
    第二轮同样的输入一个字都不说。差别只有一个——中间那些话已经问过了。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id) as (agent, canvas, repo):
        signing = a_gate(canvas, SIGNING)
        where = a_gate(canvas, WHERE)
        unsettled = [(signing.id, SIGNING), (where.id, WHERE)]
        token = agent.issue(purpose=DraftKind.OPEN_QUESTION, powers=ASK_ONLY, now=NOW)

        first = agent.open_questions(
            token, unsettled=unsettled, already_asked=frozenset(), now=NOW
        )
        post_topics(repo, space_id, first)
        asked = repo.already_asked_about(space_id)
        again = agent.open_questions(
            token, unsettled=unsettled, already_asked=asked, now=NOW
        )

    assert first, "磁带该命中却没命中，这条用例什么都没验证"
    assert {t.about_item_id for t in first} == {signing.id, where.id}
    assert asked == frozenset({signing.id, where.id})
    assert again == ()


def test_what_a_person_says_about_something_is_not_the_assistant_having_asked(
    engine: Engine,
) -> None:
    """人聊过这件事，不代表助手问过。

    「问过没有」记的是助手自己的发言。混进人说的话，一件被随口提过的事
    就再也等不到那张卡了——而那件事仍然没定。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id) as (_, canvas, repo):
        signing = a_gate(canvas, SIGNING)
        repo.say(
            space_id,
            author_id=ME,
            text="署名那件事我想过了",
            now=NOW,
            about_item_id=signing.id,
        )

        assert repo.already_asked_about(space_id) == frozenset()


# --- 没有待定的事就闭嘴 -----------------------------------------------------


def test_with_nothing_left_undecided_it_says_nothing(engine: Engine) -> None:
    """没有待定的事时发话题只能是闲聊，而闲聊正是让人学会忽略它的那件事。

    两种"没有"都要闭嘴：一件都没有，和剩下的全问过了。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id) as (agent, canvas, _):
        signing = a_gate(canvas, SIGNING)
        token = agent.issue(purpose=DraftKind.OPEN_QUESTION, powers=ASK_ONLY, now=NOW)

        nothing = agent.open_questions(
            token, unsettled=(), already_asked=frozenset(), now=NOW
        )
        all_asked = agent.open_questions(
            token,
            unsettled=[(signing.id, SIGNING)],
            already_asked=frozenset({signing.id}),
            now=NOW,
        )

    assert nothing == ()
    assert all_asked == ()


def test_it_raises_at_most_two_cards_at_a_time(engine: Engine) -> None:
    """破冰不是刷屏。一口气甩五个问题，人一个都不会答。

    三件待定的事进去，只出前两张——第三件留到下一轮，它不会丢：
    没被问过的事下次仍然在 `unsettled` 里。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id) as (agent, canvas, _):
        gates = [a_gate(canvas, title) for title in (SIGNING, WHERE, UNRECORDED)]
        token = agent.issue(purpose=DraftKind.OPEN_QUESTION, powers=ASK_ONLY, now=NOW)
        topics = agent.open_questions(
            token,
            unsettled=[(g.id, g.title) for g in gates],
            already_asked=frozenset(),
            now=NOW,
        )

    assert [t.about_item_id for t in topics] == [gates[0].id, gates[1].id]


# --- 空话不落库 -------------------------------------------------------------


def test_a_message_of_only_whitespace_never_becomes_a_bubble(engine: Engine) -> None:
    """一条只有空格的消息在界面上是一个占位气泡。

    它唯一的作用是让人以为有人说了什么——而"有人说了话"这件事，
    在一个靠聊天记录回溯的组里是要被当真的。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id) as (_, _, repo):
        for blank in ("", "   ", "\n\t "):
            with pytest.raises(ValueError, match="空消息"):
                repo.say(space_id, author_id=ME, text=blank, now=NOW)

        assert repo.history(space_id) == ()

        # 前后的空白也不留：留着，界面上就会出现看不见的缩进。
        padded = repo.say(space_id, author_id=ME, text="  我借到相机了  ", now=NOW)
        assert padded.text == "我借到相机了"


# --- 整条记录，一条都不少 ---------------------------------------------------


def test_the_whole_record_comes_back_unpaged_and_untruncated(engine: Engine) -> None:
    """「大家能看到整体的聊天记录」是这一层的承诺。

    一个默认只给最近五十条的接口会让"看看当时怎么说的"变成一件做不到的事。
    这里写 137 条：任何一个常见的默认页长（20/50/100）都会在这条断言上现形。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id) as (_, _, repo):
        for i in range(137):
            repo.say(
                space_id,
                author_id=ME if i % 2 else CHEN_MU,
                text=f"第 {i} 句",
                # 逐条推进时刻：同一时刻的多条消息之间没有可靠的先后。
                now=NOW + timedelta(seconds=i),
            )
        everything = repo.history(space_id)

    assert len(everything) == 137
    assert [m.text for m in everything] == [f"第 {i} 句" for i in range(137)]


def test_another_campus_can_neither_read_this_chat_nor_slip_into_it(
    engine: Engine,
) -> None:
    """跨租户读不到别人的聊天，也写不进别人的聊天。

    两个方向都要断：只断读，别人仍然可以往这个组里塞话；只断写，
    别人仍然看得见这个组说了什么。行级安全把两边一起挡住。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id) as (_, _, repo):
        repo.say(space_id, author_id=ME, text="我先去问问场地", now=NOW)

    with campus_connection(engine, OTHER_CAMPUS) as conn:
        theirs = MessageRepository(conn, OTHER_CAMPUS)
        stolen = theirs.history(space_id)
        theirs.say(space_id, author_id=uuid4(), text="我是别的学校的", now=NOW)

    with chatting_in(engine, space_id) as (_, _, repo):
        ours = repo.history(space_id)

    assert stolen == ()
    assert [m.text for m in ours] == ["我先去问问场地"]


# --- 助手的话一眼可辨，而且什么都定不了 -------------------------------------


def test_the_assistants_line_is_marked_as_its_own(engine: Engine) -> None:
    """分不清谁说的，"AI 起草、人类决定"就只是一句话。

    署名有两层：`is_agent` 给界面用来分通道，作者 id 由空间派生——
    它不是任何一个人，所以在成员名单里也找不到它。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id) as (agent, canvas, repo):
        signing = a_gate(canvas, SIGNING)
        repo.say(space_id, author_id=ME, text="署名那件事得定一下", now=NOW)
        token = agent.issue(purpose=DraftKind.OPEN_QUESTION, powers=ASK_ONLY, now=NOW)
        post_topics(
            repo,
            space_id,
            agent.open_questions(
                token,
                unsettled=[(signing.id, SIGNING)],
                already_asked=frozenset(),
                now=NOW,
            ),
            at=NOW + timedelta(seconds=1),
        )
        everything = repo.history(space_id)

    assert [m.is_agent for m in everything] == [False, True]
    assert everything[1].author_id == field_agent(space_id).id
    assert everything[1].author_id not in (ME, CHEN_MU)
    assert everything[1].kind is Kind.TOPIC


def test_agreeing_in_the_chat_does_not_settle_anything(engine: Engine) -> None:
    """**聊出共识不等于结门。**

    两个该点头的人在话题卡下面各写了一句"同意"，决策门一动不动：
    还开着、一个签名都没有、仍然算在"还有哪些决定没关"里。

    然后各自点一次头就关上了——这一半是必要的：少了它，这条用例可能
    只是因为这道门根本关不上而通过，那它什么都没测到。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id) as (agent, canvas, repo):
        signing = a_gate(canvas, SIGNING)
        token = agent.issue(purpose=DraftKind.OPEN_QUESTION, powers=ASK_ONLY, now=NOW)
        topics = agent.open_questions(
            token,
            unsettled=[(signing.id, SIGNING)],
            already_asked=frozenset(),
            now=NOW,
        )
        post_topics(repo, space_id, topics)
        card = repo.threads(space_id)[0].topic
        repo.say(
            space_id, author_id=ME, text="同意，就写「我们四个」", now=NOW,
            replies_to=card.id,
        )
        repo.say(
            space_id, author_id=CHEN_MU, text="我也同意，就这么定", now=NOW,
            replies_to=card.id,
        )

        chatted = canvas.item(signing.id)
        still_open = canvas.view(now=NOW).open_gates

        canvas.confirm(signing.id, by=person(ME), now=NOW)
        settled = canvas.confirm(signing.id, by=person(CHEN_MU), now=NOW)

    assert chatted.state == "open"
    assert chatted.extras.get("confirmed_by") in (None, [])
    assert [c.item.id for c in still_open] == [signing.id]
    assert settled.state == "settled"


def test_the_token_that_lets_it_ask_lets_it_do_nothing_else(engine: Engine) -> None:
    """发话题的令牌只够发话题。

    「聊天定不了任何事」不能只是这一层的自觉：拿着这张令牌，
    往画布上写一条草稿都做不到，更别说结门。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id) as (agent, _, _):
        token = agent.issue(purpose=DraftKind.OPEN_QUESTION, powers=ASK_ONLY, now=NOW)

        with pytest.raises(CapabilityRefused, match="draft"):
            agent.put_on_canvas(
                token,
                Suggestion(kind="task", title="约周四下午", grounded_in=(SIGNING,)),
                now=NOW,
            )
        with pytest.raises(CapabilityRefused, match="read_approved"):
            agent.check(token, Power.READ_APPROVED, now=NOW)


def test_a_topic_cannot_be_raised_after_the_assistant_is_switched_off(
    engine: Engine,
) -> None:
    """关掉它，连发话题的令牌都发不出来。

    「关掉助手后共域照常」的另一半：照常的是人，不是它。
    """
    space_id = open_space(engine, agent_enabled=False)
    with chatting_in(engine, space_id) as (agent, _, repo):
        with pytest.raises(AgentIsOff):
            agent.issue(purpose=DraftKind.OPEN_QUESTION, powers=ASK_ONLY, now=NOW)

        # 人自己聊照常。
        said = repo.say(space_id, author_id=ME, text="那我们自己定吧", now=NOW)
        assert [m.id for m in repo.history(space_id)] == [said.id]


# --- 起草说不出话的时候 -----------------------------------------------------


def test_a_dead_drafting_service_costs_the_topics_and_nothing_else(
    engine: Engine,
) -> None:
    """起草服务挂了：发不出话题，人自己聊照常。

    助手是增强不是前提。这条和"人主动关掉它"是同一件事的两面。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id, composer=_SilentComposer()) as (
        agent,
        canvas,
        repo,
    ):
        signing = a_gate(canvas, SIGNING)
        token = agent.issue(purpose=DraftKind.OPEN_QUESTION, powers=ASK_ONLY, now=NOW)
        topics = agent.open_questions(
            token,
            unsettled=[(signing.id, SIGNING)],
            already_asked=frozenset(),
            now=NOW,
        )
        repo.say(space_id, author_id=ME, text="署名那件事我想过了", now=NOW)
        repo.say(space_id, author_id=CHEN_MU, text="说说看", now=NOW + timedelta(seconds=1))
        everything = repo.history(space_id)

    assert topics == ()
    assert [m.text for m in everything] == ["署名那件事我想过了", "说说看"]


def test_one_thing_it_cannot_word_does_not_silence_the_other(engine: Engine) -> None:
    """写不出这一条，不该把另一条也拖下去。

    降级是**逐条**的：磁带里没有的那件事没出话题，录过的那件照常出。
    整批一起放弃的话，一次偶发失败就会让这个组一张卡都收不到。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id) as (agent, canvas, _):
        missing = a_gate(canvas, UNRECORDED)
        known = a_gate(canvas, SIGNING)
        token = agent.issue(purpose=DraftKind.OPEN_QUESTION, powers=ASK_ONLY, now=NOW)
        topics = agent.open_questions(
            token,
            unsettled=[(missing.id, UNRECORDED), (known.id, SIGNING)],
            already_asked=frozenset(),
            now=NOW,
        )

    assert [t.about_item_id for t in topics] == [known.id]


# --- 只有一层 ---------------------------------------------------------------


def test_replies_hang_under_the_topic_card_and_the_mainline_stays_out(
    engine: Engine,
) -> None:
    """回复挂在话题卡下面，主线上说的话不属于任何一张卡。

    两层以上的嵌套在手机上没人读得下去，而读不下去的讨论等于没发生——
    所以卡下面只有回复，回复下面没有东西。
    """
    space_id = open_space(engine)
    with chatting_in(engine, space_id) as (agent, canvas, repo):
        signing = a_gate(canvas, SIGNING)
        where = a_gate(canvas, WHERE)
        token = agent.issue(purpose=DraftKind.OPEN_QUESTION, powers=ASK_ONLY, now=NOW)
        post_topics(
            repo,
            space_id,
            agent.open_questions(
                token,
                unsettled=[(signing.id, SIGNING), (where.id, WHERE)],
                already_asked=frozenset(),
                now=NOW,
            ),
        )
        cards = {t.topic.about_item_id: t.topic for t in repo.threads(space_id)}
        for i, text in enumerate(("写「我们四个」就行", "我也这么想")):
            repo.say(
                space_id,
                author_id=ME if i else CHEN_MU,
                text=text,
                now=NOW + timedelta(seconds=i + 1),
                replies_to=cards[signing.id].id,
            )
        mainline = repo.say(
            space_id, author_id=ME, text="顺便说，相机借到了", now=NOW + timedelta(seconds=9)
        )
        threads = {t.topic.about_item_id: t for t in repo.threads(space_id)}
        everything = repo.history(space_id)

    assert [r.text for r in threads[signing.id].replies] == [
        "写「我们四个」就行",
        "我也这么想",
    ]
    assert threads[signing.id].answered is True
    # 没人回不是失败，是信号：这张卡问得不对，或者这件事大家其实不在意。
    assert threads[where.id].replies == ()
    assert threads[where.id].answered is False
    # 主线上那句谁都不挂，但它在整条记录里。
    assert all(mainline.id != r.id for t in threads.values() for r in t.replies)
    assert len(everything) == 5


# --- 顺序与指向（三个由测试暴露的真 bug）---


def test_two_cards_raised_in_the_same_instant_keep_their_order(
    engine: Engine,
) -> None:
    """助手一次落两张话题卡用的是**同一个时刻**。

    原来的兜底键是 `id`——随机 UUID——于是那两张卡每读一次先后都可能
    不一样，界面上会自己换位置。兜底键必须单调。
    """
    space_id = open_space(engine)
    with campus_connection(engine, CAMPUS) as conn:
        repo = MessageRepository(conn, CAMPUS)
        first = repo.say(
            space_id,
            author_id=field_agent(space_id).id,
            text="碰面地点定在哪？",
            now=NOW,
            kind=Kind.TOPIC,
            is_agent=True,
            about_item_id=uuid4(),
        )
        second = repo.say(
            space_id,
            author_id=field_agent(space_id).id,
            text="署名怎么写？",
            now=NOW,
            kind=Kind.TOPIC,
            is_agent=True,
            about_item_id=uuid4(),
        )

    # 读十次都该是同一个顺序。随机兜底键下这个断言会间歇性失败——
    # 而间歇性失败的界面比稳定错误的界面更难被相信。
    for _ in range(10):
        with campus_connection(engine, CAMPUS) as conn:
            order = [m.id for m in MessageRepository(conn, CAMPUS).history(space_id)]
        assert order == [first.id, second.id]


def test_a_reply_that_would_vanish_is_refused_instead(engine: Engine) -> None:
    """回给一条普通消息、或者指向一个不存在的 id——原来都会被接受，
    然后在话题视图里**消失**，只在平铺列表里出现。

    静默地少一条，比明确地拒一条糟得多。
    """
    space_id = open_space(engine)
    with campus_connection(engine, CAMPUS) as conn:
        repo = MessageRepository(conn, CAMPUS)
        plain = repo.say(space_id, author_id=ME, text="我周四有空", now=NOW)

        with pytest.raises(ValueError, match="话题卡"):
            repo.say(
                space_id,
                author_id=ME,
                text="回给一条普通消息",
                now=NOW,
                replies_to=plain.id,
            )
        with pytest.raises(ValueError, match="不在这里"):
            repo.say(
                space_id,
                author_id=ME,
                text="回给一个不存在的 id",
                now=NOW,
                replies_to=uuid4(),
            )


def test_a_reply_cannot_reach_into_another_space(engine: Engine) -> None:
    """别的空间的话题卡不能被回复——那条回复对两边都不可见。"""
    mine = open_space(engine)
    theirs = open_space(engine)
    with campus_connection(engine, CAMPUS) as conn:
        repo = MessageRepository(conn, CAMPUS)
        elsewhere = repo.say(
            theirs,
            author_id=field_agent(theirs).id,
            text="他们那边的话题",
            now=NOW,
            kind=Kind.TOPIC,
            is_agent=True,
            about_item_id=uuid4(),
        )
        with pytest.raises(ValueError, match="不在这里"):
            repo.say(
                mine, author_id=ME, text="插一句", now=NOW, replies_to=elsewhere.id
            )
