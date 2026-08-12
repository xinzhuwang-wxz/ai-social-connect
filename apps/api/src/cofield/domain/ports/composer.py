"""起草端口：AI 写字的地方，也是它唯一能写字的地方。

## 这个端口的形状本身就是一条约束

它**不接受提示词，只接受事实**。调用方给一组已经获准使用的事实，
起草者从中写出一段话——它不能检索、不能调工具、不能读库。

这不是洁癖。自由格式的提示拼接意味着任何一个调用点都可能把未授权的内容
拼进去，而那是一次披露事故，不是一次代码 bug。输入是**封闭集合**时，
"这段话里会不会出现他没授权的东西"才是可以被静态回答的。

同理，这也是提示注入的防线：起草者读到的每一句话都来自我们自己的数据库，
没有一句来自外部页面或对方 agent 的自由文本。

## 返回的是草稿，不是决定

`Draft` 带着它依据了哪些事实。用户点开能看到——**看不到依据的草稿，
"人类决定"就只是点一下按钮**。

草稿本身没有任何效力：它要么被真人采纳（`space_items.accepted_by`），
要么被真人签名（承诺表），否则什么都不算。这一层不负责执行这条规则，
但它的返回类型让"忘了要人确认"变成一个显眼的类型错误，而不是一个静默的默认值。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ComposerUnavailable(Exception):
    """起草服务不可用。

    调用方**必须降级为模板或纯人工**，不能让整条链路挂掉——
    ADR 0003 说得清楚：意图编译和证明转写可以被表单和模板替代，
    协商措辞降级成"对方需要你回复"也仍然可用。
    """


class DraftKind(StrEnum):
    """起草者被允许做的事。**枚举而不是自由字符串**——
    新增一种用途要显式加进来，顺带被迫回答"这一处拿掉 AI 还成立吗"。"""

    #: 受限协商里的一句话。七种结构化消息的**措辞**，不是消息类型本身。
    NEGOTIATION_REPLY = "negotiation_reply"
    #: 行动回声：把证据写成一段别人读得懂的记录。
    ACTION_ECHO = "action_echo"
    #: 记忆切面抽取：从一次完成的事里提出可复用的一句话。
    FACET_EXTRACTION = "facet_extraction"
    #: 成局证明转写。**可替代**（模板能干），所以它降级最不痛。
    PROOF_NARRATION = "proof_narration"
    #: 把一件**还没定的事**写成一句可以回答的话。
    #:
    #: 它不是"生成话题"——凭空造话题的助手会很快被所有人忽略，
    #: 而一旦被忽略，之后它说什么都没人看了。输入永远是一条已经存在的
    #: 待定事项，输出只是把它变得好回答。
    OPEN_QUESTION = "open_question"


@dataclass(frozen=True, slots=True)
class Draft:
    text: str
    #: 哪个模型写的。审计要用，换模型时的行为差异也要用。
    model: str
    #: 依据了哪些事实。**顺序与传入的 `facts` 一致**，用户点开逐条对照。
    grounded_in: tuple[str, ...]
    #: 这段话是不是从缓存/磁带里回放的。CI 里恒为真，
    #: 线上恒为假——混在一起会让"这次真的调了模型吗"无从判断。
    replayed: bool = False


class Composer(Protocol):
    """端口不说明用什么模型，也不说明用什么服务商。

    换模型不该触及任何领域测试——这是判断这条边界画得对不对的标准。
    """

    def draft(
        self,
        kind: DraftKind,
        *,
        facts: Sequence[str],
        instruction: str,
        max_chars: int = 200,
    ) -> Draft:
        """从给定事实写一段话。

        `instruction` 是**我们自己写死的任务说明**，不是用户输入，
        也不能是从别处读来的文本。用户的话属于 `facts`。
        这条区分是提示注入防线的全部——混起来这个端口就白设计了。
        """
        ...
