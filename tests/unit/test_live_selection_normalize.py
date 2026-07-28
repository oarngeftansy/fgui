import json
from hashlib import sha256
from pathlib import Path

import pytest
from lxml import etree

from figma_to_fgui.figma_selection import (
    SelectionManifest,
    SelectionNode,
    SelectionResource,
)
from figma_to_fgui.models import Bounds
from figma_to_fgui.normalize import (
    SelectionAsset,
    normalize_document,
    selection_conversion_document,
    selection_document,
)
from figma_to_fgui.pipeline import (
    MAX_SELECTION_CONVERSION_BYTES,
    ConversionLimitError,
    ConversionRequest,
    convert,
    convert_document,
)
from figma_to_fgui.project_index import index_project


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
    references = roots[0].raw_style["resourceRefs"]
    assert {key: value for key, value in roots[0].raw_style.items() if key != "resourceRefs"} == {
        "layoutMode": "VERTICAL",
        "itemSpacing": 12,
    }
    assert references == (
        {"asset": f"asset_{sha256(b'|0|image/png|6').hexdigest()[:16]}", "mimeType": "image/png"},
        {"asset": f"asset_{sha256(b'|1|image/svg+xml|6').hexdigest()[:16]}", "mimeType": "image/svg+xml"},
    )
    for raw_identifier in ("private-frame-id", "private-text-id", "private-instance-id", "hero", "mark"):
        assert raw_identifier not in str(raw)
        assert raw_identifier not in str(roots)
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


def test_selection_resources_materialize_with_opaque_references(tmp_path: Path) -> None:
    resources = tmp_path / "selection-resources"
    resources.mkdir()
    content = b"selection-raster"
    (resources / "figma-resource-key").write_bytes(content)
    manifest = SelectionManifest(
        display_name="Asset panel",
        resources=(SelectionResource(key="figma-resource-key", mime_type="image/png", size=len(content)),),
        top_level_nodes=(
            SelectionNode(
                id="figma-node-id",
                name="AssetPanel",
                type="FRAME",
                bounds=Bounds(x=0, y=0, width=600, height=400),
                resource_keys=("figma-resource-key",),
                children=(
                    SelectionNode(
                        id="figma-text-id",
                        name="Label",
                        type="TEXT",
                        bounds=Bounds(x=10, y=10, width=100, height=20),
                        text="Asset label",
                    ),
                ),
            ),
        ),
    )

    document = selection_conversion_document(manifest, resources, "f" * 64)
    result = convert_document(
        document.raw,
        Path("tests/fixtures/fgui"),
        "Sample",
        tmp_path / "staging",
        Path("rules/default/classification.yaml"),
        selection_assets=document.assets,
    )

    asset = next(item for item in result.files if item.relative_path.endswith(".png"))
    panel = next(item for item in result.files if "/Panel/" in item.relative_path)
    package = next(item for item in result.files if item.relative_path.endswith("package.xml"))
    assert (tmp_path / "staging" / asset.relative_path).read_bytes() == content
    xml = (tmp_path / "staging" / panel.relative_path).read_text("utf-8")
    package_tree = etree.parse(str(tmp_path / "staging" / package.relative_path))
    registered = package_tree.xpath("./resources/image[@name=$name]", name=Path(asset.relative_path).name)
    assert len(registered) == 1
    assert registered[0].attrib["path"] == "/assets/"
    assert registered[0].attrib["id"] not in {"img00001", "cmp00001"}
    assert f'src="{registered[0].attrib["id"]}"' in xml
    assert f'file="assets/{Path(asset.relative_path).name}"' in xml
    staged_index = index_project(tmp_path / "staging")
    assert staged_index.by_name[Path(asset.relative_path).name].id == registered[0].attrib["id"]
    for raw_identifier in ("figma-node-id", "figma-text-id", "figma-resource-key"):
        assert raw_identifier not in xml
        assert raw_identifier not in "\n".join(item.relative_path for item in result.files)

    repeated = convert_document(
        document.raw,
        Path("tests/fixtures/fgui"),
        "Sample",
        tmp_path / "repeat",
        Path("rules/default/classification.yaml"),
        selection_assets=document.assets,
    )
    assert result == repeated
    assert (tmp_path / "staging" / package.relative_path).read_bytes() == (
        tmp_path / "repeat" / package.relative_path
    ).read_bytes()


def test_selection_document_does_not_read_resource_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resources = tmp_path / "resources"
    resources.mkdir()
    resource = resources / "figma-resource-key"
    resource.write_bytes(b"resource")
    manifest = SelectionManifest(
        display_name="No buffering",
        resources=(SelectionResource(key="figma-resource-key", mime_type="image/png", size=8),),
        top_level_nodes=(
            SelectionNode(
                id="figma-node-id",
                name="Panel",
                type="FRAME",
                bounds=Bounds(x=0, y=0, width=600, height=400),
                resource_keys=("figma-resource-key",),
            ),
        ),
    )
    original = Path.read_bytes

    def no_resource_buffering(path: Path) -> bytes:
        if path == resource:
            pytest.fail("selection adapter must not buffer resource bytes")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", no_resource_buffering)

    raw = selection_document(manifest, resources)

    assert "figma-resource-key" not in str(raw)
    document = selection_conversion_document(manifest, resources, "f" * 64)
    assert document.assets[0].sha256 == sha256(b"resource").hexdigest()


def test_convert_document_rejects_multi_resource_selection_before_staging(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_bytes(b"x")
    second.write_bytes(b"y")
    size = MAX_SELECTION_CONVERSION_BYTES // 2 + 1
    assets = (
        SelectionAsset("asset_first", "image/png", first, size, sha256(b"x").hexdigest(), "f" * 64),
        SelectionAsset("asset_second", "image/png", second, size, sha256(b"y").hexdigest(), "f" * 64),
    )
    raw = {
        "id": "frame",
        "name": "Main",
        "type": "FRAME",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 600, "height": 400},
        "children": [],
    }

    with pytest.raises(ConversionLimitError, match="too large"):
        convert_document(
            raw,
            Path("tests/fixtures/fgui"),
            "Sample",
            tmp_path / "staging",
            Path("rules/default/classification.yaml"),
            selection_assets=assets,
        )

    assert not (tmp_path / "staging").exists()
