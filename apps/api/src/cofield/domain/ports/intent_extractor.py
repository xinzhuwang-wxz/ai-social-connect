"""意图抽取端口。

把一句自然语言变成结构化内容。抽取器**只产出草稿**——它没有权力让任何
东西进入撮合，那需要用户确认（见 `IntentSignal.confirm`）。

端口刻意不说明用什么实现。LLM 是一种，规则解析是另一种；换掉实现不应触及
领域测试，这也是判断这条边界画得对不对的标准。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from cofield.domain.model.intent import IntentContent


@dataclass(frozen=True, slots=True)
class FollowUpOption:
    """一个可以直接点的答案。

    `label` 是屏上那几个字，`value` 是点下去之后填进卡里的东西。
    两者分开是因为「这周内」要变成一个真实的截止时刻，
    而屏上不该出现一个 ISO 时间戳。
    """

    label: str
    value: str


@dataclass(frozen=True, slots=True)
class FollowUpQuestion:
    """一个值得问的追问。

    `narrows` 是它能收窄的字段名——**只有能实质改变可行集合的问题才配被问**。
    抽取器不许问性格、MBTI 或完整履历：那些既不影响这次能不能配上，
    问了也只是把不确定推给用户。

    ## 每个选项都要能直接填进卡里

    原先 `options` 只是几个词，界面把它们当说明文字印出来——
    **用户读得到，答不了**。一个答不了的追问比不问更糟：它明说了系统
    知道自己缺什么，然后什么也不做。

    所以每个选项带一个 `value`：点它就等于把那个值填进 `narrows` 指的
    那一栏。没有额外一轮请求——卡本来就是用户在改的草稿。
    """

    text: str
    narrows: str
    options: tuple[FollowUpOption, ...] = ()


@dataclass(frozen=True, slots=True)
class Extraction:
    content: IntentContent
    #: 最多两个。多于两个说明抽取器在把自己的不确定推给用户。
    follow_ups: tuple[FollowUpQuestion, ...] = ()
    #: 抽取器自己判断这次抽得靠不靠谱。低于阈值时界面直接退回手填表单。
    confidence: float = 1.0


class ExtractionFailed(Exception):
    """抽取失败。调用方必须降级为手填表单，不能让用户卡住。"""


class IntentExtractor(Protocol):
    def extract(self, expression: str, *, now: datetime) -> Extraction: ...
