from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

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
    PACKAGING = "packaging"
    READY = "ready"
    FAILED = "failed"


class VersionedModel(FrozenModel):
    version: Literal[1] = PROTOCOL_VERSION


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


class ProjectPackageView(VersionedModel):
    job_id: str
    status: ProjectPackageStage
    stage: ProjectPackageStage
    progress: int = Field(ge=0, le=100)
    download_name: str | None = None
    sha256: Sha256 | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    diagnostics: tuple[Diagnostic, ...] = ()


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
