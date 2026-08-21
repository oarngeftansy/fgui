from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi.testclient import TestClient
from httpx import Response

from figma_to_fgui.api import create_app
from figma_to_fgui.fgui_new_project_review import DesignerCheck, NewProjectDesignerReview
from figma_to_fgui.fgui_new_project_validate import validate_project_archive
from figma_to_fgui.models import Severity
from figma_to_fgui.service_contracts import NewProjectAdjustmentStrategy

PLUGIN_HEADERS = {"X-Figma-Plugin-Token": "writer-e2e-token"}
ONE_PIXEL_PNG = (
    Path(__file__).parents[1] / "fixtures" / "fgui-new-project" / "resources" / "one-pixel.png"
).read_bytes()


def _json_keys(value: object) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(
            key
            for item_key, item_value in value.items()
            for key in (str(item_key), *_json_keys(item_value))
        )
    if isinstance(value, list):
        return tuple(key for item in value for key in _json_keys(item))
    return ()


class PublicFlow:
    """Record only public paths and JSON field names used by this E2E."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    def request(self, method: str, path: str, **kwargs: Any) -> Response:
        self.calls.append((method, path, _json_keys(kwargs.get("json"))))
        return self.client.request(method, path, **kwargs)


def _replace_review(
    client: TestClient, build_id: str, review: NewProjectDesignerReview
) -> None:
    with sqlite3.connect(client.app.state.job_store.database) as connection:
        connection.execute(
            "UPDATE new_fgui_projects SET review_payload = ? WHERE build_id = ?",
            (review.model_dump_json(), build_id),
        )


def _download_name(response: Response) -> str:
    disposition = response.headers["content-disposition"]
    encoded = re.search(r"filename\*=[^']*''([^;]+)", disposition, flags=re.IGNORECASE)
    if encoded is not None:
        return unquote(encoded.group(1).strip('"'))
    plain = re.search(r'filename="?([^";]+)', disposition, flags=re.IGNORECASE)
    assert plain is not None, disposition
    return plain.group(1)


def test_public_plugin_writer_delivery_is_approval_gated_and_generation_safe(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            plugin_access_token=b"writer-e2e-token",
            gateway_secret=b"e" * 32,
        )
    )
    public = PublicFlow(client)

    created = public.request(
        "POST",
        "/v1/figma/selections/uploads",
        headers=PLUGIN_HEADERS,
        json={"version": 1, "idempotency_key": "neutral-image-delivery-e2e"},
    )
    assert created.status_code == 201, created.text
    upload_id = created.json()["upload_id"]
    manifest = {
        "version": 1,
        "display_name": "Neutral Image Delivery",
        "top_level_nodes": [
            {
                "id": "neutral-frame",
                "name": "NeutralFrame",
                "type": "FRAME",
                "bounds": {"x": 0, "y": 0, "width": 1, "height": 1},
                "resource_keys": ["neutral_png"],
            }
        ],
        "resources": [
            {"key": "neutral_png", "mime_type": "image/png", "size": len(ONE_PIXEL_PNG)}
        ],
        "warnings": [
            {"code": "selection-review", "message": "Review the neutral source selection."}
        ],
    }
    accepted = public.request(
        "PUT",
        f"/v1/figma/selections/uploads/{upload_id}/manifest",
        headers=PLUGIN_HEADERS,
        json=manifest,
    )
    assert accepted.status_code == 200, accepted.text
    resource = public.request(
        "PUT",
        f"/v1/figma/selections/uploads/{upload_id}/resources/neutral_png",
        headers={**PLUGIN_HEADERS, "content-type": "image/png"},
        content=ONE_PIXEL_PNG,
    )
    assert resource.status_code == 200, resource.text
    committed = public.request(
        "POST",
        f"/v1/figma/selections/uploads/{upload_id}/commit",
        headers=PLUGIN_HEADERS,
    )
    assert committed.status_code == 200, committed.text
    selection_id = committed.json()["selection_id"]

    started = public.request(
        "POST",
        f"/v1/figma/selections/{selection_id}/new-fgui-projects",
        headers=PLUGIN_HEADERS,
        json={"version": 1, "project_name": "NeutralDelivery"},
    )
    assert started.status_code == 202, started.text
    assert started.json()["status"] == "awaiting_review", started.text
    first_build_id = started.json()["build_id"]

    blocked = public.request(
        "GET",
        f"/v1/new-fgui-projects/{first_build_id}/download",
        headers=PLUGIN_HEADERS,
    )
    assert blocked.status_code == 409
    first_review_response = public.request(
        "GET",
        f"/v1/new-fgui-projects/{first_build_id}/review",
        headers=PLUGIN_HEADERS,
    )
    assert first_review_response.status_code == 200, first_review_response.text
    first_review = first_review_response.json()
    assert first_review["generation"] == 1
    assert [item["evidence_kind"] for item in first_review["image_reviews"]] == [
        "source-image"
    ]
    assert {item["evidence_kind"] for item in first_review["component_reviews"]} <= {
        "rendered",
        "structured-summary",
    }
    assert first_review["component_reviews"]
    assert first_review["package_review"] == {
        "package_name": "Generated",
        "fairy_gui_version": "6.1.4",
        "publish_target": "unity",
        "components_added": 1,
        "resources_added": 1,
        "resource_closure_valid": True,
    }
    assert first_review["warning_ids"]
    generated_url = first_review["image_reviews"][0]["generated_asset_url"]
    generated = public.request("GET", generated_url, headers=PLUGIN_HEADERS)
    assert generated.status_code == 200
    assert generated.headers["content-type"].startswith("image/png")
    assert generated.content == ONE_PIXEL_PNG

    # The production review projection deliberately declares the only strategy
    # accepted by the public adjustment endpoint. The mutation is test setup;
    # the adjustment/regeneration traffic below remains entirely public HTTP.
    stored_first = client.app.state.job_store.get_new_project(
        first_build_id, "bundled-figma-plugin"
    )
    assert stored_first.review is not None
    actionable = DesignerCheck(
        id="review:0123456789abcdef",
        severity=Severity.INFO,
        message="Keep the neutral component editable.",
        issue_id="review:0123456789abcdef",
        uir_node_id="uir:neutral-frame",
        actionable=True,
        allowed_strategies=(NewProjectAdjustmentStrategy.PRESERVE_EDITABLE,),
    )
    declared_review = stored_first.review.model_copy(
        update={"checks": (actionable, *stored_first.review.checks)}
    )
    _replace_review(client, first_build_id, declared_review)
    projected = public.request(
        "GET",
        f"/v1/new-fgui-projects/{first_build_id}/review",
        headers=PLUGIN_HEADERS,
    ).json()
    declared_check = next(item for item in projected["checks"] if item["actionable"])
    assert declared_check["allowed_strategies"] == ["preserve-editable"]

    adjusted = public.request(
        "POST",
        f"/v1/new-fgui-projects/{first_build_id}/adjustments",
        headers=PLUGIN_HEADERS,
        json={
            "version": 1,
            "candidate_id": first_build_id,
            "generation": 1,
            "issue_id": declared_check["issue_id"],
            "uir_node_id": declared_check["uir_node_id"],
            "strategy": declared_check["allowed_strategies"][0],
        },
    )
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["status"] == "adjusting"
    regenerated = public.request(
        "POST",
        f"/v1/new-fgui-projects/{first_build_id}/regenerate",
        headers=PLUGIN_HEADERS,
        json={"version": 1, "generation": 1},
    )
    assert regenerated.status_code == 202, regenerated.text
    second_build_id = regenerated.json()["build_id"]
    assert second_build_id != first_build_id
    assert regenerated.json()["status"] == "awaiting_review"

    for method, suffix, payload in (
        ("GET", "/review", None),
        (
            "POST",
            "/approve",
            {"version": 1, "generation": 1, "warning_ids": projected["warning_ids"]},
        ),
        ("GET", "/download", None),
    ):
        stale = public.request(
            method,
            f"/v1/new-fgui-projects/{first_build_id}{suffix}",
            headers=PLUGIN_HEADERS,
            **({"json": payload} if payload is not None else {}),
        )
        assert stale.status_code == 409

    second_review_response = public.request(
        "GET",
        f"/v1/new-fgui-projects/{second_build_id}/review",
        headers=PLUGIN_HEADERS,
    )
    assert second_review_response.status_code == 200, second_review_response.text
    second_review = second_review_response.json()
    assert second_review["generation"] == 2
    assert second_review["warning_ids"]
    assert tuple(
        item["id"] for item in second_review["checks"] if item["severity"] == "WARNING"
    ) == tuple(second_review["warning_ids"])
    approved = public.request(
        "POST",
        f"/v1/new-fgui-projects/{second_build_id}/approve",
        headers=PLUGIN_HEADERS,
        json={
            "version": 1,
            "generation": 2,
            "warning_ids": second_review["warning_ids"],
        },
    )
    assert approved.status_code == 200, approved.text
    approved_view = approved.json()
    assert approved_view["status"] == "approved"

    first_download = public.request(
        "GET",
        f"/v1/new-fgui-projects/{second_build_id}/download",
        headers=PLUGIN_HEADERS,
    )
    second_download = public.request(
        "GET",
        f"/v1/new-fgui-projects/{second_build_id}/download",
        headers=PLUGIN_HEADERS,
    )
    assert first_download.status_code == second_download.status_code == 200
    assert first_download.content == second_download.content
    assert len(first_download.content) == approved_view["byte_size"]
    assert hashlib.sha256(first_download.content).hexdigest() == approved_view["sha256"]
    assert _download_name(first_download) == _download_name(second_download)
    assert _download_name(first_download) == approved_view["download_name"]

    archive_path = tmp_path / "downloaded-current-candidate.zip"
    archive_path.write_bytes(first_download.content)
    stored_second = client.app.state.job_store.get_new_project(
        second_build_id, "bundled-figma-plugin"
    )
    assert stored_second.manifest is not None
    assert validate_project_archive(archive_path, stored_second.manifest) == ()

    observed_paths = tuple(path for _method, path, _keys in public.calls)
    observed_fields = {key for _method, _path, keys in public.calls for key in keys}
    assert any(path.endswith("/adjustments") for path in observed_paths)
    assert any(path.endswith("/regenerate") for path in observed_paths)
    assert observed_paths.count(f"/v1/new-fgui-projects/{second_build_id}/download") == 2
    for forbidden_path in (
        "/v1/templates",
        "/v1/projects/from-template",
        "/v1/projects/uploads",
        "/v1/projects/bind",
        "/v1/agents/",
        "/v1/figma/pairings",
    ):
        assert all(forbidden_path not in path for path in observed_paths)
    assert observed_fields.isdisjoint(
        {
            "agent_id",
            "existing_project",
            "existing_resource",
            "pairing_code",
            "project_binding",
            "project_id",
            "template_id",
        }
    )
    assert "template" not in json.dumps(public.calls, ensure_ascii=False).casefold()
