"""Policy 28 §12 Semantic Novelty Check + §7 geometry runtime checks."""
import shutil
from pathlib import Path

import pytest
from lxml import etree

from figma_to_fgui.apply import apply_bundle
from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.hifi_mapping import (
    HifiMappingError,
    apply_mapping_decision,
    build_mapping,
    require_visual_closure,
    visual_closure,
)
from figma_to_fgui.hifi_nested import inspect_component_tree
from figma_to_fgui.hifi_patch import (
    HifiPatchError,
    _new_object_id,
    build_hifi_change_bundle,
    validate_hifi_candidate,
)
from figma_to_fgui.hifi_replacement_models import HifiMappingDecision, HifiTargetRef
from figma_to_fgui.models import Bounds

SESSION_ID = "b" * 32

# bg carries a gearSize whose page still references the pre-reskin size; keep
# owns a relation to bg. The PSD moves/resizes bg so both §7 checks must fire.
PANEL = (
    '<component size="400,520">'
    '<controller name="page" pages="0,default,1,active"/>'
    "<displayList>"
    '<graph id="bg" name="card" xy="0,0" size="360,110" type="rect" fillColor="#fff0e0d0">'
    '<gearSize controller="page" pages="0" values="360,110,1,1"/>'
    "</graph>"
    '<graph id="deco" name="old_deco" xy="10,300" size="40,40" type="rect" fillColor="#ff000000"/>'
    '<graph id="keep" name="keeper" xy="200,200" size="30,30" type="rect" fillColor="#ff00ff00">'
    '<relation target="bg" sidePair="left-left"/>'
    "</graph>"
    "</displayList></component>"
)


def _target():
    return HifiTargetRef(
        project_id="p",
        project_fingerprint="f" * 64,
        package_id="pkgaa1",
        package_name="Pkg",
        directory="Panel",
        component_id="panel1",
        component_name="Panel_One",
        component_relative_path="assets/Pkg/Panel/Panel_One.xml",
    )


def _write_package(root: Path) -> None:
    (root / "assets" / "Pkg" / "Panel").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "Pkg" / "package.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?><package id="pkgaa1" name="Pkg">'
        "<resources>"
        '<component id="panel1" name="Panel_One.xml" path="/Panel/"/>'
        "</resources></package>",
        encoding="utf-8",
    )
    (root / "assets" / "Pkg" / "Panel" / "Panel_One.xml").write_text(
        PANEL, encoding="utf-8"
    )


def _shape(node_id, name, bounds, fill="#ff00aa00"):
    return SelectionNode(
        id=node_id, name=name, type="RECTANGLE",
        bounds=Bounds(x=bounds[0], y=bounds[1], width=bounds[2], height=bounds[3]),
        properties={
            "psdKind": "shape",
            "blendMode": "normal",
            "fguiGraph": {"shape": "rect", "fillColor": fill, "lineSize": 0},
        },
    )


def _manifest(with_overlap: bool) -> SelectionManifest:
    children = [
        # bg is replaced and moved/resized by the PSD (0,10 -> 360x120).
        _shape("psd-card", "card", (0, 10, 360, 120), "#fff0e0d0"),
        # A badge painting where nothing ever rendered: novelty-proven add.
        _shape("psd-badge", "badge", (300, 400, 60, 60)),
    ]
    if with_overlap:
        # A leaf overlapping old paint: not novelty, stays undecided.
        children.append(_shape("psd-overlap", "overlap", (15, 305, 30, 30)))
    return SelectionManifest(
        version=1,
        display_name="PSD",
        top_level_nodes=(
            SelectionNode(
                id="psd-root:t", name="PSD", type="FRAME",
                bounds=Bounds(x=0, y=0, width=400, height=520),
                children=tuple(children),
            ),
        ),
    )


def _draft(tmp_path, with_overlap: bool):
    root = tmp_path / "proj"
    _write_package(root)
    target = _target()
    inventory = inspect_component_tree(root, target)
    manifest = _manifest(with_overlap)
    return root, target, inventory, manifest, build_mapping(inventory, manifest)


def _decide(draft, manifest, item_id, action, disposition=None):
    return apply_mapping_decision(
        draft,
        HifiMappingDecision(
            version=1,
            mapping_revision=draft.mapping_revision,
            item_id=item_id,
            action=action,
            visual_disposition=disposition,
        ),
        manifest,
    )


def _settled(tmp_path, with_overlap: bool = False):
    root, target, inventory, manifest, draft = _draft(tmp_path, with_overlap)
    mapping = draft
    for object_id in ("deco", "keep"):
        mapping = _decide(mapping, manifest, f"old:{object_id}", "keep_old", "retire")
    return root, target, inventory, manifest, mapping


def test_novelty_classifies_empty_region_adds_and_keeps_overlaps_undecided(tmp_path):
    _, _, _, _, draft = _draft(tmp_path, with_overlap=True)

    badge = next(i for i in draft.items if i.figma_node_id == "psd-badge")
    assert badge.status == "hifi_added"
    assert badge.action == "add_visual"
    assert badge.novelty_proven

    overlap = next(i for i in draft.items if i.figma_node_id == "psd-overlap")
    assert overlap.action is None
    assert not overlap.novelty_proven


def test_closure_counts_proven_adds_and_blocks_on_unproven_pixels(tmp_path):
    _, _, _, manifest, draft = _draft(tmp_path, with_overlap=True)
    mapping = draft
    for object_id in ("deco", "keep"):
        mapping = _decide(mapping, manifest, f"old:{object_id}", "keep_old", "retire")

    report = visual_closure(mapping, manifest)
    assert report.psd_unexplained_ids == ("psd-overlap",)
    with pytest.raises(HifiMappingError) as error:
        require_visual_closure(mapping, manifest)
    assert error.value.code == "hifi_mapping_coverage_incomplete"


def test_unproven_add_is_blocked_at_build(tmp_path):
    root, _, inventory, manifest, mapping = _settled(tmp_path)
    unproven = mapping.model_copy(update={"items": tuple(
        item.model_copy(update={"novelty_proven": False})
        if item.figma_node_id == "psd-badge" else item
        for item in mapping.items
    )})

    with pytest.raises(HifiPatchError) as error:
        build_hifi_change_bundle(
            root, inventory, manifest, unproven, job_id="j" * 32
        )
    assert error.value.code == "hifi_novelty_evidence_missing"


def test_proven_add_builds_new_visual_and_flags_geometry_risks(tmp_path):
    root, target, inventory, manifest, mapping = _settled(tmp_path)
    assert mapping.unresolved_count == 0
    require_visual_closure(mapping, manifest)

    bundle = build_hifi_change_bundle(
        root, inventory, manifest, mapping, job_id="j" * 32
    )
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    apply_bundle(candidate, bundle)

    after = etree.parse(str(candidate / target.component_relative_path))
    added_id = _new_object_id("psd-badge")
    added = after.xpath(f'./displayList/*[@id="{added_id}"]')
    assert len(added) == 1
    assert added[0].tag == "graph"
    assert added[0].get("touchable") == "false"
    assert added[0].get("xy") == "300,400"
    assert added[0].get("size") == "60,60"
    remaining = {e.get("id") for e in after.xpath("./displayList/*[@id]")}
    assert remaining == {"bg", "deco", "keep", added_id}

    review = validate_hifi_candidate(
        root, candidate, inventory, mapping, session_id=SESSION_ID
    )
    assert review.protected_checks_passed
    joined = "\n".join(review.warnings)
    assert "gear 几何仍引用换皮前基准" in joined
    assert "360,110" in joined
    assert "关系锚点与目标位移不一致" in joined
    assert "old:bg" in joined or "bg" in joined
