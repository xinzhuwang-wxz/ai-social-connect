"""闭环：记录改变下一次成局证明。

**这一份是 M4 的判据。** 如果同一条需求在有已确认切面和没有时拿到的证明
一模一样，那么闭环只是看起来合上了。所以这里的核心用例不问"能不能召回"，
而问**差别具体是什么**——差出来的每一行都要能指回库里真实存在的行。

时钟用 `SimulatedClock` 快进两周，零 sleep：被替换的是时间的来源，
不是时间的语义。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Engine

from cofield.adapters.clock import FrozenClock, SimulatedClock
from cofield.adapters.persistence.consent import EnvelopeRepository
from cofield.adapters.persistence.engine import campus_connection
from cofield.adapters.persistence.events import EventRepository
from cofield.adapters.persistence.intents import IntentRepository
from cofield.adapters.persistence.memory import MemoryRepository
from cofield.adapters.persistence.schema import (
    evidence,
    memory_facets,
    principals,
    shared_events,
)
from cofield.domain.model.consent import (
    Audience,
    FieldGrant,
    MatchEnvelope,
    Purpose,
)
from cofield.domain.model.intent import IntentContent, IntentSignal, IntentState
from cofield.matching import proof as plain_proof
from cofield.matching.contracts import (
    CandidateGroup,
    EvidenceSource,
    FormationProof,
    Member,
    Requirement,
    StabilityVerdict,
)
from cofield.memory import loop
from cofield.memory.echo import ActionEcho
from cofield.memory.loop import SharedHistory

REAL = "demo-campus"
SIM = "simulation"

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
TWO_WEEKS = timedelta(days=14)
FREE = "1" * 21
VISIBLE = frozenset({"skills", "availability", "zone", "confirmed_events"})
REPO_ROOT = Path(__file__).resolve().parents[3]


# --- 装配 -------------------------------------------------------------------


def a_member(person_id: UUID, name: str, skill: str) -> Member:
    return Member(
        principal_id=person_id,
        display_name=name,
        skills=frozenset({skill}),
        availability=FREE,
        zone="南校区",
        confirmed_events=1,
    )


def a_case(
    people: Sequence[Member],
) -> tuple[CandidateGroup, Requirement, StabilityVerdict]:
    """**同一条需求。** 两次成局的输入逐字相同，包括 `intent_id`——
    否则"差别"可能只是因为换了一条需求。"""
    requirement = Requirement(
        intent_id=UUID("00000000-0000-4000-8000-000000000042"),
        requester=people[0],
        goal="再拍一支短片",
        needs=("拍摄", "剪辑"),
        team_min=3,
        team_max=4,
        # 定得足够远：两周之后离截止仍有余量，"快来不及了"那条不会跟着漂。
        deadline=NOW + timedelta(days=90),
        zone="南校区",
    )
    group = CandidateGroup(
        members=tuple(people),
        role_assignment={
            "剪辑": people[1].principal_id,
            "拍摄": people[2].principal_id,
        },
        common_slots=(9, 15),
        contributions=(),
        score=12.0,
    )
    verdict = StabilityVerdict(passed=True, defections=(), statement="不存在阻塞联盟")
    return group, requirement, verdict


def recall_at(
    engine: Engine, people: Sequence[Member], *, now: datetime, campus: str = REAL
) -> SharedHistory:
    """按当时的授权状态重新召回一次。

    `permitted` 不是测试硬塞的，是从这几个人**当时还生效**的匹配信封里
    算出来的——授权过期或撤销，这里立刻就空了。
    """
    with campus_connection(engine, campus) as conn:
        envelopes = EnvelopeRepository(conn, FrozenClock(now), campus)
        granted = [
            envelope
            for person in people
            for envelope in envelopes.list_active(person.principal_id)
        ]
        return loop.recall(
            MemoryRepository(conn, campus),
            member_ids=[m.principal_id for m in people],
            permitted=loop.permitted_facet_ids(granted, now=now),
        )


def a_proof(
    engine: Engine, people: Sequence[Member], *, now: datetime
) -> FormationProof:
    group, requirement, verdict = a_case(people)
    return loop.build(
        group,
        requirement,
        verdict,
        now=now,
        visible_fields=VISIBLE,
        history=recall_at(engine, people, now=now),
    )


def authorise(
    engine: Engine,
    *,
    principal_id: UUID,
    facet_ids: Sequence[UUID],
    now: datetime,
    ttl: timedelta = timedelta(days=30),
    campus: str = REAL,
) -> MatchEnvelope:
    """本人勾上"这次可以用我这几条经历"。

    授权挂在一条**真实的意图**上，不是凭空一个 id：切面的引用许可是
    "这一次可以用"，不是"从此以后都可以用"——库里那条外键正是这个意思。
    """
    intent = IntentSignal(
        id=uuid4(),
        principal_id=principal_id,
        state=IntentState.ACTIVE,
        raw_expression="想再拍一支短片，缺摄影和剪辑",
        content=IntentContent(goal="再拍一支短片"),
        created_at=now,
        expires_at=now + ttl,
    )
    envelope = MatchEnvelope(
        id=uuid4(),
        principal_id=principal_id,
        intent_id=intent.id,
        grants=(
            FieldGrant(
                field_name="offers",
                audience=Audience.CANDIDATES,
                purposes=frozenset({Purpose.FORMATION_PROOF}),
            ),
        ),
        created_at=now,
        expires_at=now + ttl,
        cited_facet_ids=tuple(facet_ids),
    )
    with campus_connection(engine, campus) as conn:
        IntentRepository(conn, FrozenClock(now), campus).save(intent)
        EnvelopeRepository(conn, FrozenClock(now), campus).save(envelope)
    return envelope


def they_finished(
    engine: Engine,
    members: Sequence[UUID],
    *,
    title: str,
    at: datetime,
    campus: str = REAL,
    completed: bool = True,
) -> UUID:
    with campus_connection(engine, campus) as conn:
        formed = EventRepository(conn, campus).form(
            proposal_id=uuid4(),
            action_kind="short_film",
            title=title,
            goal="拍一支 60 秒短片",
            steward_id=members[0],
            member_ids=tuple(members),
            role_assignment={},
            deadline=None,
            first_action=None,
            now=at,
        )
        if completed:
            conn.execute(
                sa.text("UPDATE shared_events SET state = 'completed' WHERE id = :i"),
                {"i": formed.event_id},
            )
    return formed.event_id


def a_confirmed_facet(
    engine: Engine,
    *,
    principal_id: UUID,
    text: str,
    now: datetime,
    event_id: UUID | None = None,
    campus: str = REAL,
) -> UUID:
    """本人写下一条并点头。

    这里刻意不走模型：切面怎么起草是 `test_echo` 的事，闭环关心的是
    **已确认的切面**改变了什么。少一层不确定，差别就归得清。
    """
    with campus_connection(engine, campus) as conn:
        repo = MemoryRepository(conn, campus)
        echo = ActionEcho(repo, composer=_NoComposer())
        facet = echo.write_own(
            principal_id=principal_id, text=text, now=now, event_id=event_id
        )
        echo.confirm(facet.id, by=principal_id, now=now)
    return facet.id


class _NoComposer:
    """这几个用例一次也不起草。

    传一个会抛异常的实现而不是 `None`，是为了让"这里其实偷偷调了模型"
    直接炸掉，而不是悄悄走进某个默认路径。
    """

    model = "none"

    def draft(self, kind: object, **kwargs: object) -> object:
        raise AssertionError("这些用例不该起草")


def texts(proof: FormationProof) -> list[str]:
    return [line.text for line in (*proof.satisfied, *proof.for_humans, *proof.uncertainties)]


def cast_of(seed_principal) -> tuple[UUID, UUID, UUID]:  # type: ignore[no-untyped-def]
    return (
        seed_principal(name="林知遥").id,
        seed_principal(name="周雨").id,
        seed_principal(name="陈牧").id,
    )


def people_of(cast: tuple[UUID, UUID, UUID]) -> tuple[Member, Member, Member]:
    return (
        a_member(cast[0], "林知遥", "写脚本"),
        a_member(cast[1], "周雨", "剪辑"),
        a_member(cast[2], "陈牧", "拍摄"),
    )


# --- M4 判据 ----------------------------------------------------------------


def test_two_weeks_later_the_same_need_gets_a_different_proof(
    engine: Engine,
    sim_clock: SimulatedClock,
    seed_principal,  # type: ignore[no-untyped-def]
) -> None:
    """**闭环合上的唯一判据。**

    同一批人、同一条需求、同一份候选组。中间发生的只有一件事：他们一起
    做完了《檐下》，本人逐项点了头，并勾上了"这次可以用"。两周之后
    再发起这条需求，成局证明必须**不一样**——差出来的正是那几行经历。

    时钟由 `SimulatedClock` 推进，测试里一次 sleep 都没有。
    """
    cast = cast_of(seed_principal)
    people = people_of(cast)

    # 零历史那一次。
    before = a_proof(engine, people, now=sim_clock.now())

    event_id = they_finished(engine, cast, title="檐下", at=sim_clock.now())
    facet_id = a_confirmed_facet(
        engine,
        principal_id=cast[1],
        text="剪过一支 60 秒短片",
        now=sim_clock.now(),
        event_id=event_id,
    )
    authorise(engine, principal_id=cast[1], facet_ids=[facet_id], now=sim_clock.now())

    later = sim_clock.advance(TWO_WEEKS)
    after = a_proof(engine, people, now=later)

    assert texts(after) != texts(before), "同一条需求拿到了同一份证明——闭环没合上"

    added = [t for t in texts(after) if t not in texts(before)]
    assert "你们上次一起完成过《檐下》。" in added
    assert "这是你们第 2 次一起做事。" in added
    assert "周雨剪过一支 60 秒短片" in added
    # 差别**只有**这三行：没有任何一条原有依据被改写或删掉。
    assert len(added) == 3
    assert [t for t in texts(before) if t not in texts(after)] == []


def test_at_one_instant_the_only_difference_is_what_was_confirmed(
    engine: Engine,
    sim_clock: SimulatedClock,
    seed_principal,  # type: ignore[no-untyped-def]
) -> None:
    """把时间这个变量也去掉：**同一时刻**，两份证明的差集恰好是历史那几行。

    上一条用例里 `now` 变过（两周），所以严格说差别有两个来源。这一条
    钉死时刻，剩下的唯一变量就是库里有没有已确认的切面。
    """
    cast = cast_of(seed_principal)
    people = people_of(cast)
    group, requirement, verdict = a_case(people)

    event_id = they_finished(engine, cast, title="檐下", at=sim_clock.now())
    facet_id = a_confirmed_facet(
        engine,
        principal_id=cast[1],
        text="剪过一支 60 秒短片",
        now=sim_clock.now(),
        event_id=event_id,
    )
    authorise(engine, principal_id=cast[1], facet_ids=[facet_id], now=sim_clock.now())

    at = sim_clock.advance(TWO_WEEKS)
    history = recall_at(engine, people, now=at)

    blank = loop.build(
        group, requirement, verdict, now=at, visible_fields=VISIBLE,
        history=SharedHistory(),
    )
    carried = loop.build(
        group, requirement, verdict, now=at, visible_fields=VISIBLE, history=history
    )

    assert set(texts(carried)) - set(texts(blank)) == {
        "你们上次一起完成过《檐下》。",
        "这是你们第 2 次一起做事。",
        "周雨剪过一支 60 秒短片",
    }
    # 零历史的那一份逐字等于不接历史的成局证明——没有历史不扣任何东西。
    plain = plain_proof.build(
        group, requirement, verdict, now=at, visible_fields=VISIBLE
    )
    assert blank == plain


def test_history_only_adds_it_never_reorders_or_removes(
    engine: Engine,
    sim_clock: SimulatedClock,
    seed_principal,  # type: ignore[no-untyped-def]
) -> None:
    """老用户的优势是**更可核验**，不是排得更前。

    历史只往后面接行：原有的每一条依据一字不改、次序不动，稳定性结论
    原样带出。如果历史能改动求解结果或删掉原有依据，它就成了一个隐性的
    社会信用分——而零历史的人首次成局会因此系统性吃亏。
    """
    cast = cast_of(seed_principal)
    people = people_of(cast)
    group, requirement, verdict = a_case(people)

    event_id = they_finished(engine, cast, title="檐下", at=sim_clock.now())
    facet_id = a_confirmed_facet(
        engine,
        principal_id=cast[1],
        text="剪过一支 60 秒短片",
        now=sim_clock.now(),
        event_id=event_id,
    )
    authorise(engine, principal_id=cast[1], facet_ids=[facet_id], now=sim_clock.now())

    at = sim_clock.advance(TWO_WEEKS)
    blank = loop.build(
        group, requirement, verdict, now=at, visible_fields=VISIBLE,
        history=SharedHistory(),
    )
    carried = loop.build(
        group, requirement, verdict, now=at, visible_fields=VISIBLE,
        history=recall_at(engine, people, now=at),
    )

    assert carried.satisfied[: len(blank.satisfied)] == blank.satisfied
    assert carried.for_humans == blank.for_humans
    assert carried.uncertainties == blank.uncertainties
    assert carried.stability is verdict
    assert carried.expires_at == blank.expires_at
    # 多出来的每一行都是"经历"这一类，不是新的一条求解结论。
    for line in carried.satisfied[len(blank.satisfied) :]:
        assert line.source is EvidenceSource.APPROVED_FACET


# --- 撤销与过期 -------------------------------------------------------------


def test_a_revoked_facet_is_gone_from_the_next_recall(
    engine: Engine,
    sim_clock: SimulatedClock,
    seed_principal,  # type: ignore[no-untyped-def]
) -> None:
    """撤销之后紧接着的这一次召回就已经读不到它了。

    机制不是"有个任务会去清理"，而是召回每次都重新读权威行——
    两者之间不存在任何可以变旧的副本。
    """
    cast = cast_of(seed_principal)
    people = people_of(cast)

    event_id = they_finished(engine, cast, title="檐下", at=sim_clock.now())
    facet_id = a_confirmed_facet(
        engine,
        principal_id=cast[1],
        text="剪过一支 60 秒短片",
        now=sim_clock.now(),
        event_id=event_id,
    )
    authorise(engine, principal_id=cast[1], facet_ids=[facet_id], now=sim_clock.now())

    at = sim_clock.advance(TWO_WEEKS)
    assert "周雨剪过一支 60 秒短片" in texts(a_proof(engine, people, now=at))

    with campus_connection(engine, REAL) as conn:
        MemoryRepository(conn, REAL).revoke(facet_id, by=cast[1], now=at)

    # 同一个时刻，没有推进时钟。
    after = a_proof(engine, people, now=at)
    assert "周雨剪过一支 60 秒短片" not in texts(after)
    # 但"你们一起做过这件事"还在：撤销的是这个人的一句话，
    # 不是那件事发生过这个事实。
    assert "你们上次一起完成过《檐下》。" in texts(after)


def test_an_expired_authorization_stops_the_recall(
    engine: Engine,
    sim_clock: SimulatedClock,
    seed_principal,  # type: ignore[no-untyped-def]
) -> None:
    """切面还在、还是已确认的，但这次授权过期了——它就引用不到。

    「已授权用于匹配、且未过期」是两个条件，缺一都不许说出口。
    """
    cast = cast_of(seed_principal)
    people = people_of(cast)

    event_id = they_finished(engine, cast, title="檐下", at=sim_clock.now())
    facet_id = a_confirmed_facet(
        engine,
        principal_id=cast[1],
        text="剪过一支 60 秒短片",
        now=sim_clock.now(),
        event_id=event_id,
    )
    envelope = authorise(
        engine,
        principal_id=cast[1],
        facet_ids=[facet_id],
        now=sim_clock.now(),
        ttl=timedelta(days=3),
    )

    still_valid = sim_clock.advance(timedelta(days=2))
    assert loop.permitted_facet_ids([envelope], now=still_valid) == frozenset({facet_id})
    assert "周雨剪过一支 60 秒短片" in texts(a_proof(engine, people, now=still_valid))

    expired = sim_clock.advance(TWO_WEEKS)
    assert loop.permitted_facet_ids([envelope], now=expired) == frozenset()
    assert "周雨剪过一支 60 秒短片" not in texts(a_proof(engine, people, now=expired))

    # 切面本身没有被动过：不能引用不等于被删除。
    with campus_connection(engine, REAL) as conn:
        state = conn.execute(
            sa.select(memory_facets.c.state).where(memory_facets.c.id == facet_id)
        ).scalar_one()
    assert state == "confirmed"


def test_a_facet_nobody_authorised_for_this_match_stays_out(
    engine: Engine,
    sim_clock: SimulatedClock,
    seed_principal,  # type: ignore[no-untyped-def]
) -> None:
    """已确认，但这次一条都没勾——默认拒绝，不是"忘了传就全放行"。"""
    cast = cast_of(seed_principal)
    people = people_of(cast)

    event_id = they_finished(engine, cast, title="檐下", at=sim_clock.now())
    a_confirmed_facet(
        engine,
        principal_id=cast[1],
        text="剪过一支 60 秒短片",
        now=sim_clock.now(),
        event_id=event_id,
    )
    # 有信封，但一条切面都没勾上：「只用这次说的话去配队」。
    authorise(engine, principal_id=cast[1], facet_ids=[], now=sim_clock.now())

    at = sim_clock.advance(TWO_WEEKS)
    history = recall_at(engine, people, now=at)
    assert history.facets == ()
    assert "周雨剪过一支 60 秒短片" not in texts(a_proof(engine, people, now=at))


def test_a_facet_of_someone_outside_the_group_never_shows_up(
    engine: Engine,
    sim_clock: SimulatedClock,
    seed_principal,  # type: ignore[no-untyped-def]
) -> None:
    """不在这个组里的人的经历，即使被授权了也不出现在这份证明里。

    默认拒绝要在每一道门上都成立，不是只在第一道门上成立——所以
    `history_lines` 自己也按组员名单再滤一道。
    """
    cast = cast_of(seed_principal)
    people = people_of(cast)
    outsider = seed_principal(name="苏晚").id

    facet_id = a_confirmed_facet(
        engine, principal_id=outsider, text="写过一份分镜", now=sim_clock.now()
    )
    authorise(engine, principal_id=outsider, facet_ids=[facet_id], now=sim_clock.now())

    at = sim_clock.advance(TWO_WEEKS)
    # 就算调用方把外人的切面硬塞进来，也写不出那一行。
    with campus_connection(engine, REAL) as conn:
        smuggled = MemoryRepository(conn, REAL).citable(
            [outsider], permitted=frozenset({facet_id})
        )
    assert len(smuggled) == 1

    group, requirement, verdict = a_case(people)
    forced = loop.build(
        group,
        requirement,
        verdict,
        now=at,
        visible_fields=VISIBLE,
        history=SharedHistory(facets=tuple(smuggled)),
    )
    assert "苏晚" not in "\n".join(texts(forced))
    assert "写过一份分镜" not in "\n".join(texts(forced))


def test_another_campus_history_never_leaks_in(
    engine: Engine,
    sim_clock: SimulatedClock,
    seed_principal,  # type: ignore[no-untyped-def]
) -> None:
    """合成校园里那批人的经历，真实校园的召回里一条都读不到。"""
    others = (
        seed_principal(campus=SIM, name="合成-0001", synthetic=True).id,
        seed_principal(campus=SIM, name="合成-0002", synthetic=True).id,
        seed_principal(campus=SIM, name="合成-0003", synthetic=True).id,
    )
    they_finished(engine, others, title="他们的片子", at=sim_clock.now(), campus=SIM)
    theirs = a_confirmed_facet(
        engine,
        principal_id=others[1],
        text="剪过一支短片",
        now=sim_clock.now(),
        campus=SIM,
    )
    authorise(
        engine,
        principal_id=others[1],
        facet_ids=[theirs],
        now=sim_clock.now(),
        campus=SIM,
    )

    at = sim_clock.advance(TWO_WEEKS)
    intruders = tuple(
        a_member(pid, f"合成-{i}", "剪辑") for i, pid in enumerate(others)
    )
    # 从真实校园问同一批人：切面、共同经历，一样都读不到。
    from_real = recall_at(engine, intruders, now=at, campus=REAL)
    assert from_real.facets == ()
    assert from_real.together == ()

    from_sim = recall_at(engine, intruders, now=at, campus=SIM)
    assert len(from_sim.facets) == 1
    assert len(from_sim.together) == 1


# --- 关系强度是数出来的 -----------------------------------------------------


def test_how_many_times_they_worked_together_is_counted_from_the_hyperedge(
    engine: Engine,
    sim_clock: SimulatedClock,
    seed_principal,  # type: ignore[no-untyped-def]
) -> None:
    """「第 3 次」是从超边上数出来的，不是某处维护的一个计数器。

    三件事各自应该被怎么算：两件三个人一起做完的算数；一件只有两个人
    参加的不算（超边不能拆成两两关系去数）；一件还没做完的也不算。
    """
    cast = cast_of(seed_principal)
    people = people_of(cast)

    they_finished(engine, cast, title="檐下", at=sim_clock.now())
    they_finished(engine, cast, title="早八", at=sim_clock.now() + timedelta(days=1))
    they_finished(engine, cast[:2], title="只有两个人的那次", at=sim_clock.now())
    they_finished(
        engine, cast, title="还在做的那件", at=sim_clock.now(), completed=False
    )

    at = sim_clock.advance(TWO_WEEKS)
    history = recall_at(engine, people, now=at)

    assert [t.title for t in history.together] == ["早八", "檐下"]
    page = texts(a_proof(engine, people, now=at))
    assert "你们上次一起完成过《早八》。" in page
    assert "这是你们第 3 次一起做事。" in page
    assert "只有两个人的那次" not in "\n".join(page)
    assert "还在做的那件" not in "\n".join(page)


def test_nowhere_in_the_database_is_there_a_stored_closeness(engine: Engine) -> None:
    """库里不存在任何一列叫熟悉度、亲密度或好友分。

    不变量 7：关系图谱是共同事件的可重建投影，不是平台对"熟不熟"的
    主观判定。一旦它变成一个被维护的字段，"可重建"就成了假话——
    而这条可以直接查表结构，不用靠 review 时凭感觉抓。
    """
    forbidden = (
        "familiar", "closeness", "intimacy", "affinity", "friendship",
        "friend_", "bond", "rapport", "chemistry", "compat",
    )
    with campus_connection(engine, REAL) as conn:
        columns = conn.execute(
            sa.text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public'"
            )
        ).all()
    assert len(columns) > 50, "一列都没读到，这条检查其实什么都没验证"
    for table_name, column_name in columns:
        for word in forbidden:
            assert word not in column_name.lower(), (
                f"{table_name}.{column_name} 看起来是一个被维护的熟悉度"
            )


# --- 每一行都指得着 ---------------------------------------------------------


def test_every_added_citation_points_at_a_row_that_exists(
    engine: Engine,
    sim_clock: SimulatedClock,
    seed_principal,  # type: ignore[no-untyped-def]
) -> None:
    """多出来的每一行都要能追到具体的事件、切面与素材那几行。

    追不到就是编的。这条查的是数据库里真有那一行，不是"字符串格式对"。
    """
    cast = cast_of(seed_principal)
    people = people_of(cast)

    event_id = they_finished(engine, cast, title="檐下", at=sim_clock.now())
    exhibit_id = uuid4()
    with campus_connection(engine, REAL) as conn:
        conn.execute(
            sa.insert(evidence).values(
                id=exhibit_id,
                campus_id=REAL,
                event_id=event_id,
                kind="artifact",
                title="成片 檐下.mp4",
                uploaded_by=cast[1],
                created_at=sim_clock.now(),
            )
        )
    with campus_connection(engine, REAL) as conn:
        repo = MemoryRepository(conn, REAL)
        echo = ActionEcho(repo, composer=_NoComposer())
        facet = echo.write_own(
            principal_id=cast[1],
            text="剪过一支 60 秒短片",
            now=sim_clock.now(),
            event_id=event_id,
            evidence_ids=(exhibit_id,),
        )
        echo.confirm(facet.id, by=cast[1], now=sim_clock.now())
    authorise(engine, principal_id=cast[1], facet_ids=[facet.id], now=sim_clock.now())

    at = sim_clock.advance(TWO_WEEKS)
    history = recall_at(engine, people, now=at)
    lines = loop.history_lines(
        history, member_ids=frozenset(m.principal_id for m in people)
    )

    assert lines
    checked = 0
    for line in lines:
        assert line.refers_to, "多出来的每一行都要指得着"
        for token in line.refers_to:
            checked += 1
            assert _row_exists(engine, token), f"{token} 指向库里不存在的行：{line.text}"
    assert checked >= 4


def _row_exists(engine: Engine, token: str) -> bool:
    """`refers_to` 里的一个引用，在库里到底有没有对应的那一行。"""
    kind, _, raw = token.partition(":")
    tables = {
        "event": (shared_events, shared_events.c.id),
        "facet": (memory_facets, memory_facets.c.id),
        "evidence": (evidence, evidence.c.id),
        "principal": (principals, principals.c.id),
    }
    if kind not in tables:
        return False
    table, key = tables[kind]
    with campus_connection(engine, REAL) as conn:
        found = conn.execute(
            sa.select(sa.func.count()).select_from(table).where(key == UUID(raw))
        ).scalar_one()
    return bool(found)


# --- 用户读到的每一个字 -----------------------------------------------------


def domain_terms() -> frozenset[str]:
    text = (REPO_ROOT / "CONTEXT.md").read_text(encoding="utf-8")
    terms = frozenset(re.findall(r"^\*\*([^*（]+)（", text, flags=re.MULTILINE))
    assert len(terms) > 20, "没读到术语表，黑名单是空的"
    return terms


STEMS = (
    "意图", "主体", "切面", "共域", "求解", "约束", "提案", "证明", "授权",
    "撮合", "稳定", "代理", "智能体", "凭证", "信封", "回声", "素材", "超边",
    "TTL",
)
SCORES = ("%", "百分比", "匹配度", "评分", "得分", "分数", "契合度", "熟悉度", "亲密度")


def test_the_lines_history_adds_carry_no_domain_vocabulary(
    engine: Engine,
    sim_clock: SimulatedClock,
    seed_principal,  # type: ignore[no-untyped-def]
) -> None:
    """「你们上次一起完成过《檐下》」要读起来像一句人话。

    多出来的这几行是最容易泄漏术语的地方——它们直接来自治理层的概念。
    """
    cast = cast_of(seed_principal)
    people = people_of(cast)

    event_id = they_finished(engine, cast, title="檐下", at=sim_clock.now())
    facet_id = a_confirmed_facet(
        engine,
        principal_id=cast[1],
        text="剪过一支 60 秒短片",
        now=sim_clock.now(),
        event_id=event_id,
    )
    authorise(engine, principal_id=cast[1], facet_ids=[facet_id], now=sim_clock.now())

    at = sim_clock.advance(TWO_WEEKS)
    proof = a_proof(engine, people, now=at)

    banned = (*domain_terms(), *STEMS, *SCORES)
    for line in (*proof.satisfied, *proof.for_humans, *proof.uncertainties):
        for word in banned:
            assert word not in line.text, f"{word!r} 出现在了给人看的句子里：{line.text}"
    assert "12.0" not in "\n".join(texts(proof)), "总分泄漏到了界面上"


def test_what_was_cited_stays_in_the_record_even_after_it_is_revoked(
    engine: Engine,
    sim_clock: SimulatedClock,
    seed_principal,  # type: ignore[no-untyped-def]
) -> None:
    """撤销阻止的是**新的**使用，不是抹掉已经发生过的事。

    所以引用了哪几条要写进 `notes`——那一面是给申诉、导出与运营看的，
    用领域词汇是合法的（07 §2.1 例外一）。日常简化，追责时完整。
    """
    cast = cast_of(seed_principal)
    people = people_of(cast)

    event_id = they_finished(engine, cast, title="檐下", at=sim_clock.now())
    facet_id = a_confirmed_facet(
        engine,
        principal_id=cast[1],
        text="剪过一支 60 秒短片",
        now=sim_clock.now(),
        event_id=event_id,
    )
    authorise(engine, principal_id=cast[1], facet_ids=[facet_id], now=sim_clock.now())

    at = sim_clock.advance(TWO_WEEKS)
    issued = a_proof(engine, people, now=at)
    assert any(str(facet_id) in note for note in issued.notes)
    assert any("共同完成过的事件数：1" in note for note in issued.notes)

    with campus_connection(engine, REAL) as conn:
        MemoryRepository(conn, REAL).revoke(facet_id, by=cast[1], now=at)

    reissued = a_proof(engine, people, now=at)
    assert not any(str(facet_id) in note for note in reissued.notes)
    # 已经发出去的那一份没有被追改——它带着有效期，会自然过期。
    assert any(str(facet_id) in note for note in issued.notes)


def test_the_screen_never_shows_a_line_without_something_to_point_at(
    engine: Engine,
    sim_clock: SimulatedClock,
    seed_principal,  # type: ignore[no-untyped-def]
) -> None:
    """零历史时这一层一行都不加，也一行都不减。

    冷启动的人拿到的是一份完整的成局证明，只是没有"上次一起做过什么"。
    """
    cast = cast_of(seed_principal)
    people = people_of(cast)
    group, requirement, verdict = a_case(people)

    at = sim_clock.now()
    history = recall_at(engine, people, now=at)
    assert history.is_empty

    carried = loop.build(
        group, requirement, verdict, now=at, visible_fields=VISIBLE, history=history
    )
    plain = plain_proof.build(
        group, requirement, verdict, now=at, visible_fields=VISIBLE
    )
    assert carried == plain
    assert carried.satisfied and carried.for_humans
