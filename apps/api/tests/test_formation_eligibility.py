"""谁可以出现在同一个成局提案里。

这是纯领域规则，不碰数据库——它必须在求解阶段就能廉价地大量调用。
"""

from __future__ import annotations

from uuid import uuid4

from cofield.domain.model.formation import eligibility
from cofield.domain.model.principal import CampusId, Principal


def person(campus: str = "demo-campus", *, synthetic: bool = False) -> Principal:
    return Principal(
        id=uuid4(),
        campus_id=CampusId(campus),
        display_name="合成主体" if synthetic else "真人",
        is_synthetic=synthetic,
    )


def test_all_real_same_campus_is_allowed() -> None:
    assert eligibility([person(), person(), person()]).ok


def test_all_synthetic_same_campus_is_allowed() -> None:
    """仿真人口内部当然可以互相成局，否则仿真跑不起来。"""
    members = [person("simulation", synthetic=True) for _ in range(3)]
    assert eligibility(members).ok


def test_synthetic_must_never_join_a_real_proposal() -> None:
    """这条不是测试便利，是治理要求：真人不应该以为自己在和真人配队。"""
    verdict = eligibility([person(), person("demo-campus", synthetic=True)])

    assert not verdict.ok
    assert "合成主体不能与真人" in (verdict.reason or "")


def test_cross_campus_is_refused() -> None:
    verdict = eligibility([person("campus-a"), person("campus-b")])

    assert not verdict.ok
    assert "跨校园" in (verdict.reason or "")


def test_empty_proposal_is_refused() -> None:
    assert not eligibility([]).ok
