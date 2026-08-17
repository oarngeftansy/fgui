from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Severity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class DecisionSource(StrEnum):
    AI = "AI"
    RULE = "RULE"
    FALLBACK = "FALLBACK"


class SemanticType(StrEnum):
    PANEL = "Panel"
    COMPONENT = "Component"
    IMAGE = "Image"
    TEXT = "Text"
    BUTTON = "Button"
    LABEL = "Label"
    LIST = "List"
    SLIDER = "Slider"


class Bounds(FrozenModel):
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class Diagnostic(FrozenModel):
    code: str
    severity: Severity
    message: str
    node_id: str | None = None
    path: str | None = None
    rule_id: str | None = None
    rule_version: int | None = None


class NormalizedNode(FrozenModel):
    id: str
    name: str
    type: str
    bounds: Bounds
    children: tuple[NormalizedNode, ...] = ()
    text: str | None = None
    rotation: float = 0
    opacity: float = Field(default=1, ge=0, le=1)
    visible: bool = True
    source_order: int = 0
    properties: dict[str, Any] = Field(default_factory=dict)
    raw_style: dict[str, Any] = Field(default_factory=dict)


class NineSliceGrid(FrozenModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ProjectResource(FrozenModel):
    id: str
    name: str
    kind: str
    package_id: str
    relative_path: str
    scale9grid: NineSliceGrid | None = None


class ClassificationDecision(FrozenModel):
    node_id: str
    output_type: str
    rule_id: str
    rule_version: int
    evidence: tuple[str, ...]
    confidence: float = Field(ge=0, le=1)
    source: DecisionSource = DecisionSource.RULE
    semantic_name: str | None = None
    semantic_type: SemanticType | None = None


class ResourcePlan(FrozenModel):
    node_id: str
    action: str
    resource_name: str
    resource_id: str
    relative_path: str


class GeneratedFile(FrozenModel):
    relative_path: str
    sha256: str
    size: int = Field(ge=0)


class ChangeSet(FrozenModel):
    version: int = 1
    applicable: bool
    source_snapshot_sha256: str
    files: tuple[GeneratedFile, ...]
    diagnostics: tuple[Diagnostic, ...]
