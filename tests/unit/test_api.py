from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from figma_to_fgui.api import create_app
from figma_to_fgui.service_contracts import ChangeBundle


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
        )
    )


def register_and_bind(client: TestClient, agent_id: str = "agent-1") -> None:
    response = client.post(
        "/v1/agents/register",
        json={"version": 1, "agent_id": agent_id, "name": "Desk"},
    )
    assert response.status_code == 200
    response = client.post(
        "/v1/projects/bind",
        json={"version": 1, "project_id": "project-1", "agent_id": agent_id},
    )
    assert response.status_code == 200


def create_job(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/v1/jobs",
        json={
            "version": 1,
            "fixture_name": "simple-frame.json",
            "project_id": "project-1",
            "package_name": "Sample",
        },
    )
    assert response.status_code == 200
    return response.json()


def assert_designer_job_is_safe(payload: dict[str, object]) -> None:
    for forbidden in (
        "artifact_sha256",
        "project_fingerprint",
        "diagnostics",
        "rule_id",
        "relative_path",
        "changeset",
    ):
        assert forbidden not in payload


def assert_redacted_bundle(response: Response, job_id: str, migration: str) -> None:
    assert response.status_code == 200
    headers = response.headers
    assert headers["deprecation"] == "true"
    assert migration in headers["link"]
    payload = response.json()
    bundle = ChangeBundle.model_validate(payload)
    assert bundle.job_id == job_id
    assert bundle.files == ()
    for forbidden in ("sha256", "content_b64", "relative_path", "<component", "rule_id"):
        assert forbidden not in response.text


def test_job_public_routes_hide_operational_details(client: TestClient) -> None:
    register_and_bind(client)
    created = create_job(client)
    assert created["status"] == "ready_for_review"
    assert_designer_job_is_safe(created)
    job_id = created["job_id"]

    assert client.get(f"/v1/jobs/{job_id}").status_code == 200
    assert_designer_job_is_safe(client.get(f"/v1/jobs/{job_id}").json())
    preview = client.get(f"/v1/jobs/{job_id}/preview")
    assert_redacted_bundle(preview, job_id, "/designer-preview")
    assert_redacted_bundle(
        client.get(f"/v1/jobs/{job_id}/changeset"), job_id, "/assignments/"
    )

    approved = client.post(f"/v1/jobs/{job_id}/approve")
    assert approved.json()["status"] == "approved"
    assert_designer_job_is_safe(approved.json())
    assert client.post(f"/v1/jobs/{job_id}/approve").json() == approved.json()

    assignment = client.get("/v1/agents/agent-1/assignments/next")
    assert assignment.status_code == 200
    assert assignment.json()["status"] == "applying"
    assert client.get("/v1/agents/agent-1/assignments/next").status_code == 204

    bundle = client.get(f"/v1/agents/agent-1/assignments/{job_id}/artifact")
    assert bundle.status_code == 200
    assert bundle.json()["job_id"] == job_id
    assert bundle.json()["files"]
    assert client.get(f"/v1/agents/agent-2/assignments/{job_id}/artifact").status_code == 409

    applied = client.post(
        f"/v1/jobs/{job_id}/apply-result",
        json={
            "version": 1,
            "job_id": job_id,
            "agent_id": "agent-1",
            "project_id": "project-1",
            "status": "applied",
        },
    )
    assert applied.status_code == 200
    assert_designer_job_is_safe(applied.json())


def test_wrong_agent_cannot_claim_job(client: TestClient) -> None:
    register_and_bind(client, "agent-a")
    client.post(
        "/v1/agents/register",
        json={"version": 1, "agent_id": "agent-b", "name": "Other"},
    )
    job_id = create_job(client)["job_id"]
    client.post(f"/v1/jobs/{job_id}/approve")
    assert client.get("/v1/agents/agent-b/assignments/next").status_code == 204


def test_fixture_path_escape_is_rejected_without_leaking_paths(client: TestClient) -> None:
    register_and_bind(client)
    response = client.post(
        "/v1/jobs",
        json={
            "version": 1,
            "fixture_name": "../fgui/Sample/package.xml",
            "project_id": "project-1",
            "package_name": "Sample",
        },
    )
    assert response.status_code == 400
    assert "tests" not in response.text
    assert ":\\" not in response.text


def test_missing_job_returns_structured_not_found(client: TestClient) -> None:
    response = client.get("/v1/jobs/missing")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
