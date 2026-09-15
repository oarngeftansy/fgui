from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi.testclient import TestClient

from figma_to_fgui.api import create_app

FIXTURE = Path(__file__).parents[1] / "fixtures/hifi_replacement"
HEADERS = {"x-figma-plugin-token": "test-token"}


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            plugin_access_token=b"test-token",
        )
    )


def _upload_project(client: TestClient, tmp_path: Path) -> str:
    source = FIXTURE / "old_project"
    archive = tmp_path / "OldVillage.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for path in source.rglob("*"):
            if path.is_file() and ".figma-to-fgui-preview" not in path.parts:
                output.write(path, path.relative_to(source).as_posix())
    with archive.open("rb") as content:
        response = client.post(
            "/v1/projects/uploads",
            files={"project": (archive.name, content, "application/zip")},
            headers=HEADERS,
        )
    assert response.status_code == 201, response.text
    return response.json()["project_id"]


def _upload_selection(client: TestClient) -> str:
    created = client.post(
        "/v1/figma/selections/uploads",
        json={"version": 1, "idempotency_key": "hifi-selection"},
        headers=HEADERS,
    )
    upload_id = created.json()["upload_id"]
    manifest = (FIXTURE / "hifi-selection.json").read_text("utf-8")
    assert client.put(
        f"/v1/figma/selections/uploads/{upload_id}/manifest",
        content=manifest.encode("utf-8"),
        headers={**HEADERS, "content-type": "application/json"},
    ).status_code == 200
    resource = (FIXTURE / "selection/resources/hifi-board").read_bytes()
    assert client.put(
        f"/v1/figma/selections/uploads/{upload_id}/resources/hifi-board",
        content=resource,
        headers={**HEADERS, "content-type": "image/png"},
    ).status_code == 200
    committed = client.post(
        f"/v1/figma/selections/uploads/{upload_id}/commit", headers=HEADERS
    )
    assert committed.status_code == 200, committed.text
    return committed.json()["selection_id"]


def _target(client: TestClient, project_id: str) -> dict[str, object]:
    response = client.get(f"/v1/projects/{project_id}/hifi-targets", headers=HEADERS)
    assert response.status_code == 200, response.text
    tree = response.json()
    package = next(item for item in tree["packages"] if item["name"] == "MyVillage")
    directory = next(item for item in package["directories"] if item["path"] == "Panel")
    component = next(
        item for item in directory["components"] if item["resource_id"] == "sketch01"
    )
    return {
        "version": 1,
        "project_id": project_id,
        "project_fingerprint": tree["project_fingerprint"],
        "package_id": package["package_id"],
        "package_name": package["name"],
        "directory": directory["path"],
        "component_id": component["resource_id"],
        "component_name": component["name"],
        "component_relative_path": component["relative_path"],
    }


def test_hifi_api_requires_mapping_review_editor_check_and_approval(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id = _upload_project(client, tmp_path)
    selection_id = _upload_selection(client)
    target = _target(client, project_id)
    created = client.post(
        "/v1/hifi-replacements",
        json={
            "version": 1,
            "project_id": project_id,
            "selection_id": selection_id,
            "target": target,
            "idempotency_key": "replacement-1",
        },
        headers=HEADERS,
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    assert client.get(
        f"/v1/hifi-replacements/{session_id}/download", headers=HEADERS
    ).status_code == 409

    while True:
        mapping = client.get(
            f"/v1/hifi-replacements/{session_id}/mapping", headers=HEADERS
        ).json()
        unresolved = next((item for item in mapping["items"] if item["action"] is None), None)
        if unresolved is None:
            break
        if unresolved["status"] in {"uncertain", "suggested"}:
            action = "retarget"
        elif unresolved["status"] == "hifi_added" and unresolved["figma_node_id"] == "progress-bubble":
            action = "add_visual"
        elif unresolved["status"] in {"hifi_added", "blocked"}:
            action = "exception"
        else:
            action = "keep_old"
        response = client.post(
            f"/v1/hifi-replacements/{session_id}/mapping-decisions",
            json={
                "version": 1,
                "mapping_revision": mapping["mapping_revision"],
                "item_id": unresolved["item_id"],
                "action": action,
                **(
                    {"figma_node_id": unresolved["candidates"][0]}
                    if action == "retarget"
                    else {}
                ),
            },
            headers=HEADERS,
        )
        assert response.status_code == 200, response.text

    mapping = client.get(
        f"/v1/hifi-replacements/{session_id}/mapping", headers=HEADERS
    ).json()
    built = client.post(
        f"/v1/hifi-replacements/{session_id}/build",
        json={"version": 1, "mapping_revision": mapping["mapping_revision"]},
        headers=HEADERS,
    )
    assert built.status_code == 200, built.text
    assert built.json()["status"] == "review_ready"
    review = client.get(
        f"/v1/hifi-replacements/{session_id}/review", headers=HEADERS
    )
    assert review.status_code == 200
    assert review.json()["protected_checks_passed"] is True
    assert review.json()["approvable"] is True
    assert len(review.json()["candidate_sha256"]) == 64
    assert {item["kind"] for item in review.json()["object_diffs"]} >= {
        "changed",
        "added",
        "kept",
    }
    candidate = client.get(
        f"/v1/hifi-replacements/{session_id}/candidate/download", headers=HEADERS
    )
    assert candidate.status_code == 200
    assert candidate.content.startswith(b"PK")
    candidate_sha256 = review.json()["candidate_sha256"]
    assert client.get(
        f"/v1/hifi-replacements/{session_id}/download", headers=HEADERS
    ).status_code == 409

    stale = client.post(
        f"/v1/hifi-replacements/{session_id}/approve",
        json={
            "version": 1,
            "layout_checked": True,
            "references_checked": True,
            "interactions_checked": True,
            "editor_version": "6.1.4",
            "candidate_sha256": "0" * 64,
        },
        headers=HEADERS,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "hifi_candidate_stale"

    incomplete = client.post(
        f"/v1/hifi-replacements/{session_id}/approve",
        json={
            "version": 1,
            "layout_checked": True,
            "references_checked": False,
            "interactions_checked": True,
            "editor_version": "6.1.4",
            "candidate_sha256": candidate_sha256,
        },
        headers=HEADERS,
    )
    assert incomplete.status_code == 409
    assert incomplete.json()["detail"]["code"] == "hifi_editor_checks_incomplete"
    approved = client.post(
        f"/v1/hifi-replacements/{session_id}/approve",
        json={
            "version": 1,
            "layout_checked": True,
            "references_checked": True,
            "interactions_checked": True,
            "editor_version": "6.1.4",
            "candidate_sha256": candidate_sha256,
        },
        headers=HEADERS,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    delivered = client.get(
        f"/v1/hifi-replacements/{session_id}/download", headers=HEADERS
    )
    assert delivered.status_code == 200
    assert delivered.content == candidate.content


def test_hifi_routes_require_plugin_access(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post("/v1/hifi-replacements", json={})
    assert response.status_code == 401
