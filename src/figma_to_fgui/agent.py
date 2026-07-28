from __future__ import annotations

import os
from pathlib import Path

import httpx
from pydantic import Field

from figma_to_fgui.apply import ApplyError, apply_bundle
from figma_to_fgui.models import Diagnostic, FrozenModel, Severity
from figma_to_fgui.service_contracts import (
    AgentRegistration,
    ApplyResult,
    ApplyStatus,
    ChangeBundle,
    JobView,
    ProjectBinding,
)


class AgentConfig(FrozenModel):
    version: int = 1
    agent_id: str
    name: str
    api_url: str = "http://127.0.0.1:8765"
    projects: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> AgentConfig:
        return cls.model_validate_json(path.read_text("utf-8"))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(self.model_dump_json(indent=2), "utf-8")
        os.replace(temporary, path)


def default_config_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data is None:
        raise RuntimeError("LOCALAPPDATA is unavailable")
    return Path(local_app_data) / "FigmaToFGUI" / "agent.json"


class AgentClient:
    def __init__(
        self,
        config: AgentConfig,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.config.api_url,
            transport=self.transport,
            timeout=httpx.Timeout(30, connect=5),
        )

    def register(self) -> AgentRegistration:
        registration = AgentRegistration(agent_id=self.config.agent_id, name=self.config.name)
        with self._client() as client:
            response = client.post("/v1/agents/register", json=registration.model_dump(mode="json"))
            response.raise_for_status()
        return registration

    def bind(self, project_id: str) -> ProjectBinding:
        binding = ProjectBinding(project_id=project_id, agent_id=self.config.agent_id)
        with self._client() as client:
            response = client.post("/v1/projects/bind", json=binding.model_dump(mode="json"))
            response.raise_for_status()
        return binding

    def poll_once(self) -> ApplyResult | None:
        with self._client() as client:
            response = client.get(f"/v1/agents/{self.config.agent_id}/assignments/next")
            if response.status_code == 204:
                return None
            response.raise_for_status()
            job = JobView.model_validate(response.json())
            bundle_response = client.get(f"/v1/jobs/{job.job_id}/changeset")
            bundle_response.raise_for_status()
            bundle = ChangeBundle.model_validate(bundle_response.json())
            result = self._apply(job, bundle)
            report = client.post(
                f"/v1/jobs/{job.job_id}/apply-result",
                json=result.model_dump(mode="json"),
            )
            report.raise_for_status()
            return result

    def _apply(self, job: JobView, bundle: ChangeBundle) -> ApplyResult:
        project_path = self.config.projects.get(job.project_id)
        if project_path is None:
            return self._failure(job, "project_not_bound", "Project is not bound on this Agent")
        try:
            summary = apply_bundle(Path(project_path), bundle)
        except (ApplyError, OSError) as error:
            rollback = getattr(error, "rollback_succeeded", None)
            return self._failure(job, type(error).__name__, "Local apply failed", rollback)
        return ApplyResult(
            job_id=job.job_id,
            agent_id=self.config.agent_id,
            project_id=job.project_id,
            status=ApplyStatus.APPLIED,
            changed_paths=summary.changed_paths,
        )

    def _failure(
        self,
        job: JobView,
        code: str,
        message: str,
        rollback_succeeded: bool | None = None,
    ) -> ApplyResult:
        return ApplyResult(
            job_id=job.job_id,
            agent_id=self.config.agent_id,
            project_id=job.project_id,
            status=ApplyStatus.FAILED,
            rollback_succeeded=rollback_succeeded,
            diagnostics=(Diagnostic(code=code, severity=Severity.ERROR, message=message),),
        )
