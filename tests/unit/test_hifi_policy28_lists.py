from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.hifi_mapping import (
    apply_mapping_decision,
    build_mapping,
    require_psd_coverage,
)
from figma_to_fgui.hifi_nested import inspect_component_tree
from figma_to_fgui.hifi_replacement_models import HifiMappingDecision
from figma_to_fgui.models import Bounds


def _project(tmp_path):
    from figma_to_fgui.hifi_replacement_models import HifiTargetRef

    root = tmp_path / "proj"
    (root / "assets" / "Pkg" / "Panel").mkdir(parents=True)
    (root / "assets" / "Pkg" / "Component").mkdir(parents=True)
    (root / "assets" / "Pkg" / "package.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?><package id="pkgaa1" name="Pkg">'
        "<resources>"
        '<component id="panel1" name="Panel_One.xml" path="/Panel/"/>'
        '<component id="item1" name="Item_Row.xml" path="/Component/"/>'
        "</resources></package>",
        encoding="utf-8",
    )
    (root / "assets" / "Pkg" / "Panel" / "Panel_One.xml").write_text(
        '<component size="400,520"><displayList>'
        '<list id="lst" name="records" xy="20,30" size="360,240" lineGap="12" '
        'defaultItem="ui://pkgaa1item1"/>'
        "</displayList></component>",
        encoding="utf-8",
    )
    (root / "assets" / "Pkg" / "Component" / "Item_Row.xml").write_text(
        '<component size="360,215"><displayList>'
        '<graph id="bg" name="card" xy="0,0" size="360,110" type="rect" fillColor="#fff0e0d0"/>'
        '<loader id="head" name="head" xy="33,39" size="176,176"/>'
        "</displayList></component>",
        encoding="utf-8",
    )
    target = HifiTargetRef(
        project_id="p",
        project_fingerprint="f" * 64,
        package_id="pkgaa1",
        package_name="Pkg",
        directory="Panel",
        component_id="panel1",
        component_name="Panel_One",
        component_relative_path="assets/Pkg/Panel/Panel_One.xml",
    )
    return root, target


def _manifest():
    def leaf(node_id, name, bounds, kind):
        return SelectionNode(
            id=node_id, name=name, type="RECTANGLE" if kind == "shape" else "IMAGE",
            bounds=Bounds(x=bounds[0], y=bounds[1], width=bounds[2], height=bounds[3]),
            properties={"psdKind": kind, "blendMode": "normal"},
        )

    row0 = SelectionNode(
        id="row0", name="Row 1", type="GROUP",
        bounds=Bounds(x=20, y=30, width=360, height=215),
        children=(
            SelectionNode(
                id="row0-card", name="card", type="RECTANGLE",
                bounds=Bounds(x=20, y=30, width=360, height=110),
                properties={
                    "psdKind": "shape",
                    "blendMode": "normal",
                    "fguiGraph": {"shape": "rect", "fillColor": "#fff0e0d0", "lineSize": 0},
                },
            ),
            leaf("row0-avatar", "avatar", (53, 69, 176, 176), "pixel"),
        ),
    )
    row1 = SelectionNode(
        id="row1", name="Row 2", type="GROUP",
        bounds=Bounds(x=20, y=257, width=360, height=215),
        children=(
            leaf("row1-card", "card", (20, 257, 360, 110), "shape"),
            leaf("row1-avatar", "avatar", (53, 296, 176, 176), "pixel"),
        ),
    )
    return SelectionManifest(
        version=1,
        display_name="PSD",
        top_level_nodes=(
            SelectionNode(
                id="psd-root:t", name="PSD", type="FRAME",
                bounds=Bounds(x=0, y=0, width=400, height=520),
                children=(row0, row1),
            ),
        ),
    )


def test_row_repeats_and_runtime_mocks_are_excluded_from_matching(tmp_path):
    root, target = _project(tmp_path)
    inventory = inspect_component_tree(root, target)
    manifest = _manifest()

    draft = build_mapping(inventory, manifest)

    repeats = set(draft.row_repeat_node_ids)
    assert repeats == {"row1", "row1-card", "row1-avatar", "row0-avatar"}
    node_ids = {item.figma_node_id for item in draft.items if item.figma_node_id}
    assert not node_ids & {"row1", "row1-card", "row1-avatar", "row0-avatar"}
    card = next(item for item in draft.items if item.old_object_id == "lst:bg")
    assert card.figma_node_id == "row0-card"
    head = next(item for item in draft.items if item.old_object_id == "lst:head")
    assert head.status == "fgui_only"
    assert head.action == "keep_old"
    assert head.legacy_state == "PRESERVE_RUNTIME"

    decided = apply_mapping_decision(
        draft,
        HifiMappingDecision(
            version=1,
            mapping_revision=draft.mapping_revision,
            item_id=card.item_id,
            action="accept",
        ),
        manifest,
    )
    require_psd_coverage(decided, manifest)
    kept = next(i for i in decided.items if i.old_object_id == "lst:bg")
    assert kept.legacy_state == "RESTYLE"
