import json
from pathlib import Path

from figma_to_fgui.figma_selection import (
    SelectionManifest,
    SelectionNode,
    SelectionResource,
)
from figma_to_fgui.models import Bounds
from figma_to_fgui.normalize import normalize_document, selection_document
from figma_to_fgui.pipeline import ConversionRequest, convert, convert_document


def test_selection_document_normalizes_live_nodes_without_figma_rest_shape(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "hero").write_bytes(b"raster")
    (resources / "mark").write_text("<svg/>", "utf-8")
    manifest = SelectionManifest(
        display_name="Checkout",
        resources=(
            SelectionResource(key="hero", mime_type="image/png", size=6),
            SelectionResource(key="mark", mime_type="image/svg+xml", size=6),
        ),
        top_level_nodes=(
            SelectionNode(
                id="private-frame-id",
                name="Checkout Panel",
                type="FRAME",
                bounds=Bounds(x=10, y=20, width=600, height=400),
                style={"layoutMode": "VERTICAL", "itemSpacing": 12},
                properties={"State": "Default"},
                resource_keys=("hero", "mark"),
                children=(
                    SelectionNode(
                        id="private-text-id",
                        name="Purchase label",
                        type="TEXT",
                        bounds=Bounds(x=30, y=44, width=160, height=28),
                        text="Buy now",
                        source_order=1,
                        style={"fontSize": 20},
                    ),
                    SelectionNode(
                        id="private-instance-id",
                        name="Button instance",
                        type="INSTANCE",
                        bounds=Bounds(x=30, y=90, width=160, height=44),
                        source_order=2,
                    ),
                ),
            ),
            SelectionNode(
                id="private-second-frame-id",
                name="Second panel",
                type="FRAME",
                bounds=Bounds(x=700, y=20, width=600, height=400),
                source_order=4,
            ),
        ),
    )

    raw = selection_document(manifest, resources)
    roots, diagnostics = normalize_document(raw)

    assert diagnostics == ()
    assert [node.name for node in roots] == ["Checkout Panel", "Second panel"]
    assert [node.name for node in roots[0].children] == ["Purchase label", "Button instance"]
    assert roots[0].bounds == Bounds(x=10, y=20, width=600, height=400)
    assert roots[0].children[0].text == "Buy now"
    assert roots[1].source_order == 4
    assert roots[0].properties == {"State": "Default"}
    assert roots[0].raw_style == {
        "layoutMode": "VERTICAL",
        "itemSpacing": 12,
        "resourceRefs": (
            {"path": "resources/hero", "mimeType": "image/png"},
            {"path": "resources/mark", "mimeType": "image/svg+xml"},
        ),
    }
    assert "absoluteBoundingBox" not in str(manifest.model_dump())


def test_convert_document_preserves_fixture_conversion_bytes(tmp_path: Path) -> None:
    raw = json.loads(Path("tests/fixtures/figma/simple-frame.json").read_text("utf-8"))
    converted = convert_document(
        raw,
        Path("tests/fixtures/fgui"),
        "Sample",
        tmp_path / "document",
        Path("rules/default/classification.yaml"),
    )
    legacy = convert(
        ConversionRequest(
            figma_json=Path("tests/fixtures/figma/simple-frame.json"),
            project_root=Path("tests/fixtures/fgui"),
            package_name="Sample",
            staging_root=tmp_path / "legacy",
            classification_rules=Path("rules/default/classification.yaml"),
        )
    )

    assert converted == legacy
    assert (tmp_path / "document/Sample/Panel/Panel_Sample_Main.xml").read_bytes() == (
        tmp_path / "legacy/Sample/Panel/Panel_Sample_Main.xml"
    ).read_bytes()
