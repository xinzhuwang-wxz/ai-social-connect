"""用户主体。

拥有意图、信息、决定权与退出权的真人——以及仿真人口中代表真人位置的合成主体。
两者在数据结构上同形，但**永远不能出现在同一个成局提案里**（见 formation.py）。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


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
