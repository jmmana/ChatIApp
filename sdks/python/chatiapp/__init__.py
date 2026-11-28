"""Cliente oficial de Python para ChatIApp.

Los modelos de la API (`_generated`) salen de `docs/openapi/v1.json`; el cliente de chat, el
streaming y los eventos están escritos a mano.
"""

from ._generated import SPEC_VERSION, CancelOut, EmbedSessionOut, EmbedSessionRequest, EndUser
from .client import ChatIApp
from .errors import ChatIAppError
from .events import (
    AnswerDeltaEvent,
    AnswerEvent,
    ClarificationEvent,
    ErrorEvent,
    ReasoningEvent,
    ResultEvent,
    SqlEvent,
    StepEvent,
    StreamEvent,
    TurnCompletedEvent,
    TurnStartedEvent,
    UnknownEvent,
)
from .models import Turn

__all__ = [
    "SPEC_VERSION",
    "AnswerDeltaEvent",
    "AnswerEvent",
    "CancelOut",
    "ChatIApp",
    "ChatIAppError",
    "ClarificationEvent",
    "EmbedSessionOut",
    "EmbedSessionRequest",
    "EndUser",
    "ErrorEvent",
    "ReasoningEvent",
    "ResultEvent",
    "SqlEvent",
    "StepEvent",
    "StreamEvent",
    "Turn",
    "TurnCompletedEvent",
    "TurnStartedEvent",
    "UnknownEvent",
]
