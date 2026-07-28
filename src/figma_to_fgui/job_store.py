from __future__ import annotations

import sqlite3
from pathlib import Path

from figma_to_fgui.service_contracts import (
    AgentRegistration,
    ApplyResult,
    ApplyStatus,
    JobStatus,
    JobView,
    ProjectBinding,
)


class StoreError(RuntimeError):
    code = "store_error"


class NotFound(StoreError):
    code = "not_found"


class InvalidTransition(StoreError):
    code = "invalid_transition"


class OwnershipMismatch(StoreError):
    code = "ownership_mismatch"


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
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_status_project
                    ON jobs(status, project_id, job_id);
                CREATE TABLE IF NOT EXISTS apply_results (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
                    payload TEXT NOT NULL
                );
                """
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

    def create_job(self, job: JobView) -> JobView:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs(job_id, project_id, status, payload) VALUES (?, ?, ?, ?)",
                (job.job_id, job.project_id, job.status, job.model_dump_json()),
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
