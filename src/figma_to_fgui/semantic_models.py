from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from figma_to_fgui.models import (
    ClassificationDecision,
    DecisionSource,
    Diagnostic,
    FrozenModel,
)

__all__ = [
    "DecisionSource",
    "ReparentSuggestion",
    "SemanticAnalysisOutcome",
    "SemanticDecision",
    "SemanticResponse",
    "SemanticType",
]


class SemanticType(StrEnum):
    PANEL = "Panel"
    COMPONENT = "Component"
    IMAGE = "Image"
    TEXT = "Text"
    BUTTON = "Button"
    LABEL = "Label"
    LIST = "List"
    SLIDER = "Slider"


class ReparentSuggestion(FrozenModel):
    new_parent: str = Field(min_length=1, max_length=160)


class SemanticDecision(FrozenModel):
    node_id: str = Field(min_length=1, max_length=160)
    semantic_type: SemanticType
    fgui_name: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$",
    )
    children_roles: dict[str, Literal["title", "icon", "bar", "grip", "bg"]] = Field(
        default_factory=dict
    )
    state_pages: dict[str, str] = Field(default_factory=dict)
    reparent: ReparentSuggestion | None = None
    confidence: float = Field(ge=0, le=1)
    risks: tuple[str, ...] = ()


class SemanticResponse(FrozenModel):
    version: Literal[1] = 1
    decisions: tuple[SemanticDecision, ...]
    screenshot_recommended: bool = False
    screenshot_reason: str | None = Field(default=None, max_length=240)


class SemanticAnalysisOutcome(FrozenModel):
    overrides: tuple[ClassificationDecision, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    screenshot_recommended: bool = False
    screenshot_reason: str | None = Field(default=None, max_length=240)
