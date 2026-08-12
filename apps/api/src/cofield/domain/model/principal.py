"""用户主体。

拥有意图、信息、决定权与退出权的真人——以及仿真人口中代表真人位置的合成主体。
两者在数据结构上同形，但**永远不能出现在同一个成局提案里**（见 formation.py）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

#: 起占位名用的字。和仿真人口用**同一份**——两处各写一套的话，
#: 真人和合成人在同一屏上看起来像两个物种。
SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
GIVEN = "然轩宇泽睿曦航嘉磊佳怡欣悦茜蕾晨旭霖沐禾一凡子墨昀笙桐屿"


def placeholder_name(principal_id: UUID) -> str:
    """真名到位之前，先给一个能把人区分开的名字。

    ## 为什么不能是「同学」加 id 后四位

    因为它**撞**。一支四个人的队里出现「同学0002、同学0002、同学0002」
    的时候，队友是谁这件事就不成立了——而这一屏问的正是"要不要和这几个人
    一起做事"。

    ## 为什么看起来像个真名

    因为屏上同时有真人和仿真人口，两边用不同的起名法会让他们看起来像
    两个物种。这个名字**是占位**，真名来自校园身份；但在那之前，
    它至少要是一个人能记住、能在群里叫出口的东西。

    确定性：同一个 id 永远得到同一个名字。随机起名会让同一个人在两次
    查询之间换名字，而"他是谁"是这一屏唯一要回答的问题。

    先散列再取字：直接对 `int` 取模的话，只差最后一位的两个 id 会得到
    只差一个姓的名字（赵睿轩、钱睿轩、孙睿轩）——看着像一家人。
    """
    digest = hashlib.blake2b(principal_id.bytes, digest_size=6).digest()
    return (
        SURNAMES[digest[0] % len(SURNAMES)]
        + GIVEN[digest[1] % len(GIVEN)]
        + GIVEN[digest[2] % len(GIVEN)]
    )


@dataclass(frozen=True, slots=True)
class CampusId:
    """校园即策略与数据边界。仿真租户是一个独立的 campus。"""

    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValueError("campus_id 不能为空")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Principal:
    """一个用户主体。

    `is_synthetic` 不是一个可有可无的标记：它承载一条治理要求——
    真人永远不应该以为自己在和真人配队。
    """

    id: UUID
    campus_id: CampusId
    display_name: str
    is_synthetic: bool = False
    #: 自己写的一段话。它**故意不被结构化**——"想找个写朋克风格文案的"
    #: 这类需求没有字段接得住，只有原话接得住。
    #: 它是可授权字段，不是默认公开（见 consent.GRANTABLE_FIELDS）。
    self_intro: str | None = None
    #: 专业。参与 CROSS_MAJOR 软目标，也可被授权出现在成局证明里。
    major: str | None = None
    #: 我能补上的洞。漏斗第一段按它做精确过滤，求解器的角色覆盖**只认它**。
    #: 词表是封闭的（见 model/skills.py）——词表外的值匹配零个人。
    skills: tuple[str, ...] = ()
    #: 我想参与的方向。**只放宽召回，不放宽承诺**：说"想参与拍短片"的人
    #: 可以被叫来一起做，但不会被当成会剪辑的人塞进剪辑那个坑里。
    #:
    #: 它和 `skills` 的区别不是措辞，是这个产品少了它就转不动——
    #: 一个刚做完一件事、想再接一个的人，要的不是发起，是**参与**。
    open_to: tuple[str, ...] = ()
    #: 常在的校区。`None` = 哪个校区都行，硬过滤不排除他。
    zone: str | None = None
    #: 已确认完成的事件数。**闭环靠它合上**——它是「上次一起完成过 X」
    #: 这句话的唯一来源。派生自已确认的事件参与，不手工写。
    confirmed_events: int = 0
