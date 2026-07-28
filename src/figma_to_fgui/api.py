from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.types import Scope

from figma_to_fgui.artifacts import ArtifactIntegrityError, ArtifactStore
from figma_to_fgui.designer_preview import (
    DesignerPreview,
    build_designer_preview,
    is_designer_image,
)
from figma_to_fgui.figma_pairing import PairingError, PairingStore, require_scope
from figma_to_fgui.figma_selection import (
    SelectionError,
    SelectionManifest,
    SelectionTopLevelSummary,
    SelectionView,
)
from figma_to_fgui.image_preview import encode_webp_preview
from figma_to_fgui.job_store import JobStore, NotFound, StoreError
from figma_to_fgui.models import Diagnostic, Severity
from figma_to_fgui.normalize import selection_document
from figma_to_fgui.pipeline import convert_document
from figma_to_fgui.project_store import ProjectIntegrityError, ProjectStore
from figma_to_fgui.project_upload import (
    DEFAULT_UPLOAD_LIMITS,
    UploadError,
    _upload_error,
    extract_project_zip,
)
from figma_to_fgui.selection_store import SelectionStore
from figma_to_fgui.service_contracts import (
    AgentRegistration,
    ApplyResult,
    ChangeBundle,
    ChangeFile,
    FigmaDeviceView,
    FileOperation,
    JobCreate,
    JobStatus,
    JobSummary,
    JobView,
    PackageView,
    PairingCodeView,
    PairingExchange,
    PluginCredentialView,
    PluginPrincipal,
    PluginScope,
    ProjectBinding,
    ProjectJobCreate,
    ProjectUploadView,
    SelectionProjectJobCreate,
)
from figma_to_fgui.uploaded_project import UploadedProjectVersion, index_uploaded_project

_UPLOAD_CHUNK_BYTES = 64 * 1024
_PROJECT_NOT_FOUND_MESSAGE = "鎵句笉鍒拌繖涓?FairyGUI 宸ョ▼銆?"
_ASSET_NOT_FOUND_MESSAGE = "鎵句笉鍒拌繖寮犻瑙堝浘鐗囥€俙"
_VITE_HASHED_ASSET = re.compile(r"^.+-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$")
_PAIRING_MESSAGE = "Pairing request could not be completed."
_SELECTION_MESSAGE = "Selection upload could not be completed."
_SELECTION_MANIFEST_BYTES = 5 * 1024 * 1024


class _ImmutableStaticFiles(StaticFiles):
    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        if _VITE_HASHED_ASSET.fullmatch(Path(full_path).name):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def create_app(
    data_dir: Path,
    fixtures_root: Path,
    rules_path: Path,
    web_dist: Path | None = None,
    health_instance_token: str | None = None,
    plugin_secret: bytes | None = None,
    allow_fixture_jobs: bool = False,
) -> FastAPI:
    index_html: Path | None = None
    assets_dir: Path | None = None
    if web_dist is not None:
        index_html = web_dist / "index.html"
        assets_dir = web_dist / "assets"
        if not web_dist.is_dir() or not index_html.is_file() or not assets_dir.is_dir():
            raise ValueError("web_dist must be a directory containing index.html")
    store = JobStore(data_dir / "server.db")
    store.initialize()
    artifacts = ArtifactStore(data_dir / "artifacts")
    project_store = ProjectStore(data_dir)
    selection_store = SelectionStore(data_dir)
    pairing_store = (
        PairingStore(data_dir / "server.db", plugin_secret, lambda: datetime.now(UTC))
        if plugin_secret is not None
        else None
    )
    if pairing_store is not None:
        pairing_store.initialize()
    app = FastAPI(title="Figma to FGUI Local Service", version="0.1.0")

    def pairing_error(error: PairingError) -> HTTPException:
        status = 429 if error.code == "pairing_rate_limited" else 401
        if error.code.startswith("pairing_code_"):
            status = 400
        return _error(status, error.code, _PAIRING_MESSAGE)

    def selection_error(error: SelectionError) -> HTTPException:
        status = 400
        if error.code in {"selection_not_found", "selection_owner_denied"}:
            status = 404
        elif error.code in {"selection_upload_state", "selection_resource_duplicate"}:
            status = 409
        elif error.code == "selection_upload_expired":
            status = 410
        code = "selection_not_found" if error.code == "selection_owner_denied" else error.code
        return _error(status, code, _SELECTION_MESSAGE)

    def configured_pairing_store() -> PairingStore:
        if pairing_store is None:
            raise _error(503, "plugin_credential_invalid", _PAIRING_MESSAGE)
        return pairing_store

    def authenticate_plugin(
        authorization: str | None, *, required_scope: PluginScope | str | None = None
    ) -> PluginPrincipal:
        if authorization is None:
            raise PairingError("plugin_credential_invalid")
        scheme, separator, credential = authorization.partition(" ")
        if scheme != "Bearer" or separator == "" or not credential or " " in credential:
            raise PairingError("plugin_credential_invalid")
        if pairing_store is None:
            raise PairingError("plugin_credential_invalid")
        principal = pairing_store.authenticate(credential)
        return principal if required_scope is None else require_scope(principal, required_scope)

    app.state.authenticate_plugin = authenticate_plugin
    app.state.data_dir = data_dir

    def selection_view(selection_id: str, device_id: str) -> SelectionView:
        version = selection_store.get(selection_id, device_id)
        return SelectionView(
            selection_id=version.selection_id,
            display_name=version.manifest.display_name,
            top_level_summaries=tuple(
                SelectionTopLevelSummary(name=node.name, type=node.type)
                for node in version.manifest.top_level_nodes
            ),
            preview_urls=tuple(
                f"/v1/figma/selections/{version.selection_id}/previews/{index}"
                for index in range(version.preview_count)
            ),
            warnings=version.manifest.warnings,
        )

    def selection_principal(request: Request, scope: PluginScope) -> PluginPrincipal:
        try:
            principal = authenticate_plugin(request.headers.get("authorization"), required_scope=scope)
            selection_store.expire_uploads()
            return principal
        except PairingError as error:
            raise pairing_error(error) from error

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

    def preview_image(job: JobView, bundle: ChangeBundle, change_index: int, side: Literal["before", "after"]) -> bytes | None:
        if change_index < 0 or change_index >= len(bundle.files):
            return None
        change = bundle.files[change_index]
        if not is_designer_image(change.relative_path):
            return None
        if side == "before":
            try:
                content = (preview_root(job) / change.relative_path).read_bytes()
            except OSError:
                return None
        else:
            try:
                content = base64.b64decode(change.content_b64, validate=True)
            except ValueError:
                return None
        rendered = encode_webp_preview(content)
        return None if rendered is None else rendered[2]

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
    def health(response: Response) -> dict[str, str]:
        if health_instance_token is not None:
            response.headers["X-Figma-To-FGUI-Instance"] = health_instance_token
        return {"status": "ok"}

    @app.post("/v1/figma/pairings", status_code=201)
    def create_pairing() -> PairingCodeView:
        return configured_pairing_store().create_code()

    @app.post("/v1/figma/pairings/exchange")
    async def exchange_pairing(request: Request) -> PluginCredentialView:
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise TypeError("pairing exchange must be an object")
            if type(payload.get("version")) is not int or payload["version"] != 1:
                raise TypeError("pairing exchange version is invalid")
            exchange = PairingExchange.model_validate(payload)
        except (TypeError, ValidationError, ValueError):
            raise _error(400, "pairing_code_invalid", _PAIRING_MESSAGE) from None
        try:
            client_address = request.client
            source_key = client_address.host if client_address is not None and client_address.host else "unknown"
            return configured_pairing_store().exchange(
                exchange.code, exchange.device_name, source_key=source_key
            )
        except PairingError as error:
            raise pairing_error(error) from error

    @app.get("/v1/figma/devices")
    def list_figma_devices() -> tuple[FigmaDeviceView, ...]:
        return configured_pairing_store().list_devices()

    @app.delete("/v1/figma/devices/{device_id}")
    def revoke_figma_device(device_id: str) -> FigmaDeviceView:
        try:
            return configured_pairing_store().revoke(device_id)
        except PairingError as error:
            raise pairing_error(error) from error

    @app.post("/v1/figma/selections/uploads", status_code=201)
    async def create_selection_upload(request: Request) -> dict[str, str | int]:
        principal = selection_principal(request, PluginScope.SELECTION_UPLOAD)
        try:
            payload = await request.json()
            if (
                not isinstance(payload, dict)
                or set(payload) != {"version", "idempotency_key"}
                or payload["version"] != 1
                or not isinstance(payload["idempotency_key"], str)
            ):
                raise ValueError("invalid upload request")
            upload = selection_store.create_upload(principal.device_id, payload["idempotency_key"])
        except (SelectionError, TypeError, ValueError):
            error = SelectionError("invalid_selection_upload")
            raise selection_error(error) from None
        return {"version": 1, "upload_id": upload.upload_id}

    @app.put("/v1/figma/selections/uploads/{upload_id}/manifest")
    async def put_selection_manifest(upload_id: str, request: Request) -> dict[str, str | int]:
        principal = selection_principal(request, PluginScope.SELECTION_UPLOAD)
        try:
            content = bytearray()
            async for received in request.stream():
                content.extend(received)
                if len(content) > _SELECTION_MANIFEST_BYTES:
                    raise SelectionError("selection_too_large")
            def no_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
                document: dict[str, object] = {}
                for key, value in pairs:
                    if key in document:
                        raise SelectionError("invalid_selection_manifest")
                    document[key] = value
                return document

            payload = json.loads(content, object_pairs_hook=no_duplicate_object)
            if not isinstance(payload, dict):
                raise TypeError("manifest must be an object")
            manifest = SelectionManifest.model_validate(payload)
            upload = selection_store.put_manifest(upload_id, principal.device_id, manifest)
        except (RecursionError, SelectionError, TypeError, ValidationError, ValueError) as error:
            selection = error if isinstance(error, SelectionError) else SelectionError("invalid_selection_manifest")
            raise selection_error(selection) from None
        return {"version": 1, "state": upload.state}

    @app.put("/v1/figma/selections/uploads/{upload_id}/resources/{resource_key}")
    async def put_selection_resource(
        upload_id: str, resource_key: str, request: Request
    ) -> dict[str, str | int]:
        principal = selection_principal(request, PluginScope.SELECTION_UPLOAD)
        try:
            temporary_path = selection_store.prepare_resource(upload_id, principal.device_id, resource_key, request.headers.get("content-type", ""))
            written = 0
            try:
                with temporary_path.open("wb") as destination:
                    async for received in request.stream():
                        for offset in range(0, len(received), _UPLOAD_CHUNK_BYTES):
                            chunk = received[offset : offset + _UPLOAD_CHUNK_BYTES]
                            written += len(chunk)
                            if written > selection_store.max_resource_bytes:
                                raise SelectionError("selection_too_large")
                            destination.write(chunk)
                upload = selection_store.put_resource_path(upload_id, principal.device_id, resource_key, request.headers.get("content-type", ""), temporary_path)
            finally:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)
        except SelectionError as error:
            raise selection_error(error) from None
        return {"version": 1, "state": upload.state}

    @app.post("/v1/figma/selections/uploads/{upload_id}/commit")
    def commit_selection_upload(upload_id: str, request: Request) -> SelectionView:
        principal = selection_principal(request, PluginScope.SELECTION_UPLOAD)
        try:
            version = selection_store.commit(upload_id, principal.device_id)
            return selection_view(version.selection_id, principal.device_id)
        except SelectionError as error:
            raise selection_error(error) from None

    @app.get("/v1/figma/selections/{selection_id}")
    def get_selection(selection_id: str, request: Request) -> SelectionView:
        principal = selection_principal(request, PluginScope.SELECTION_READ_OWN_STATUS)
        try:
            return selection_view(selection_id, principal.device_id)
        except SelectionError as error:
            raise selection_error(error) from None

    @app.get("/v1/figma/selections/{selection_id}/previews/{preview_index}")
    def get_selection_preview(selection_id: str, preview_index: int, request: Request) -> FileResponse:
        principal = selection_principal(request, PluginScope.SELECTION_READ_OWN_STATUS)
        try:
            return FileResponse(selection_store.preview_path(selection_id, principal.device_id, preview_index), media_type="image/webp")
        except SelectionError as error:
            raise selection_error(error) from None

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
        raw: dict[str, object],
        project_id: str,
        package_name: str,
        project_root: Path,
        project_fingerprint: str | None = None,
        package_names: tuple[str, ...] = (),
        selection_id: str | None = None,
        selection_fingerprint: str | None = None,
    ) -> JobView:
        job_id = uuid.uuid4().hex
        with tempfile.TemporaryDirectory(dir=data_dir) as temporary:
            staging = Path(temporary) / "staging"
            try:
                result = convert_document(
                    raw,
                    project_root,
                    package_name,
                    staging,
                    rules_path,
                )
            except (OSError, ValueError) as error:
                job = JobView(
                    job_id=job_id,
                    project_id=project_id,
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
                return store.create_job(job, selection_id, selection_fingerprint)

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

        bundle = ChangeBundle(job_id=job_id, project_id=project_id, files=tuple(files))
        digest = artifacts.put(bundle)
        status = JobStatus.READY_FOR_REVIEW if result.applicable else JobStatus.CONVERSION_FAILED
        return store.create_job(
            JobView(
                job_id=job_id,
                project_id=project_id,
                project_fingerprint=project_fingerprint,
                package_names=package_names,
                status=status,
                diagnostics=result.diagnostics,
                artifact_sha256=digest,
            ),
            selection_id,
            selection_fingerprint,
        )

    def fixture_document(fixture_name: str) -> dict[str, object]:
        if Path(fixture_name).name != fixture_name:
            raise _error(400, "invalid_fixture", "fixture name must be a file name")
        source = fixtures_root / "figma" / fixture_name
        if not source.is_file():
            raise _error(400, "invalid_fixture", "fixture does not exist")
        payload = json.loads(source.read_text("utf-8"))
        if not isinstance(payload, dict):
            raise _error(400, "invalid_fixture", "fixture does not contain a document")
        return payload

    @app.post("/v1/jobs")
    def create_job(request: JobCreate) -> JobSummary:
        if not allow_fixture_jobs:
            raise _error(404, "not_found", "resource not found")
        return job_summary(
            create_conversion_job(
                fixture_document(request.fixture_name),
                request.project_id,
                request.package_name,
                fixtures_root / "fgui",
                package_names=(request.package_name,),
            )
        )

    @app.post("/v1/projects/{project_id}/jobs")
    def create_uploaded_project_job(project_id: str, request: ProjectJobCreate) -> JobSummary:
        if not allow_fixture_jobs:
            raise _error(404, "not_found", "resource not found")
        if request.project_id != project_id:
            raise _error(400, "project_mismatch", "route and request project IDs differ")
        version = load_uploaded_project(project_id)
        try:
            project_root = project_store.artifact_path(project_id)
        except ProjectIntegrityError as error:
            raise _error(404, "project_not_found", _PROJECT_NOT_FOUND_MESSAGE) from error
        return job_summary(
            create_conversion_job(
                fixture_document(request.fixture_name),
                request.project_id,
                request.package_name,
                project_root,
                version.fingerprint,
                tuple(package.name for package in version.packages),
            )
        )

    @app.post("/v1/figma/selections/{selection_id}/projects/{project_id}/jobs")
    def create_selection_project_job(
        selection_id: str, project_id: str, request: SelectionProjectJobCreate
    ) -> JobSummary:
        if request.selection_id != selection_id or request.project_id != project_id:
            raise _error(400, "project_mismatch", "route and request IDs differ")
        version = load_uploaded_project(project_id)
        try:
            project_root = project_store.artifact_path(project_id)
            selection_root = selection_store.artifact_path(selection_id)
            manifest = SelectionManifest.model_validate_json(
                (selection_root / "manifest.json").read_text("utf-8")
            )
            raw = selection_document(manifest, selection_root / "resources")
        except (OSError, SelectionError, ValueError) as error:
            raise _error(404, "selection_not_found", _SELECTION_MESSAGE) from error
        return job_summary(
            create_conversion_job(
                raw,
                project_id,
                request.package_name,
                project_root,
                version.fingerprint,
                tuple(package.name for package in version.packages),
                selection_id,
                selection_root.name,
            )
        )

    @app.get("/v1/jobs/{job_id}/designer-preview")
    def designer_preview(job_id: str, details: str | None = None) -> DesignerPreview | dict[str, object]:
        job = load_job(job_id)
        before_root = preview_root(job)
        bundle = load_bundle(job_id)
        def image_url(change_index: int, side: Literal["before", "after"]) -> str | None:
            if preview_image(job, bundle, change_index, side) is None:
                return None
            return f"/v1/jobs/{job_id}/designer-preview/images/{change_index}/{side}"

        preview = build_designer_preview(before_root, bundle, job.diagnostics, image_url=image_url)
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
        content = preview_image(job, bundle, change_index, side)
        if content is None:
            raise _error(404, "preview_image_not_found", "preview image is unavailable")
        return Response(content=content, media_type="image/webp")

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

    if index_html is not None and assets_dir is not None:
        app.mount("/assets", _ImmutableStaticFiles(directory=assets_dir), name="web-assets")

        @app.get("/{client_route:path}", include_in_schema=False)
        def web_console(client_route: str) -> FileResponse:
            if client_route == "health" or client_route.startswith("v1/"):
                raise _error(404, "not_found", "resource not found")
            return FileResponse(index_html, media_type="text/html")

    return app
