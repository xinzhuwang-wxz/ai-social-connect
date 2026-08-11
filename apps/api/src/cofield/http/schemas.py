"""API 契约。

这一层是 OpenAPI 3.1 的来源，前端类型由它自动派生——**任何一层都不手写类型**。
领域用 dataclass（不能依赖第三方），API 用 Pydantic，转换只在这里发生。

字段名跨三层保持一致：领域 `principal_id`、API `principal_id`、
前端 `principalId`（仅由 codegen 做大小写转换）。不做层间语义翻译。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from cofield.domain.model.action_kind import ActionKind
from cofield.domain.model.intent import Conflict, IntentContent, IntentSignal
from cofield.domain.ports.intent_extractor import Extraction, FollowUpQuestion


class TimeWindowOut(BaseModel):
    earliest: datetime
    deadline: datetime


class TeamSizeOut(BaseModel):
    minimum: int
    maximum: int


class IntentContentOut(BaseModel):
    goal: str
    offers: list[str] = []
    needs: list[str] = []
    time_window: TimeWindowOut | None = None
    location_scope: str | None = None
    team_size: TeamSizeOut | None = None
    boundaries: list[str] = []
    open_questions: list[str] = []
    #: 抽取器没把握的字段。界面据此提示用户重点核对，而不是默默当成事实。
    uncertain_fields: list[str] = []

    @classmethod
    def of(cls, content: IntentContent) -> IntentContentOut:
        return cls(
            goal=content.goal,
            offers=list(content.offers),
            needs=list(content.needs),
            time_window=(
                TimeWindowOut(
                    earliest=content.time_window.earliest,
                    deadline=content.time_window.deadline,
                )
                if content.time_window
                else None
            ),
            location_scope=content.location_scope,
            team_size=(
                TeamSizeOut(
                    minimum=content.team_size.minimum,
                    maximum=content.team_size.maximum,
                )
                if content.team_size
                else None
            ),
            boundaries=list(content.boundaries),
            open_questions=list(content.open_questions),
            uncertain_fields=sorted(content.uncertain_fields),
        )


class IntentContentIn(BaseModel):
    """用户校对后回传的内容。抽取给的是草稿，这才是权威。"""

    goal: str = Field(min_length=1, max_length=200)
    offers: list[str] = []
    needs: list[str] = []
    time_window: TimeWindowOut | None = None
    location_scope: str | None = None
    team_size: TeamSizeOut | None = None
    boundaries: list[str] = []
    open_questions: list[str] = []


class ConflictOut(BaseModel):
    """指出是哪两条约束打架，不泛泛说"输入有误"。"""

    field: str
    detail: str

    @classmethod
    def of(cls, conflict: Conflict) -> ConflictOut:
        return cls(field=conflict.field, detail=conflict.detail)


class FollowUpOut(BaseModel):
    text: str
    narrows: str
    options: list[str] = []

    @classmethod
    def of(cls, question: FollowUpQuestion) -> FollowUpOut:
        return cls(
            text=question.text, narrows=question.narrows, options=list(question.options)
        )


class CompileRequest(BaseModel):
    expression: Annotated[str, Field(min_length=1, max_length=2000)]


class CompileResponse(BaseModel):
    """抽取结果。**它只是草稿**——没有用户确认，什么都进不了撮合。"""

    content: IntentContentOut
    follow_ups: list[FollowUpOut] = []
    conflicts: list[ConflictOut] = []
    confidence: float
    #: 置信度过低时前端直接退回手填表单，不拿一份瞎猜的结构去配队。
    fall_back_to_form: bool

    @classmethod
    def of(
        cls, extraction: Extraction, conflicts: tuple[Conflict, ...], *, threshold: float
    ) -> CompileResponse:
        return cls(
            content=IntentContentOut.of(extraction.content),
            follow_ups=[FollowUpOut.of(q) for q in extraction.follow_ups],
            conflicts=[ConflictOut.of(c) for c in conflicts],
            confidence=extraction.confidence,
            fall_back_to_form=extraction.confidence < threshold,
        )


class IntentOut(BaseModel):
    id: UUID
    principal_id: UUID
    state: str
    raw_expression: str
    content: IntentContentOut
    created_at: datetime
    expires_at: datetime | None = None
    is_matchable: bool
    #: 它属于哪张场景卡。撮合窗口长度由它决定，界面上要据此说
    #: "明早 8 点开始配队"。
    action_kind: str | None = None

    @classmethod
    def of(cls, signal: IntentSignal) -> IntentOut:
        return cls(
            id=signal.id,
            principal_id=signal.principal_id,
            state=signal.state.value,
            raw_expression=signal.raw_expression,
            content=IntentContentOut.of(signal.content),
            created_at=signal.created_at,
            expires_at=signal.expires_at,
            is_matchable=signal.is_matchable,
            action_kind=signal.action_kind,
        )


class CreateIntentRequest(BaseModel):
    expression: Annotated[str, Field(min_length=1, max_length=2000)]
    content: IntentContentIn
    #: 挑了哪张场景卡。**可以不挑**——首屏有卡但也能直接写一句话，
    #: 不挑的那一拨按默认窗口清算，不能因为"没归类"就永远不撮合。
    action_kind: str | None = None
    #: 还没想清楚就先存着。念头只对本人可见，不参与撮合，也不进任何公共列表。
    stash: bool = False


class ReviseIntentRequest(BaseModel):
    content: IntentContentIn


class StarterOut(BaseModel):
    key: str
    title: str
    #: 一句完整的好例子，不是"请输入…"——它同时告诉用户什么表达能被接住。
    example: str
    roles: list[str] = []


class ActionKindOut(BaseModel):
    key: str
    label: str
    starter: StarterOut
    risk_tier: str
    place_precision: str
    agent_reply_policy: str
    matching_window_seconds: int

    @classmethod
    def of(cls, kind: ActionKind) -> ActionKindOut:
        return cls(
            key=kind.key,
            label=kind.label,
            starter=StarterOut(
                key=kind.key,
                title=kind.starter.title,
                example=kind.starter.example,
                roles=list(kind.seat_model.roles),
            ),
            risk_tier=kind.risk_tier.value,
            place_precision=kind.place_precision.value,
            agent_reply_policy=kind.agent_reply_policy.value,
            matching_window_seconds=int(kind.matching_window.total_seconds()),
        )
