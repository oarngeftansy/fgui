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
from figma_to_fgui.job_store import JobStore
from figma_to_fgui.service_contracts import (
    ChangeBundle,
    ChangeFile,
    FileOperation,
    JobStatus,
    JobView,
)


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
