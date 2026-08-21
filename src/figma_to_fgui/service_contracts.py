from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from figma_to_fgui.models import Diagnostic, FrozenModel
from figma_to_fgui.paths import safe_relative_path

PROTOCOL_VERSION: Literal[1] = 1
Sha256 = str


class JobStatus(StrEnum):
    CREATED = "created"
    READY_FOR_REVIEW = "ready_for_review"
    CONVERSION_FAILED = "conversion_failed"
    APPROVED = "approved"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"
    REJECTED = "rejected"


class FileOperation(StrEnum):
    CREATE = "create"
    REPLACE = "replace"


class ApplyStatus(StrEnum):
    APPLIED = "applied"
    FAILED = "failed"


class ProjectPackageStage(StrEnum):
    UPLOADING = "uploading"
    PARSING = "parsing"
    CONVERTING = "converting"
    CHECKING = "checking"
    AWAITING_SCREENSHOT_CONSENT = "awaiting_screenshot_consent"
    PACKAGING = "packaging"
    READY = "ready"
    FAILED = "failed"


class VersionedModel(FrozenModel):
    version: Literal[1] = PROTOCOL_VERSION


class StrictVersionedModel(VersionedModel):
    """Versioned wire input/output that never relies on Python coercion."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False, strict=True)

    @field_validator("version", mode="before")
    @classmethod
    def validate_exact_version(cls, value: object) -> object:
        if type(value) is not int or value != PROTOCOL_VERSION:
            raise ValueError("version must be the builtin integer 1")
        return value


class PairingCodeView(VersionedModel):
    code: str = Field(pattern=r"^\d{6}$")
    expires_at: datetime
    console_credential: str = Field(min_length=20)


class PairingExchange(VersionedModel):
    code: str
    device_name: str = Field(min_length=1, max_length=120)


class FigmaDeviceView(VersionedModel):
    device_id: str
    device_name: str
    created_at: datetime
    revoked_at: datetime | None = None


class ConsolePairingStatusView(VersionedModel):
    state: Literal["waiting_for_device", "paired"]
    expires_at: datetime
    device: FigmaDeviceView | None = None


class PluginCredentialView(VersionedModel):
    credential: str
    device: FigmaDeviceView


class PluginScope(StrEnum):
    SELECTION_UPLOAD = "selection:upload"
    SELECTION_READ_OWN_STATUS = "selection:read-own-status"


class PluginPrincipal(FrozenModel):
    device_id: str
    scopes: tuple[PluginScope, ...] = ()


class ChangeFile(FrozenModel):
    operation: FileOperation
    relative_path: str
    before_sha256: Sha256 | None = None
    after_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    content_b64: str

    @model_validator(mode="after")
    def validate_operation(self) -> Self:
        object.__setattr__(self, "relative_path", safe_relative_path(self.relative_path))
        if self.operation is FileOperation.REPLACE and self.before_sha256 is None:
            raise ValueError("replace operation requires before_sha256")
        if self.operation is FileOperation.CREATE and self.before_sha256 is not None:
            raise ValueError("create operation forbids before_sha256")
        if self.before_sha256 is not None and len(self.before_sha256) != 64:
            raise ValueError("before_sha256 must be a SHA-256 digest")
        return self


class ChangeBundle(VersionedModel):
    job_id: str
    project_id: str
    files: tuple[ChangeFile, ...]


class AgentRegistration(VersionedModel):
    agent_id: str
    name: str


class ProjectBinding(VersionedModel):
    project_id: str
    agent_id: str


class JobCreate(VersionedModel):
    fixture_name: str
    project_id: str
    package_name: str


class ProjectJobCreate(VersionedModel):
    project_id: str
    package_name: str
    fixture_name: str


class SelectionProjectJobCreate(VersionedModel):
    selection_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    project_id: str
    package_name: str


class PackageView(FrozenModel):
    name: str
    resource_count: int = Field(ge=0)


class ProjectUploadView(VersionedModel):
    project_id: str
    display_name: str
    packages: tuple[PackageView, ...]


class TemplateOption(FrozenModel):
    template_id: str
    fairygui_version: str
    target_platform: str
    display_name: str


class ProjectOptionsView(VersionedModel):
    options: tuple[TemplateOption, ...]


class CreateTemplateProject(VersionedModel):
    template_id: str
    project_name: str = Field(pattern=r"^[\w\-\u4e00-\u9fff]{1,64}$")


class ProjectPackageRequest(VersionedModel):
    mode: Literal["create", "update"]
    project_name: str = Field(pattern=r"^[\w\-\u4e00-\u9fff]{1,64}$")


class ScreenshotConsentRequest(VersionedModel):
    approved: bool


class NewFguiProjectRequest(StrictVersionedModel):
    project_name: str = Field(pattern=r"^[\w\-\u4e00-\u9fff]{1,64}$")


class NewFguiProjectStage(StrEnum):
    CONVERTING = "converting"
    CHECKING = "checking"
    PACKAGING = "packaging"
    AWAITING_REVIEW = "awaiting_review"
    ADJUSTING = "adjusting"
    REGENERATING = "regenerating"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class NewFguiProjectView(StrictVersionedModel):
    build_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    generation: int = Field(default=1, ge=1)
    status: Literal[
        "converting",
        "checking",
        "packaging",
        "awaiting_review",
        "adjusting",
        "regenerating",
        "approved",
        "rejected",
        "failed",
    ]
    stage: Literal[
        "converting",
        "checking",
        "packaging",
        "awaiting_review",
        "adjusting",
        "regenerating",
        "approved",
        "rejected",
        "failed",
    ]
    progress: int = Field(ge=0, le=100)
    download_name: str | None = Field(
        default=None, min_length=1, max_length=160, pattern=r"^[\w\-\u4e00-\u9fff]+-FairyGUI\.zip$"
    )
    sha256: Sha256 | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    byte_size: int | None = Field(default=None, ge=0)
    diagnostics: tuple[Diagnostic, ...] = ()

    @model_validator(mode="after")
    def validate_stage_and_artifact(self) -> Self:
        if self.status != self.stage:
            raise ValueError("new-project status and stage must match")
        artifact_fields = (self.download_name, self.sha256, self.byte_size)
        if any(item is None for item in artifact_fields) != all(
            item is None for item in artifact_fields
        ):
            raise ValueError("new-project artifact metadata must be complete")
        return self


class NewProjectAdjustmentStrategy(StrEnum):
    PRESERVE_EDITABLE = "preserve-editable"
    RASTERIZE_SUBTREE = "rasterize-subtree"
    INCLUDE_CONTAINED_DEFINITION = "include-contained-definition"


class NewProjectDispositionLevel(StrEnum):
    NATIVE = "native"
    RASTER_PRESERVED = "raster_preserved"
    EDITABLE_RISK = "editable_risk"
    BLOCKED = "blocked"


class NewProjectDispositionReason(StrEnum):
    GRADIENT_PAINT = "gradient_paint"
    VISUAL_EFFECT = "visual_effect"
    MASK_COMPOSITE = "mask_composite"
    INSTANCE_COMPOSITE = "instance_composite"
    VISUAL_STYLE = "visual_style"
    UNREPRESENTABLE_TRANSFORM = "unrepresentable_transform"
    RICH_TEXT_RUNS = "rich_text_runs"
    COMPONENT_DEFINITION_MISSING = "component_definition_missing"
    INTERACTION_UNSUPPORTED = "interaction_unsupported"
    RESOURCE_MISSING = "resource_missing"


class NewProjectConversionDisposition(StrictVersionedModel):
    id: str = Field(pattern=r"^disposition:[0-9a-f]{16}$")
    source_node_id: str = Field(
        alias="sourceNodeId", min_length=1, max_length=256, pattern=r".*\S.*"
    )
    source_name: str = Field(
        alias="sourceName", min_length=1, max_length=160, pattern=r".*\S.*"
    )
    source_type: str = Field(
        alias="sourceType", min_length=1, max_length=64, pattern=r"^[A-Z_]+$"
    )
    level: NewProjectDispositionLevel
    reason: NewProjectDispositionReason
    default_strategy: NewProjectAdjustmentStrategy | None = Field(alias="defaultStrategy")
    allowed_strategies: tuple[NewProjectAdjustmentStrategy, ...] = Field(
        alias="allowedStrategies"
    )
    visual_impact: Literal["unchanged", "visual_preserved", "may_differ"] = Field(
        alias="visualImpact"
    )
    editability_impact: Literal[
        "unchanged", "subtree_not_editable", "text_not_editable"
    ] = Field(alias="editabilityImpact")
    component_impact: Literal["unchanged", "instance_not_reusable"] = Field(
        alias="componentImpact"
    )
    blocks_approval: bool = Field(alias="blocksApproval")

    @model_validator(mode="after")
    def validate_strategy_and_level(self) -> Self:
        if len(self.allowed_strategies) != len(set(self.allowed_strategies)):
            raise ValueError("allowed disposition strategies must be unique")
        if (self.default_strategy is None) != (not self.allowed_strategies):
            raise ValueError("default disposition strategy must match the allowed set")
        if (
            self.default_strategy is not None
            and self.default_strategy not in self.allowed_strategies
        ):
            raise ValueError("default disposition strategy must be allowed")
        if self.blocks_approval != (self.level is NewProjectDispositionLevel.BLOCKED):
            raise ValueError("only blocked dispositions block approval")
        return self


class NewProjectIssueKind(StrEnum):
    RASTER_FALLBACK = "raster-fallback"
    DEFINITION_MISSING = "definition-missing"


class NewProjectAdjustment(StrictVersionedModel):
    issue_id: str = Field(
        alias="issueId", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    source_node_id: str = Field(
        alias="sourceNodeId", min_length=1, max_length=256, pattern=r".*\S.*"
    )
    issue_kind: NewProjectIssueKind = Field(alias="issueKind")
    strategy: NewProjectAdjustmentStrategy


class NewProjectAdjustmentRequest(StrictVersionedModel):
    candidate_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    generation: int = Field(ge=1)
    issue_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    uir_node_id: str = Field(min_length=1, max_length=256, pattern=r".*\S.*")
    strategy: NewProjectAdjustmentStrategy


class NewProjectRegenerateRequest(StrictVersionedModel):
    generation: int = Field(ge=1)


class NewProjectApprovalRequest(StrictVersionedModel):
    generation: int = Field(ge=1)
    warning_ids: tuple[str, ...] = ()

    @field_validator("warning_ids")
    @classmethod
    def validate_warning_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(
            not item or len(item) > 128 or re.fullmatch(r"[A-Za-z0-9_.:-]+", item) is None
            for item in value
        ):
            raise ValueError("warning_ids must be unique public check IDs")
        return value


class NewProjectRejectRequest(StrictVersionedModel):
    generation: int = Field(ge=1)


class ProjectPackageView(VersionedModel):
    job_id: str
    status: ProjectPackageStage
    stage: ProjectPackageStage
    progress: int = Field(ge=0, le=100)
    download_name: str | None = None
    sha256: Sha256 | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    screenshot_reason: str | None = Field(default=None, min_length=1, max_length=240)
    diagnostics: tuple[Diagnostic, ...] = ()

    @field_validator("screenshot_reason", mode="before")
    @classmethod
    def normalize_screenshot_reason(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None


class JobSummary(VersionedModel):
    job_id: str
    project_id: str
    status: JobStatus


class JobView(VersionedModel):
    job_id: str
    project_id: str
    project_fingerprint: Sha256 | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    package_names: tuple[str, ...] = ()
    status: JobStatus
    diagnostics: tuple[Diagnostic, ...] = ()
    artifact_sha256: Sha256 | None = None


class ApplyResult(VersionedModel):
    job_id: str
    agent_id: str
    project_id: str
    status: ApplyStatus
    changed_paths: tuple[str, ...] = ()
    rollback_succeeded: bool | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
