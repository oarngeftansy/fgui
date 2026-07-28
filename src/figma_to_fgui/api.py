from __future__ import annotations

import base64
import hashlib
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response

from figma_to_fgui.artifacts import ArtifactIntegrityError, ArtifactStore
from figma_to_fgui.job_store import JobStore, NotFound, StoreError
from figma_to_fgui.models import Diagnostic, Severity
from figma_to_fgui.pipeline import ConversionRequest, convert
from figma_to_fgui.service_contracts import (
    AgentRegistration,
    ApplyResult,
    ChangeBundle,
    ChangeFile,
    FileOperation,
    JobCreate,
    JobStatus,
    JobView,
    ProjectBinding,
)


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def create_app(data_dir: Path, fixtures_root: Path, rules_path: Path) -> FastAPI:
    store = JobStore(data_dir / "server.db")
    store.initialize()
    artifacts = ArtifactStore(data_dir / "artifacts")
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

    @app.post("/v1/jobs")
    def create_job(request: JobCreate) -> JobView:
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
                        project_root=fixtures_root / "fgui",
                        package_name=request.package_name,
                        staging_root=staging,
                        classification_rules=rules_path,
                    )
                )
            except (OSError, ValueError) as error:
                job = JobView(
                    job_id=job_id,
                    project_id=request.project_id,
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
            project_root = fixtures_root / "fgui"
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
                status=status,
                diagnostics=result.diagnostics,
                artifact_sha256=digest,
            )
        )

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str) -> JobView:
        return load_job(job_id)

    @app.get("/v1/jobs/{job_id}/preview")
    def preview_job(job_id: str) -> ChangeBundle:
        return load_bundle(job_id)

    @app.post("/v1/jobs/{job_id}/approve")
    def approve_job(job_id: str) -> JobView:
        try:
            return store.approve_job(job_id)
        except StoreError as error:
            status = 404 if isinstance(error, NotFound) else 409
            raise _error(status, error.code, str(error)) from error

    @app.get("/v1/agents/{agent_id}/assignments/next", response_model=None)
    def claim_next(agent_id: str) -> JobView | Response:
        job = store.claim_next(agent_id)
        return job if job is not None else Response(status_code=204)

    @app.get("/v1/jobs/{job_id}/changeset")
    def get_changeset(job_id: str) -> ChangeBundle:
        return load_bundle(job_id)

    @app.post("/v1/jobs/{job_id}/apply-result")
    def record_result(job_id: str, result: ApplyResult) -> JobView:
        if job_id != result.job_id:
            raise _error(400, "job_mismatch", "route and result job IDs differ")
        try:
            return store.record_apply_result(result)
        except StoreError as error:
            status = 404 if isinstance(error, NotFound) else 409
            raise _error(status, error.code, str(error)) from error

    return app
