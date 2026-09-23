from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from psd_tools import PSDImage

from figma_to_fgui.api import create_app
from figma_to_fgui.psd_intake import PsdIntakeError, inspect_psd


def test_inspect_psd_reports_source_identity_and_document_shape(tmp_path: Path) -> None:
    source = tmp_path / "screen.psd"
    PSDImage.new(mode="RGB", size=(1080, 2340), depth=16).save(source)

    report = inspect_psd(source, source_name=source.name)

    assert report.source_name == "screen.psd"
    assert report.byte_size == source.stat().st_size
    assert len(report.sha256) == 64
    assert report.width == 1080
    assert report.height == 2340
    assert report.depth == 16
    assert report.color_mode == "RGB"
    assert report.layer_count == 0
    assert report.kind_counts == {}
    assert report.blocking_issues == ()


def test_inspect_psd_rejects_non_psd_without_reading_it_as_an_image(tmp_path: Path) -> None:
    source = tmp_path / "screen.psd"
    source.write_bytes(b"not a psd")

    with pytest.raises(PsdIntakeError, match="invalid_psd"):
        inspect_psd(source, source_name=source.name)


def test_psd_inspection_api_streams_and_reports_the_uploaded_source(tmp_path: Path) -> None:
    source = tmp_path / "screen.psd"
    PSDImage.new(mode="RGB", size=(1080, 2340), depth=16).save(source)
    client = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            plugin_access_token=b"test-token",
        )
    )

    with source.open("rb") as content:
        response = client.post(
            "/v1/hifi-sources/psd/inspect",
            files={"psd": (source.name, content, "image/vnd.adobe.photoshop")},
            headers={"x-figma-plugin-token": "test-token"},
        )

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["source_name"] == "screen.psd"
    assert report["width"] == 1080
    assert report["height"] == 2340
    assert report["depth"] == 16
    assert report["warnings"] == ["16_bit_pixels_must_not_be_downconverted"]
    assert not list((tmp_path / "data" / "psd-intake").glob("*.psd"))


def test_psd_inspection_api_requires_plugin_access(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            plugin_access_token=b"test-token",
        )
    )

    response = client.post("/v1/hifi-sources/psd/inspect", files={"psd": ("x.psd", b"8BPS", "image/vnd.adobe.photoshop")})

    assert response.status_code == 401
