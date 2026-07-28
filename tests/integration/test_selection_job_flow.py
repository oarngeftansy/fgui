from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from figma_to_fgui.agent import AgentClient, AgentConfig, bind_local_project
from figma_to_fgui.api import create_app
from figma_to_fgui.service_contracts import ApplyStatus
from tests.helpers.zip_projects import write_project_zip


def _credential(client: TestClient) -> str:
    code = client.post("/v1/figma/pairings").json()["code"]
    return client.post(
        "/v1/figma/pairings/exchange",
        json={"version": 1, "code": code, "device_name": "Figma desktop"},
    ).json()["credential"]


def _commit_selection(client: TestClient) -> str:
    headers = {"authorization": f"Bearer {_credential(client)}"}
    upload = client.post(
        "/v1/figma/selections/uploads",
        json={"version": 1, "idempotency_key": "live-checkout"},
        headers=headers,
    )
    assert upload.status_code == 201, upload.text
    manifest = {
        "version": 1,
        "display_name": "Live checkout",
        "top_level_nodes": [
            {
                "id": "figma-private-frame",
                "name": "LiveCheckout",
                "type": "FRAME",
                "bounds": {"x": 0, "y": 0, "width": 600, "height": 400},
                "children": [
                    {
                        "id": "figma-private-text",
                        "name": "Live label",
                        "type": "TEXT",
                        "bounds": {"x": 20, "y": 30, "width": 200, "height": 30},
                        "text": "Live text wins",
                    }
                ],
            }
        ],
    }
    assert client.put(
        f"/v1/figma/selections/uploads/{upload.json()['upload_id']}/manifest",
        json=manifest,
        headers=headers,
    ).status_code == 200
    committed = client.post(
        f"/v1/figma/selections/uploads/{upload.json()['upload_id']}/commit", headers=headers
    )
    assert committed.status_code == 200, committed.text
    return str(committed.json()["selection_id"])


def test_live_selection_job_uses_committed_selection_and_not_fixture(tmp_path: Path) -> None:
    archive = write_project_zip(
        tmp_path / "GameUI.zip",
        {
            "Sample/package.xml": b"<package id='sample'><resources/></package>",
        },
    )
    local_project = tmp_path / "local-project"
    (local_project / "Sample").mkdir(parents=True)
    (local_project / "Sample/package.xml").write_bytes(
        b"<package id='sample'><resources/></package>"
    )
    server = TestClient(
        create_app(
            data_dir=tmp_path / "server",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            plugin_secret=b"s" * 32,
        )
    )
    selection_id = _commit_selection(server)
    with archive.open("rb") as content:
        uploaded = server.post(
            "/v1/projects/uploads",
            files={"project": (archive.name, content, "application/zip")},
        )
    assert uploaded.status_code == 201, uploaded.text
    project_id = str(uploaded.json()["project_id"])
    assert server.post(
        "/v1/agents/register",
        json={"version": 1, "agent_id": "agent-1", "name": "Desk"},
    ).status_code == 200
    assert server.post(
        "/v1/projects/bind",
        json={"version": 1, "project_id": project_id, "agent_id": "agent-1"},
    ).status_code == 200
    fixture_job = server.post(
        f"/v1/projects/{project_id}/jobs",
        json={
            "version": 1,
            "project_id": project_id,
            "fixture_name": "simple-frame.json",
            "package_name": "Sample",
        },
    )
    assert fixture_job.status_code == 404
    created = server.post(
        f"/v1/figma/selections/{selection_id}/projects/{project_id}/jobs",
        json={
            "version": 1,
            "selection_id": selection_id,
            "project_id": project_id,
            "package_name": "Sample",
        },
    )
    assert created.status_code == 200, created.text
    job_id = str(created.json()["job_id"])
    for forbidden in ("selection_id", "fingerprint", "figma-private", "fixture"):
        assert forbidden not in created.text.lower()
    with sqlite3.connect(tmp_path / "server" / "server.db") as connection:
        source = connection.execute(
            "SELECT selection_id, selection_fingerprint FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
    assert source == (selection_id, source[1])
    assert len(source[1]) == 64
    preview = server.get(f"/v1/jobs/{job_id}/designer-preview")
    assert preview.status_code == 200, preview.text
    assert "figma-private" not in preview.text.lower()
    fixture = Path("tests/fixtures/figma/simple-frame.json")
    original_fixture = fixture.read_bytes()
    try:
        fixture.write_text('{"name":"fixture mutation"}', "utf-8")
        assert server.post(f"/v1/jobs/{job_id}/approve").status_code == 200

        def relay(request: httpx.Request) -> httpx.Response:
            response = server.request(
                request.method,
                request.url.path,
                content=request.content,
                headers={"content-type": request.headers.get("content-type", "application/json")},
            )
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        applied = AgentClient(
            AgentConfig(
                agent_id="agent-1",
                name="Desk",
                api_url="http://service.test",
                projects={project_id: bind_local_project(local_project)},
            ),
            transport=httpx.MockTransport(relay),
        ).poll_once()
    finally:
        fixture.write_bytes(original_fixture)

    assert applied is not None and applied.status is ApplyStatus.APPLIED
    target = local_project / "Sample" / "Panel" / "Panel_Sample_LiveCheckout.xml"
    assert b"Live text wins" in target.read_bytes()
    assert hashlib.sha256(target.read_bytes()).hexdigest()
    assert server.get(f"/v1/jobs/{job_id}").json()["status"] == "applied"
