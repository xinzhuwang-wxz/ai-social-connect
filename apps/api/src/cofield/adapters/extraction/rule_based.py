"""规则抽取器：不依赖任何模型的真实现。

它不是 LLM 的桩。它真的解析中文里的相对日期、角色缺口和团队规模，
只是覆盖面窄——所以它对自己没把握的字段会**如实标注**，并把问题
交给追问，而不是编一个值出来。

存在的理由有两个：没有模型凭证时产品仍然能用；以及它给 LLM 抽取器
提供了一个可对照的下限——如果 LLM 的结果还不如它，那就是提示词的问题。
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta

from cofield.domain.model.intent import IntentContent, TeamSize, TimeWindow
from cofield.domain.model.skills import normalise
from cofield.domain.ports.intent_extractor import (
    Extraction,
    FollowUpOption,
    FollowUpQuestion,
    IntentExtractor,
)

_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

_OFFER_PATTERNS = [
    re.compile(r"我(?:会|能|可以|擅长|负责)([^，。；,;！!？?\n]{1,20})"),
    re.compile(r"(?:我有|自带)([^，。；,;！!？?\n]{1,20})"),
]
_NEED_PATTERNS = [
    # "不认识会拍摄和剪辑的人" —— 否定式表达的其实是需求，这是最常见的说法
    re.compile(r"不(?:认识|会|懂)(?:会)?([^，。；,;！!？?\n]{1,24})"),
    re.compile(
        r"(?:缺|差|需要|想找|要找|找|求|招|招募)"
        r"(?:一?个|几个|两个|三个)?([^，。；,;！!？?\n]{1,20})"
    ),
]
_NOISE = re.compile(r"^(?:什么|谁|人|的|了|吗|呢)+$")
#: 含这些词的短语说的是"一起做某事"，不是一个角色缺口。
#: 用 search 而不是 match——它们通常出现在短语中间。
_NOT_A_ROLE = re.compile(r"一起|合作|组队|搭子")
_TRAILING = re.compile(r"(?:的人|的同学|的伙伴|的人选|的队友)$")
#: 抽出来的短语常常是并列的（"拍摄和剪辑"），拆开才是可用的角色缺口。
_CONJUNCTION = re.compile(r"[和、跟与]|以及|还有")

_BOUNDARY_HINTS = {
    "正脸": "是否允许出现人物正脸",
    "露脸": "是否允许出现人物正脸",
    "署名": "署名规则",
    "公开": "是否公开发布",
    "发布": "是否公开发布",
}


class RuleIntentExtractor:
    """按规则抽取。对拿不准的字段标 uncertain，绝不猜。"""

    def extract(self, expression: str, *, now: datetime) -> Extraction:
        text = expression.strip()
        uncertain: set[str] = set()
        follow_ups: list[FollowUpQuestion] = []

        deadline = _parse_deadline(text, now=now)
        window = TimeWindow(earliest=now, deadline=deadline) if deadline else None

        offers, _ = _collect(text, _OFFER_PATTERNS)
        needs, needs_unclear = _collect(text, _NEED_PATTERNS)
        if not needs:
            uncertain.add("needs")
        elif needs_unclear:
            # 认出来一部分，还有一部分说的东西结构化字段装不下。
            # 标成"我猜的"让用户过目——他一眼就能看出漏了什么，
            # 而系统自己永远猜不出那半句该归到哪个词上。
            uncertain.add("needs")

        size = _parse_team_size(text) or _infer_size(needs)
        told_size = _parse_team_size(text) is not None
        if size is not None and not told_size:
            uncertain.add("team_size")
        place = _parse_place(text)

        # ## 追问按"能收窄多少"排，不按顺手排
        #
        # 缺的角色最能收窄可行集合（它直接进 SQL 精确过滤），人数次之
        # （它是求解器的硬约束），时间和地点再次之。
        #
        # **上限仍然是两个。** 多问一个就是多一次把不确定推回给用户，
        # 而 PRD 自己也写着"不要强制用户进行十几分钟的对话"。
        if not needs or needs_unclear:
            follow_ups.append(
                FollowUpQuestion(text="你最缺哪种人？", narrows="needs")
            )
        if not told_size:
            follow_ups.append(
                FollowUpQuestion(
                    text="希望找几个人？",
                    narrows="team_size",
                    options=(
                        FollowUpOption(label="就两个人", value="2-2"),
                        FollowUpOption(label="三四个", value="3-4"),
                        FollowUpOption(label="五六个", value="5-6"),
                        FollowUpOption(label="人多点也行", value="3-8"),
                    ),
                )
            )
        if window is None:
            uncertain.add("time_window")
            follow_ups.append(
                FollowUpQuestion(
                    text="这件事什么时候要完成？",
                    narrows="time_window",
                    options=(
                        FollowUpOption(label="这周内", value=_in_days(now, 7)),
                        FollowUpOption(label="两周内", value=_in_days(now, 14)),
                        FollowUpOption(label="这个月", value=_in_days(now, 30)),
                        FollowUpOption(label="没有硬性截止", value=""),
                    ),
                )
            )
        if place is None:
            follow_ups.append(
                FollowUpQuestion(
                    text="大概在哪边？",
                    narrows="location_scope",
                    options=(
                        FollowUpOption(label="东校区", value="东校区"),
                        FollowUpOption(label="西校区", value="西校区"),
                        FollowUpOption(label="南校区", value="南校区"),
                        FollowUpOption(label="都行", value=""),
                    ),
                )
            )

        boundaries = tuple(
            sorted({v for k, v in _BOUNDARY_HINTS.items() if k in text})
        )

        content = IntentContent(
            goal=_goal_of(text),
            offers=offers,
            needs=needs,
            time_window=window,
            location_scope=place,
            team_size=size,
            boundaries=(),
            # 边界线索出现在原话里时，它们是"要留给真人决定的事"，
            # 不是已经定下来的约束——所以进 open_questions 而不是 boundaries。
            open_questions=boundaries,
            uncertain_fields=frozenset(uncertain),
        )

        return Extraction(
            content=content,
            follow_ups=tuple(follow_ups[:2]),  # 最多两个，多了是把不确定推给用户
            confidence=_confidence(content),
        )


def _goal_of(text: str) -> str:
    """目标取第一个完整分句——用户通常先说要做什么。"""
    first = re.split(r"[，。；,;！!？?\n]", text, maxsplit=1)[0].strip()
    return first or text[:40]


def _collect(text: str, patterns: list[re.Pattern[str]]) -> tuple[tuple[str, ...], bool]:
    """抽出角色缺口，**归一到平台认识的词表**。

    返回（认出来的, 有没有没认出来的）。

    ## 为什么必须归一

    `needs` 直接喂给 SQL 的精确过滤。抽成「会剪辑」而不是「剪辑」，
    这条需求就永远匹配不到人——而校园里明明有两百个人会剪辑。
    静默是最坏的部分：没有报错，只是结果永远为空。

    ## 没认出来的不丢

    原话完整保留在 `raw_expression` 里，语义召回读的就是它。
    「朋克风格文案」里的"朋克"本来就不在词表里，那一路正是为它准备的。
    这一层要做的是**认出哪些属于结构化字段**，不是把所有东西都塞进去。

    但要**让用户知道**只认出了一部分——所以第二个返回值会让 `needs`
    被标成"我猜的"，界面上那个可编辑的徽标就是为这件事存在的。
    """
    found: list[str] = []
    missed = False
    for pattern in patterns:
        for raw in pattern.findall(text):
            phrase = _TRAILING.sub("", raw.strip(" 的和与、"))
            for part in _CONJUNCTION.split(phrase):
                item = _TRAILING.sub("", part.strip(" 的和与、"))
                if not item or _NOISE.match(item):
                    continue
                skill = normalise(item)
                if skill is not None:
                    # 词表命中是强证据，压过"一起/组队"那条启发式——
                    # "想找人一起做数据分析"里，数据分析确实是缺口。
                    if skill not in found:
                        found.append(skill)
                    continue
                if _NOT_A_ROLE.search(item) or len(item) > 12:
                    continue
                # 认不出来的：不进 needs（进了也匹配不到人），但要留个记号。
                missed = True
    return tuple(found), missed


def _parse_deadline(text: str, *, now: datetime) -> datetime | None:
    end_of_day = time(23, 59, tzinfo=now.tzinfo)

    if m := re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", text):
        month, day = int(m.group(1)), int(m.group(2))
        year = now.year + (1 if month < now.month else 0)
        return datetime.combine(datetime(year, month, day), end_of_day)

    for phrase, days in (("今天", 0), ("明天", 1), ("后天", 2), ("大后天", 3)):
        if phrase in text:
            return datetime.combine((now + timedelta(days=days)).date(), end_of_day)

    if m := re.search(r"(本|这|下)?\s*(?:周|星期|礼拜)\s*([一二三四五六日天])", text):
        target = _WEEKDAYS[m.group(2)]
        ahead = (target - now.weekday()) % 7
        if m.group(1) == "下":
            ahead += 7
        elif ahead == 0:
            ahead = 7  # "周五"在周五当天说，通常指下一个周五
        return datetime.combine((now + timedelta(days=ahead)).date(), end_of_day)

    if m := re.search(r"(\d+)\s*(?:天|日)(?:内|以内|之内)", text):
        return datetime.combine(
            (now + timedelta(days=int(m.group(1)))).date(), end_of_day
        )
    if m := re.search(r"(\d+)\s*(?:周|星期)(?:内|以内|之内)", text):
        return datetime.combine(
            (now + timedelta(weeks=int(m.group(1)))).date(), end_of_day
        )
    return None


def _parse_place(text: str) -> str | None:
    if m := re.search(r"([东西南北中]校区|[一-龥]{2,6}(?:校区|楼|馆|中心))", text):
        return m.group(1)
    if "校内" in text:
        return "校内"
    return None


def _in_days(now: datetime, days: int) -> str:
    """「这周内」变成一个真实的截止时刻。

    屏上不该出现 ISO 时间戳，卡里也不该出现「这周内」这种存不进
    时间列的东西——所以标签和值从一开始就是两样。
    """
    return (now + timedelta(days=days)).isoformat()


_CN_NUM = {"两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}


def _parse_team_size(text: str) -> TeamSize | None:
    if m := re.search(r"(\d+)\s*[-~到至]\s*(\d+)\s*(?:个)?人", text):
        return TeamSize(minimum=max(2, int(m.group(1))), maximum=int(m.group(2)))
    # 「三四个人」「两三个」——中文里紧挨着的两个数字就是一个范围，
    # 中间不写连接词。
    #
    # 少了这一条，「三四个人」被读成**四到四**：比用户说的更紧。而更紧的
    # 约束正是杀死匹配的东西——真实走查里，一条"三四个人"的需求因此
    # 要求恰好四人，校园里有人能接却凑不出队。
    #
    # 只认相邻的（三四、两三、四五）：不相邻的两个数字挨在一起通常不是
    # 范围（「二五个人」不是一种说法），宁可不认也不要猜错。
    if m := re.search(r"([两二三四五六七八])\s*([两二三四五六七八])\s*(?:个)?人?", text):
        low, high = _CN_NUM[m.group(1)], _CN_NUM[m.group(2)]
        if high == low + 1:
            return TeamSize(minimum=max(2, low), maximum=high)
    if m := re.search(r"([\d两二三四五六七八])\s*(?:个)?人(?:的)?(?:团队|队伍|小组)?", text):
        raw = m.group(1)
        n = _CN_NUM.get(raw) or int(raw)
        if n >= 2:
            return TeamSize(minimum=n, maximum=n)
    return None


def _infer_size(needs: tuple[str, ...]) -> TeamSize | None:
    """从角色缺口推团队规模。推出来的一律标 uncertain——这是推断不是事实。"""
    if not needs:
        return None
    base = len(needs) + 1
    return TeamSize(minimum=max(2, base), maximum=base + 1)


def _confidence(content: IntentContent) -> float:
    """置信度只反映抽到了多少可用信息，不反映抽得对不对——后者要用户来判。"""
    signals = [
        bool(content.goal.strip()),
        bool(content.needs),
        content.time_window is not None,
        bool(content.offers),
    ]
    return round(sum(signals) / len(signals), 2)


_: IntentExtractor = RuleIntentExtractor()
