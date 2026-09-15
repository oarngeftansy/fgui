from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from figma_to_fgui.service_contracts import Sha256, StrictVersionedModel

HifiMappingStatus = Literal["matched", "suggested", "uncertain", "fgui_only", "hifi_added", "blocked"]
HifiMappingAction = Literal["accept", "retarget", "keep_old", "add_visual", "exception"]


class HifiTargetRef(StrictVersionedModel):
    project_id: str = Field(min_length=1, max_length=128)
    project_fingerprint: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    package_id: str = Field(min_length=1, max_length=128)
    package_name: str = Field(min_length=1, max_length=256)
    directory: str = Field(min_length=1, max_length=1024)
    component_id: str = Field(min_length=1, max_length=128)
    component_name: str = Field(min_length=1, max_length=256)
    component_relative_path: str = Field(min_length=1, max_length=2048)


class HifiComponentOption(StrictVersionedModel):
    resource_id: str
    name: str
    relative_path: str
    selectable: bool = True
    reason: str | None = None


class HifiDirectoryOption(StrictVersionedModel):
    path: str
    selectable: bool = True
    reason: str | None = None
    components: tuple[HifiComponentOption, ...] = ()


class HifiPackageOption(StrictVersionedModel):
    package_id: str
    name: str
    directories: tuple[HifiDirectoryOption, ...] = ()


class HifiProjectTreeView(StrictVersionedModel):
    project_id: str
    project_fingerprint: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    packages: tuple[HifiPackageOption, ...]


class FguiObjectRef(StrictVersionedModel):
    object_id: str
    name: str
    object_type: str
    parent_id: str | None = None
    child_index: int = Field(ge=0)
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)
    resource_id: str | None = None
    shared_resource: bool = False
    protected_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    controller_refs: tuple[str, ...] = ()
    transition_refs: tuple[str, ...] = ()
    relation_refs: tuple[str, ...] = ()
    unknown_attributes: tuple[str, ...] = ()


class FguiComponentInventory(StrictVersionedModel):
    target: HifiTargetRef
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    objects: tuple[FguiObjectRef, ...]
    unknown_tags: tuple[str, ...] = ()
    parse_complete: bool


class HifiMappingEvidence(StrictVersionedModel):
    name_score: float = Field(ge=0, le=1)
    position_score: float = Field(ge=0, le=1)
    size_score: float = Field(ge=0, le=1)
    type_score: float = Field(ge=0, le=1)
    parent_score: float = Field(ge=0, le=1)
    order_score: float = Field(ge=0, le=1)


class HifiMappingItem(StrictVersionedModel):
    item_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    old_object_id: str | None = None
    old_name: str | None = None
    figma_node_id: str | None = None
    figma_name: str | None = None
    status: HifiMappingStatus
    score: float = Field(ge=0, le=1)
    evidence: HifiMappingEvidence
    action: HifiMappingAction | None = None
    candidates: tuple[str, ...] = ()
    old_bounds: tuple[float, float, float, float] | None = None
    figma_bounds: tuple[float, float, float, float] | None = None


class HifiMappingDecision(StrictVersionedModel):
    mapping_revision: int = Field(ge=1)
    item_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    action: HifiMappingAction
    figma_node_id: str | None = Field(default=None, max_length=256)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_action_node(self) -> Self:
        if self.action == "retarget" and self.figma_node_id is None:
            raise ValueError("retarget requires figma_node_id")
        if self.action != "retarget" and self.figma_node_id is not None:
            raise ValueError("figma_node_id is only valid for retarget")
        return self


class HifiMappingDraft(StrictVersionedModel):
    mapping_revision: int = Field(ge=1)
    items: tuple[HifiMappingItem, ...]
    unresolved_count: int = Field(ge=0)


class HifiDiffItem(StrictVersionedModel):
    relative_path: str
    operation: Literal["create", "replace"]
    before_sha256: Sha256 | None = None
    after_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    summary: str


class HifiObjectDiff(StrictVersionedModel):
    item_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    kind: Literal["changed", "added", "kept", "exception"]
    old_object_id: str | None = Field(default=None, max_length=128)
    old_name: str | None = Field(default=None, max_length=256)
    figma_node_id: str | None = Field(default=None, max_length=256)
    figma_name: str | None = Field(default=None, max_length=256)
    changed_fields: tuple[str, ...] = ()
    summary: str = Field(min_length=1, max_length=500)


class HifiReplacementReview(StrictVersionedModel):
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    mapping_revision: int = Field(ge=1)
    target: HifiTargetRef
    changed_files: tuple[HifiDiffItem, ...]
    object_diffs: tuple[HifiObjectDiff, ...]
    protected_checks_passed: bool
    parse_coverage_complete: bool
    approvable: bool
    candidate_sha256: Sha256 | None = None
    warnings: tuple[str, ...] = ()
    editor_check_required: bool = True


class HifiReplacementView(StrictVersionedModel):
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    status: Literal[
        "mapping", "building", "review_ready", "approved", "rejected", "failed", "superseded"
    ]
    selection_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    target: HifiTargetRef
    mapping_revision: int = Field(ge=1)
    unresolved_count: int = Field(ge=0)
    artifact_ready: bool = False


class HifiReplacementCreate(StrictVersionedModel):
    project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    selection_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    target: HifiTargetRef
    idempotency_key: str = Field(min_length=1, max_length=200)


class HifiReplacementBuildRequest(StrictVersionedModel):
    mapping_revision: int = Field(ge=1)


class HifiEditorChecks(StrictVersionedModel):
    layout_checked: bool
    references_checked: bool
    interactions_checked: bool
    editor_version: Literal["6.1.4"]
    candidate_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_every_check(self) -> Self:
        if not (self.layout_checked and self.references_checked and self.interactions_checked):
            raise ValueError("all editor checks are required")
        return self


class HifiReplacementRejectRequest(StrictVersionedModel):
    reason: str = Field(min_length=1, max_length=500)
