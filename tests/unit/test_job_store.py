from __future__ import annotations

from pathlib import Path

import pytest

from figma_to_fgui.job_store import InvalidTransition, JobStore
from figma_to_fgui.models import Diagnostic, Severity
from figma_to_fgui.service_contracts import (
    AgentRegistration,
    ApplyResult,
    ApplyStatus,
    JobStatus,
    JobView,
    ProjectBinding,
)


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    result = JobStore(tmp_path / "jobs.db")
    result.initialize()
    return result


def ready_job(job_id: str = "job-1", project_id: str = "project-1") -> JobView:
    return JobView(
        job_id=job_id,
        project_id=project_id,
        status=JobStatus.READY_FOR_REVIEW,
        artifact_sha256="a" * 64,
    )


def register_bound_agent(store: JobStore) -> None:
    store.register_agent(AgentRegistration(agent_id="agent-a", name="A"))
    store.bind_project(ProjectBinding(project_id="project-1", agent_id="agent-a"))


def test_only_bound_agent_claims_approved_job(store: JobStore) -> None:
    register_bound_agent(store)
    store.register_agent(AgentRegistration(agent_id="agent-b", name="B"))
    store.create_job(ready_job())
    store.approve_job("job-1")
    assert store.claim_next("agent-b") is None
    assignment = store.claim_next("agent-a")
    assert assignment is not None
    assert assignment.status is JobStatus.APPLYING


def test_approved_job_can_only_be_claimed_once(store: JobStore) -> None:
    register_bound_agent(store)
    store.create_job(ready_job())
    store.approve_job("job-1")
    assert store.claim_next("agent-a") is not None
    assert store.claim_next("agent-a") is None


def test_approval_is_idempotent(store: JobStore) -> None:
    register_bound_agent(store)
    store.create_job(ready_job())
    first = store.approve_job("job-1")
    second = store.approve_job("job-1")
    assert first == second
    assert second.status is JobStatus.APPROVED


def test_job_with_error_cannot_be_approved(store: JobStore) -> None:
    store.create_job(
        JobView(
            job_id="job-1",
            project_id="project-1",
            status=JobStatus.CONVERSION_FAILED,
            diagnostics=(Diagnostic(code="bad", severity=Severity.ERROR, message="bad"),),
        )
    )
    with pytest.raises(InvalidTransition):
        store.approve_job("job-1")


@pytest.mark.parametrize(
    "status",
    [
        JobStatus.CREATED,
        JobStatus.CONVERSION_FAILED,
        JobStatus.APPROVED,
        JobStatus.APPLYING,
        JobStatus.APPLIED,
        JobStatus.FAILED,
    ],
)
def test_only_ready_for_review_jobs_can_be_rejected(store: JobStore, status: JobStatus) -> None:
    store.create_job(
        JobView(
            job_id="job-1",
            project_id="project-1",
            status=status,
            artifact_sha256="a" * 64,
        )
    )

    with pytest.raises(InvalidTransition):
        store.reject_job("job-1")


def test_repeated_terminal_result_is_idempotent(store: JobStore) -> None:
    register_bound_agent(store)
    store.create_job(ready_job())
    store.approve_job("job-1")
    assert store.claim_next("agent-a") is not None
    result = ApplyResult(
        job_id="job-1",
        agent_id="agent-a",
        project_id="project-1",
        status=ApplyStatus.APPLIED,
        changed_paths=("Sample/Main.xml",),
    )
    store.record_apply_result(result)
    store.record_apply_result(result)
    assert store.get_job("job-1").status is JobStatus.APPLIED
