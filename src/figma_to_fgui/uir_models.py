from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import ConfigDict, Field

from figma_to_fgui.models import Bounds, Diagnostic, FrozenModel

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class UIRModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class SemanticStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    FALLBACK = "fallback"


class ConversionMode(StrEnum):
    NATIVE = "native"
    COMPONENT_REFERENCE = "componentReference"
    EXISTING_RESOURCE = "existingResource"
    RASTER_FALLBACK = "rasterFallback"
    UNSUPPORTED = "unsupported"


class MappingStatus(StrEnum):
    VERIFIED = "verified"
    MISSING = "missing"
    CONFLICT = "conflict"


class UIRSource(UIRModel):
    kind: Literal["figma"] = "figma"
    revision: str = Field(pattern=SHA256_PATTERN)
    selection_id: str = Field(alias="selectionId", min_length=1, max_length=256)


class UIRNodeSource(UIRModel):
    node_id: str = Field(alias="nodeId", min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=64)
    name: str = Field(max_length=256)
    fingerprint: str = Field(pattern=SHA256_PATTERN)


class UIRGeometry(UIRModel):
    resolved_bounds: Bounds = Field(alias="resolvedBounds")
    local_transform: tuple[float, float, float, float, float, float] | None = Field(
        default=None, alias="localTransform"
    )
    rotation: float = 0
    opacity: float = Field(default=1, ge=0, le=1)


class UIRSemantic(UIRModel):
    name: str | None = Field(default=None, max_length=128)
    role: str | None = Field(default=None, max_length=64)
    status: SemanticStatus = SemanticStatus.CANDIDATE
    decision_ref: str | None = Field(default=None, alias="decisionRef")


class UIRConversion(UIRModel):
    mode: ConversionMode
    reasons: tuple[str, ...] = ()
    asset_ref: str | None = Field(default=None, alias="assetRef")


class UIRComponentInstance(UIRModel):
    definition_ref: str | None = Field(default=None, alias="definitionRef")
    variant_properties: dict[str, str] = Field(
        default_factory=dict, alias="variantProperties"
    )
    overrides: dict[str, Any] = Field(default_factory=dict)


class UIRNode(UIRModel):
    id: str = Field(min_length=1, max_length=128)
    source: UIRNodeSource
    semantic: UIRSemantic
    parent_id: str | None = Field(default=None, alias="parentId")
    children: tuple[str, ...] = ()
    z_index: int = Field(alias="zIndex", ge=0)
    geometry: UIRGeometry
    layout: dict[str, Any] = Field(default_factory=dict)
    visual: dict[str, Any] = Field(default_factory=dict)
    text: dict[str, Any] | None = None
    component: UIRComponentInstance | None = None
    interactions: tuple[dict[str, Any], ...] = ()
    conversion: UIRConversion


class UIRComponentDefinition(UIRModel):
    id: str = Field(min_length=1, max_length=128)
    source_node_id: str = Field(alias="sourceNodeId", min_length=1, max_length=128)
    name: str = Field(max_length=256)
    properties: dict[str, Any] = Field(default_factory=dict)


class UIRNineSlice(UIRModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class UIRAsset(UIRModel):
    id: str = Field(min_length=1, max_length=128)
    logical_id: str = Field(alias="logicalId", min_length=1, max_length=256)
    mime_type: str = Field(alias="mimeType", min_length=1, max_length=128)
    sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    source_node_id: str | None = Field(
        default=None, alias="sourceNodeId", max_length=128
    )
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    nine_slice: UIRNineSlice | None = Field(default=None, alias="nineSlice")
    export_format: Literal["png", "jpg", "webp"] = Field(
        default="png", alias="exportFormat"
    )


class UIRMappingDecision(UIRModel):
    id: str = Field(min_length=1, max_length=128)
    candidate_key: str = Field(alias="candidateKey", min_length=1, max_length=128)
    status: MappingStatus
    evidence: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)
    rule_source: str = Field(alias="ruleSource", min_length=1, max_length=256)
    human_decision: str | None = Field(
        default=None, alias="humanDecision", max_length=256
    )


class UIRDocument(UIRModel):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    document_id: str = Field(alias="documentId", min_length=1, max_length=128)
    compiler_version: str = Field(alias="compilerVersion", min_length=1, max_length=64)
    source: UIRSource
    roots: tuple[str, ...]
    nodes: dict[str, UIRNode]
    component_definitions: dict[str, UIRComponentDefinition] = Field(
        default_factory=dict, alias="componentDefinitions"
    )
    assets: dict[str, UIRAsset] = Field(default_factory=dict)
    mapping_decisions: dict[str, UIRMappingDecision] = Field(
        default_factory=dict, alias="mappingDecisions"
    )
    diagnostics: tuple[Diagnostic, ...] = ()
