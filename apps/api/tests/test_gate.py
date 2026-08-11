"""确认门与原子成局。

这里断言的是两条**不可越过**的约束，而且是用**可查询的事实**断言的，
不是断言"我们没写那行代码"：

> 未获真人确认的提案不创建事件、共域或任何关系边
> 达到门槛时在单一事务内创建承诺、事件、成员关系与共域

跑在真 Postgres 上，事务是真的，唯一约束是真的。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from cofield.adapters.persistence.engine import campus_connection, owner_connection
from cofield.adapters.persistence.events import EventRepository
from cofield.formation.gate import (
    Commitment,
    CommitmentState,
    GateVerdict,
    evaluate,
    terms_digest,
)
from cofield.formation.service import ConfirmationGate

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
SIM = "simulation"


@pytest.fixture(autouse=True)
def _clean(engine: Engine):  # type: ignore[no-untyped-def]
    yield
    with owner_connection(engine) as conn:
        conn.execute(
            sa.text(
                "TRUNCATE formation_proposals, commitments, shared_events, "
                "event_members, spaces, space_items CASCADE"
            )
        )


def _seed_proposal(
    engine: Engine,
    *,
    members: tuple[UUID, ...],
    expires_at: datetime | None = None,
    first_action: str = "先碰一次面，把分工定下来",
) -> UUID:
    """造一个提案。用真表真列——这一层不该有任何简化的替身。"""
    proposal_id = uuid4()
    with campus_connection(engine, SIM) as conn:
        conn.execute(
            sa.text(
                "INSERT INTO formation_proposals "
                "(id, campus_id, intent_id, action_kind, cleared_at, member_ids, "
                " proof, stability_passed, expires_at, terms_digest, version) "
                "VALUES (:id, :campus, :intent, :kind, :cleared, :members, "
                " CAST(:proof AS json), true, :expires, :digest, 1)"
            ),
            {
                "id": proposal_id,
                "campus": SIM,
                "intent": uuid4(),
                "kind": "creative_work",
                "cleared": NOW,
                "members": list(members),
                "proof": (
                    '{"satisfied": [{"text": "拍一支 60 秒短片"}], '
                    '"for_humans": [{"text": "' + first_action + '"}]}'
                ),
                "expires": expires_at or NOW + timedelta(days=2),
                "digest": "d0",
            },
        )
    return proposal_id


def _members(n: int = 3) -> tuple[UUID, ...]:
    return tuple(uuid4() for _ in range(n))


def _commitment(
    person: UUID, state: CommitmentState, *, condition: str | None = None
) -> Commitment:
    return Commitment(
        id=uuid4(),
        proposal_id=uuid4(),
        principal_id=person,
        state=state,
        condition=condition,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=36),
    )


# --- 门本身（纯函数，不碰库）---


def test_nobody_answering_is_not_the_same_as_refusing() -> None:
    """没回和拒绝在产品上是两件事。

    混起来，「还在等谁」这一屏就说不出话，而且会把一个只是没看到消息的人
    当成拒绝，直接把整局判死。
    """
    people = _members(3)
    state = evaluate((), expected_members=people, now=NOW)

    assert state.verdict is GateVerdict.WAITING
    assert set(state.waiting_on) == set(people)
    assert state.declined_by == ()


def test_i_can_but_is_not_a_yes() -> None:
    """「我可以，但……」不算同意，门不认它。

    少了这一档，想参与但有顾虑的人只能在"违心答应"和"直接拒绝"之间
    二选一——这两种结果对所有人都更差。
    """
    a, b, c = _members(3)
    state = evaluate(
        (
            _commitment(a, CommitmentState.ACCEPTED),
            _commitment(b, CommitmentState.CONDITIONAL, condition="我周四要上课"),
            _commitment(c, CommitmentState.ACCEPTED),
        ),
        expected_members=(a, b, c),
        now=NOW,
    )

    assert state.verdict is GateVerdict.NEEDS_REVISION
    assert state.conditions == ((b, "我周四要上课"),)


def test_one_refusal_ends_this_version() -> None:
    a, b, c = _members(3)
    state = evaluate(
        (
            _commitment(a, CommitmentState.ACCEPTED),
            _commitment(b, CommitmentState.DECLINED),
        ),
        expected_members=(a, b, c),
        now=NOW,
    )

    assert state.verdict is GateVerdict.DECLINED
    assert state.declined_by == (b,)


def test_everyone_saying_yes_opens_the_gate() -> None:
    people = _members(3)
    state = evaluate(
        tuple(_commitment(p, CommitmentState.ACCEPTED) for p in people),
        expected_members=people,
        now=NOW,
    )

    assert state.can_form


def test_the_window_closing_is_not_a_refusal() -> None:
    """过期的人没有拒绝，只是这次没赶上。

    说成拒绝会让他在别人眼里背一个他没做过的决定。
    """
    a, b = _members(2)
    state = evaluate(
        (
            _commitment(a, CommitmentState.ACCEPTED),
            _commitment(b, CommitmentState.PENDING),
        ),
        expected_members=(a, b),
        now=NOW + timedelta(days=3),
    )

    assert state.verdict is GateVerdict.EXPIRED
    assert state.declined_by == ()


# --- 条款摘要 ---


def test_changing_who_is_in_the_group_invalidates_the_old_yes() -> None:
    """同意是对某一版条款的同意，不是对"这个提案"的永久授权。"""
    a, b, c, d = _members(4)
    base = {
        "role_assignment": {"剪辑": b},
        "common_slots": (3, 4),
        "zone": "东校区",
        "deadline": NOW + timedelta(days=5),
    }

    assert terms_digest(member_ids=(a, b, c), **base) != terms_digest(  # type: ignore[arg-type]
        member_ids=(a, b, d), **base  # type: ignore[arg-type]
    )


def test_reordering_the_same_people_is_not_a_new_deal() -> None:
    """同一批人换个顺序不是新条款——否则每次求解都会白白让人重新确认。"""
    a, b, c = _members(3)
    base = {
        "role_assignment": {"剪辑": b},
        "common_slots": (3, 4),
        "zone": None,
        "deadline": NOW,
    }

    assert terms_digest(member_ids=(a, b, c), **base) == terms_digest(  # type: ignore[arg-type]
        member_ids=(c, a, b), **base  # type: ignore[arg-type]
    )


def test_changing_the_agreed_time_invalidates_it() -> None:
    a, b = _members(2)
    base = {
        "member_ids": (a, b),
        "role_assignment": {},
        "zone": None,
        "deadline": NOW,
    }

    assert terms_digest(common_slots=(3, 4), **base) != terms_digest(  # type: ignore[arg-type]
        common_slots=(9, 10), **base  # type: ignore[arg-type]
    )


# --- 原子性：不达门槛什么都不产生 ---


def test_nothing_at_all_exists_until_the_gate_opens(engine: Engine) -> None:
    """**未获真人确认的提案不创建事件、共域或任何关系边。**

    断言的是四个可查询的计数，不是"我们没写那行代码"。
    """
    a, b, c = _members(3)
    proposal_id = _seed_proposal(engine, members=(a, b, c))

    with campus_connection(engine, SIM) as conn:
        gate = ConfirmationGate(conn, SIM)
        gate.invite(proposal_id, now=NOW)
        outcome = gate.decide(
            proposal_id, a, state=CommitmentState.ACCEPTED, now=NOW
        )
        assert outcome.formed is None

        counts = {
            table: conn.execute(
                sa.text(f"SELECT count(*) FROM {table}")  # noqa: S608
            ).scalar_one()
            for table in ("shared_events", "event_members", "spaces", "space_items")
        }

    assert counts == {
        "shared_events": 0,
        "event_members": 0,
        "spaces": 0,
        "space_items": 0,
    }


def test_a_refusal_leaves_no_trace_on_anyone(engine: Engine) -> None:
    """拒绝是零负担的：不产生关系边，也不给拒绝的人留下任何记录。"""
    a, b, c = _members(3)
    proposal_id = _seed_proposal(engine, members=(a, b, c))

    with campus_connection(engine, SIM) as conn:
        gate = ConfirmationGate(conn, SIM)
        gate.invite(proposal_id, now=NOW)
        gate.decide(proposal_id, a, state=CommitmentState.ACCEPTED, now=NOW)
        outcome = gate.decide(
            proposal_id, b, state=CommitmentState.DECLINED, now=NOW
        )
        edges = EventRepository(conn, SIM).count_edges(b)

    assert outcome.state.verdict is GateVerdict.DECLINED
    assert edges == 0


def test_the_gate_opening_creates_everything_at_once(engine: Engine) -> None:
    """**达到门槛时在单一事务内创建承诺、事件、成员关系与共域。**"""
    a, b, c = _members(3)
    proposal_id = _seed_proposal(engine, members=(a, b, c))

    with campus_connection(engine, SIM) as conn:
        gate = ConfirmationGate(conn, SIM)
        gate.invite(proposal_id, now=NOW)
        for person in (a, b):
            gate.decide(proposal_id, person, state=CommitmentState.ACCEPTED, now=NOW)
        outcome = gate.decide(
            proposal_id, c, state=CommitmentState.ACCEPTED, now=NOW
        )

        assert outcome.formed is not None
        members = conn.execute(
            sa.text("SELECT count(*) FROM event_members WHERE event_id = :e"),
            {"e": outcome.formed.event_id},
        ).scalar_one()
        space = conn.execute(
            sa.text("SELECT count(*) FROM spaces WHERE event_id = :e"),
            {"e": outcome.formed.event_id},
        ).scalar_one()

    assert members == 3
    assert space == 1


def test_the_space_is_not_empty_on_arrival(engine: Engine) -> None:
    """成员共同定下的第一个动作要成为空间里看得见的东西。

    空空的共域和群聊没区别。第一屏就该有一件具体的事，
    而且它必须来自大家刚刚确认的内容，不是系统编的欢迎语。
    """
    people = _members(2)
    proposal_id = _seed_proposal(
        engine, members=people, first_action="先定下周四晚上碰面的地点"
    )

    with campus_connection(engine, SIM) as conn:
        gate = ConfirmationGate(conn, SIM)
        gate.invite(proposal_id, now=NOW)
        for person in people:
            outcome = gate.decide(
                proposal_id, person, state=CommitmentState.ACCEPTED, now=NOW
            )
        assert outcome.formed is not None
        row = conn.execute(
            sa.text(
                "SELECT title, drafted_by_agent FROM space_items WHERE space_id = :s"
            ),
            {"s": outcome.formed.space_id},
        ).one()

    assert row.title == "先定下周四晚上碰面的地点"
    assert row.drafted_by_agent is False, "第一个动作来自真人的确认，不是助手起草的"


def test_confirming_twice_does_not_make_two_events(engine: Engine) -> None:
    """重复提交不产生重复事件，写操作幂等。

    靠唯一约束，不靠"先查一下再插"——并发下先查后插会同时通过检查。
    """
    people = _members(2)
    proposal_id = _seed_proposal(engine, members=people)

    with campus_connection(engine, SIM) as conn:
        gate = ConfirmationGate(conn, SIM)
        gate.invite(proposal_id, now=NOW)
        for person in people:
            first = gate.decide(
                proposal_id, person, state=CommitmentState.ACCEPTED, now=NOW
            )
        again = gate.decide(
            proposal_id, people[-1], state=CommitmentState.ACCEPTED, now=NOW
        )
        total = conn.execute(sa.text("SELECT count(*) FROM shared_events")).scalar_one()

    assert first.formed is not None and first.formed.created is True
    assert again.formed is not None and again.formed.created is False
    assert again.formed.event_id == first.formed.event_id
    assert total == 1


def test_the_agent_token_is_not_minted_inside_the_transaction(engine: Engine) -> None:
    """场域智能体授权在事务提交之后才生成。

    这两件事的失败后果不对称：事务回滚掉一个本该存在的事件，用户会以为
    系统坏了；而多发一张令牌给一个不存在的空间，是一个真实的权限泄漏。
    所以门只**交出**待办，不自己做掉。
    """
    people = _members(2)
    proposal_id = _seed_proposal(engine, members=people)

    with campus_connection(engine, SIM) as conn:
        gate = ConfirmationGate(conn, SIM)
        gate.invite(proposal_id, now=NOW)
        for person in people:
            outcome = gate.decide(
                proposal_id, person, state=CommitmentState.ACCEPTED, now=NOW
            )

    assert outcome.formed is not None
    assert outcome.grant_agent_for_space == outcome.formed.space_id
    # 第二次确认不该再发一张。
    with campus_connection(engine, SIM) as conn:
        repeat = ConfirmationGate(conn, SIM).decide(
            proposal_id, people[0], state=CommitmentState.ACCEPTED, now=NOW
        )
    assert repeat.grant_agent_for_space is None


# --- 条件接受生成新版本 ---


def test_a_condition_makes_a_new_version_and_voids_the_old_one(
    engine: Engine,
) -> None:
    """改条款是**新增一行**而不是改旧行。

    谁在哪一版上答应过什么，申诉时要查得出来。
    """
    a, b = _members(2)
    proposal_id = _seed_proposal(engine, members=(a, b))

    with campus_connection(engine, SIM) as conn:
        gate = ConfirmationGate(conn, SIM)
        gate.invite(proposal_id, now=NOW)
        gate.decide(proposal_id, a, state=CommitmentState.ACCEPTED, now=NOW)
        outcome = gate.decide(
            proposal_id,
            b,
            state=CommitmentState.CONDITIONAL,
            now=NOW,
            condition="我周四要上课，能不能换到周五",
        )

        assert outcome.revised_proposal_id is not None
        old = conn.execute(
            sa.text(
                "SELECT withdrawn_at, version FROM formation_proposals WHERE id = :i"
            ),
            {"i": proposal_id},
        ).one()
        new = conn.execute(
            sa.text(
                "SELECT supersedes, version, terms_digest "
                "FROM formation_proposals WHERE id = :i"
            ),
            {"i": outcome.revised_proposal_id},
        ).one()

    assert old.withdrawn_at is not None, "旧版没作废，会有人对着过期条款点确认"
    assert new.supersedes == proposal_id
    assert new.version == old.version + 1
    assert new.terms_digest != "d0", "新版摘要没变，旧的「我加入」会被误当成对新条款的同意"


def test_a_withdrawn_version_stops_accepting_answers(engine: Engine) -> None:
    a, b = _members(2)
    proposal_id = _seed_proposal(engine, members=(a, b))

    with campus_connection(engine, SIM) as conn:
        gate = ConfirmationGate(conn, SIM)
        gate.invite(proposal_id, now=NOW)
        gate.decide(
            proposal_id, b, state=CommitmentState.CONDITIONAL, now=NOW, condition="换个时间"
        )

        with pytest.raises(ValueError, match="作废"):
            gate.decide(proposal_id, a, state=CommitmentState.ACCEPTED, now=NOW)


def test_a_condition_without_saying_what_it_is_is_rejected(engine: Engine) -> None:
    """有条件接受必须说清条件，否则对方无从回应。"""
    people = _members(2)
    proposal_id = _seed_proposal(engine, members=people)

    with campus_connection(engine, SIM) as conn:
        gate = ConfirmationGate(conn, SIM)
        gate.invite(proposal_id, now=NOW)
        with pytest.raises(ValueError, match="条件"):
            gate.decide(
                proposal_id, people[0], state=CommitmentState.CONDITIONAL, now=NOW
            )


# --- 只有真人能推动 ---


def test_an_outsider_cannot_vote_on_someone_elses_proposal(engine: Engine) -> None:
    """不在名单里的人投票要明确失败，不能静默创建一条承诺。

    静默创建等于任何人都能给任意提案投票。
    """
    people = _members(2)
    proposal_id = _seed_proposal(engine, members=people)

    with campus_connection(engine, SIM) as conn:
        gate = ConfirmationGate(conn, SIM)
        gate.invite(proposal_id, now=NOW)
        with pytest.raises(ValueError, match="名单"):
            gate.decide(proposal_id, uuid4(), state=CommitmentState.ACCEPTED, now=NOW)


def test_an_answer_cannot_be_reset_to_unanswered(engine: Engine) -> None:
    """把答复改回「还没回」没有真实含义，允许它只会制造一种绕过门槛的方式。"""
    people = _members(2)
    proposal_id = _seed_proposal(engine, members=people)

    with campus_connection(engine, SIM) as conn:
        gate = ConfirmationGate(conn, SIM)
        gate.invite(proposal_id, now=NOW)
        with pytest.raises(ValueError, match="还没回"):
            gate.decide(
                proposal_id, people[0], state=CommitmentState.PENDING, now=NOW
            )


def test_inviting_twice_does_not_reset_anyones_answer(engine: Engine) -> None:
    """运维重跑一次清算，不该把已经答应的人清回「还没回」。"""
    people = _members(3)
    proposal_id = _seed_proposal(engine, members=people)

    with campus_connection(engine, SIM) as conn:
        gate = ConfirmationGate(conn, SIM)
        gate.invite(proposal_id, now=NOW)
        gate.decide(proposal_id, people[0], state=CommitmentState.ACCEPTED, now=NOW)
        reopened = gate.invite(proposal_id, now=NOW + timedelta(hours=1))
        state = gate.status(proposal_id, now=NOW + timedelta(hours=1))

    assert reopened == 0
    assert people[0] not in state.waiting_on


def test_a_formed_event_stays_inside_its_tenant(engine: Engine) -> None:
    people = _members(2)
    proposal_id = _seed_proposal(engine, members=people)

    with campus_connection(engine, SIM) as conn:
        gate = ConfirmationGate(conn, SIM)
        gate.invite(proposal_id, now=NOW)
        for person in people:
            gate.decide(proposal_id, person, state=CommitmentState.ACCEPTED, now=NOW)

    with campus_connection(engine, "demo-campus") as conn:
        leaked = conn.execute(
            sa.text("SELECT count(*) FROM shared_events")
        ).scalar_one()

    assert leaked == 0
