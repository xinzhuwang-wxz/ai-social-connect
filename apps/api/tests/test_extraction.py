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


# --- 「三四个人」 ---


def test_two_numbers_side_by_side_are_a_range_not_the_bigger_one() -> None:
    """中文里紧挨着的两个数字就是一个范围，中间不写连接词。

    读成「四到四」比用户说的更紧，而更紧的约束正是杀死匹配的东西——
    真实走查里，一条"三四个人"的需求因此要求恰好四人，
    校园里有人能接却凑不出队。
    """
    result = RuleIntentExtractor().extract("想拍支短片，缺个会剪辑的，三四个人", now=NOW)

    size = result.content.team_size
    assert size is not None
    assert (size.minimum, size.maximum) == (3, 4)


def test_a_plain_number_still_means_exactly_that_many() -> None:
    """「四个人」就是四个人，不能被上一条顺手放宽。"""
    result = RuleIntentExtractor().extract("想拍支短片，缺个会剪辑的，四个人", now=NOW)

    size = result.content.team_size
    assert size is not None
    assert (size.minimum, size.maximum) == (4, 4)


def test_the_majors_a_person_can_pick_are_the_ones_the_campus_has() -> None:
    """真人能填的专业，必须就是仿真人口里存在的那批。

    两处各写一份的话，真人能填出一个校园里根本不存在的专业，而跨专业
    那条软目标会因此永远算不出东西来——**没有报错，只是那条目标失效了**。
    技能词表已经有一条同样的用例守着，专业是后补的那一条。
    """
    from cofield.domain.model.skills import MAJORS
    from cofield.simulation.population import MAJORS as POPULATION_MAJORS

    assert set(MAJORS) == {name for name, _ in POPULATION_MAJORS}


# --- 追问要能答 ---


def test_every_option_carries_something_that_can_be_filled_in() -> None:
    """选项不能只是几个词。

    原先 `options` 是纯字符串，界面把它们当说明文字印出来——**用户读得到，
    答不了**。一个答不了的追问比不问更糟：它明说了系统知道自己缺什么，
    然后什么也不做。
    """
    result = RuleIntentExtractor().extract("想找人一起做点事", now=NOW)

    assert result.follow_ups, "什么都没说清，却一个问题都不问"
    for question in result.follow_ups:
        for option in question.options:
            assert option.label, "屏上没字"
            # value 可以是空串（「没有硬性截止」「都行」就是把这一栏留空），
            # 但它必须是一个**明确的答案**，不是缺省。
            assert isinstance(option.value, str)


def test_it_asks_what_narrows_the_most_first() -> None:
    """缺的角色最能收窄可行集合，先问它；人数次之。

    上限仍然是两个——多问一个就是多一次把不确定推回给用户。
    """
    result = RuleIntentExtractor().extract("周末想找人爬山", now=NOW)

    assert len(result.follow_ups) <= 2
    assert [q.narrows for q in result.follow_ups][:2] == ["needs", "team_size"]


def test_a_time_option_is_a_real_moment_not_a_phrase() -> None:
    """「这周内」得变成一个能存进时间列的时刻。

    屏上不该出现 ISO 时间戳，卡里也不该出现「这周内」——所以标签和值
    从一开始就是两样东西。
    """
    result = RuleIntentExtractor().extract("想拍个短片，缺个会剪辑的，三个人", now=NOW)
    when = next(q for q in result.follow_ups if q.narrows == "time_window")

    soon = next(o for o in when.options if o.label == "这周内")
    assert datetime.fromisoformat(soon.value) > NOW
    # 「没有硬性截止」是一个真实的答案：它把这一栏留空，而不是不回答。
    assert next(o for o in when.options if "没有" in o.label).value == ""
