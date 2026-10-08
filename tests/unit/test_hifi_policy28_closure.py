"""Policy 28 §14/§16: bidirectional visual closure and the BLOCK gate."""
import pytest

from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.hifi_mapping import (
    HifiMappingError,
    apply_mapping_decision,
    build_mapping,
    keep_old_would_conflict,
    require_visual_closure,
    visual_closure,
)
from figma_to_fgui.hifi_nested import inspect_component_tree
from figma_to_fgui.hifi_replacement_models import (
    HifiMappingDecision,
    HifiMappingDraft,
    HifiMappingEvidence,
    HifiMappingItem,
)
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


def _decided(tmp_path):
    root, target = _project(tmp_path)
    inventory = inspect_component_tree(root, target)
    manifest = _manifest()
    draft = build_mapping(inventory, manifest)
    card = next(item for item in draft.items if item.old_object_id == "lst:bg")
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
    return decided, manifest


def _flip(draft, old_object_id, **update):
    return draft.model_copy(update={
        "items": tuple(
            item.model_copy(update=update)
            if item.old_object_id == old_object_id else item
            for item in draft.items
        )
    })


def test_closed_pair_reports_full_bidirectional_closure(tmp_path):
    decided, manifest = _decided(tmp_path)

    report = visual_closure(decided, manifest)

    assert report.complete
    assert report.psd_required == 1
    assert report.psd_explained == 1
    assert report.psd_unexplained_ids == ()
    assert report.psd_closure == 1.0
    assert report.legacy_required >= 3
    assert report.legacy_settled == report.legacy_required
    assert report.legacy_unexplained == ()
    assert report.legacy_closure == 1.0
    assert require_visual_closure(decided, manifest).complete


def test_fresh_fixture_auto_matches_and_closes(tmp_path):
    root, target = _project(tmp_path)
    inventory = inspect_component_tree(root, target)
    manifest = _manifest()
    draft = build_mapping(inventory, manifest)

    report = visual_closure(draft, manifest)

    assert report.complete
    assert report.psd_unexplained_ids == ()
    assert report.legacy_unexplained == ()


def test_undecided_pair_reports_both_gaps_and_blocks(tmp_path):
    root, target = _project(tmp_path)
    inventory = inspect_component_tree(root, target)
    manifest = _manifest()
    draft = build_mapping(inventory, manifest)
    undecided = _flip(draft, "lst:bg", action=None, legacy_state=None)

    report = visual_closure(undecided, manifest)

    assert not report.complete
    assert report.psd_unexplained_ids == ("row0-card",)
    assert "old:lst:bg:undecided" in report.legacy_unexplained
    with pytest.raises(HifiMappingError) as error:
        require_visual_closure(undecided, manifest)
    assert error.value.code == "hifi_mapping_coverage_incomplete"


def test_unexplained_keep_old_blocks_the_candidate(tmp_path):
    decided, manifest = _decided(tmp_path)
    conflicted = _flip(decided, "lst:head", legacy_state="USER_DECISION_CONFLICT")

    report = visual_closure(conflicted, manifest)

    assert report.psd_closure == 1.0
    assert report.legacy_unexplained == ("old:lst:head:USER_DECISION_CONFLICT",)
    assert not report.complete
    with pytest.raises(HifiMappingError) as error:
        require_visual_closure(conflicted, manifest)
    assert error.value.code == "hifi_legacy_closure_incomplete"


def test_pending_removal_candidate_stays_unexplained(tmp_path):
    decided, manifest = _decided(tmp_path)
    pending = _flip(decided, "lst:head", action=None, legacy_state="REMOVE_CANDIDATE")

    report = visual_closure(pending, manifest)

    assert report.legacy_unexplained == ("old:lst:head:REMOVE_CANDIDATE",)
    with pytest.raises(HifiMappingError) as error:
        require_visual_closure(pending, manifest)
    assert error.value.code == "hifi_legacy_closure_incomplete"


def test_keep_old_would_conflict_flags_only_visible_static_visuals():
    evidence = HifiMappingEvidence(
        version=1, name_score=0, position_score=0, size_score=0,
        type_score=0, parent_score=0, order_score=0,
    )

    def item(**overrides):
        base = dict(
            version=1, item_id="old:n1", old_object_id="n1",
            old_object_type="image", status="fgui_only",
            action=None, score=0, evidence=evidence,
        )
        base.update(overrides)
        return HifiMappingItem(**base)

    assert keep_old_would_conflict(item())
    assert not keep_old_would_conflict(item(old_object_type="loader"))
    assert not keep_old_would_conflict(item(visual_disposition="retire"))
    assert not keep_old_would_conflict(item(old_object_type="text", default_visible=False))
    assert not keep_old_would_conflict(item(preserve_runtime_text=True))


def test_retire_disposition_settles_the_legacy_visual(tmp_path):
    decided, manifest = _decided(tmp_path)
    retired = _flip(decided, "lst:head", legacy_state="RETIRE")

    report = visual_closure(retired, manifest)

    assert report.legacy_unexplained == ()
    assert report.complete
    assert require_visual_closure(retired, manifest).complete


def test_non_psd_flow_has_no_psd_side_and_keeps_legacy_leniency():
    manifest = SelectionManifest(
        version=1,
        display_name="Figma",
        top_level_nodes=(
            SelectionNode(
                id="0:1", name="Frame", type="FRAME",
                bounds=Bounds(x=0, y=0, width=100, height=100),
            ),
        ),
    )
    evidence = HifiMappingEvidence(
        version=1, name_score=0, position_score=0, size_score=0,
        type_score=0, parent_score=0, order_score=0,
    )
    draft = HifiMappingDraft(
        version=1,
        policy_revision=28,
        mapping_revision=1,
        items=(
            HifiMappingItem(
                version=1, item_id="old:n7", old_object_id="n7",
                old_object_type="image", status="fgui_only",
                action="keep_old", score=0, evidence=evidence,
            ),
        ),
        unresolved_count=0,
    )

    report = visual_closure(draft, manifest)

    assert report.psd_required == 0
    assert report.psd_closure == 1.0
    assert report.legacy_unexplained == ()
    assert report.complete

    conflicted = draft.model_copy(update={
        "items": (draft.items[0].model_copy(
            update={"legacy_state": "USER_DECISION_CONFLICT"}
        ),),
    })
    assert not visual_closure(conflicted, manifest).complete
