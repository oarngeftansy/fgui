from __future__ import annotations

import sqlite3
from dataclasses import dataclass
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


@dataclass(frozen=True)
class StoredPackage:
    view: ProjectPackageView
    artifact_path: Path | None
    request_identity: str
    generation: int


@dataclass(frozen=True)
class PackageAttempt:
    view: ProjectPackageView
    generation: int
    should_build: bool


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
    def __init__(self, database: Path) -> None:
        self.database = database

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
                    payload TEXT NOT NULL
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
                    payload TEXT NOT NULL,
                    artifact_path TEXT
                );
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}
            if "selection_id" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN selection_id TEXT")
            if "selection_fingerprint" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN selection_fingerprint TEXT")
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
    ) -> JobView:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs(job_id, project_id, status, selection_id, selection_fingerprint, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    job.job_id,
                    job.project_id,
                    job.status,
                    selection_id,
                    selection_fingerprint,
                    job.model_dump_json(),
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

    def get_job_selection_id(self, job_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT selection_id FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise NotFound("job not found")
        selection_id = row["selection_id"]
        return selection_id if isinstance(selection_id, str) else None

    @staticmethod
    def _stored_package(row: sqlite3.Row) -> StoredPackage:
        artifact = Path(row["artifact_path"]) if row["artifact_path"] is not None else None
        return StoredPackage(
            view=ProjectPackageView.model_validate_json(row["payload"]),
            artifact_path=artifact,
            request_identity=str(row["request_identity"]),
            generation=int(row["generation"]),
        )

    def begin_package(
        self,
        job_id: str,
        request_identity: str,
        package: ProjectPackageView,
    ) -> PackageAttempt:
        if (
            package.job_id != job_id
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
                if stored.view.stage is not ProjectPackageStage.FAILED:
                    return PackageAttempt(stored.view, stored.generation, False)
                generation = stored.generation + 1
                updated = connection.execute(
                    "UPDATE project_packages SET stage = ?, generation = ?, payload = ?, "
                    "artifact_path = NULL WHERE job_id = ? AND request_identity = ? "
                    "AND generation = ? AND stage = ?",
                    (
                        package.stage,
                        generation,
                        package.model_dump_json(),
                        job_id,
                        request_identity,
                        stored.generation,
                        ProjectPackageStage.FAILED,
                    ),
                )
                if updated.rowcount != 1:
                    raise InvalidTransition("package retry lost its state lease")
                return PackageAttempt(package, generation, True)
            connection.execute(
                "INSERT INTO project_packages"
                "(job_id, request_identity, stage, generation, payload) VALUES (?, ?, ?, ?, ?)",
                (job_id, request_identity, package.stage, 1, package.model_dump_json()),
            )
        return PackageAttempt(package, 1, True)

    def get_package(
        self, job_id: str, request_identity: str | None = None
    ) -> StoredPackage:
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
            if (
                int(existing["generation"]) != generation
                or current not in expected_stages
                or package.stage not in _PACKAGE_TRANSITIONS.get(current, set())
            ):
                raise InvalidTransition("package transition lost its state lease")
            assignments = "stage = ?, payload = ?"
            values: list[object] = [package.stage, package.model_dump_json()]
            if artifact_path is not _PRESERVE_ARTIFACT:
                assignments += ", artifact_path = ?"
                values.append(None if artifact_path is None else str(artifact_path))
            values.extend((job_id, request_identity, generation, current))
            updated = connection.execute(
                f"UPDATE project_packages SET {assignments} WHERE job_id = ? "
                "AND request_identity = ? AND generation = ? AND stage = ?",
                values,
            )
            if updated.rowcount != 1:
                raise InvalidTransition("package transition lost its state lease")
        return package

    def recover_incomplete_packages(self) -> int:
        recovered = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT job_id, stage, generation FROM project_packages "
                "WHERE stage IN (?, ?)",
                (ProjectPackageStage.CHECKING, ProjectPackageStage.PACKAGING),
            ).fetchall()
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
                    "UPDATE project_packages SET stage = ?, payload = ? WHERE job_id = ? "
                    "AND generation = ? AND stage = ?",
                    (
                        ProjectPackageStage.FAILED,
                        failed.model_dump_json(),
                        row["job_id"],
                        row["generation"],
                        row["stage"],
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
