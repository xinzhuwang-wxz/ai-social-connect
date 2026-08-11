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
class FollowUpQuestion:
    """一个值得问的追问。

    `narrows` 是它能收窄的字段名——**只有能实质改变可行集合的问题才配被问**。
    抽取器不许问性格、MBTI 或完整履历。
    """

    text: str
    narrows: str
    options: tuple[str, ...] = ()


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
