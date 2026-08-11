"""受限协商。

两句话：**代理只能说七种话，没有一种构成同意**；**"交还给真人"用的是 A2A
协议自己的中断态，不是我们自研的状态机**（ADR 0004）。

这一层负责怎么谈。谈的结果算不算数，是确认门的事。
"""

from cofield.negotiation.messages import (
    DISCLOSURE_LABEL,
    MAX_NOTE_CHARS,
    ConditionalResponse,
    Conflict,
    ConsentRequest,
    ConstraintIntersection,
    DisclosureDenied,
    EvidenceCitation,
    HumanOnlyDecision,
    MessageKind,
    ProposalRevision,
    RestrictedMessage,
    SpeakerMode,
    Topic,
    UnsupportedMessageKind,
    Utterance,
    disclosed,
    from_a2a,
    to_a2a,
)
from cofield.negotiation.session import (
    MAX_ROUNDS,
    Difference,
    HandedBackToHuman,
    NegotiationClosed,
    NegotiationSession,
    NotCitable,
    ReciprocalView,
    Standing,
    TooManyRounds,
)

__all__ = [
    "DISCLOSURE_LABEL",
    "MAX_NOTE_CHARS",
    "MAX_ROUNDS",
    "ConditionalResponse",
    "Conflict",
    "ConsentRequest",
    "ConstraintIntersection",
    "Difference",
    "DisclosureDenied",
    "EvidenceCitation",
    "HandedBackToHuman",
    "HumanOnlyDecision",
    "MessageKind",
    "NegotiationClosed",
    "NegotiationSession",
    "NotCitable",
    "ProposalRevision",
    "ReciprocalView",
    "RestrictedMessage",
    "SpeakerMode",
    "Standing",
    "TooManyRounds",
    "Topic",
    "UnsupportedMessageKind",
    "Utterance",
    "disclosed",
    "from_a2a",
    "to_a2a",
]
