from __future__ import annotations

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from figma_to_fgui.agent import AgentClient, AgentConfig, bind_local_project
from figma_to_fgui.api import create_app
from figma_to_fgui.service_contracts import ApplyStatus
from tests.helpers.figma_selections import commit_live_selection, pair_plugin_device
from tests.helpers.zip_projects import write_project_zip


def test_live_selection_http_review_agent_and_stale_write_loop(tmp_path: Path) -> None:
    """Exercise the public plugin, console, project, and Agent contracts together."""
    fixture_root = tmp_path / "fixtures"
    fixture_root.mkdir()
    (fixture_root / "figma").mkdir()
    fixture = fixture_root / "figma" / "simple-frame.json"
    fixture.write_text('{"name":"fixture must never be read"}', "utf-8")
    local_project = tmp_path / "local-project"
    target = local_project / "Sample" / "Panel" / "Panel_Sample_LiveCheckout.xml"
    target.parent.mkdir(parents=True)
    original = b"<component name='old'/>"
    target.write_bytes(original)
    package = local_project / "Sample" / "package.xml"
    package.write_bytes(b"<package id='sample'><resources/></package>")
    server = TestClient(
        create_app(
            data_dir=tmp_path / "server",
            fixtures_root=fixture_root,
            rules_path=Path("rules/default/classification.yaml"),
            plugin_secret=b"s" * 32,
        )
    )
    paired = pair_plugin_device(server, "Figma desktop")
    selection = commit_live_selection(server, paired.credential, name="LiveCheckout", text="Live text wins")
    current = server.get(
        "/v1/figma/pairings/current/selection",
        headers={"x-figma-console-session": paired.console_session},
    )
    assert current.status_code == 200
    assert current.json()["selection_id"] == selection.selection_id
    for forbidden in ("credential", "secret", "private-node", "asset-png", "asset-svg"):
        assert forbidden not in current.text.lower()

    archive = write_project_zip(
        tmp_path / "GameUI.zip",
        {
            "Sample/package.xml": package.read_bytes(),
            "Sample/Panel/Panel_Sample_LiveCheckout.xml": original,
        },
    )
    with archive.open("rb") as content:
        uploaded = server.post(
            "/v1/projects/uploads",
            files={"project": (archive.name, content, "application/zip")},
        )
    assert uploaded.status_code == 201, uploaded.text
    project_id = str(uploaded.json()["project_id"])
    assert server.post(
        "/v1/agents/register", json={"version": 1, "agent_id": "agent-1", "name": "Desk"}
    ).status_code == 200
    assert server.post(
        "/v1/projects/bind", json={"version": 1, "project_id": project_id, "agent_id": "agent-1"}
    ).status_code == 200
    first_job = _create_live_job(server, paired.console_session, selection.selection_id, project_id)
    first_preview = server.get(f"/v1/jobs/{first_job}/designer-preview")
    assert first_preview.status_code == 200, first_preview.text
    assert "Live text wins" not in first_preview.text
    advanced = server.get(f"/v1/jobs/{first_job}/designer-preview?details=advanced")
    assert advanced.status_code == 200, advanced.text
    generated = next(
        item for item in advanced.json()["details"]["files"]
        if item["relative_path"] == "Sample/Panel/Panel_Sample_LiveCheckout.xml"
    )
    fixture.write_text('{"name":"mutated fixture"}', "utf-8")
    assert server.post(f"/v1/jobs/{first_job}/approve").json()["status"] == "approved"

    agent = _agent(server, project_id, local_project)
    applied = agent.poll_once()
    assert applied is not None and applied.status is ApplyStatus.APPLIED
    assert b"Live text wins" in target.read_bytes()
    assert target.read_bytes() != generated["before_xml"].encode("utf-8")
    backup = local_project / ".figma-to-fgui" / "backups" / first_job / target.relative_to(local_project)
    assert backup.read_bytes() == original

    # The second upload represents the designer's freshly indexed source tree.
    # Generated selection resources are recreated by its next job, so they are
    # intentionally absent from this minimal local project fixture.
    assets = local_project / "Sample" / "assets"
    for generated_asset in assets.iterdir():
        generated_asset.unlink()
    assets.rmdir()
    second_archive = write_project_zip(
        tmp_path / "GameUI-current.zip",
        {
            "Sample/package.xml": package.read_bytes(),
            "Sample/Panel/Panel_Sample_LiveCheckout.xml": target.read_bytes(),
        },
    )
    with second_archive.open("rb") as content:
        uploaded_second = server.post(
            "/v1/projects/uploads",
            files={"project": (second_archive.name, content, "application/zip")},
        )
    assert uploaded_second.status_code == 201, uploaded_second.text
    second_project_id = str(uploaded_second.json()["project_id"])
    assert server.post(
        "/v1/projects/bind", json={"version": 1, "project_id": second_project_id, "agent_id": "agent-1"}
    ).status_code == 200
    second_selection = commit_live_selection(server, paired.credential, name="LiveCheckout", text="Second live text")
    second_job = _create_live_job(server, paired.console_session, second_selection.selection_id, second_project_id)
    assert server.post(f"/v1/jobs/{second_job}/approve").status_code == 200

    def stale_relay(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/{second_job}/artifact"):
            target.write_bytes(b"<component name='local-change'/>")
        return _relay(server, request)

    stale_agent = AgentClient(
        agent.config.model_copy(
            update={"projects": {project_id: bind_local_project(local_project), second_project_id: bind_local_project(local_project)}}
        ),
        transport=httpx.MockTransport(stale_relay),
    )
    blocked = stale_agent.poll_once()
    assert blocked is not None and blocked.status is ApplyStatus.FAILED
    assert blocked.diagnostics[0].code == "local_project_changed"
    assert target.read_bytes() == b"<component name='local-change'/>"
    assert not (local_project / ".figma-to-fgui" / "backups" / second_job).exists()


def _create_live_job(server: TestClient, console_session: str, selection_id: str, project_id: str) -> str:
    created = server.post(
        f"/v1/figma/selections/{selection_id}/projects/{project_id}/jobs",
        json={"version": 1, "selection_id": selection_id, "project_id": project_id, "package_name": "Sample"},
        headers={"x-figma-console-session": console_session},
    )
    assert created.status_code == 200, created.text
    return str(created.json()["job_id"])


def _relay(server: TestClient, request: httpx.Request) -> httpx.Response:
    response = server.request(
        request.method,
        request.url.path,
        content=request.content,
        headers={"content-type": request.headers.get("content-type", "application/json")},
    )
    return httpx.Response(response.status_code, content=response.content, headers=response.headers)


def _agent(server: TestClient, project_id: str, local_project: Path) -> AgentClient:
    return AgentClient(
        AgentConfig(
            agent_id="agent-1",
            name="Desk",
            api_url="http://service.test",
            projects={project_id: bind_local_project(local_project)},
        ),
        transport=httpx.MockTransport(lambda request: _relay(server, request)),
    )
