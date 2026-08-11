"""共域：随产品发布的四种条目。

这是**配置，不是规则**——所以它在 `canvas` 外面。画布那一份文件里
不出现任何一种条目的名字；规则挂在下面这些声明的属性上。
加一种条目是在这个元组里加一条，画布、仓储、表结构都不用动。

`kind` 一张表而不是四张表，理由同上：新增一种条目应该是新增一条声明，
不是新增一张表加一套 CRUD。

界面上这些东西不叫这些名字。`label` 那一列已经是用户词了——
共域在界面上叫「我们的空间」或直接叫项目名（07 §2）。
"""

from __future__ import annotations

from cofield.space.canvas import (
    ABOUT,
    CONFIRMED_BY,
    DECIDERS,
    DISCARDED,
    REACH,
    SOURCE,
    Actor,
    AgentCannotDecide,
    AgentIsOff,
    Canvas,
    CanvasRefused,
    CanvasView,
    Card,
    DraftDoesNotCount,
    IllegalMove,
    ItemKind,
    ItemKindRegistry,
    MissingProvenance,
    NotYoursToDecide,
    Progress,
    Reach,
    UnknownItemKind,
    field_agent,
    person,
)

SHIPPED_ITEM_KINDS: tuple[ItemKind, ...] = (
    ItemKind(
        key="task",
        label="要做的事",
        states=("todo", "doing", "done"),
        done_states=frozenset({"done"}),
        # 只有这一类计入"做完了多少"。空间因真实行动证据生长，
        # 不因聊天量、签到或助手写了多少条生长（不变量 6）。
        counts_toward_progress=True,
    ),
    ItemKind(
        key="material",
        label="我们做的东西",
        states=("shared",),
        # 上传即成立，没有生命周期——但**必须带来源和可见范围**。
        # 没有来源、同意或撤销路径的内容不能成为权威长期记忆（不变量 5）。
        required_extras=(SOURCE, REACH),
    ),
    ItemKind(
        key="decision_gate",
        label="要定的事",
        states=("open", "settled"),
        done_states=frozenset({"settled"}),
        # 谁必须点头写在 `deciders` 里，一个都不能少。
        # 助手关不掉它——那不是这里能配的，是画布里的规则。
        needs_human_decision=True,
        required_extras=(DECIDERS,),
    ),
    ItemKind(
        key="note",
        label="记一笔",
        states=("open",),
    ),
)

item_kinds = ItemKindRegistry(SHIPPED_ITEM_KINDS)

__all__ = [
    "ABOUT",
    "CONFIRMED_BY",
    "DECIDERS",
    "DISCARDED",
    "REACH",
    "SHIPPED_ITEM_KINDS",
    "SOURCE",
    "Actor",
    "AgentCannotDecide",
    "AgentIsOff",
    "Canvas",
    "CanvasRefused",
    "CanvasView",
    "Card",
    "DraftDoesNotCount",
    "IllegalMove",
    "ItemKind",
    "ItemKindRegistry",
    "MissingProvenance",
    "NotYoursToDecide",
    "Progress",
    "Reach",
    "UnknownItemKind",
    "field_agent",
    "item_kinds",
    "person",
]
