from __future__ import annotations

from pathlib import Path

import pytest

from figma_to_fgui import api
from figma_to_fgui.job_store import (
    InvalidTransition,
    JobStore,
    PackageConsentConflict,
)
from figma_to_fgui.models import Diagnostic, Severity
from figma_to_fgui.service_contracts import (
    AgentRegistration,
    ApplyResult,
    ApplyStatus,
    JobStatus,
    JobView,
    ProjectBinding,
    ProjectPackageStage,
    ProjectPackageView,
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


def _checking_package() -> ProjectPackageView:
    return ProjectPackageView(
        job_id="job-1",
        status=ProjectPackageStage.CHECKING,
        stage=ProjectPackageStage.CHECKING,
        progress=70,
    )


def test_conversion_reference_preserves_selection_fingerprint(store: JobStore) -> None:
    store.create_job(
        ready_job(),
        selection_id="selection-1",
        selection_fingerprint="selection-fingerprint",
        conversion_source="selection",
        conversion_source_id="selection-1",
        conversion_package_name="SelectionPackage",
    )

    reference = store.get_job_conversion_reference("job-1")

    assert reference.selection_fingerprint == "selection-fingerprint"


def test_screenshot_consent_is_generation_bound_idempotent_and_conflict_safe(
    store: JobStore,
) -> None:
    store.create_job(ready_job())
    attempt = store.begin_package("job-1", "request", "instance", _checking_package())
    waiting = _checking_package().model_copy(
        update={
            "status": ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT,
            "stage": ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT,
            "screenshot_reason": "Visual hierarchy needs confirmation.",
        }
    )

    store.await_screenshot_consent(
        "job-1", "request", attempt.generation, "instance", waiting
    )
    first = store.record_screenshot_consent("job-1", attempt.generation, False)
    duplicate = store.record_screenshot_consent("job-1", attempt.generation, False)

    assert first == duplicate
    assert duplicate.screenshot_consent is False
    with pytest.raises(PackageConsentConflict):
        store.record_screenshot_consent("job-1", attempt.generation, True)
    with pytest.raises(InvalidTransition):
        store.record_screenshot_consent("job-1", attempt.generation + 1, False)


def test_screenshot_attachment_requires_approval_and_binds_digest_and_path(
    store: JobStore, tmp_path: Path
) -> None:
    store.create_job(ready_job())
    attempt = store.begin_package("job-1", "request", "instance", _checking_package())
    waiting = _checking_package().model_copy(
        update={
            "status": ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT,
            "stage": ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT,
            "screenshot_reason": "Need screenshot.",
        }
    )
    store.await_screenshot_consent(
        "job-1", "request", attempt.generation, "instance", waiting
    )
    screenshot = tmp_path / "screenshot.png"
    screenshot.write_bytes(b"png")

    with pytest.raises(InvalidTransition):
        store.attach_screenshot(
            "job-1", attempt.generation, "a" * 64, screenshot
        )

    store.record_screenshot_consent("job-1", attempt.generation, True)
    attached = store.attach_screenshot(
        "job-1", attempt.generation, "a" * 64, screenshot
    )
    duplicate = store.attach_screenshot(
        "job-1", attempt.generation, "a" * 64, screenshot
    )

    assert attached == duplicate
    assert attached.screenshot_digest == "a" * 64
    assert attached.screenshot_path == screenshot
    with pytest.raises(PackageConsentConflict):
        store.attach_screenshot(
            "job-1", attempt.generation, "b" * 64, tmp_path / "other.png"
        )


def test_screenshot_conversion_commit_is_generation_bound_compare_and_swap(
    store: JobStore, tmp_path: Path
) -> None:
    store.create_job(ready_job())
    checking = _checking_package()
    first = store.begin_package("job-1", "request", "instance-a", checking)
    waiting = checking.model_copy(
        update={
            "status": ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT,
            "stage": ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT,
            "screenshot_reason": "Need screenshot.",
        }
    )
    store.await_screenshot_consent(
        "job-1", "request", first.generation, "instance-a", waiting
    )
    store.record_screenshot_consent("job-1", first.generation, True)
    store.attach_screenshot(
        "job-1", first.generation, "a" * 64, tmp_path / "screenshot.png"
    )
    first_candidate = ready_job().model_copy(update={"artifact_sha256": "b" * 64})
    late_candidate = ready_job().model_copy(update={"artifact_sha256": "c" * 64})

    winner = store.commit_screenshot_conversion(
        "job-1", first.generation, "a" * 64, first_candidate
    )
    loser = store.commit_screenshot_conversion(
        "job-1", first.generation, "a" * 64, late_candidate
    )

    assert winner.committed is True
    assert loser.committed is False
    assert loser.package.screenshot_candidate == first_candidate

    packaging = waiting.model_copy(
        update={
            "status": ProjectPackageStage.PACKAGING,
            "stage": ProjectPackageStage.PACKAGING,
            "screenshot_reason": None,
        }
    )
    store.resume_package_after_screenshot(
        "job-1", first.generation, "instance-a", packaging
    )
    failed = packaging.model_copy(
        update={
            "status": ProjectPackageStage.FAILED,
            "stage": ProjectPackageStage.FAILED,
        }
    )
    store.transition_package(
        "job-1",
        "request",
        first.generation,
        "instance-a",
        (ProjectPackageStage.PACKAGING,),
        failed,
    )
    second = store.begin_package("job-1", "request", "instance-b", checking)
    stale = store.commit_screenshot_conversion(
        "job-1", first.generation, "a" * 64, late_candidate
    )

    assert second.generation == first.generation + 1
    assert stale.committed is False
    assert stale.package.generation == second.generation
    assert stale.package.screenshot_candidate is None


def test_old_generation_cleanup_cannot_delete_new_generation_screenshot(
    store: JobStore, tmp_path: Path
) -> None:
    store.create_job(ready_job())
    checking = _checking_package()
    first = store.begin_package("job-1", "request", "instance-a", checking)
    failed = checking.model_copy(
        update={
            "status": ProjectPackageStage.FAILED,
            "stage": ProjectPackageStage.FAILED,
        }
    )
    store.transition_package(
        "job-1",
        "request",
        first.generation,
        "instance-a",
        (ProjectPackageStage.CHECKING,),
        failed,
    )
    second = store.begin_package("job-1", "request", "instance-b", checking)
    waiting = checking.model_copy(
        update={
            "status": ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT,
            "stage": ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT,
            "screenshot_reason": "Need screenshot.",
        }
    )
    store.await_screenshot_consent(
        "job-1", "request", second.generation, "instance-b", waiting
    )
    store.record_screenshot_consent("job-1", second.generation, True)
    screenshot_root = tmp_path / "semantic-screenshots"
    screenshot_root.mkdir()
    new_path = screenshot_root / "new-generation.png"
    new_path.write_bytes(b"new")
    store.attach_screenshot("job-1", second.generation, "b" * 64, new_path)

    api._cleanup_semantic_screenshot(
        store,
        "job-1",
        first.generation,
        "a" * 64,
        new_path,
        screenshot_root,
    )

    assert new_path.read_bytes() == b"new"
    assert store.get_package("job-1").screenshot_path == new_path

    outside_path = tmp_path / "outside-screenshot.png"
    outside_path.write_bytes(b"outside")
    api._cleanup_semantic_screenshot(
        store,
        "job-1",
        first.generation,
        "a" * 64,
        outside_path,
        screenshot_root,
    )

    assert outside_path.read_bytes() == b"outside"
