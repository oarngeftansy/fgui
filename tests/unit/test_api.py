from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from figma_to_fgui.api import create_app


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


def test_job_can_be_previewed_approved_and_claimed(client: TestClient) -> None:
    register_and_bind(client)
    created = create_job(client)
    assert created["status"] == "ready_for_review"
    job_id = created["job_id"]

    preview = client.get(f"/v1/jobs/{job_id}/preview")
    assert preview.status_code == 200
    assert preview.json()["files"][0]["relative_path"].endswith(".xml")

    approved = client.post(f"/v1/jobs/{job_id}/approve")
    assert approved.json()["status"] == "approved"
    assert client.post(f"/v1/jobs/{job_id}/approve").json() == approved.json()

    assignment = client.get("/v1/agents/agent-1/assignments/next")
    assert assignment.status_code == 200
    assert assignment.json()["status"] == "applying"
    assert client.get("/v1/agents/agent-1/assignments/next").status_code == 204

    bundle = client.get(f"/v1/jobs/{job_id}/changeset")
    assert bundle.status_code == 200
    assert bundle.json()["job_id"] == job_id


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
