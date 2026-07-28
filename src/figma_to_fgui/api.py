from __future__ import annotations

import base64
import hashlib
import os
import shutil
import tempfile
import uuid
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from figma_to_fgui.artifacts import ArtifactIntegrityError, ArtifactStore
from figma_to_fgui.designer_preview import (
    DesignerPreview,
    build_designer_preview,
    is_designer_image,
)
from figma_to_fgui.job_store import JobStore, NotFound, StoreError
from figma_to_fgui.models import Diagnostic, Severity
from figma_to_fgui.pipeline import ConversionRequest, convert
from figma_to_fgui.project_store import ProjectIntegrityError, ProjectStore
from figma_to_fgui.project_upload import (
    DEFAULT_UPLOAD_LIMITS,
    UploadError,
    _upload_error,
    extract_project_zip,
)
from figma_to_fgui.service_contracts import (
    AgentRegistration,
    ApplyResult,
    ChangeBundle,
    ChangeFile,
    FileOperation,
    JobCreate,
    JobStatus,
    JobSummary,
    JobView,
    PackageView,
    ProjectBinding,
    ProjectJobCreate,
    ProjectUploadView,
)
from figma_to_fgui.uploaded_project import UploadedProjectVersion, index_uploaded_project

_UPLOAD_CHUNK_BYTES = 64 * 1024
_PROJECT_NOT_FOUND_MESSAGE = "鎵句笉鍒拌繖涓?FairyGUI 宸ョ▼銆?"
_ASSET_NOT_FOUND_MESSAGE = "鎵句笉鍒拌繖寮犻瑙堝浘鐗囥€俙"


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def create_app(data_dir: Path, fixtures_root: Path, rules_path: Path) -> FastAPI:
    store = JobStore(data_dir / "server.db")
    store.initialize()
    artifacts = ArtifactStore(data_dir / "artifacts")
    project_store = ProjectStore(data_dir)
    app = FastAPI(title="Figma to FGUI Local Service", version="0.1.0")

    def load_job(job_id: str) -> JobView:
        try:
            return store.get_job(job_id)
        except NotFound as error:
            raise _error(404, error.code, str(error)) from error

    def load_bundle(job_id: str) -> ChangeBundle:
        job = load_job(job_id)
        if job.artifact_sha256 is None:
            raise _error(409, "artifact_unavailable", "job has no applicable changeset")
        try:
            return artifacts.get(job.artifact_sha256)
        except (ArtifactIntegrityError, OSError) as error:
            raise _error(409, "artifact_integrity", "changeset artifact is unavailable") from error

    def preview_root(job: JobView) -> Path:
        if job.project_fingerprint is None:
            return fixtures_root / "fgui"
        try:
            return project_store.artifact_path(job.project_id)
        except ProjectIntegrityError as error:
            raise _error(404, "project_not_found", _PROJECT_NOT_FOUND_MESSAGE) from error

    def job_summary(job: JobView) -> JobSummary:
        return JobSummary(job_id=job.job_id, project_id=job.project_id, status=job.status)

    def redacted_bundle(job_id: str, response: Response, migration_link: str) -> ChangeBundle:
        job = load_job(job_id)
        response.headers["Deprecation"] = "true"
        response.headers["Link"] = f'<{migration_link}>; rel="successor-version"'
        return ChangeBundle(job_id=job.job_id, project_id=job.project_id, files=())

    def project_view(version: UploadedProjectVersion) -> ProjectUploadView:
        return ProjectUploadView(
            project_id=version.project_id,
            display_name=version.original_name,
            packages=tuple(
                PackageView(
                    name=package.name,
                    resource_count=sum(file.package_name == package.name for file in version.files),
                )
                for package in version.packages
            ),
        )

    def load_uploaded_project(project_id: str) -> UploadedProjectVersion:
        try:
            return project_store.get(project_id)
        except ProjectIntegrityError as error:
            raise _error(404, "project_not_found", _PROJECT_NOT_FOUND_MESSAGE) from error

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/agents/register")
    def register_agent(agent: AgentRegistration) -> AgentRegistration:
        return store.register_agent(agent)

    @app.post("/v1/projects/bind")
    def bind_project(binding: ProjectBinding) -> ProjectBinding:
        try:
            return store.bind_project(binding)
        except StoreError as error:
            raise _error(404, error.code, str(error)) from error

    @app.post("/v1/projects/uploads", status_code=201)
    async def upload_project(
        project: Annotated[UploadFile | None, File()] = None,
    ) -> ProjectUploadView:
        if project is None:
            upload_error = _upload_error("invalid_fgui_project")
            raise _error(400, upload_error.code, upload_error.user_message)
        filename = project.filename or ""
        if (
            Path(filename).suffix.lower() != ".zip"
            or project.content_type not in {"application/zip", "application/x-zip-compressed"}
        ):
            raise _error(400, "invalid_fgui_project", _upload_error("invalid_fgui_project").user_message)

        uploads = data_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_upload = tempfile.mkstemp(prefix="upload-", suffix=".zip", dir=uploads)
        upload_path = Path(temporary_upload)
        extracted_path = uploads / f"extract-{uuid.uuid4().hex}"
        try:
            written = 0
            with os.fdopen(descriptor, "wb") as destination:
                while chunk := await project.read(_UPLOAD_CHUNK_BYTES):
                    written += len(chunk)
                    if written > DEFAULT_UPLOAD_LIMITS.max_compressed_bytes:
                        raise _upload_error("archive_too_large")
                    destination.write(chunk)
            extracted = extract_project_zip(upload_path, extracted_path)
            version = index_uploaded_project(extracted.root, Path(filename).name)
            return project_view(project_store.create(version, extracted.root))
        except UploadError as error:
            raise _error(400, error.code, error.user_message) from error
        except (KeyError, OSError, ProjectIntegrityError, ValueError) as error:
            upload_error = _upload_error("invalid_fgui_project")
            raise _error(400, upload_error.code, upload_error.user_message) from error
        finally:
            with suppress(Exception):
                await project.close()
            with suppress(Exception):
                upload_path.unlink(missing_ok=True)
            with suppress(Exception):
                shutil.rmtree(extracted_path)

    @app.get("/v1/projects/{project_id}")
    def get_project(project_id: str) -> ProjectUploadView:
        return project_view(load_uploaded_project(project_id))

    @app.get("/v1/projects/{project_id}/packages")
    def get_project_packages(project_id: str) -> ProjectUploadView:
        return project_view(load_uploaded_project(project_id))

    @app.get("/v1/projects/{project_id}/assets/{asset_id}/thumbnail")
    def get_asset_thumbnail(project_id: str, asset_id: str) -> FileResponse:
        load_uploaded_project(project_id)
        try:
            thumbnail = project_store.thumbnail_path(project_id, asset_id)
        except ProjectIntegrityError as error:
            raise _error(404, "asset_not_found", _ASSET_NOT_FOUND_MESSAGE) from error
        return FileResponse(thumbnail, media_type="image/webp")

    def create_conversion_job(
        request: JobCreate | ProjectJobCreate,
        project_root: Path,
        project_fingerprint: str | None = None,
        package_names: tuple[str, ...] = (),
    ) -> JobView:
        if Path(request.fixture_name).name != request.fixture_name:
            raise _error(400, "invalid_fixture", "fixture name must be a file name")
        source = fixtures_root / "figma" / request.fixture_name
        if not source.is_file():
            raise _error(400, "invalid_fixture", "fixture does not exist")

        job_id = uuid.uuid4().hex
        with tempfile.TemporaryDirectory(dir=data_dir) as temporary:
            staging = Path(temporary) / "staging"
            try:
                result = convert(
                    ConversionRequest(
                        figma_json=source,
                        project_root=project_root,
                        package_name=request.package_name,
                        staging_root=staging,
                        classification_rules=rules_path,
                    )
                )
            except (OSError, ValueError) as error:
                job = JobView(
                    job_id=job_id,
                    project_id=request.project_id,
                    project_fingerprint=project_fingerprint,
                    package_names=package_names,
                    status=JobStatus.CONVERSION_FAILED,
                    diagnostics=(
                        Diagnostic(
                            code="conversion_failed",
                            severity=Severity.ERROR,
                            message=type(error).__name__,
                        ),
                    ),
                )
                return store.create_job(job)

            files: list[ChangeFile] = []
            for generated in result.files:
                content = (staging / generated.relative_path).read_bytes()
                existing = project_root / generated.relative_path
                operation = FileOperation.REPLACE if existing.is_file() else FileOperation.CREATE
                before = hashlib.sha256(existing.read_bytes()).hexdigest() if existing.is_file() else None
                files.append(
                    ChangeFile(
                        operation=operation,
                        relative_path=generated.relative_path,
                        before_sha256=before,
                        after_sha256=generated.sha256,
                        content_b64=base64.b64encode(content).decode("ascii"),
                    )
                )

        bundle = ChangeBundle(job_id=job_id, project_id=request.project_id, files=tuple(files))
        digest = artifacts.put(bundle)
        status = JobStatus.READY_FOR_REVIEW if result.applicable else JobStatus.CONVERSION_FAILED
        return store.create_job(
            JobView(
                job_id=job_id,
                project_id=request.project_id,
                project_fingerprint=project_fingerprint,
                package_names=package_names,
                status=status,
                diagnostics=result.diagnostics,
                artifact_sha256=digest,
            )
        )

    @app.post("/v1/jobs")
    def create_job(request: JobCreate) -> JobSummary:
        return job_summary(
            create_conversion_job(request, fixtures_root / "fgui", package_names=(request.package_name,))
        )

    @app.post("/v1/projects/{project_id}/jobs")
    def create_uploaded_project_job(project_id: str, request: ProjectJobCreate) -> JobSummary:
        if request.project_id != project_id:
            raise _error(400, "project_mismatch", "route and request project IDs differ")
        version = load_uploaded_project(project_id)
        try:
            project_root = project_store.artifact_path(project_id)
        except ProjectIntegrityError as error:
            raise _error(404, "project_not_found", _PROJECT_NOT_FOUND_MESSAGE) from error
        return job_summary(
            create_conversion_job(
                request,
                project_root,
                version.fingerprint,
                tuple(package.name for package in version.packages),
            )
        )

    @app.get("/v1/jobs/{job_id}/designer-preview")
    def designer_preview(job_id: str, details: str | None = None) -> DesignerPreview | dict[str, object]:
        job = load_job(job_id)
        before_root = preview_root(job)
        bundle = load_bundle(job_id)
        preview = build_designer_preview(before_root, bundle, job.diagnostics, job_id=job_id)
        if details != "advanced":
            return preview
        files: list[dict[str, str | None]] = []
        for change in bundle.files:
            path = before_root / change.relative_path
            before_xml = path.read_text("utf-8") if path.suffix == ".xml" and path.is_file() else None
            content = base64.b64decode(change.content_b64)
            after_xml = content.decode("utf-8") if path.suffix == ".xml" else None
            files.append(
                {
                    "operation": change.operation,
                    "relative_path": change.relative_path,
                    "before_sha256": change.before_sha256,
                    "after_sha256": change.after_sha256,
                    "before_xml": before_xml,
                    "after_xml": after_xml,
                }
            )
        return {
            "preview": preview.model_dump(mode="json"),
            "details": {
                "files": files,
                "diagnostics": [item.model_dump(mode="json") for item in job.diagnostics],
            },
        }

    @app.get("/v1/jobs/{job_id}/designer-preview/images/{change_index}/{side}")
    def designer_preview_image(job_id: str, change_index: int, side: Literal["before", "after"]) -> Response:
        job = load_job(job_id)
        bundle = load_bundle(job_id)
        if change_index < 0 or change_index >= len(bundle.files):
            raise _error(404, "preview_image_not_found", "preview image is unavailable")
        change = bundle.files[change_index]
        if not is_designer_image(change.relative_path):
            raise _error(404, "preview_image_not_found", "preview image is unavailable")
        if side == "before":
            path = preview_root(job) / change.relative_path
            try:
                content = path.read_bytes()
            except OSError as error:
                raise _error(404, "preview_image_not_found", "preview image is unavailable") from error
        else:
            try:
                content = base64.b64decode(change.content_b64, validate=True)
            except ValueError as error:
                raise _error(404, "preview_image_not_found", "preview image is unavailable") from error
        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()
                media_type = Image.MIME.get(image.format)
        except (OSError, UnidentifiedImageError) as error:
            raise _error(404, "preview_image_not_found", "preview image is unavailable") from error
        if media_type is None or not media_type.startswith("image/"):
            raise _error(404, "preview_image_not_found", "preview image is unavailable")
        return Response(content=content, media_type=media_type)

    @app.get("/v1/jobs/{job_id}/preview")
    def preview_job(job_id: str, response: Response) -> ChangeBundle:
        return redacted_bundle(job_id, response, f"/v1/jobs/{job_id}/designer-preview")

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str) -> JobSummary:
        return job_summary(load_job(job_id))

    @app.post("/v1/jobs/{job_id}/approve")
    def approve_job(job_id: str) -> JobSummary:
        try:
            return job_summary(store.approve_job(job_id))
        except StoreError as error:
            status = 404 if isinstance(error, NotFound) else 409
            raise _error(status, error.code, str(error)) from error

    @app.post("/v1/jobs/{job_id}/reject")
    def reject_job(job_id: str) -> JobSummary:
        try:
            return job_summary(store.reject_job(job_id))
        except StoreError as error:
            status = 404 if isinstance(error, NotFound) else 409
            raise _error(status, error.code, str(error)) from error

    @app.get("/v1/agents/{agent_id}/assignments/next", response_model=None)
    def claim_next(agent_id: str) -> JobView | Response:
        job = store.claim_next(agent_id)
        return job if job is not None else Response(status_code=204)

    @app.get("/v1/agents/{agent_id}/assignments/{job_id}/artifact")
    def get_assignment_artifact(agent_id: str, job_id: str) -> ChangeBundle:
        try:
            store.get_assignment_artifact_job(agent_id, job_id)
        except StoreError as error:
            status = 404 if isinstance(error, NotFound) else 409
            raise _error(status, error.code, str(error)) from error
        return load_bundle(job_id)

    @app.get("/v1/jobs/{job_id}/changeset")
    def get_changeset(job_id: str, response: Response) -> ChangeBundle:
        return redacted_bundle(
            job_id,
            response,
            "/v1/agents/{agent_id}/assignments/next",
        )

    @app.post("/v1/jobs/{job_id}/apply-result")
    def record_result(job_id: str, result: ApplyResult) -> JobSummary:
        if job_id != result.job_id:
            raise _error(400, "job_mismatch", "route and result job IDs differ")
        try:
            return job_summary(store.record_apply_result(result))
        except StoreError as error:
            status = 404 if isinstance(error, NotFound) else 409
            raise _error(status, error.code, str(error)) from error

    return app
