"""规则抽取器：把一句话变成一张能改的需求卡。

这里最要紧的一条是**词表对齐**：`needs` 直接喂给 SQL 的精确过滤，
抽出词表外的值等于让这条需求永远匹配不到人，而且没有任何报错。
"""

from __future__ import annotations

from datetime import UTC, datetime

from cofield.adapters.extraction import RuleIntentExtractor
from cofield.domain.model.skills import ALIASES, SKILLS

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)




# --- 词表对齐 ---


def test_needs_always_land_in_the_platform_vocabulary() -> None:
    """`needs` 直接喂给 SQL 精确过滤，词表外的值匹配**零个人**。

    这个 bug 真的发生过：「缺个会剪辑的」抽成 `会剪辑`，于是这条需求
    永远配不到人，而校园里明明有两百个会剪辑的。**静默是最坏的部分**——
    没有报错，只是结果永远为空。
    """
    extractor = RuleIntentExtractor()
    sayings = (
        "想拍支短片，缺个会剪辑的和一个会拍摄的，这周末，三四个人",
        "缺个会剪辑的",
        "找个会写文案的人",
        "想找人一起做数据分析",
        "缺剪辑和拍摄",
        "我不会剪辑，需要有人帮忙",
        "招一个懂前端的",
        "需要一位摄影",
        "求个做PPT的",
    )

    for saying in sayings:
        needs = extractor.extract(saying, now=NOW).content.needs
        assert needs, f"「{saying}」一个缺口都没抽出来"
        outside = [n for n in needs if n not in SKILLS]
        assert not outside, f"「{saying}」抽出了词表外的 {outside}——它们匹配不到任何人"


def test_what_the_vocabulary_cannot_hold_is_flagged_not_swallowed() -> None:
    """认不出来的不进 `needs`（进了也匹配不到人），但要**让用户看见**。

    原话完整留在 `raw_expression` 里给语义召回用，而界面上那个"我猜的"
    徽标让用户一眼看出漏了什么——系统自己永远猜不出那半句该归到哪个词上。
    """
    result = RuleIntentExtractor().extract(
        "缺个会剪辑的，还需要一个能镇住场子的老江湖", now=NOW
    )

    assert "剪辑" in result.content.needs
    assert "needs" in result.content.uncertain_fields


def test_the_two_vocabularies_are_the_same_one() -> None:
    """合成人口和抽取器必须用同一份词表。

    两处各写一份的话，仿真里会出现现实中抽不出来的技能——
    那种测试跑得再绿也证明不了什么。
    """
    from cofield.simulation.population import SKILL_ABUNDANCE

    assert set(SKILL_ABUNDANCE) == SKILLS


def test_every_alias_points_at_a_real_skill() -> None:
    """别名表指向词表外的词，等于给用户挖了个坑：他照着说，系统认了，
    然后匹配不到任何人。"""
    assert set(ALIASES.values()) <= SKILLS
