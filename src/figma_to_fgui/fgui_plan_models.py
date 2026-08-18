from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from figma_to_fgui.models import Bounds, Diagnostic, FrozenModel

_FORBIDDEN_BINDING_FIELDS = frozenset({"packageId", "componentId", "src", "pkg"})
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class FrozenDict(dict[str, Any]):
    """A dict-compatible mapping that rejects all ordinary mutation methods."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("mapping is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable  # type: ignore[assignment]
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable  # type: ignore[assignment]


def _freeze_mapping(value: Mapping[str, Any]) -> FrozenDict:
    return FrozenDict(
        {key: _freeze_nested(value[key]) for key in sorted(value)}
    )


def _freeze_nested(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_nested(item) for item in value)
    if isinstance(value, (set, frozenset)):
        frozen_items = (_freeze_nested(item) for item in value)
        return tuple(sorted(frozen_items, key=_stable_sort_key))
    return value


def _stable_sort_key(value: Any) -> str:
    """Order frozen set members without depending on hash iteration order."""
    return f"{type(value).__module__}.{type(value).__qualname__}:{value!r}"


def _reject_binding_fields(value: Any) -> Any:
    """Reject target-project binding keys even when nested in an opaque fact map."""
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in _FORBIDDEN_BINDING_FIELDS:
                raise ValueError(f"project binding field is not allowed: {key}")
            _reject_binding_fields(nested)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for nested in value:
            _reject_binding_fields(nested)
    return value


class PlanModel(FrozenModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
    )

    @model_validator(mode="before")
    @classmethod
    def reject_project_binding_fields(cls, value: Any) -> Any:
        return _reject_binding_fields(value)


class CapabilityStatus(StrEnum):
    NATIVE = "native"
    RASTER_FALLBACK = "rasterFallback"
    UNSUPPORTED = "unsupported"


class PlanNodeType(StrEnum):
    CONTAINER = "container"
    TEXT = "text"
    RICH_TEXT = "richText"
    IMAGE = "image"
    LOADER = "loader"
    COMPONENT_REFERENCE = "componentReference"
    RASTER_SUBTREE = "rasterSubtree"


class MaskMode(StrEnum):
    NATIVE_CLIP = "nativeClip"
    NATIVE_MASK = "nativeMask"
    RASTER_SUBTREE = "rasterSubtree"


class MaskKind(StrEnum):
    RECTANGLE = "rectangle"
    ROUNDED_RECTANGLE = "roundedRectangle"
    IMAGE = "image"
    BOOLEAN = "boolean"
    GRADIENT = "gradient"
    BLUR = "blur"
    BLEND = "blend"


class TransformPlan(PlanModel):
    bounds: Bounds
    rotation: float = 0
    opacity: float = Field(default=1, ge=0, le=1)


class TextPlan(PlanModel):
    content: str
    font_candidates: tuple[str, ...] = Field(default=(), alias="fontCandidates")
    font_size: float | None = Field(default=None, alias="fontSize", gt=0)
    color: str | None = None
    horizontal_align: str | None = Field(default=None, alias="horizontalAlign")
    vertical_align: str | None = Field(default=None, alias="verticalAlign")
    style_facts: dict[str, object] = Field(default_factory=dict, alias="styleFacts")

    @field_validator("style_facts", mode="after")
    @classmethod
    def freeze_style_facts(cls, value: dict[str, object]) -> dict[str, object]:
        return _freeze_mapping(value)


class ResourcePlan(PlanModel):
    id: str
    source_asset_ref: str = Field(alias="sourceAssetRef")
    mime_type: str = Field(alias="mimeType")
    export_format: Literal["png", "jpg", "webp"] = Field(alias="exportFormat")
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    nine_slice: tuple[int, int, int, int] | None = Field(default=None, alias="nineSlice")
    consumers: tuple[str, ...]
    reason: str | None = None


class ComponentReferencePlan(PlanModel):
    candidate_key: str = Field(alias="candidateKey")
    variant_properties: dict[str, str] = Field(default_factory=dict, alias="variantProperties")

    @field_validator("variant_properties", mode="after")
    @classmethod
    def freeze_variant_properties(cls, value: dict[str, str]) -> dict[str, str]:
        return _freeze_mapping(value)


class MaskPlan(PlanModel):
    id: str
    mode: MaskMode
    kind: MaskKind
    mask_node_ref: str = Field(alias="maskNodeRef")
    content_node_refs: tuple[str, ...] = Field(alias="contentNodeRefs")
    resource_ref: str | None = Field(default=None, alias="resourceRef")


class CapabilityDecision(PlanModel):
    id: str
    node_ref: str = Field(alias="nodeRef")
    status: CapabilityStatus
    rule_id: str = Field(alias="ruleId")
    rule_version: int = Field(alias="ruleVersion", ge=1)
    evidence: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    blocking: bool = False


class FGUIPlanNode(PlanModel):
    id: str
    uir_node_ref: str = Field(alias="uirNodeRef")
    parent_id: str | None = Field(default=None, alias="parentId")
    children: tuple[str, ...] = ()
    z_index: int = Field(alias="zIndex", ge=0)
    type: PlanNodeType
    transform: TransformPlan
    text: TextPlan | None = None
    resource_ref: str | None = Field(default=None, alias="resourceRef")
    component: ComponentReferencePlan | None = None
    mask_ref: str | None = Field(default=None, alias="maskRef")
    decision_ref: str | None = Field(default=None, alias="decisionRef")


class FGUIPlanDocument(PlanModel):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    document_id: str = Field(alias="documentId")
    source_uir_sha256: str = Field(alias="sourceUirSha256", pattern=SHA256_PATTERN)
    profile_version: str = Field(alias="profileVersion")
    rule_version: int = Field(alias="ruleVersion", ge=1)
    bindable: bool
    roots: tuple[str, ...]
    nodes: dict[str, FGUIPlanNode]
    resources: dict[str, ResourcePlan] = Field(default_factory=dict)
    masks: dict[str, MaskPlan] = Field(default_factory=dict)
    decisions: dict[str, CapabilityDecision] = Field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()

    @field_validator("nodes", "resources", "masks", "decisions", mode="after")
    @classmethod
    def freeze_document_mappings(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _freeze_mapping(value)
