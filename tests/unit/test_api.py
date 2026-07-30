from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image

from figma_to_fgui.api import create_app
from figma_to_fgui.artifacts import ArtifactStore
from figma_to_fgui.figma_selection import SelectionManifest
from figma_to_fgui.job_store import JobStore
from figma_to_fgui.selection_store import SelectionStore
from figma_to_fgui.service_contracts import (
    ChangeBundle,
    ChangeFile,
    FileOperation,
    JobStatus,
    JobView,
)
from tests.helpers.zip_projects import write_project_zip


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            allow_fixture_jobs=True,
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
    response = client.get("/health")

    assert response.json() == {"status": "ok"}
    assert "x-figma-to-fgui-instance" not in response.headers


def test_health_echoes_configured_instance_token_only_in_header(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            health_instance_token="test-instance-token",
        )
    )

    response = client.get("/health")

    assert response.json() == {"status": "ok"}
    assert response.headers["x-figma-to-fgui-instance"] == "test-instance-token"


def test_public_origin_cors_allows_only_the_configured_https_origin(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            public_origin="https://fgui.corp.example",
        )
    )

    allowed = client.options(
        "/v1/figma/pairings", headers={
            "Origin": "https://fgui.corp.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    blocked = client.options(
        "/v1/figma/pairings", headers={
            "Origin": "https://other.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert allowed.headers["access-control-allow-origin"] == "https://fgui.corp.example"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in blocked.headers


def test_plugin_access_accepts_only_configured_token_and_null_origin(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            plugin_access_token=b"test-plugin-token",
        )
    )

    preflight = client.options(
        "/v1/figma/selections/uploads",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-figma-plugin-token,content-type",
        },
    )

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "null"
    blocked_origin = client.options(
        "/v1/figma/selections/uploads",
        headers={"Origin": "https://other.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in blocked_origin.headers
    assert (
        client.post("/v1/figma/selections/uploads", json={"version": 1, "idempotency_key": "k"}).status_code
        == 401
    )
    assert client.post(
        "/v1/figma/selections/uploads",
        json={"version": 1, "idempotency_key": "k"},
        headers={"X-Figma-Plugin-Token": "wrong"},
    ).status_code == 401
    assert (
        client.post(
            "/v1/figma/selections/uploads",
            json={"version": 1, "idempotency_key": "k"},
            headers={"X-Figma-Plugin-Token": "test-plugin-token"},
        ).status_code
        == 201
    )


def test_gateway_secret_blocks_raw_api_requests_before_endpoint_logic(tmp_path: Path) -> None:
    token = b"g" * 32
    client = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            plugin_secret=b"p" * 32,
            gateway_secret=token,
            public_origin="https://fgui.corp.example",
            allow_fixture_jobs=True,
        )
    )
    requests = (
        ("POST", "/v1/agents/register"),
        ("POST", "/v1/projects/bind"),
        ("POST", "/v1/jobs/missing/approve"),
        ("GET", "/v1/agents/agent-1/assignments/next"),
        ("GET", "/v1/agents/agent-1/assignments/missing/artifact"),
        ("POST", "/v1/jobs/missing/apply-result"),
        ("POST", "/v1/figma/pairings"),
        ("POST", "/v1/figma/selections/uploads"),
    )

    for method, path in requests:
        assert client.request(method, path).status_code == 401
        assert client.request(
            method, path, headers={"X-Figma-Gateway-Token": "wrong"}
        ).status_code == 401

    headers = {"X-Figma-Gateway-Token": token.decode("ascii")}
    assert client.post(
        "/v1/agents/register", headers=headers, json={"version": 1, "agent_id": "agent-1", "name": "Desk"}
    ).status_code == 200
    assert client.post("/v1/figma/pairings", headers=headers).status_code == 201
    assert client.get("/health").status_code == 200

    preflight = client.options(
        "/v1/figma/pairings", headers={
            "Origin": "https://fgui.corp.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://fgui.corp.example"


def test_plugin_access_bypasses_the_gateway_boundary_for_plugin_routes(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            plugin_access_token=b"test-plugin-token",
            gateway_secret=b"g" * 32,
        )
    )

    response = client.post(
        "/v1/figma/selections/uploads",
        json={"version": 1, "idempotency_key": "k"},
        headers={"X-Figma-Plugin-Token": "test-plugin-token"},
    )

    assert response.status_code == 201


def test_template_project_routes_use_approved_catalog_and_project_store(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    template = templates / "fgui-2024-web"
    package = template / "Starter"
    package.mkdir(parents=True)
    (template / "template.json").write_text(
        '{"template_id":"fgui-2024-web","fairygui_version":"2024.2",'
        '"target_platform":"web","display_name":"Web starter"}',
        "utf-8",
    )
    (package / "package.xml").write_text("<package id='starter'><resources/></package>", "utf-8")
    client = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            templates_root=templates,
            plugin_access_token=b"test-plugin-token",
            gateway_secret=b"g" * 32,
        )
    )
    headers = {"X-Figma-Plugin-Token": "test-plugin-token"}

    options = client.get("/v1/figma/project-options", headers=headers)
    unknown = client.post(
        "/v1/projects/from-template",
        headers=headers,
        json={"version": 1, "template_id": "missing", "project_name": "Quiz"},
    )
    invalid_name = client.post(
        "/v1/projects/from-template",
        headers=headers,
        json={"version": 1, "template_id": "fgui-2024-web", "project_name": "../Quiz"},
    )
    created = client.post(
        "/v1/projects/from-template",
        headers=headers,
        json={"version": 1, "template_id": "fgui-2024-web", "project_name": "Quiz"},
    )

    assert options.json() == {
        "version": 1,
        "options": [
            {
                "template_id": "fgui-2024-web",
                "fairygui_version": "2024.2",
                "target_platform": "web",
                "display_name": "Web starter",
            }
        ],
    }
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "template_not_found"
    assert invalid_name.status_code == 400
    assert invalid_name.json()["detail"]["code"] == "invalid_project_name"
    assert created.status_code == 201
    project = created.json()
    assert project["display_name"] == "Quiz"
    assert project["packages"] == [{"name": "Quiz", "resource_count": 1}]
    assert client.get(f"/v1/projects/{project['project_id']}", headers=headers).json() == project

def _plugin_manifest() -> dict[str, object]:
    image = _image("red", "PNG", (1, 1))
    return {
        "version": 1,
        "display_name": "Checkout",
        "top_level_nodes": [
            {
                "id": "12:4",
                "name": "Checkout",
                "type": "FRAME",
                "bounds": {"x": 0, "y": 0, "width": 32, "height": 16},
                "resource_keys": ["hero"],
            }
        ],
        "resources": [{"key": "hero", "mime_type": "image/png", "size": len(image)}],
    }


def _plugin_project_zip(tmp_path: Path) -> Path:
    return write_project_zip(
        tmp_path / "GameUI.zip",
        {
            "Sample/package.xml": (
                b"<package id='pkg-sample'><resources>"
                b"<image id='img-background' name='Background.png' path='assets'/>"
                b"</resources></package>"
            ),
            "Sample/Panel/Main.xml": b"<component/>",
            "Sample/assets/Background.png": _image("blue", "PNG", (1, 1)),
        },
    )


def test_direct_plugin_policy_rejects_wrong_tokens_and_allows_every_task_one_route(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            plugin_access_token=b"test-plugin-token",
            gateway_secret=b"g" * 32,
        )
    )
    headers = {"X-Figma-Plugin-Token": "test-plugin-token"}
    wrong = {"X-Figma-Plugin-Token": "wrong"}
    image = _image("red", "PNG", (1, 1))

    assert client.post(
        "/v1/figma/selections/uploads",
        headers=wrong,
        json={"version": 1, "idempotency_key": "direct"},
    ).status_code == 401
    upload_id = client.post(
        "/v1/figma/selections/uploads",
        headers=headers,
        json={"version": 1, "idempotency_key": "direct"},
    ).json()["upload_id"]

    manifest_url = f"/v1/figma/selections/uploads/{upload_id}/manifest"
    assert client.put(manifest_url, headers=wrong, json=_plugin_manifest()).status_code == 401
    assert client.put(manifest_url, headers=headers, json=_plugin_manifest()).status_code == 200

    resource_url = f"/v1/figma/selections/uploads/{upload_id}/resources/hero"
    assert client.put(resource_url, headers={**wrong, "content-type": "image/png"}, content=image).status_code == 401
    assert client.put(resource_url, headers={**headers, "content-type": "image/png"}, content=image).status_code == 200

    commit_url = f"/v1/figma/selections/uploads/{upload_id}/commit"
    assert client.post(commit_url, headers=wrong).status_code == 401
    selection = client.post(commit_url, headers=headers)
    assert selection.status_code == 200
    selection_id = selection.json()["selection_id"]

    selection_url = f"/v1/figma/selections/{selection_id}"
    preview_url = f"{selection_url}/previews/0"
    assert client.get(selection_url, headers=wrong).status_code == 401
    assert client.get(selection_url, headers=headers).status_code == 200
    assert client.get(preview_url, headers=wrong).status_code == 401
    assert client.get(preview_url, headers=headers).status_code == 200

    project_zip = _plugin_project_zip(tmp_path)
    with project_zip.open("rb") as content:
        assert client.post(
            "/v1/projects/uploads",
            headers=wrong,
            files={"project": (project_zip.name, content, "application/zip")},
        ).status_code == 401
    with project_zip.open("rb") as content:
        project = client.post(
            "/v1/projects/uploads",
            headers=headers,
            files={"project": (project_zip.name, content, "application/zip")},
        )
    assert project.status_code == 201
    project_id = project.json()["project_id"]

    project_url = f"/v1/projects/{project_id}"
    packages_url = f"{project_url}/packages"
    thumbnail_url = f"{project_url}/assets/img-background/thumbnail"
    for url in (project_url, packages_url, thumbnail_url):
        assert client.get(url, headers=wrong).status_code == 401
        assert client.get(url, headers=headers).status_code == 200

    job_url = f"/v1/figma/selections/{selection_id}/projects/{project_id}/jobs"
    job_payload = {
        "version": 1,
        "selection_id": selection_id,
        "project_id": project_id,
        "package_name": "Sample",
    }
    assert client.post(job_url, headers=wrong, json=job_payload).status_code == 401
    job = client.post(job_url, headers=headers, json=job_payload)
    assert job.status_code == 200
    status_url = f"/v1/jobs/{job.json()['job_id']}"
    assert client.get(status_url, headers=wrong).status_code == 401
    assert client.get(status_url, headers=headers).status_code == 200


def test_direct_token_mode_preserves_authenticated_console_job_status(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    JobStore(data_dir / "server.db").initialize()
    JobStore(data_dir / "server.db").create_job(
        JobView(job_id="console-job", project_id="project-1", status=JobStatus.CREATED)
    )
    client = TestClient(
        create_app(
            data_dir=data_dir,
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            plugin_access_token=b"test-plugin-token",
            gateway_secret=b"g" * 32,
        )
    )

    response = client.get(
        "/v1/jobs/console-job", headers={"X-Figma-Gateway-Token": "g" * 32}
    )

    assert response.status_code == 200


def test_direct_token_mode_preserves_console_session_selection_job_creation(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    gateway_headers = {"X-Figma-Gateway-Token": "g" * 32}
    plugin_headers = {"X-Figma-Plugin-Token": "test-plugin-token"}
    client = TestClient(
        create_app(
            data_dir=data_dir,
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            plugin_secret=b"p" * 32,
            plugin_access_token=b"test-plugin-token",
            gateway_secret=b"g" * 32,
        )
    )
    pairing = client.post("/v1/figma/pairings", headers=gateway_headers).json()
    exchanged = client.post(
        "/v1/figma/pairings/exchange",
        headers=gateway_headers,
        json={"version": 1, "code": pairing["code"], "device_name": "Figma desktop"},
    ).json()
    device_id = exchanged["device"]["device_id"]
    selection_store = SelectionStore(data_dir)
    upload = selection_store.create_upload(device_id, "console-selection")
    manifest = SelectionManifest.model_validate(_plugin_manifest())
    selection_store.put_manifest(upload.upload_id, device_id, manifest)
    selection_store.put_resource(
        upload.upload_id, device_id, "hero", "image/png", _image("red", "PNG", (1, 1))
    )
    selection = selection_store.commit(upload.upload_id, device_id)
    project_zip = _plugin_project_zip(tmp_path)
    with project_zip.open("rb") as content:
        project = client.post(
            "/v1/projects/uploads",
            headers=plugin_headers,
            files={"project": (project_zip.name, content, "application/zip")},
        ).json()
    job_url = f"/v1/figma/selections/{selection.selection_id}/projects/{project['project_id']}/jobs"

    response = client.post(
        job_url,
        headers={**gateway_headers, "X-Figma-Console-Session": pairing["console_credential"]},
        json={
            "version": 1,
            "selection_id": selection.selection_id,
            "project_id": project["project_id"],
            "package_name": "Sample",
        },
    )

    assert response.status_code == 200, response.text


def test_gateway_still_protects_legacy_pairing_routes(tmp_path: Path) -> None:
    gateway_token = b"g" * 32
    client = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            plugin_secret=b"p" * 32,
            gateway_secret=gateway_token,
        )
    )
    gateway_headers = {"X-Figma-Gateway-Token": gateway_token.decode("ascii")}
    code = client.post("/v1/figma/pairings", headers=gateway_headers).json()["code"]
    credential = client.post(
        "/v1/figma/pairings/exchange",
        headers=gateway_headers,
        json={"version": 1, "code": code, "device_name": "Figma desktop"},
    ).json()["credential"]
    request_headers = {"authorization": f"Bearer {credential}"}

    assert client.post(
        "/v1/figma/selections/uploads",
        headers=request_headers,
        json={"version": 1, "idempotency_key": "k"},
    ).status_code == 401
    assert client.post(
        "/v1/figma/selections/uploads",
        headers={**gateway_headers, **request_headers},
        json={"version": 1, "idempotency_key": "k"},
    ).status_code == 201


def test_gateway_secret_leaves_health_and_plugin_shell_accessible(tmp_path: Path) -> None:
    web_dist = tmp_path / "web-dist"
    (web_dist / "assets").mkdir(parents=True)
    (web_dist / "index.html").write_text("<div id='root'></div>", "utf-8")
    client = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            web_dist=web_dist,
            gateway_secret=b"g" * 32,
        )
    )

    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/figma-plugin").status_code == 200


def _image(color: str, image_format: str, size: tuple[int, int] = (2, 2)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, image_format)
    return output.getvalue()


def test_designer_image_routes_only_serve_declared_image_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixtures = tmp_path / "fixtures"
    before = _image("red", "TIFF", (1200, 700))
    after = _image("blue", "BMP", (900, 800))
    image_path = fixtures / "fgui" / "Sample" / "assets" / "Hero.tiff"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(before)
    app = create_app(
        data_dir=tmp_path / "data",
        fixtures_root=fixtures,
        rules_path=Path("rules/default/classification.yaml"),
    )
    bundle = ChangeBundle(
        job_id="image-job",
        project_id="project-1",
        files=(
            ChangeFile(
                operation=FileOperation.REPLACE,
                relative_path="Sample/assets/Hero.tiff",
                before_sha256=hashlib.sha256(before).hexdigest(),
                after_sha256=hashlib.sha256(after).hexdigest(),
                content_b64=base64.b64encode(after).decode("ascii"),
            ),
            ChangeFile(
                operation=FileOperation.REPLACE,
                relative_path="Sample/Panel/Main.xml",
                before_sha256="a" * 64,
                after_sha256="b" * 64,
                content_b64=base64.b64encode(b"<component/>").decode("ascii"),
            ),
        ),
    )
    artifact_sha256 = ArtifactStore(tmp_path / "data" / "artifacts").put(bundle)
    JobStore(tmp_path / "data" / "server.db").create_job(
        JobView(
            job_id=bundle.job_id,
            project_id=bundle.project_id,
            status=JobStatus.READY_FOR_REVIEW,
            artifact_sha256=artifact_sha256,
        )
    )
    browser = TestClient(app)

    preview = browser.get("/v1/jobs/image-job/designer-preview")
    assert preview.status_code == 200
    change = preview.json()["changes"][0]
    assert change["before_image_url"] == "/v1/jobs/image-job/designer-preview/images/0/before"
    assert change["after_image_url"] == "/v1/jobs/image-job/designer-preview/images/0/after"
    assert "Sample/assets" not in preview.text

    before_response = browser.get(change["before_image_url"])
    after_response = browser.get(change["after_image_url"])
    assert before_response.status_code == after_response.status_code == 200
    assert before_response.headers["content-type"] == after_response.headers["content-type"] == "image/webp"
    for response in (before_response, after_response):
        with Image.open(BytesIO(response.content)) as preview_image:
            assert preview_image.format == "WEBP"
            assert max(preview_image.size) <= 512
    assert before_response.content != before
    assert after_response.content != after
    assert browser.get("/v1/jobs/image-job/designer-preview/images/1/after").status_code == 404
    assert browser.get("/v1/jobs/image-job/designer-preview/images/9/before").status_code == 404

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 3)
    unavailable = browser.get("/v1/jobs/image-job/designer-preview").json()["changes"][0]
    assert unavailable["before_image_url"] is None
    assert unavailable["after_image_url"] is None
    assert browser.get("/v1/jobs/image-job/designer-preview/images/0/before").status_code == 404
    assert browser.get("/v1/jobs/image-job/designer-preview/images/0/after").status_code == 404
