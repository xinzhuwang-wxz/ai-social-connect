"""行动回声：事实变成一条本人点过头、随时收得回的记忆。

断言的不是"能生成草稿"，而是**没点过头的那条确实进不去、收回之后下一次
立刻就没有了**。两条都用可查询的事实来说——查数据库里那一行现在是什么状态，
查重新生成的证明里还有没有那句话——不是断言"我们没写那行代码"。

真 PostgreSQL，真迁移，真模型的真输出（磁带回放）。
本地重录：`COFIELD_LLM_MODE=record uv run pytest tests/test_echo.py`（要 `ARK_API_KEY`）。
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from cofield.adapters.llm import Cassette, LiteLLMComposer
from cofield.adapters.persistence.engine import campus_connection
from cofield.adapters.persistence.events import EventRepository
from cofield.adapters.persistence.memory import (
    EvidenceItem,
    FacetState,
    MemoryRepository,
)
from cofield.adapters.persistence.schema import evidence, memory_facets
from cofield.matching.contracts import (
    CandidateGroup,
    FormationProof,
    Member,
    ProofLine,
    Requirement,
    StabilityVerdict,
)
from cofield.memory import loop
from cofield.memory.echo import (
    AGENT_DRAFT_HINT,
    HEADLINE,
    MY_RECORD,
    REVOKE_LABEL,
    ActionEcho,
    NothingToConfirm,
    NotYours,
)

REAL = "demo-campus"
SIM = "simulation"

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
CASSETTES = Path(__file__).resolve().parent / "cassettes"
REPO_ROOT = Path(__file__).resolve().parents[3]

#: 这次一起做的事，以及它留下的三件东西。
#:
#: 磁带的键里含事实原文，所以**改动下面任何一个字都会导致回放未命中**——
#: 那不是脆弱，那正是我们要的：换了输入就该重新录，不该沿用旧输出。
FILM = "檐下"
EXHIBITS: tuple[tuple[str, str, str | None, int], ...] = (
    ("photo", "拍摄当天的现场照", None, 0),
    ("note", "分镜脚本第 3 版", None, 0),
    ("artifact", "成片 檐下.mp4", "60 秒，三个镜头", 1),
)

FREE = "1" * 21
VISIBLE = frozenset({"skills", "availability", "zone", "confirmed_events"})


@pytest.fixture
def composer() -> Cassette:
    """默认回放。录制模式由环境变量切换，不由测试代码切换——
    测试里能切到 record，就等于 CI 里也可能悄悄开始花钱。"""
    return Cassette(LiteLLMComposer(), directory=CASSETTES)


# --- 装配 -------------------------------------------------------------------


@contextmanager
def echo_at(
    engine: Engine, composer: Cassette, campus: str = REAL
) -> Iterator[tuple[ActionEcho, MemoryRepository]]:
    with campus_connection(engine, campus) as conn:
        repo = MemoryRepository(conn, campus)
        yield ActionEcho(repo, composer=composer), repo


def a_completed_event(
    engine: Engine, members: Sequence[UUID], *, campus: str = REAL, title: str = FILM
) -> UUID:
    """一件真的做完了的事。走 `EventRepository`，不是直接塞行——
    共同事件只有一个诞生入口，测试也不该给自己开第二个。"""
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
            now=NOW,
        )
        conn.execute(
            sa.text("UPDATE shared_events SET state = 'completed' WHERE id = :i"),
            {"i": formed.event_id},
        )
    return formed.event_id


def exhibits_of(
    engine: Engine,
    event_id: UUID,
    members: Sequence[UUID],
    *,
    campus: str = REAL,
    exhibits: tuple[tuple[str, str, str | None, int], ...] = EXHIBITS,
) -> tuple[UUID, ...]:
    ids: list[UUID] = []
    with campus_connection(engine, campus) as conn:
        repo = MemoryRepository(conn, campus)
        for offset, (kind, title, body, who) in enumerate(exhibits):
            item = EvidenceItem(
                id=uuid4(),
                event_id=event_id,
                kind=kind,
                title=title,
                body=body,
                uploaded_by=members[who],
                created_at=NOW + timedelta(minutes=offset),
            )
            repo.add_evidence(item)
            ids.append(item.id)
    return tuple(ids)


def a_case(people: Sequence[Member]) -> tuple[CandidateGroup, Requirement, StabilityVerdict]:
    """一次成局的输入。截止定得远，免得"快来不及了"那条跟着时间漂。"""
    requirement = Requirement(
        intent_id=uuid4(),
        requester=people[0],
        goal="再拍一支短片",
        needs=("拍摄", "剪辑"),
        team_min=3,
        team_max=4,
        deadline=NOW + timedelta(days=60),
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


def a_member(person_id: UUID, name: str, skill: str) -> Member:
    return Member(
        principal_id=person_id,
        display_name=name,
        skills=frozenset({skill}),
        availability=FREE,
        zone="南校区",
        confirmed_events=1,
    )


def lines_of(proof: FormationProof) -> tuple[ProofLine, ...]:
    return (*proof.satisfied, *proof.for_humans, *proof.uncertainties)


def page_of(proof: FormationProof) -> str:
    return "\n".join(line.text for line in lines_of(proof))


def a_proof(
    engine: Engine,
    people: Sequence[Member],
    *,
    permitted: frozenset[UUID],
    now: datetime = NOW,
) -> FormationProof:
    """重新生成一份证明。每次都重新 `recall`——这正是被测的东西。"""
    group, requirement, verdict = a_case(people)
    with campus_connection(engine, REAL) as conn:
        history = loop.recall(
            MemoryRepository(conn, REAL),
            member_ids=[m.principal_id for m in people],
            permitted=permitted,
        )
    return loop.build(
        group,
        requirement,
        verdict,
        now=now,
        visible_fields=VISIBLE,
        history=history,
    )


@pytest.fixture
def cast(seed_principal) -> tuple[UUID, UUID, UUID]:  # type: ignore[no-untyped-def]
    """发起人、剪辑、摄影。名字来自 07 的示例，不是随机串——
    读断言的人要能一眼看出说的是谁。"""
    return (
        seed_principal(name="林知遥").id,
        seed_principal(name="周雨").id,
        seed_principal(name="陈牧").id,
    )


# --- 这一屏打开时看到的是证据 -----------------------------------------------


def test_the_screen_opens_with_evidence_not_an_empty_box(
    engine: Engine, composer: Cassette, cast: tuple[UUID, UUID, UUID]
) -> None:
    """事结束的那一刻没人想写小作文。给空框，多数人会跳过。"""
    event_id = a_completed_event(engine, cast)
    exhibit_ids = exhibits_of(engine, event_id, cast)

    with echo_at(engine, composer) as (echo, _):
        gathered = echo.gather(event_id)
        drafts = echo.draft_for(event_id=event_id, principal_id=cast[1], now=NOW)

    assert [e.id for e in gathered] == list(exhibit_ids), "证据没有按放上来的先后出现"
    assert len(drafts) == 1
    # 草稿的每一句都写自这些事实，用户点开能逐条对照。
    assert drafts[0].grounded_in[0] == f"这次一起做的是《{FILM}》"
    assert "他自己放上来的：成片 檐下.mp4（60 秒，三个镜头）" in drafts[0].grounded_in
    assert drafts[0].facet.text.strip()


def test_a_draft_points_back_at_the_evidence_it_came_from(
    engine: Engine, composer: Cassette, cast: tuple[UUID, UUID, UUID]
) -> None:
    """说不出来源的一条记忆，本人无从判断该不该留着它。

    所以断言不止是"`evidence_ids` 非空"——每个 id 都要在证据表里
    真查得到那一行。
    """
    event_id = a_completed_event(engine, cast)
    exhibit_ids = exhibits_of(engine, event_id, cast)

    with echo_at(engine, composer) as (echo, _):
        drafts = echo.draft_for(event_id=event_id, principal_id=cast[1], now=NOW)
    facet = drafts[0].facet

    assert facet.event_id == event_id
    assert set(facet.evidence_ids) == set(exhibit_ids)
    with campus_connection(engine, REAL) as conn:
        found = conn.execute(
            sa.select(evidence.c.id).where(evidence.c.id.in_(list(facet.evidence_ids)))
        ).scalars().all()
    assert set(found) == set(exhibit_ids), "切面指向了证据表里不存在的行"


def test_a_guess_and_a_person_are_told_apart_in_the_data_not_only_on_screen(
    engine: Engine, composer: Cassette, cast: tuple[UUID, UUID, UUID]
) -> None:
    """AI 草稿与人工内容必须在**数据里**分得开。

    只在界面上加个角标，换一个前端就没了；而"这句话是谁写的"是申诉时
    要查得出来的事。
    """
    event_id = a_completed_event(engine, cast)
    exhibits_of(engine, event_id, cast)

    with echo_at(engine, composer) as (echo, repo):
        guessed = echo.draft_for(event_id=event_id, principal_id=cast[1], now=NOW)[0]
        mine = echo.write_own(
            principal_id=cast[1], text="剪过一支 60 秒短片", now=NOW, event_id=event_id
        )
        rows = {
            f.id: f for f in repo.for_principal(cast[1])
        }

    assert guessed.hint == AGENT_DRAFT_HINT
    assert rows[guessed.facet.id].drafted_by_agent is True
    assert rows[mine.id].drafted_by_agent is False
    # 两条都还只是草稿——本人写的那条也一样，通往"算数"的路只有一条。
    assert rows[guessed.facet.id].state is FacetState.DRAFT
    assert rows[mine.id].state is FacetState.DRAFT


# --- 只有本人能点头 ---------------------------------------------------------


def test_nobody_can_endorse_a_facet_on_somebody_elses_behalf(
    engine: Engine, composer: Cassette, cast: tuple[UUID, UUID, UUID]
) -> None:
    """描述个人能力的切面只有本人能确认。

    被拒之后那一行必须**原封不动**：如果它悄悄变成了 confirmed，
    这条守卫就只是抛了个异常而已。
    """
    event_id = a_completed_event(engine, cast)
    exhibits_of(engine, event_id, cast)

    with echo_at(engine, composer) as (echo, _):
        facet = echo.draft_for(event_id=event_id, principal_id=cast[1], now=NOW)[0].facet

    with echo_at(engine, composer) as (echo, _):
        with pytest.raises(NotYours):
            echo.confirm(facet.id, by=cast[0], now=NOW)
        with pytest.raises(NotYours):
            echo.revoke(facet.id, by=cast[0], now=NOW)

    with campus_connection(engine, REAL) as conn:
        row = conn.execute(
            sa.select(memory_facets.c.state, memory_facets.c.confirmed_at).where(
                memory_facets.c.id == facet.id
            )
        ).one()
    assert row.state == "draft"
    assert row.confirmed_at is None


# --- 未确认的进不了任何证明 -------------------------------------------------


def test_an_unconfirmed_facet_never_reaches_any_proof(
    engine: Engine, composer: Cassette, cast: tuple[UUID, UUID, UUID]
) -> None:
    """**即使本次匹配明确授权引用它**，没点过头的那条也一个字都不出现。

    先证明这条守卫是活的：同一条切面在本人点头之后确实写得出来。
    否则这个用例可能只是因为代码根本没写那一行而通过。
    """
    event_id = a_completed_event(engine, cast)
    exhibits_of(engine, event_id, cast)
    people = (
        a_member(cast[0], "林知遥", "写脚本"),
        a_member(cast[1], "周雨", "剪辑"),
        a_member(cast[2], "陈牧", "拍摄"),
    )

    with echo_at(engine, composer) as (echo, _):
        facet = echo.draft_for(event_id=event_id, principal_id=cast[1], now=NOW)[0].facet
    permitted = frozenset({facet.id})

    while_draft = a_proof(engine, people, permitted=permitted)
    assert facet.text not in page_of(while_draft)
    assert not any(
        f"facet:{facet.id}" in line.refers_to for line in lines_of(while_draft)
    )

    with echo_at(engine, composer) as (echo, _):
        echo.confirm(facet.id, by=cast[1], now=NOW)

    after = a_proof(engine, people, permitted=permitted)
    assert facet.text in page_of(after), "本人点头之后仍然写不出来，这条守卫测不到东西"
    assert f"周雨{facet.text}" in page_of(after)


# --- 撤销即时生效 -----------------------------------------------------------


def test_revoking_takes_effect_on_the_very_next_proof(
    engine: Engine, composer: Cassette, cast: tuple[UUID, UUID, UUID]
) -> None:
    """收回之后**紧接着**重新生成的那份证明里，那句话就不在了。

    时钟一格都没有走：如果它需要等一个清理任务、一次缓存过期或者一次
    重建索引，这个用例就会失败——而那正是"标记为已删除但还在用"的样子。
    """
    event_id = a_completed_event(engine, cast)
    exhibits_of(engine, event_id, cast)
    people = (
        a_member(cast[0], "林知遥", "写脚本"),
        a_member(cast[1], "周雨", "剪辑"),
        a_member(cast[2], "陈牧", "拍摄"),
    )

    with echo_at(engine, composer) as (echo, _):
        facet = echo.draft_for(event_id=event_id, principal_id=cast[1], now=NOW)[0].facet
        echo.confirm(facet.id, by=cast[1], now=NOW)
    permitted = frozenset({facet.id})

    assert facet.text in page_of(a_proof(engine, people, permitted=permitted, now=NOW))

    with echo_at(engine, composer) as (echo, _):
        echo.revoke(facet.id, by=cast[1], now=NOW)

    # 同一个 NOW。没有 sleep，没有推进时钟。
    after = a_proof(engine, people, permitted=permitted, now=NOW)
    assert facet.text not in page_of(after)
    assert not any(f"facet:{facet.id}" in line.refers_to for line in lines_of(after))

    # 可查询的事实：权威行上再也没有"已确认"这个状态了。
    with campus_connection(engine, REAL) as conn:
        still_confirmed = conn.execute(
            sa.select(sa.func.count())
            .select_from(memory_facets)
            .where(memory_facets.c.id == facet.id)
            .where(memory_facets.c.state == "confirmed")
        ).scalar_one()
        revoked_at = conn.execute(
            sa.select(memory_facets.c.revoked_at).where(memory_facets.c.id == facet.id)
        ).scalar_one()
    assert still_confirmed == 0
    assert revoked_at == NOW


def test_a_revoked_facet_has_no_way_back(
    engine: Engine, composer: Cassette, cast: tuple[UUID, UUID, UUID]
) -> None:
    """收回就是收回。留一条"再确认一次"的路，撤销就退化成"暂时不用"。"""
    event_id = a_completed_event(engine, cast)
    exhibits_of(engine, event_id, cast)

    with echo_at(engine, composer) as (echo, _):
        facet = echo.draft_for(event_id=event_id, principal_id=cast[1], now=NOW)[0].facet
        echo.confirm(facet.id, by=cast[1], now=NOW)
        echo.revoke(facet.id, by=cast[1], now=NOW)

    with echo_at(engine, composer) as (echo, repo):
        with pytest.raises(NothingToConfirm):
            echo.confirm(facet.id, by=cast[1], now=NOW + timedelta(days=1))
        current = repo.get_facet(facet.id)

    assert current is not None
    assert current.state is FacetState.REVOKED
    assert current.citable is False


def test_a_person_still_sees_what_they_revoked(
    engine: Engine, composer: Cassette, cast: tuple[UUID, UUID, UUID]
) -> None:
    """「我的经历」要给出完整的一份：猜过什么、点过什么、收回过什么。

    只给已确认的那部分，"系统记住了什么"这个问题就永远答不完整。
    """
    event_id = a_completed_event(engine, cast)
    exhibits_of(engine, event_id, cast)

    with echo_at(engine, composer) as (echo, _):
        guessed = echo.draft_for(event_id=event_id, principal_id=cast[1], now=NOW)[0].facet
        kept = echo.write_own(principal_id=cast[1], text="拍过一次夜戏", now=NOW)
        echo.confirm(kept.id, by=cast[1], now=NOW)
        echo.revoke(guessed.id, by=cast[1], now=NOW)
        mine = echo.my_record(cast[1])

    states = {f.id: f.state for f in mine}
    assert states[guessed.id] is FacetState.REVOKED
    assert states[kept.id] is FacetState.CONFIRMED


# --- 抽不出来不是故障 -------------------------------------------------------


def test_when_the_model_cannot_write_a_person_still_can(
    engine: Engine, composer: Cassette, cast: tuple[UUID, UUID, UUID]
) -> None:
    """起草服务不可用时，这一屏降级但不消失。

    用的是回放未命中——一次真的"外部服务给不出结果"，不是给我们自己的
    某一层套一个假实现。红线的例外只有这一处，而它正是这一处。
    """
    if composer.mode != "replay":
        pytest.skip("这条只在回放模式下有意义")

    event_id = a_completed_event(engine, cast, title="没有录过的一件事")
    exhibits_of(
        engine,
        event_id,
        cast,
        exhibits=(("note", "一件从来没有被录过的证据", None, 1),),
    )
    people = (
        a_member(cast[0], "林知遥", "写脚本"),
        a_member(cast[1], "周雨", "剪辑"),
        a_member(cast[2], "陈牧", "拍摄"),
    )

    with echo_at(engine, composer) as (echo, _):
        assert echo.draft_for(event_id=event_id, principal_id=cast[1], now=NOW) == ()
        assert echo.recap(event_id) is None
        # 抽不出草稿不影响本人手写一条，也不影响它进入下一次成局。
        mine = echo.write_own(
            principal_id=cast[1], text="剪过一支 60 秒短片", now=NOW, event_id=event_id
        )
        echo.confirm(mine.id, by=cast[1], now=NOW)

    page = page_of(a_proof(engine, people, permitted=frozenset({mine.id})))
    assert "周雨剪过一支 60 秒短片" in page


# --- 只存事实，不存评价 -----------------------------------------------------


def test_neither_table_has_anywhere_to_put_a_score(engine: Engine) -> None:
    """一旦开始存"这次谁表现好"，它就变成打分系统，
    而打分系统会让人不敢参加自己不擅长的事。

    这条查的是**表结构**：没有一列能装下一个分数。"没实现"会被后来的人
    补上，"没有位置"不会。
    """
    scoring = ("score", "rating", "rank", "grade", "star", "point", "level",
               "reputation", "credit", "trust", "quality", "performance")
    with campus_connection(engine, REAL) as conn:
        columns = conn.execute(
            sa.text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND table_name IN ('evidence', 'memory_facets')"
            )
        ).all()
    assert columns, "一列都没读到，这条检查其实什么都没验证"
    for table_name, column_name in columns:
        for word in scoring:
            assert word not in column_name.lower(), (
                f"{table_name}.{column_name} 看起来能装下一个分数"
            )


# --- 跨租户 -----------------------------------------------------------------


def test_another_campus_reads_none_of_this(
    engine: Engine, composer: Cassette, seed_principal
) -> None:  # type: ignore[no-untyped-def]
    """知道对方的主键也读不到。隔离不依赖 id 不可猜。"""
    stranger = seed_principal(campus=SIM, name="合成-0007", synthetic=True).id
    with campus_connection(engine, SIM) as conn:
        repo = MemoryRepository(conn, SIM)
        echo = ActionEcho(repo, composer=composer)
        theirs = echo.write_own(principal_id=stranger, text="剪过一支短片", now=NOW)
        echo.confirm(theirs.id, by=stranger, now=NOW)

    with campus_connection(engine, REAL) as conn:
        here = MemoryRepository(conn, REAL)
        assert here.get_facet(theirs.id) is None
        assert here.for_principal(stranger) == []
        assert here.citable([stranger], permitted=frozenset({theirs.id})) == []

    with campus_connection(engine, SIM) as conn:
        there = MemoryRepository(conn, SIM)
        assert len(there.citable([stranger], permitted=frozenset({theirs.id}))) == 1


# --- 用户读到的每一个字 -----------------------------------------------------


def domain_terms() -> frozenset[str]:
    """黑名单直接从 CONTEXT.md 的术语表生成——07 §2.1 就是这么要求的。

    手抄一份清单会跟着文档漂移。读原文的代价是路径写错时测试会静默通过，
    所以下面那条数量断言不是保险，是这个做法能成立的前提。
    """
    text = (REPO_ROOT / "CONTEXT.md").read_text(encoding="utf-8")
    terms = frozenset(re.findall(r"^\*\*([^*（]+)（", text, flags=re.MULTILINE))
    assert len(terms) > 20, "没读到术语表，黑名单是空的"
    return terms


STEMS = (
    "意图", "主体", "切面", "共域", "求解", "约束", "提案", "证明", "授权",
    "撮合", "稳定", "代理", "智能体", "凭证", "信封", "回声", "素材", "草稿",
    "确认状态", "TTL",
)
SCORES = ("%", "百分比", "匹配度", "评分", "得分", "分数", "契合度", "熟悉度", "亲密度")


def test_nothing_a_person_reads_uses_the_vocabulary_of_the_code(
    engine: Engine, composer: Cassette, cast: tuple[UUID, UUID, UUID]
) -> None:
    """这一屏上的每一个字都要过这一关——包括模型写出来的那几句。

    术语泄漏是这个产品最大的落地风险，而它可被机器检查，就不该靠 review
    时凭感觉抓。模型的输出同样在检查范围内：它写的东西是直接给学生看的。
    """
    event_id = a_completed_event(engine, cast)
    exhibits_of(engine, event_id, cast)
    people = (
        a_member(cast[0], "林知遥", "写脚本"),
        a_member(cast[1], "周雨", "剪辑"),
        a_member(cast[2], "陈牧", "拍摄"),
    )

    with echo_at(engine, composer) as (echo, _):
        facet = echo.draft_for(event_id=event_id, principal_id=cast[1], now=NOW)[0].facet
        recap = echo.recap(event_id)
        echo.confirm(facet.id, by=cast[1], now=NOW)

    assert recap is not None
    proof = a_proof(engine, people, permitted=frozenset({facet.id}))
    on_screen = [
        HEADLINE,
        MY_RECORD,
        AGENT_DRAFT_HINT,
        REVOKE_LABEL,
        facet.text,
        recap.text,
        *(line.text for line in lines_of(proof)),
    ]

    banned = (*domain_terms(), *STEMS, *SCORES)
    for sentence in on_screen:
        for word in banned:
            assert word not in sentence, f"{word!r} 出现在了给人看的句子里：{sentence}"


def test_the_words_on_screen_are_the_ones_the_language_map_prescribes() -> None:
    """07 §2 与 §5 定死了这几处的说法。写死在常量里，改文案要改一处。"""
    assert HEADLINE == "这次留下了什么"
    assert MY_RECORD == "我的经历"
    # 权利必须顺手，不能庄严：两个字的按钮，不是一份申请表。
    assert REVOKE_LABEL == "撤销"
    assert len(REVOKE_LABEL) <= 4
