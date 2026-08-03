from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

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


class StoreError(RuntimeError):
    code = "store_error"


class NotFound(StoreError):
    code = "not_found"


class InvalidTransition(StoreError):
    code = "invalid_transition"


class OwnershipMismatch(StoreError):
    code = "ownership_mismatch"


class PackageRequestConflict(StoreError):
    code = "package_request_conflict"


class PackageConsentConflict(StoreError):
    code = "package_consent_conflict"


@dataclass(frozen=True)
class StoredPackage:
    view: ProjectPackageView
    artifact_path: Path | None
    request_identity: str
    generation: int
    owner_id: str | None
    lease_expires_at: datetime | None
    screenshot_consent: bool | None
    screenshot_digest: str | None
    screenshot_path: Path | None
    request_payload: str | None
    screenshot_candidate: JobView | None
    screenshot_completed: bool
    screenshot_completion_diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class JobConversionReference:
    source: str
    source_id: str
    package_name: str
    selection_fingerprint: str | None


@dataclass(frozen=True)
class PackageAttempt:
    view: ProjectPackageView
    generation: int
    should_build: bool
    owner_id: str | None
    lease_expires_at: datetime | None


@dataclass(frozen=True)
class ScreenshotConversionCommit:
    package: StoredPackage
    committed: bool


_PRESERVE_ARTIFACT = object()
_PACKAGE_TRANSITIONS = {
    ProjectPackageStage.CHECKING: {
        ProjectPackageStage.PACKAGING,
        ProjectPackageStage.FAILED,
    },
    ProjectPackageStage.PACKAGING: {
        ProjectPackageStage.READY,
        ProjectPackageStage.FAILED,
    },
    ProjectPackageStage.READY: {ProjectPackageStage.FAILED},
}


class JobStore:
    def __init__(
        self,
        database: Path,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        package_lease_duration: timedelta = timedelta(minutes=2),
    ) -> None:
        if package_lease_duration.total_seconds() <= 0:
            raise ValueError("package lease duration must be positive")
        self.database = database
        self.clock = clock
        self.package_lease_duration = package_lease_duration

    @property
    def package_heartbeat_interval(self) -> float:
        return max(0.01, self.package_lease_duration.total_seconds() / 3)

    def _new_lease(self) -> tuple[datetime, float]:
        expires_at = self.clock() + self.package_lease_duration
        return expires_at, expires_at.timestamp()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_bindings (
                    project_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    selection_id TEXT,
                    selection_fingerprint TEXT,
                    payload TEXT NOT NULL,
                    conversion_source TEXT,
                    conversion_source_id TEXT,
                    conversion_package_name TEXT,
                    screenshot_reason TEXT
                );
                CREATE INDEX IF NOT EXISTS jobs_status_project
                    ON jobs(status, project_id, job_id);
                CREATE TABLE IF NOT EXISTS apply_results (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_packages (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
                    request_identity TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    owner_id TEXT,
                    lease_expires_at REAL,
                    payload TEXT NOT NULL,
                    artifact_path TEXT,
                    screenshot_consent INTEGER,
                    screenshot_digest TEXT,
                    screenshot_path TEXT,
                    request_payload TEXT,
                    screenshot_candidate_payload TEXT,
                    screenshot_completed INTEGER NOT NULL DEFAULT 0,
                    screenshot_completion_diagnostics TEXT
                );
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}
            if "selection_id" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN selection_id TEXT")
            if "selection_fingerprint" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN selection_fingerprint TEXT")
            if "conversion_source" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN conversion_source TEXT")
            if "conversion_source_id" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN conversion_source_id TEXT")
            if "conversion_package_name" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN conversion_package_name TEXT")
            if "screenshot_reason" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN screenshot_reason TEXT")
            package_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(project_packages)")
            }
            added_stage = "stage" not in package_columns
            if added_stage:
                connection.execute(
                    "ALTER TABLE project_packages ADD COLUMN stage TEXT NOT NULL DEFAULT 'checking'"
                )
            if "generation" not in package_columns:
                connection.execute(
                    "ALTER TABLE project_packages ADD COLUMN generation INTEGER NOT NULL DEFAULT 1"
                )
            if "owner_id" not in package_columns:
                connection.execute("ALTER TABLE project_packages ADD COLUMN owner_id TEXT")
            if "lease_expires_at" not in package_columns:
                connection.execute(
                    "ALTER TABLE project_packages ADD COLUMN lease_expires_at REAL"
                )
            if "screenshot_consent" not in package_columns:
                connection.execute(
                    "ALTER TABLE project_packages ADD COLUMN screenshot_consent INTEGER"
                )
            if "screenshot_digest" not in package_columns:
                connection.execute(
                    "ALTER TABLE project_packages ADD COLUMN screenshot_digest TEXT"
                )
            if "screenshot_path" not in package_columns:
                connection.execute(
                    "ALTER TABLE project_packages ADD COLUMN screenshot_path TEXT"
                )
            if "request_payload" not in package_columns:
                connection.execute(
                    "ALTER TABLE project_packages ADD COLUMN request_payload TEXT"
                )
            if "screenshot_candidate_payload" not in package_columns:
                connection.execute(
                    "ALTER TABLE project_packages ADD COLUMN screenshot_candidate_payload TEXT"
                )
            if "screenshot_completed" not in package_columns:
                connection.execute(
                    "ALTER TABLE project_packages ADD COLUMN screenshot_completed INTEGER NOT NULL DEFAULT 0"
                )
            if "screenshot_completion_diagnostics" not in package_columns:
                connection.execute(
                    "ALTER TABLE project_packages ADD COLUMN screenshot_completion_diagnostics TEXT"
                )
            if added_stage:
                for row in connection.execute(
                    "SELECT job_id, payload FROM project_packages"
                ).fetchall():
                    view = ProjectPackageView.model_validate_json(row["payload"])
                    connection.execute(
                        "UPDATE project_packages SET stage = ? WHERE job_id = ?",
                        (view.stage, row["job_id"]),
                    )

    def register_agent(self, agent: AgentRegistration) -> AgentRegistration:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO agents(agent_id, payload) VALUES (?, ?) "
                "ON CONFLICT(agent_id) DO UPDATE SET payload = excluded.payload",
                (agent.agent_id, agent.model_dump_json()),
            )
        return agent

    def bind_project(self, binding: ProjectBinding) -> ProjectBinding:
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO project_bindings(project_id, agent_id, payload) VALUES (?, ?, ?) "
                    "ON CONFLICT(project_id) DO UPDATE SET "
                    "agent_id = excluded.agent_id, payload = excluded.payload",
                    (binding.project_id, binding.agent_id, binding.model_dump_json()),
                )
            except sqlite3.IntegrityError as error:
                raise NotFound("agent is not registered") from error
        return binding

    def create_job(
        self,
        job: JobView,
        selection_id: str | None = None,
        selection_fingerprint: str | None = None,
        conversion_source: str | None = None,
        conversion_source_id: str | None = None,
        conversion_package_name: str | None = None,
        screenshot_reason: str | None = None,
    ) -> JobView:
        reference = (
            conversion_source,
            conversion_source_id,
            conversion_package_name,
        )
        if any(value is None for value in reference) and any(
            value is not None for value in reference
        ):
            raise ValueError("conversion reference must be complete")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs(job_id, project_id, status, selection_id, selection_fingerprint, "
                "payload, conversion_source, conversion_source_id, conversion_package_name, "
                "screenshot_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.job_id,
                    job.project_id,
                    job.status,
                    selection_id,
                    selection_fingerprint,
                    job.model_dump_json(),
                    conversion_source,
                    conversion_source_id,
                    conversion_package_name,
                    screenshot_reason,
                ),
            )
        return job

    def get_job(self, job_id: str) -> JobView:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise NotFound("job not found")
        return JobView.model_validate_json(row["payload"])

    def update_job_conversion(self, job: JobView) -> JobView:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM jobs WHERE job_id = ?", (job.job_id,)
            ).fetchone()
            if row is None:
                raise NotFound("job not found")
            current = JobView.model_validate_json(row["payload"])
            if (
                current.project_id != job.project_id
                or current.status
                not in {JobStatus.READY_FOR_REVIEW, JobStatus.CONVERSION_FAILED}
                or job.status
                not in {JobStatus.READY_FOR_REVIEW, JobStatus.CONVERSION_FAILED}
            ):
                raise InvalidTransition("job conversion cannot be replaced")
            self._save_job(connection, job)
        return job

    def get_job_selection_id(self, job_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT selection_id FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise NotFound("job not found")
        selection_id = row["selection_id"]
        return selection_id if isinstance(selection_id, str) else None

    def get_job_conversion_reference(self, job_id: str) -> JobConversionReference:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT conversion_source, conversion_source_id, conversion_package_name, "
                "selection_fingerprint "
                "FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise NotFound("job not found")
        source = row["conversion_source"]
        source_id = row["conversion_source_id"]
        package_name = row["conversion_package_name"]
        if not all(
            isinstance(value, str) and value
            for value in (source, source_id, package_name)
        ):
            raise NotFound("job conversion reference not found")
        return JobConversionReference(
            source=str(source),
            source_id=str(source_id),
            package_name=str(package_name),
            selection_fingerprint=(
                str(row["selection_fingerprint"])
                if row["selection_fingerprint"] is not None
                else None
            ),
        )

    def get_job_screenshot_reason(self, job_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT screenshot_reason FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise NotFound("job not found")
        reason = row["screenshot_reason"]
        return str(reason) if reason is not None else None

    @staticmethod
    def _stored_package(row: sqlite3.Row) -> StoredPackage:
        artifact = Path(row["artifact_path"]) if row["artifact_path"] is not None else None
        lease = (
            datetime.fromtimestamp(float(row["lease_expires_at"]), UTC)
            if row["lease_expires_at"] is not None
            else None
        )
        return StoredPackage(
            view=ProjectPackageView.model_validate_json(row["payload"]),
            artifact_path=artifact,
            request_identity=str(row["request_identity"]),
            generation=int(row["generation"]),
            owner_id=row["owner_id"] if isinstance(row["owner_id"], str) else None,
            lease_expires_at=lease,
            screenshot_consent=(
                bool(row["screenshot_consent"])
                if row["screenshot_consent"] is not None
                else None
            ),
            screenshot_digest=(
                str(row["screenshot_digest"])
                if row["screenshot_digest"] is not None
                else None
            ),
            screenshot_path=(
                Path(row["screenshot_path"])
                if row["screenshot_path"] is not None
                else None
            ),
            request_payload=(
                str(row["request_payload"])
                if row["request_payload"] is not None
                else None
            ),
            screenshot_candidate=(
                JobView.model_validate_json(row["screenshot_candidate_payload"])
                if row["screenshot_candidate_payload"] is not None
                else None
            ),
            screenshot_completed=bool(row["screenshot_completed"]),
            screenshot_completion_diagnostics=tuple(
                Diagnostic.model_validate(item)
                for item in json.loads(row["screenshot_completion_diagnostics"] or "[]")
            ),
        )

    def begin_package(
        self,
        job_id: str,
        request_identity: str,
        owner_id: str,
        package: ProjectPackageView,
        request_payload: str | None = None,
    ) -> PackageAttempt:
        if (
            not owner_id
            or package.job_id != job_id
            or package.status is not ProjectPackageStage.CHECKING
            or package.stage is not ProjectPackageStage.CHECKING
        ):
            raise InvalidTransition("a package attempt must begin in checking")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise NotFound("job not found")
            existing = connection.execute(
                "SELECT * FROM project_packages WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if existing is not None:
                if existing["request_identity"] != request_identity:
                    raise PackageRequestConflict("a different package request already exists")
                stored = self._stored_package(existing)
                now = self.clock()
                live = (
                    stored.view.stage
                    in {ProjectPackageStage.CHECKING, ProjectPackageStage.PACKAGING}
                    and stored.lease_expires_at is not None
                    and stored.lease_expires_at > now
                )
                if stored.view.stage is not ProjectPackageStage.FAILED and (
                    stored.view.stage
                    in {
                        ProjectPackageStage.READY,
                        ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT,
                    }
                    or live
                ):
                    return PackageAttempt(
                        stored.view,
                        stored.generation,
                        False,
                        stored.owner_id,
                        stored.lease_expires_at,
                    )
                generation = stored.generation + 1
                expires_at, lease_timestamp = self._new_lease()
                updated = connection.execute(
                    "UPDATE project_packages SET stage = ?, generation = ?, payload = ?, "
                    "artifact_path = NULL, owner_id = ?, lease_expires_at = ?, "
                    "screenshot_consent = NULL, screenshot_digest = NULL, screenshot_path = NULL, "
                    "screenshot_candidate_payload = NULL, screenshot_completed = 0, "
                    "screenshot_completion_diagnostics = NULL, "
                    "request_payload = COALESCE(?, request_payload) "
                    "WHERE job_id = ? AND request_identity = ? AND generation = ? AND stage = ?",
                    (
                        package.stage,
                        generation,
                        package.model_dump_json(),
                        owner_id,
                        lease_timestamp,
                        request_payload,
                        job_id,
                        request_identity,
                        stored.generation,
                        stored.view.stage,
                    ),
                )
                if updated.rowcount != 1:
                    raise InvalidTransition("package retry lost its state lease")
                return PackageAttempt(package, generation, True, owner_id, expires_at)
            expires_at, lease_timestamp = self._new_lease()
            connection.execute(
                "INSERT INTO project_packages"
                "(job_id, request_identity, stage, generation, owner_id, lease_expires_at, payload, "
                "request_payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    request_identity,
                    package.stage,
                    1,
                    owner_id,
                    lease_timestamp,
                    package.model_dump_json(),
                    request_payload,
                ),
            )
        return PackageAttempt(package, 1, True, owner_id, expires_at)

    def await_screenshot_consent(
        self,
        job_id: str,
        request_identity: str,
        generation: int,
        owner_id: str,
        package: ProjectPackageView,
    ) -> ProjectPackageView:
        if (
            package.job_id != job_id
            or package.status is not ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT
            or package.stage is not ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT
            or package.screenshot_reason is None
        ):
            raise InvalidTransition("screenshot consent requires a safe reason")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                "UPDATE project_packages SET stage = ?, payload = ?, owner_id = NULL, "
                "lease_expires_at = NULL WHERE job_id = ? AND request_identity = ? "
                "AND generation = ? AND stage = ? AND owner_id = ? AND lease_expires_at > ?",
                (
                    package.stage,
                    package.model_dump_json(),
                    job_id,
                    request_identity,
                    generation,
                    ProjectPackageStage.CHECKING,
                    owner_id,
                    self.clock().timestamp(),
                ),
            )
            if updated.rowcount != 1:
                raise InvalidTransition("package transition lost its state lease")
        return package

    def record_screenshot_consent(
        self, job_id: str, generation: int, approved: bool
    ) -> StoredPackage:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM project_packages WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFound("package not found")
            if int(row["generation"]) != generation:
                raise InvalidTransition("screenshot consent generation changed")
            recorded = row["screenshot_consent"]
            if recorded is not None:
                if bool(recorded) != approved:
                    raise PackageConsentConflict("screenshot consent is already recorded")
                return self._stored_package(row)
            if ProjectPackageStage(row["stage"]) is not ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT:
                raise InvalidTransition("package is not awaiting screenshot consent")
            connection.execute(
                "UPDATE project_packages SET screenshot_consent = ? WHERE job_id = ? "
                "AND generation = ? AND screenshot_consent IS NULL",
                (int(approved), job_id, generation),
            )
            updated = connection.execute(
                "SELECT * FROM project_packages WHERE job_id = ?", (job_id,)
            ).fetchone()
            if updated is None:
                raise NotFound("package not found")
            return self._stored_package(updated)

    def complete_screenshot_conversion(
        self,
        job_id: str,
        generation: int,
        digest: str,
        candidate: JobView | None,
        fallback_diagnostics: tuple[Diagnostic, ...] = (),
    ) -> ScreenshotConversionCommit:
        candidate_is_valid = candidate is not None and (
            candidate.job_id == job_id
            and candidate.artifact_sha256 is not None
            and candidate.status
            in {JobStatus.READY_FOR_REVIEW, JobStatus.CONVERSION_FAILED}
        )
        fallback_is_valid = candidate is None and bool(fallback_diagnostics)
        if not candidate_is_valid and not fallback_is_valid:
            raise InvalidTransition("screenshot conversion candidate is invalid")
        if candidate is not None and fallback_diagnostics:
            raise InvalidTransition("screenshot conversion outcome is ambiguous")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM project_packages WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFound("package not found")
            baseline_row = connection.execute(
                "SELECT payload FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if baseline_row is None:
                raise NotFound("job not found")
            baseline = JobView.model_validate_json(baseline_row["payload"])
            if candidate is not None and baseline.project_id != candidate.project_id:
                raise InvalidTransition("screenshot conversion project changed")
            matches = (
                int(row["generation"]) == generation
                and row["screenshot_digest"] == digest
                and row["screenshot_consent"] == 1
            )
            if (
                not matches
                or bool(row["screenshot_completed"])
                or ProjectPackageStage(row["stage"])
                is not ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT
            ):
                return ScreenshotConversionCommit(self._stored_package(row), False)
            updated = connection.execute(
                "UPDATE project_packages SET screenshot_candidate_payload = ?, "
                "screenshot_completed = 1, screenshot_completion_diagnostics = ? "
                "WHERE job_id = ? AND generation = ? AND stage = ? "
                "AND screenshot_consent = 1 AND screenshot_digest = ? "
                "AND screenshot_completed = 0",
                (
                    candidate.model_dump_json() if candidate is not None else None,
                    json.dumps(
                        [item.model_dump(mode="json") for item in fallback_diagnostics],
                        separators=(",", ":"),
                    ),
                    job_id,
                    generation,
                    ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT,
                    digest,
                ),
            )
            committed = updated.rowcount == 1
            current = connection.execute(
                "SELECT * FROM project_packages WHERE job_id = ?", (job_id,)
            ).fetchone()
            if current is None:
                raise NotFound("package not found")
            return ScreenshotConversionCommit(self._stored_package(current), committed)

    def attach_screenshot(
        self, job_id: str, generation: int, digest: str, path: Path
    ) -> StoredPackage:
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise InvalidTransition("screenshot digest is invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM project_packages WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFound("package not found")
            if int(row["generation"]) != generation:
                raise InvalidTransition("screenshot upload generation changed")
            if row["screenshot_digest"] is not None:
                if row["screenshot_digest"] != digest:
                    raise PackageConsentConflict("a different screenshot is already attached")
                return self._stored_package(row)
            if (
                ProjectPackageStage(row["stage"])
                is not ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT
                or row["screenshot_consent"] != 1
            ):
                raise InvalidTransition("screenshot upload is not authorized")
            connection.execute(
                "UPDATE project_packages SET screenshot_digest = ?, screenshot_path = ? "
                "WHERE job_id = ? AND generation = ? AND screenshot_digest IS NULL",
                (digest, str(path), job_id, generation),
            )
            updated = connection.execute(
                "SELECT * FROM project_packages WHERE job_id = ?", (job_id,)
            ).fetchone()
            if updated is None:
                raise NotFound("package not found")
            return self._stored_package(updated)

    def resume_package_after_screenshot(
        self,
        job_id: str,
        generation: int,
        owner_id: str,
        package: ProjectPackageView,
    ) -> StoredPackage:
        if (
            not owner_id
            or package.job_id != job_id
            or package.status is not ProjectPackageStage.PACKAGING
            or package.stage is not ProjectPackageStage.PACKAGING
        ):
            raise InvalidTransition("resumed package must enter packaging")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM project_packages WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFound("package not found")
            approved = row["screenshot_consent"] == 1
            upload_ready = row["screenshot_digest"] is not None
            conversion_completed = bool(row["screenshot_completed"])
            if (
                int(row["generation"]) != generation
                or ProjectPackageStage(row["stage"])
                is not ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT
                or row["screenshot_consent"] is None
                or (approved and (not upload_ready or not conversion_completed))
            ):
                raise InvalidTransition("screenshot decision is incomplete")
            expires_at, lease_timestamp = self._new_lease()
            connection.execute(
                "UPDATE project_packages SET stage = ?, payload = ?, owner_id = ?, "
                "lease_expires_at = ? WHERE job_id = ? AND generation = ? AND stage = ?",
                (
                    package.stage,
                    package.model_dump_json(),
                    owner_id,
                    lease_timestamp,
                    job_id,
                    generation,
                    ProjectPackageStage.AWAITING_SCREENSHOT_CONSENT,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM project_packages WHERE job_id = ?", (job_id,)
            ).fetchone()
            if updated is None:
                raise NotFound("package not found")
            stored = self._stored_package(updated)
            return StoredPackage(
                view=stored.view,
                artifact_path=stored.artifact_path,
                request_identity=stored.request_identity,
                generation=stored.generation,
                owner_id=stored.owner_id,
                lease_expires_at=expires_at,
                screenshot_consent=stored.screenshot_consent,
                screenshot_digest=stored.screenshot_digest,
                screenshot_path=stored.screenshot_path,
                request_payload=stored.request_payload,
                screenshot_candidate=stored.screenshot_candidate,
                screenshot_completed=stored.screenshot_completed,
                screenshot_completion_diagnostics=stored.screenshot_completion_diagnostics,
            )

    def clear_screenshot_path(self, job_id: str, generation: int, digest: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE project_packages SET screenshot_path = NULL WHERE job_id = ? "
                "AND generation = ? AND screenshot_digest = ?",
                (job_id, generation, digest),
            )

    def get_package(
        self, job_id: str, request_identity: str | None = None
    ) -> StoredPackage:
        self.recover_expired_packages(job_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM project_packages WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise NotFound("package not found")
        if request_identity is not None and row["request_identity"] != request_identity:
            raise PackageRequestConflict("a different package request already exists")
        return self._stored_package(row)

    def transition_package(
        self,
        job_id: str,
        request_identity: str,
        generation: int,
        owner_id: str | None,
        expected_stages: tuple[ProjectPackageStage, ...],
        package: ProjectPackageView,
        artifact_path: Path | None | object = _PRESERVE_ARTIFACT,
    ) -> ProjectPackageView:
        if package.job_id != job_id or package.status is not package.stage:
            raise InvalidTransition("package status and stage must match")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM project_packages WHERE job_id = ?", (job_id,)
            ).fetchone()
            if existing is None:
                raise NotFound("package not found")
            if existing["request_identity"] != request_identity:
                raise PackageRequestConflict("package request identity changed")
            current = ProjectPackageStage(existing["stage"])
            active = current in {
                ProjectPackageStage.CHECKING,
                ProjectPackageStage.PACKAGING,
            }
            lease_is_live = (
                existing["lease_expires_at"] is not None
                and float(existing["lease_expires_at"]) > self.clock().timestamp()
            )
            if (
                int(existing["generation"]) != generation
                or current not in expected_stages
                or package.stage not in _PACKAGE_TRANSITIONS.get(current, set())
                or (active and (existing["owner_id"] != owner_id or not lease_is_live))
                or (not active and owner_id is not None)
            ):
                raise InvalidTransition("package transition lost its state lease")
            assignments = "stage = ?, payload = ?"
            values: list[object] = [package.stage, package.model_dump_json()]
            if package.stage in {ProjectPackageStage.READY, ProjectPackageStage.FAILED}:
                assignments += ", owner_id = NULL, lease_expires_at = NULL"
            else:
                _, lease_timestamp = self._new_lease()
                assignments += ", lease_expires_at = ?"
                values.append(lease_timestamp)
            if artifact_path is not _PRESERVE_ARTIFACT:
                assignments += ", artifact_path = ?"
                values.append(None if artifact_path is None else str(artifact_path))
            values.extend((job_id, request_identity, generation, current))
            owner_predicate = "owner_id IS NULL" if owner_id is None else "owner_id = ?"
            if owner_id is not None:
                values.append(owner_id)
            updated = connection.execute(
                f"UPDATE project_packages SET {assignments} WHERE job_id = ? "
                f"AND request_identity = ? AND generation = ? AND stage = ? AND {owner_predicate}",
                values,
            )
            if updated.rowcount != 1:
                raise InvalidTransition("package transition lost its state lease")
        return package

    def renew_package_lease(
        self,
        job_id: str,
        request_identity: str,
        generation: int,
        owner_id: str,
    ) -> datetime:
        expires_at, lease_timestamp = self._new_lease()
        now = self.clock().timestamp()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                "UPDATE project_packages SET lease_expires_at = ? WHERE job_id = ? "
                "AND request_identity = ? AND generation = ? AND owner_id = ? "
                "AND stage IN (?, ?) AND lease_expires_at > ?",
                (
                    lease_timestamp,
                    job_id,
                    request_identity,
                    generation,
                    owner_id,
                    ProjectPackageStage.CHECKING,
                    ProjectPackageStage.PACKAGING,
                    now,
                ),
            )
            if updated.rowcount != 1:
                raise InvalidTransition("package lease is no longer owned")
        return expires_at

    def recover_expired_packages(self, job_id: str | None = None) -> int:
        recovered = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            query = (
                "SELECT job_id, stage, generation FROM project_packages "
                "WHERE stage IN (?, ?) AND (lease_expires_at IS NULL OR lease_expires_at <= ?)"
            )
            parameters: list[object] = [
                ProjectPackageStage.CHECKING,
                ProjectPackageStage.PACKAGING,
                self.clock().timestamp(),
            ]
            if job_id is not None:
                query += " AND job_id = ?"
                parameters.append(job_id)
            rows = connection.execute(query, parameters).fetchall()
            for row in rows:
                failed = ProjectPackageView(
                    job_id=row["job_id"],
                    status=ProjectPackageStage.FAILED,
                    stage=ProjectPackageStage.FAILED,
                    progress=90,
                    diagnostics=(
                        Diagnostic(
                            code="package_interrupted",
                            severity=Severity.ERROR,
                            message="Project package build was interrupted. Retry the request.",
                        ),
                    ),
                )
                updated = connection.execute(
                    "UPDATE project_packages SET stage = ?, payload = ?, owner_id = NULL, "
                    "lease_expires_at = NULL WHERE job_id = ? AND generation = ? AND stage = ? "
                    "AND (lease_expires_at IS NULL OR lease_expires_at <= ?)",
                    (
                        ProjectPackageStage.FAILED,
                        failed.model_dump_json(),
                        row["job_id"],
                        row["generation"],
                        row["stage"],
                        self.clock().timestamp(),
                    ),
                )
                recovered += updated.rowcount
        return recovered

    def _save_job(self, connection: sqlite3.Connection, job: JobView) -> None:
        connection.execute(
            "UPDATE jobs SET status = ?, payload = ? WHERE job_id = ?",
            (job.status, job.model_dump_json(), job.job_id),
        )

    def approve_job(self, job_id: str) -> JobView:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFound("job not found")
            job = JobView.model_validate_json(row["payload"])
            if job.status is JobStatus.APPROVED:
                return job
            if job.status is not JobStatus.READY_FOR_REVIEW:
                raise InvalidTransition("job is not ready for approval")
            job = job.model_copy(update={"status": JobStatus.APPROVED})
            self._save_job(connection, job)
            return job

    def reject_job(self, job_id: str) -> JobView:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFound("job not found")
            job = JobView.model_validate_json(row["payload"])
            if job.status is JobStatus.REJECTED:
                return job
            if job.status is not JobStatus.READY_FOR_REVIEW:
                raise InvalidTransition("job is not ready for rejection")
            job = job.model_copy(update={"status": JobStatus.REJECTED})
            self._save_job(connection, job)
            return job

    def claim_next(self, agent_id: str) -> JobView | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT jobs.payload
                FROM jobs
                JOIN project_bindings USING(project_id)
                WHERE jobs.status = ? AND project_bindings.agent_id = ?
                ORDER BY jobs.job_id
                LIMIT 1
                """,
                (JobStatus.APPROVED, agent_id),
            ).fetchone()
            if row is None:
                return None
            job = JobView.model_validate_json(row["payload"])
            job = job.model_copy(update={"status": JobStatus.APPLYING})
            self._save_job(connection, job)
            return job

    def get_assignment_artifact_job(self, agent_id: str, job_id: str) -> JobView:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT jobs.payload, project_bindings.agent_id
                FROM jobs
                JOIN project_bindings USING(project_id)
                WHERE jobs.job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise NotFound("job or project binding not found")
        if row["agent_id"] != agent_id:
            raise OwnershipMismatch("assignment does not belong to this agent")
        job = JobView.model_validate_json(row["payload"])
        if job.status is not JobStatus.APPLYING:
            raise InvalidTransition("job is not applying")
        return job

    def record_apply_result(self, result: ApplyResult) -> JobView:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload FROM apply_results WHERE job_id = ?", (result.job_id,)
            ).fetchone()
            if existing is not None:
                if ApplyResult.model_validate_json(existing["payload"]) != result:
                    raise InvalidTransition("a different terminal result already exists")
                return self.get_job(result.job_id)

            row = connection.execute(
                """
                SELECT jobs.payload, project_bindings.agent_id
                FROM jobs
                JOIN project_bindings USING(project_id)
                WHERE jobs.job_id = ?
                """,
                (result.job_id,),
            ).fetchone()
            if row is None:
                raise NotFound("job or project binding not found")
            job = JobView.model_validate_json(row["payload"])
            if row["agent_id"] != result.agent_id or job.project_id != result.project_id:
                raise OwnershipMismatch("apply result does not own this job")
            if job.status is not JobStatus.APPLYING:
                raise InvalidTransition("job is not applying")
            status = JobStatus.APPLIED if result.status is ApplyStatus.APPLIED else JobStatus.FAILED
            job = job.model_copy(update={"status": status})
            connection.execute(
                "INSERT INTO apply_results(job_id, payload) VALUES (?, ?)",
                (result.job_id, result.model_dump_json()),
            )
            self._save_job(connection, job)
            return job
