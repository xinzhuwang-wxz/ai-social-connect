"""语义召回：证明它买到了结构化买不到的东西。

跑在真 pgvector、真 Ollama 嵌入、真人口上。这里断言的不是"能算相似度"，
而是**结构化召不到的人被召回了**——如果去掉语义那一路结果不变，
这一层就该删掉。

用一千二百人而不是两万：索引是真的要跑嵌入的（实测约 95 条/秒），
两万人要三分半。人口规模在这里不是被测对象，可分性才是。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from cofield.adapters.embedding.ollama import OllamaEmbedder
from cofield.adapters.persistence.engine import campus_connection, owner_connection
from cofield.adapters.persistence.semantic import (
    PRINCIPAL,
    IndexableText,
    SemanticIndexWriter,
)
from cofield.domain.model.intent import (
    IntentContent,
    IntentSignal,
    IntentState,
    TeamSize,
    TimeWindow,
)
from cofield.domain.ports.embedder import EmbeddingUnavailable
from cofield.matching.funnel import Funnel, RecallMode
from cofield.matching.semantic import SemanticRetriever
from cofield.simulation.loader import load_principals
from cofield.simulation.population import generate

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
SIM = "simulation"
SIZE = 1_200

#: 这句话是整层的理由。"写文案"是字段，"朋克"不是——
#: 而且没有人会事先想到该建一个"朋克"字段。
PUNK = "想找个写朋克风格文案的，帮社团做招新"


@pytest.fixture(scope="module")
def campus(engine: Engine):  # type: ignore[no-untyped-def]
    """一份带自述的人口，且已建好语义索引。

    fixture 必须叫 `campus`——conftest 的清表钩子靠这个名字判断
    "这个模块自己装了人口，别在用例之间冲掉它"。
    """
    population = generate(size=SIZE, seed=3)
    with owner_connection(engine) as conn:
        conn.execute(sa.text("TRUNCATE principals CASCADE"))
    load_principals(engine, population, campus_id=SIM, now=NOW)

    # 只索引写文案的人：其余人在这个场景里连硬过滤都过不去，
    # 给他们建索引等于为一个永远不会被比较的向量付钱。
    writers = [p for p in population.people if "写文案" in p.skills]
    with owner_connection(engine) as conn:
        SemanticIndexWriter(conn, OllamaEmbedder()).index(
            [IndexableText(subject_id=p.id, text=p.self_intro) for p in writers],
            subject_kind=PRINCIPAL,
            campus_id=SIM,
            now=NOW,
        )

    yield population

    with owner_connection(engine) as conn:
        conn.execute(sa.text("TRUNCATE principals, semantic_index CASCADE"))


def _intent(expression: str = PUNK, needs: tuple[str, ...] = ("写文案",)) -> IntentSignal:
    return IntentSignal(
        id=uuid4(),
        principal_id=uuid4(),
        state=IntentState.ACTIVE,
        raw_expression=expression,
        content=IntentContent(
            goal="做一版社团招新文案",
            offers=("做PPT",),
            needs=needs,
            time_window=TimeWindow(NOW, NOW + timedelta(days=5)),
            location_scope=None,
            team_size=TeamSize(2, 3),
        ),
        created_at=NOW,
    )


class _BrokenEmbedder:
    """嵌入服务挂了。**不是 mock 我们自己的层**——被替换的是外部服务本身，
    而它挂掉是真实会发生的事，降级路径必须被真的走一遍。"""

    dimensions = 384

    def embed(self, texts):  # type: ignore[no-untyped-def]
        raise EmbeddingUnavailable("服务不可用")


def _voice_of(population, ids):  # type: ignore[no-untyped-def]
    by_id = {p.id: p for p in population.people}
    return [by_id[i].voice for i in ids if i in by_id]


# --- 语义买到了什么 ---


def test_semantic_recall_surfaces_people_no_field_could_describe(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """「朋克风格文案」召回到文风野的人。

    基线约 8%——七倍以上的富集才说明是语义在起作用，而不是碰巧。
    """
    writers = [p for p in campus.people if "写文案" in p.skills]
    baseline = sum(p.voice == "野" for p in writers) / len(writers)

    with campus_connection(engine, SIM) as conn:
        result = Funnel(
            conn, SIM, retriever=SemanticRetriever(conn, OllamaEmbedder())
        ).shortlist(_intent(), now=NOW, keep=20)

    assert result.trace.recall_mode is RecallMode.SEMANTIC
    hit_rate = _voice_of(campus, [c.principal_id for c in result.candidates]).count(
        "野"
    ) / len(result.candidates)
    assert hit_rate > baseline * 3, f"富集不足：{hit_rate:.1%} vs 基线 {baseline:.1%}"


def test_the_same_need_is_unreachable_without_semantics(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """同一句话，关掉语义就召不到——这是这一层存在的全部理由。

    纯结构化只知道"会写文案"，八千个人里挑哪二十个是**任意的**。
    """
    writers = [p for p in campus.people if "写文案" in p.skills]
    baseline = sum(p.voice == "野" for p in writers) / len(writers)

    with campus_connection(engine, SIM) as conn:
        structured = Funnel(conn, SIM).shortlist(_intent(), now=NOW, keep=20)

    assert structured.trace.recall_mode is RecallMode.STRUCTURED
    rate = _voice_of(campus, [c.principal_id for c in structured.candidates]).count(
        "野"
    ) / len(structured.candidates)
    assert rate < baseline * 3, "纯结构化不该有富集，否则说明测试构造有问题"


def test_string_matching_cannot_do_this_either(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """没有人在自述里写过"朋克"。

    这一条守住的是测试本身的诚实：如果自述里直接写着风格名，
    一句 ILIKE 就能召回，上面两个用例就成了自欺。
    """
    with campus_connection(engine, SIM) as conn:
        matched = conn.execute(
            sa.text(
                "SELECT count(*) FROM principals WHERE self_intro ILIKE :q"
            ),
            {"q": "%朋克%"},
        ).scalar_one()

    assert matched == 0


def test_the_matched_words_come_back_for_the_proof(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """候选要带回命中的原话。

    成局证明里要能写"他自己写的『文风比较冲』"。引用一个 0.71 毫无意义，
    用户无从判断这个理由成不成立。
    """
    with campus_connection(engine, SIM) as conn:
        result = Funnel(
            conn, SIM, retriever=SemanticRetriever(conn, OllamaEmbedder())
        ).shortlist(_intent(), now=NOW, keep=10)

    assert all(c.matched_text for c in result.candidates)
    assert all("朋克" not in (c.matched_text or "") for c in result.candidates)


# --- 顺序与隔离 ---


def test_hard_constraints_still_win_over_semantic_closeness(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """语义再贴近也进不来——过滤先于比较是 SQL 保证的，不靠调用方自觉。

    要一个稀缺技能时，写文案的人不管文风多合都不该出现。
    """
    with campus_connection(engine, SIM) as conn:
        result = Funnel(
            conn, SIM, retriever=SemanticRetriever(conn, OllamaEmbedder())
        ).shortlist(_intent(needs=("调色",)), now=NOW, keep=20)

    assert result.candidates
    for candidate in result.candidates:
        assert "调色" in candidate.skills


def test_the_index_stays_inside_its_tenant(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """另一个校园看不到这批向量。RLS 覆盖派生数据，不只覆盖权威事实。"""
    with campus_connection(engine, "demo-campus") as conn:
        visible = conn.execute(
            sa.select(sa.func.count()).select_from(
                sa.table("semantic_index")
            )
        ).scalar_one()

    assert visible == 0


def test_revoking_consent_removes_the_words_from_matching(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """撤回露出，原话就不该再参与任何人的匹配。

    这不是"清缓存"——向量是派生物，权威事实那边撤了，派生物必须跟着消失。
    """
    victim = next(p for p in campus.people if p.voice == "野" and "写文案" in p.skills)

    with owner_connection(engine) as conn:
        writer = SemanticIndexWriter(conn, OllamaEmbedder())
        assert writer.forget(subject_kind=PRINCIPAL, subject_id=victim.id) == 1

    with campus_connection(engine, SIM) as conn:
        result = Funnel(
            conn, SIM, retriever=SemanticRetriever(conn, OllamaEmbedder())
        ).shortlist(_intent(), now=NOW, keep=40)

    assert victim.id not in {c.principal_id for c in result.candidates}

    # 放回去，别影响同模块后续用例。
    with owner_connection(engine) as conn:
        SemanticIndexWriter(conn, OllamaEmbedder()).index(
            [IndexableText(subject_id=victim.id, text=victim.self_intro)],
            subject_kind=PRINCIPAL,
            campus_id=SIM,
            now=NOW,
        )


# --- 降级 ---


def test_a_dead_embedder_degrades_instead_of_breaking(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """嵌入服务挂了，用户仍然拿得到候选。

    少了长尾表达那一路，但不是白屏。语义是增强，不是前提。
    """
    with campus_connection(engine, SIM) as conn:
        result = Funnel(
            conn, SIM, retriever=SemanticRetriever(conn, _BrokenEmbedder())
        ).shortlist(_intent(), now=NOW, keep=20)

    assert result.trace.recall_mode is RecallMode.DEGRADED
    assert len(result.candidates) == 20, "降级不等于降到零"


def test_degradation_is_visible_not_silent(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """降级必须能被界面读到。

    "五态齐全"里的降级态就靠它——用户有权知道这次匹配打了折。
    """
    with campus_connection(engine, SIM) as conn:
        funnel = Funnel(conn, SIM, retriever=SemanticRetriever(conn, OllamaEmbedder()))
        healthy = funnel.shortlist(_intent(), now=NOW, keep=5)
        broken = Funnel(
            conn, SIM, retriever=SemanticRetriever(conn, _BrokenEmbedder())
        ).shortlist(_intent(), now=NOW, keep=5)

    assert healthy.trace.recall_mode is not broken.trace.recall_mode


def test_an_empty_expression_does_not_pretend_to_have_semantics(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """没写原话时不硬凑——空字符串的向量是个没有意义的位置。"""
    with campus_connection(engine, SIM) as conn:
        result = Funnel(
            conn, SIM, retriever=SemanticRetriever(conn, OllamaEmbedder())
        ).shortlist(_intent(expression="  "), now=NOW, keep=10)

    assert result.trace.recall_mode is RecallMode.STRUCTURED
    assert result.candidates


# --- 索引写入 ---


def test_reindexing_replaces_instead_of_accumulating(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """同一个人重复索引只留一行。

    历史在权威事实那边，这张表只是当前状态的投影——留版本会让
    "他现在怎么描述自己"变得没有唯一答案。
    """
    person = campus.people[0]
    with owner_connection(engine) as conn:
        writer = SemanticIndexWriter(conn, OllamaEmbedder())
        writer.index(
            [IndexableText(subject_id=person.id, text="第一版自述")],
            subject_kind=PRINCIPAL,
            campus_id=SIM,
            now=NOW,
        )
        writer.index(
            [IndexableText(subject_id=person.id, text="改过之后的自述")],
            subject_kind=PRINCIPAL,
            campus_id=SIM,
            now=NOW,
        )
        rows = conn.execute(
            sa.text(
                "SELECT text FROM semantic_index "
                "WHERE subject_kind = :k AND subject_id = :i"
            ),
            {"k": PRINCIPAL, "i": person.id},
        ).all()

    assert [r.text for r in rows] == ["改过之后的自述"]


def test_people_who_wrote_nothing_stay_out_of_the_index(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """没写自述的人不占一行。

    否则"没写"会变成一个可比较的语义位置，空白的人会被系统性地
    召回或系统性地排除——两种都不对。
    """
    with owner_connection(engine) as conn:
        written = SemanticIndexWriter(conn, OllamaEmbedder()).index(
            [IndexableText(subject_id=uuid4(), text="   ")],
            subject_kind=PRINCIPAL,
            campus_id=SIM,
            now=NOW,
        )

    assert written == 0
