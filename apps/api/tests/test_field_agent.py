"""场域智能体：它能做什么，以及它**永远**做不到什么。

这里断言的不是"助手能写建议"，而是三件更重要的事：

1. 它拿不到任何凭证——每件事都要一张绑空间、绑用途、绑纪元的令牌
2. 成员或策略一变，旧令牌**立刻**作废，不等过期
3. 它说不出话的时候（模型挂了、关掉了），共域一步都不少

真 PostgreSQL、真令牌校验、真磁带回放。
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
from cofield.adapters.persistence.schema import spaces as spaces_table
from cofield.adapters.persistence.spaces import SpaceRepository
from cofield.domain.ports.composer import ComposerUnavailable, Draft, DraftKind
from cofield.space import Canvas, ItemKindRegistry, item_kinds, person
from cofield.space.agent import (
    FORBIDDEN,
    TOKEN_TTL,
    Capability,
    CapabilityRefused,
    FieldAgent,
    Power,
    Suggestion,
)
from cofield.space.canvas import AgentIsOff

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
CAMPUS = "demo-campus"
CASSETTES = Path(__file__).resolve().parent / "cassettes"

ME = uuid4()
CHEN_MU = uuid4()

READ_AND_DRAFT = frozenset({Power.READ_APPROVED, Power.DRAFT})


@pytest.fixture(autouse=True)
def _clear(engine: Engine) -> Generator[None, None, None]:
    yield
    with owner_connection(engine) as conn:
        conn.execute(sa.text("TRUNCATE spaces, space_items CASCADE"))


def open_space(engine: Engine, *, campus: str = CAMPUS, agent_enabled: bool = True) -> UUID:
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
def field_agent_on(
    engine: Engine,
    space_id: UUID,
    *,
    campus: str = CAMPUS,
    composer: object | None = None,
    kinds: ItemKindRegistry = item_kinds,
) -> Generator[tuple[FieldAgent, Canvas], None, None]:
    with campus_connection(engine, campus) as conn:
        repo = SpaceRepository(conn, campus)
        space = repo.get(space_id)
        assert space is not None
        canvas = Canvas(repo, space, kinds)
        agent = FieldAgent(
            conn,
            canvas,
            composer=composer or Cassette(LiteLLMComposer(), directory=CASSETTES),  # type: ignore[arg-type]
            campus_id=campus,
        )
        yield agent, canvas


# --- 凭证：它一张都没有 ---


def test_the_forbidden_powers_are_not_even_expressible(engine: Engine) -> None:
    """改承诺、增删成员、发布素材、批准记忆、花钱、跨共域——设计上不给。

    第一道是类型层：它们一个都不在 `Power` 里，所以**写不出来**，
    不是"写得出来但会被过滤掉"。这条断言守的就是这件事——
    哪天有人往 `Power` 里加了一个，这里立刻红。
    """
    assert not {p.value for p in Power} & set(FORBIDDEN)
    assert FORBIDDEN, "清单空了等于这条判断被悄悄删掉了"


def test_a_capability_name_smuggled_in_as_a_string_is_refused(
    engine: Engine,
) -> None:
    """第二道是运行时：动态拼出来的能力名照样被拒。

    类型检查管不了从配置或请求体读进来的字符串，所以两道都要有。
    而且必须是"权限被拒"而不是"服务出错"——后者会被当成故障去重试。
    """
    space_id = open_space(engine)
    with field_agent_on(engine, space_id) as (agent, _):
        for forbidden in FORBIDDEN:
            with pytest.raises(CapabilityRefused, match="永远不发"):
                agent.issue(
                    purpose=DraftKind.NEGOTIATION_REPLY,
                    powers=frozenset({forbidden}),  # type: ignore[arg-type]
                    now=NOW,
                )
        with pytest.raises(CapabilityRefused, match="不认识"):
            agent.issue(
                purpose=DraftKind.NEGOTIATION_REPLY,
                powers=frozenset({"read_everything"}),  # type: ignore[arg-type]
                now=NOW,
            )


def test_a_token_from_another_space_does_not_work_here(engine: Engine) -> None:
    """跨共域在令牌校验这一步被挡死。

    存储命名空间隔离不是靠"我们不会去查别的空间"这种自觉。
    """
    mine = open_space(engine)
    theirs = open_space(engine)

    with field_agent_on(engine, mine) as (agent, _):
        stolen = Capability(
            space_id=theirs,
            powers=READ_AND_DRAFT,
            epoch=1,
            expires_at=NOW + TOKEN_TTL,
            purpose=DraftKind.NEGOTIATION_REPLY,
        )
        with pytest.raises(CapabilityRefused, match="不是这个空间"):
            agent.check(stolen, Power.READ_APPROVED, now=NOW)


def test_a_token_only_carries_the_powers_it_was_given(engine: Engine) -> None:
    space_id = open_space(engine)
    with field_agent_on(engine, space_id) as (agent, _):
        read_only = agent.issue(
            purpose=DraftKind.NEGOTIATION_REPLY,
            powers=frozenset({Power.READ_APPROVED}),
            now=NOW,
        )
        agent.check(read_only, Power.READ_APPROVED, now=NOW)
        with pytest.raises(CapabilityRefused, match="draft"):
            agent.check(read_only, Power.DRAFT, now=NOW)


def test_a_token_expires(engine: Engine) -> None:
    space_id = open_space(engine)
    with field_agent_on(engine, space_id) as (agent, _):
        token = agent.issue(
            purpose=DraftKind.NEGOTIATION_REPLY, powers=READ_AND_DRAFT, now=NOW
        )
        agent.check(token, Power.DRAFT, now=NOW)
        with pytest.raises(CapabilityRefused, match="过期"):
            agent.check(token, Power.DRAFT, now=NOW + TOKEN_TTL + timedelta(seconds=1))


# --- 撤销必须是即时的 ---


def test_a_membership_change_kills_every_outstanding_token_at_once(
    engine: Engine,
) -> None:
    """**这条是能力令牌设计的全部理由。**

    短过期能挡住"很久以前发的令牌"，挡不住"三十秒前发的、而这三十秒里
    有人退出了"。撤销必须是即时的，而唯一即时的手段是让所有旧令牌一起作废。
    """
    space_id = open_space(engine)
    with field_agent_on(engine, space_id) as (agent, _):
        token = agent.issue(
            purpose=DraftKind.NEGOTIATION_REPLY, powers=READ_AND_DRAFT, now=NOW
        )
        agent.check(token, Power.DRAFT, now=NOW)

        agent.bump_epoch()  # 有人退出了 / 同意变了 / 策略改了

        # 令牌还没过期，但已经不管用了。
        with pytest.raises(CapabilityRefused, match="作废"):
            agent.check(token, Power.DRAFT, now=NOW + timedelta(seconds=1))


def test_bumping_the_epoch_is_monotonic(engine: Engine) -> None:
    """单调计数器就够，不需要维护一张吊销名单。

    吊销名单会引入"查的时候它还有效、用的时候已经无效"的窗口。
    """
    space_id = open_space(engine)
    with field_agent_on(engine, space_id) as (agent, _):
        first = agent.bump_epoch()
        second = agent.bump_epoch()

    assert second == first + 1


# --- 关掉它 ---


def test_switching_it_off_stops_every_entry_point(engine: Engine) -> None:
    """关掉之后连令牌都发不出来，更别说起草。"""
    space_id = open_space(engine, agent_enabled=False)
    with field_agent_on(engine, space_id) as (agent, _):
        with pytest.raises(AgentIsOff):
            agent.issue(
                purpose=DraftKind.NEGOTIATION_REPLY, powers=READ_AND_DRAFT, now=NOW
            )


def test_a_token_issued_before_it_was_switched_off_stops_working(
    engine: Engine,
) -> None:
    """关掉的一瞬间就该生效，不是等手上的令牌用完。"""
    space_id = open_space(engine)
    with field_agent_on(engine, space_id) as (agent, _):
        token = agent.issue(
            purpose=DraftKind.NEGOTIATION_REPLY, powers=READ_AND_DRAFT, now=NOW
        )

    with campus_connection(engine, CAMPUS) as conn:
        conn.execute(
            sa.update(spaces_table)
            .where(spaces_table.c.id == space_id)
            .values(agent_enabled=False)
        )

    with field_agent_on(engine, space_id) as (agent, _):
        with pytest.raises(AgentIsOff):
            agent.check(token, Power.DRAFT, now=NOW)


# --- 它说不出话的时候 ---


def test_a_dead_model_makes_it_quiet_not_broken(engine: Engine) -> None:
    """模型挂了，助手闭嘴，共域照常。

    助手是增强不是前提——这条和 #10 那条「关掉助手后人工流程一步不少」
    是同一件事的两面：一个是人主动关，一个是它自己坏了。
    """
    space_id = open_space(engine)
    with field_agent_on(engine, space_id, composer=_SilentComposer()) as (agent, canvas):
        canvas.add("task", "先定下碰面地点", by=person(ME), now=NOW)
        token = agent.issue(
            purpose=DraftKind.NEGOTIATION_REPLY, powers=READ_AND_DRAFT, now=NOW
        )
        suggestions = agent.suggest_next_steps(token, now=NOW)

        # 助手没话说，但画布照常。
        canvas.add("task", "借设备", by=person(CHEN_MU), now=NOW)
        view = canvas.view(now=NOW)

    assert suggestions == ()
    assert len(view.cards) == 2


def test_an_empty_space_makes_it_shut_up_rather_than_invent(engine: Engine) -> None:
    """空空的空间里助手无话可说。

    这时候闭嘴比编一条"欢迎开始协作"好——后者是纯粹的噪音，
    而且会让用户学会忽略它说的所有话。
    """
    space_id = open_space(engine)
    with field_agent_on(engine, space_id) as (agent, _):
        token = agent.issue(
            purpose=DraftKind.NEGOTIATION_REPLY, powers=READ_AND_DRAFT, now=NOW
        )
        assert agent.suggest_next_steps(token, now=NOW) == ()


# --- 它说得出话的时候 ---


def test_what_it_says_can_always_be_traced_back(engine: Engine) -> None:
    """看不到依据的建议，"人类决定"就只是点一下按钮。"""
    space_id = open_space(engine)
    with field_agent_on(engine, space_id) as (agent, canvas):
        canvas.add("task", "周雨能补上缺的剪辑", by=person(ME), now=NOW)
        canvas.add("task", "你们四个人周四下午都空着", by=person(ME), now=NOW)
        canvas.add("task", "这件事的截止时间是下周日", by=person(ME), now=NOW)
        token = agent.issue(
            purpose=DraftKind.PROOF_NARRATION, powers=READ_AND_DRAFT, now=NOW
        )
        suggestions = agent.suggest_next_steps(token, now=NOW)

    assert suggestions
    for suggestion in suggestions:
        assert suggestion.grounded_in, "没有依据的建议不该出现"


def test_a_suggestion_without_grounds_never_reaches_the_canvas(
    engine: Engine,
) -> None:
    """「点开看依据」这个承诺要么永远成立，要么就不成立。

    有时有东西有时没有，等于这个承诺不存在。
    """
    space_id = open_space(engine)
    with field_agent_on(engine, space_id) as (agent, _):
        token = agent.issue(
            purpose=DraftKind.NEGOTIATION_REPLY, powers=READ_AND_DRAFT, now=NOW
        )
        with pytest.raises(CapabilityRefused, match="依据"):
            agent.put_on_canvas(
                token,
                Suggestion(kind="task", title="随便做点什么", grounded_in=()),
                now=NOW,
            )


def test_what_it_puts_on_the_canvas_does_not_count_yet(engine: Engine) -> None:
    """助手放上去的东西标着「等你过目」，在被采纳之前不算数。

    「不算数」的四条行为由 #10 守着，这里只断言它确实进了那一栏。
    """
    space_id = open_space(engine)
    with field_agent_on(engine, space_id) as (agent, canvas):
        canvas.add("task", "周雨能补上缺的剪辑", by=person(ME), now=NOW)
        token = agent.issue(
            purpose=DraftKind.PROOF_NARRATION, powers=READ_AND_DRAFT, now=NOW
        )
        suggestion = agent.put_on_canvas(
            token,
            Suggestion(kind="task", title="约周四下午", grounded_in=("周雨能补上缺的剪辑",)),
            now=NOW,
        )
        view = canvas.view(now=NOW)
        item = canvas.item(suggestion.item_id)  # type: ignore[arg-type]

    assert item.drafted_by_agent is True
    assert item.accepted_by is None
    assert any(card.item.id == item.id for card in view.drafts)
    assert all(card.item.id != item.id for card in view.cards)


def test_it_never_reads_its_own_unaccepted_drafts(engine: Engine) -> None:
    """助手只看已批准的东西。

    读自己上次写的，它会开始引用自己，越写越远——而且每一轮都离
    真人确认过的事实更远一点。
    """
    space_id = open_space(engine)
    with field_agent_on(engine, space_id) as (agent, canvas):
        canvas.add("task", "周雨能补上缺的剪辑", by=person(ME), now=NOW)
        token = agent.issue(
            purpose=DraftKind.PROOF_NARRATION, powers=READ_AND_DRAFT, now=NOW
        )
        agent.put_on_canvas(
            token,
            Suggestion(
                kind="task",
                title="助手编的一条东西",
                grounded_in=("周雨能补上缺的剪辑",),
            ),
            now=NOW,
        )
        second = agent.suggest_next_steps(token, now=NOW)

    for suggestion in second:
        assert "助手编的一条东西" not in suggestion.grounded_in


def test_it_gives_at_most_a_handful(engine: Engine) -> None:
    """一次甩十条建议，人不会挑，只会全部忽略。

    实证：搜索上限 3→100 时福利显著下降。那和没有助手一样，
    只是多占了屏幕。
    """
    space_id = open_space(engine)
    with field_agent_on(engine, space_id) as (agent, canvas):
        for i in range(8):
            canvas.add("task", f"已经确认的第 {i} 件事", by=person(ME), now=NOW)
        token = agent.issue(
            purpose=DraftKind.PROOF_NARRATION, powers=READ_AND_DRAFT, now=NOW
        )
        suggestions = agent.suggest_next_steps(token, now=NOW)

    assert len(suggestions) <= 3


# --- 提议投票 ---


def test_it_proposes_a_vote_only_about_something_already_undecided(
    engine: Engine,
) -> None:
    """凭空造一次投票和凭空造一个话题一样，会很快被所有人忽略。"""
    space_id = open_space(engine)
    thing = uuid4()
    with field_agent_on(engine, space_id) as (agent, _):
        token = agent.issue(
            purpose=DraftKind.OPEN_QUESTION, powers=(Power.ASK,), now=NOW
        )
        made = agent.propose_poll(
            token,
            about=(thing, "周六去东湖还是磨山"),
            options=["东湖", "磨山"],
            already_asked=frozenset(),
            now=NOW,
        )

    assert made is not None
    assert made.kind == "poll"
    # 看得到依据。看不到依据的建议，"人类决定"就只是点一下按钮。
    assert "东湖" in made.grounded_in


def test_it_does_not_propose_the_same_vote_twice(engine: Engine) -> None:
    """同一件事问第二遍最伤——它说明这个助手没在听。"""
    space_id = open_space(engine)
    thing = uuid4()
    with field_agent_on(engine, space_id) as (agent, _):
        token = agent.issue(
            purpose=DraftKind.OPEN_QUESTION, powers=(Power.ASK,), now=NOW
        )
        assert (
            agent.propose_poll(
                token,
                about=(thing, "去哪"),
                options=["东湖", "磨山"],
                already_asked=frozenset({thing}),
                now=NOW,
            )
            is None
        )


def test_one_option_is_not_a_vote(engine: Engine) -> None:
    """一个选项的投票不是投票，是通知。"""
    space_id = open_space(engine)
    with field_agent_on(engine, space_id) as (agent, _):
        token = agent.issue(
            purpose=DraftKind.OPEN_QUESTION, powers=(Power.ASK,), now=NOW
        )
        assert (
            agent.propose_poll(
                token,
                about=(uuid4(), "去哪"),
                options=["东湖"],
                already_asked=frozenset(),
                now=NOW,
            )
            is None
        )


def test_proposing_a_vote_needs_the_asking_power(engine: Engine) -> None:
    """能力令牌管着它，和别的动作一样。"""
    space_id = open_space(engine)
    with field_agent_on(engine, space_id) as (agent, _):
        token = agent.issue(
            purpose=DraftKind.NEGOTIATION_REPLY, powers=(Power.DRAFT,), now=NOW
        )
        with pytest.raises(CapabilityRefused):
            agent.propose_poll(
                token,
                about=(uuid4(), "去哪"),
                options=["东湖", "磨山"],
                already_asked=frozenset(),
                now=NOW,
            )
