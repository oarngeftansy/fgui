from __future__ import annotations

from pathlib import Path

from figma_to_fgui.hifi_mapping import build_mapping
from figma_to_fgui.hifi_project_inspector import (
    inspect_component,
    inspect_hifi_targets,
    target_from_option,
)
from figma_to_fgui.psd_hifi_adapter import psd_source_manifest
from figma_to_fgui.psd_intake import PsdInspection, PsdLayer
from figma_to_fgui.psd_source_store import PsdRasterResource, PsdSource
from figma_to_fgui.uploaded_project import index_uploaded_project

FIXTURE = Path(__file__).parents[1] / "fixtures/hifi_replacement"


def _layer(
    index: int,
    name: str,
    kind: str,
    bounds: tuple[int, int, int, int],
    *,
    parent_id: str | None = None,
    text: str | None = None,
) -> PsdLayer:
    source_hash = "a" * 64
    return PsdLayer(
        id=f"psd-layer:{source_hash}:{index + 1}",
        native_id=index + 1,
        parent_id=parent_id,
        document_index=index,
        sibling_index=index,
        name=name,
        path=(name,),
        kind=kind,
        bounds=bounds,
        visible=True,
        effective_visible=True,
        opacity=255,
        blend_mode="normal",
        clipping=False,
        text=text,
        has_pixel_mask=False,
        has_vector_mask=False,
        has_effects=False,
    )


def test_psd_hifi_ir_reuses_existing_mapping_with_hierarchy_and_text() -> None:
    layers = (
        _layer(0, "TitleBar", "type", (48, 30, 404, 76), text="Village Notes"),
        _layer(1, "CharacterSilhouette", "shape", (54, 101, 264, 347)),
        _layer(2, "Btn_Next", "group", (568, 337, 688, 381)),
    )
    source = PsdSource(
        version=1,
        source_id="a" * 64,
        inspection=PsdInspection(
            source_name="screen.psd",
            byte_size=123,
            sha256="a" * 64,
            width=750,
            height=420,
            depth=8,
            color_mode="RGB",
            layer_count=len(layers),
            kind_counts={"group": 1, "shape": 1, "type": 1},
            text_layer_count=1,
            smart_object_count=0,
            adjustment_layer_count=0,
            effect_layer_count=0,
            blocking_issues=(),
            warnings=(),
        ),
        layers=layers,
    )
    manifest = psd_source_manifest(source)

    root = FIXTURE / "old_project"
    project = index_uploaded_project(root, "old.zip")
    tree = inspect_hifi_targets(root, project)
    package = tree.packages[0]
    directory = next(item for item in package.directories if item.path == "Panel")
    component = next(item for item in directory.components if item.resource_id == "sketch01")
    inventory = inspect_component(root, target_from_option(project, package, directory, component))
    mapping = build_mapping(inventory, manifest)

    assert manifest.top_level_nodes[0].type == "FRAME"
    assert manifest.top_level_nodes[0].children[0].text == "Village Notes"
    title = next(item for item in mapping.items if item.old_name == "TitleBar")
    assert title.figma_node_id == layers[0].id
    assert title.status == "matched"
    assert mapping.model_dump_json() == build_mapping(inventory, manifest).model_dump_json()


def test_psd_hifi_ir_attaches_generated_raster_to_visual_layer() -> None:
    layer = _layer(0, "Card", "shape", (10, 20, 110, 80))
    source = PsdSource(
        version=1,
        source_id="a" * 64,
        inspection=PsdInspection(
            source_name="screen.psd",
            byte_size=123,
            sha256="a" * 64,
            width=750,
            height=420,
            depth=8,
            color_mode="RGB",
            layer_count=1,
            kind_counts={"shape": 1},
            text_layer_count=0,
            smart_object_count=0,
            adjustment_layer_count=0,
            effect_layer_count=0,
            blocking_issues=("shape_styles_require_equivalence_check",),
            warnings=(),
        ),
        layers=(layer,),
    )
    raster = PsdRasterResource(
        layer_id=layer.id,
        key="psd-card",
        mime_type="image/png",
        size=456,
    )

    manifest = psd_source_manifest(source, raster_resources={layer.id: raster})

    assert manifest.resources[0].key == "psd-card"
    assert manifest.resources[0].size == 456
    assert manifest.top_level_nodes[0].children[0].resource_keys == ("psd-card",)
