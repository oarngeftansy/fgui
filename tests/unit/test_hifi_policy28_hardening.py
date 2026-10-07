from __future__ import annotations

"""Policy 28 Hardening: Golden Regression Corpus.

Every case proves one conservation property end to end: no PSD source leaf
silently disappears, no ownership record vanishes without an explicit
release, no legacy object stays in an unexplained state, no dangling
reference survives a confirmed removal, and no pending user decision can be
bypassed on the way to Build.
"""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from psd_tools import PSDImage

from figma_to_fgui.api import create_app
from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.hifi_conservation import (
    OWNERSHIP_CONSERVATION_CODE,
    HifiConservationError,
    record_stage,
    require_ownership_conservation,
)
from figma_to_fgui.hifi_mapping import (
    _psd_coverage,
    build_mapping,
    normalize_legacy_states,
    visual_closure,
)
from figma_to_fgui.hifi_removal_review import build_removal_review
from figma_to_fgui.hifi_replacement_models import (
    FguiBehaviorSummary,
    FguiComponentInventory,
    FguiObjectRef,
    HifiMappingDraft,
    HifiMappingEvidence,
    HifiMappingItem,
    HifiTargetRef,
)
from figma_to_fgui.hifi_semantic_reskin import normalize_psd_semantic_reskin
from figma_to_fgui.models import Bounds
from tests.unit.test_hifi_policy28_removal import (
    PANEL,
    _target as _panel_target,
    _write_package,
)

FIXTURE = Path(__file__).parents[1] / "fixtures/hifi_replacement"
HEADERS = {"x-figma-plugin-token": "test-token"}
_SHA = "0" * 64


# ---------------------------------------------------------------------------
# Shared builders
# ---------------------------------------------------------------------------


def _evidence() -> HifiMappingEvidence:
    return HifiMappingEvidence(
        version=1,
        name_score=0.0,
        position_score=0.0,
        size_score=0.0,
        type_score=0.0,
        parent_score=0.0,
        order_score=0.0,
    )


def _item(
    item_id: str,
    *,
    old_object_id: str | None = None,
    old_object_type: str | None = "loader",
    node_id: str | None = None,
    status: str = "fgui_only",
    action: str | None = None,
    legacy_state: str | None = None,
    owned: tuple[str, ...] = (),
    owned_group_id: str | None = None,
    visual_disposition: str = "preserve",
    default_visible: bool | None = True,
    score: float = 0.5,
) -> HifiMappingItem:
    return HifiMappingItem(
        version=1,
        item_id=item_id,
        old_object_id=old_object_id,
        old_object_type=old_object_type,
        figma_node_id=node_id,
        status=status,
        score=score,
        evidence=_evidence(),
        action=action,
        legacy_state=legacy_state,
        owned_source_ids=owned,
        owned_group_id=owned_group_id,
        visual_disposition=visual_disposition,
        default_visible=default_visible,
    )


def _draft(*items: HifiMappingItem) -> HifiMappingDraft:
    return HifiMappingDraft(
        version=1,
        mapping_revision=1,
        items=items,
        unresolved_count=sum(1 for item in items if item.action is None),
    )


def _inv_target() -> HifiTargetRef:
    return HifiTargetRef(
        project_id="project",
        project_fingerprint=_SHA,
        package_id="pkg",
        package_name="Package",
        directory="/",
        component_id="root",
        component_name="Root",
        component_relative_path="assets/Package/Root.xml",
    )


def _old(
    object_id: str,
    object_type: str,
    *,
    parent_id: str | None = None,
    child_index: int = 0,
    behavior_roles: tuple[str, ...] = (),
) -> FguiObjectRef:
    return FguiObjectRef(
        object_id=object_id,
        name=object_id,
        object_type=object_type,
        parent_id=parent_id,
        child_index=child_index,
        x=100.0,
        y=100.0,
        width=300.0,
        height=80.0,
        protected_sha256=_SHA,
        behavior_roles=behavior_roles,
    )


def _inventory(*objects: FguiObjectRef) -> FguiComponentInventory:
    return FguiComponentInventory(
        version=1,
        target=_inv_target(),
        width=1080.0,
        height=1920.0,
        objects=objects,
        behavior=FguiBehaviorSummary(
            version=1,
            protected_sha256=_SHA,
            gear_count=0,
            relation_count=0,
            action_count=0,
        ),
        parse_complete=True,
        expanded_instances=True,
    )


def _leaf(
    leaf_id: str,
    *,
    x: float = 100.0,
    y: float = 100.0,
    width: float = 30.0,
    height: float = 12.0,
) -> SelectionNode:
    return SelectionNode(
        id=leaf_id,
        name=leaf_id,
        type="IMAGE",
        bounds=Bounds(x=x, y=y, width=width, height=height),
        properties={"psdKind": "shape"},
    )


def _bundle_manifest(
    leaf_count: int, *, group_id: str = "deco-bundle"
) -> SelectionManifest:
    leaves = tuple(
        _leaf(f"deco-{index}", x=100.0 + index, y=100.0 + index * 13.0)
        for index in range(leaf_count)
    )
    group = SelectionNode(
        id=group_id,
        name="Deco",
        type="GROUP",
        bounds=Bounds(x=0.0, y=0.0, width=1080.0, height=1920.0),
        children=leaves,
    )
    root = SelectionNode(
        id="psd-root:" + "a" * 64,
        name="PSD",
        type="FRAME",
        bounds=Bounds(x=0.0, y=0.0, width=1080.0, height=1920.0),
        children=(group,),
    )
    return SelectionManifest(version=1, display_name="PSD", top_level_nodes=(root,))


def _bundle_ids(leaf_count: int) -> tuple[str, ...]:
    return tuple(f"deco-{index}" for index in range(leaf_count))


def _owned_union(draft: HifiMappingDraft) -> set[str]:
    return {
        source_id
        for item in draft.items
        if item.action in {"accept", "retarget"}
        for source_id in item.owned_source_ids
    }


# ---------------------------------------------------------------------------
# Conservation unit cases
# ---------------------------------------------------------------------------


def test_conservation_blocks_silent_ownership_drop() -> None:
    manifest = _bundle_manifest(2)
    group_id = "deco-bundle"
    before = _draft(
        _item(
            "old:host",
            old_object_id="host",
            node_id="deco-0",
            status="matched",
            action="accept",
            owned=("deco-0", "deco-1"),
            owned_group_id=group_id,
        )
    )
    after = _draft(
        _item(
            "old:host",
            old_object_id="host",
            node_id="deco-0",
            status="matched",
            action="accept",
            owned=("deco-0",),
            owned_group_id=group_id,
        )
    )
    with pytest.raises(HifiConservationError) as error:
        require_ownership_conservation(
            {"deco-0", "deco-1"},
            after,
            manifest,
            transformation="test_drop",
        )
    assert error.value.code == OWNERSHIP_CONSERVATION_CODE
    assert "deco-1" in str(error.value)


def test_conservation_accepts_explicit_release() -> None:
    manifest = _bundle_manifest(2)
    after = _draft(
        _item(
            "old:host",
            old_object_id="host",
            node_id="deco-0",
            status="matched",
            action="accept",
            owned=("deco-0",),
            owned_group_id="deco-bundle",
        )
    )
    lost = require_ownership_conservation(
        {"deco-0", "deco-1"},
        after,
        manifest,
        transformation="test_release",
        released=frozenset({"deco-1"}),
    )
    assert lost == ()


def test_conservation_accepts_carrier_swap() -> None:
    manifest = _bundle_manifest(1)
    after = _draft(
        _item(
            "old:host2",
            old_object_id="host2",
            node_id="deco-0",
            status="matched",
            action="accept",
            owned=("deco-0",),
            owned_group_id="deco-bundle",
        )
    )
    lost = require_ownership_conservation(
        {"deco-0"}, after, manifest, transformation="test_swap"
    )
    assert lost == ()


def test_record_stage_appends_ledger_entry_with_counts() -> None:
    manifest = _bundle_manifest(2)
    draft = _draft(
        _item(
            "old:host",
            old_object_id="host",
            node_id="deco-0",
            status="matched",
            action="accept",
            owned=("deco-0", "deco-1"),
            owned_group_id="deco-bundle",
        ),
        _item(
            "old:waiting",
            old_object_id="waiting",
            old_object_type="image",
            status="fgui_only",
            legacy_state="REMOVE_CANDIDATE",
        ),
    )
    recorded = record_stage(draft, manifest, transformation="stage_x")
    assert len(recorded.stage_ledger) == 1
    entry = recorded.stage_ledger[0]
    assert entry.transformation == "stage_x"
    assert entry.source_count == 2
    assert entry.owned_source_count == 2
    assert entry.owned_carrier_count == 1
    assert entry.remove_candidate_count == 1
    assert entry.pending_decision_count == 1
    assert entry.lost_source_ids == ()


def test_record_stage_blocks_chain_loss() -> None:
    manifest = _bundle_manifest(2)
    before = _draft(
        _item(
            "old:host",
            old_object_id="host",
            node_id="deco-0",
            status="matched",
            action="accept",
            owned=("deco-0", "deco-1"),
            owned_group_id="deco-bundle",
        )
    )
    after = _draft(
        _item(
            "old:host",
            old_object_id="host",
            node_id="deco-0",
            status="matched",
            action="accept",
            owned=("deco-0",),
            owned_group_id="deco-bundle",
        )
    )
    with pytest.raises(HifiConservationError) as error:
        record_stage(after, manifest, transformation="chain", before=before)
    assert error.value.code == OWNERSHIP_CONSERVATION_CODE


def test_stale_legacy_tag_is_repaired_to_action_fate() -> None:
    stale = _item(
        "old:promoted",
        old_object_id="promoted",
        old_object_type="loader",
        node_id="deco-0",
        status="matched",
        action="accept",
        legacy_state="REMOVE_CANDIDATE",
        owned=("deco-0",),
    )
    repaired = normalize_legacy_states([stale])
    assert repaired[0].legacy_state == "REPLACE"


def test_pending_classification_is_preserved_by_repair() -> None:
    pending = _item(
        "old:waiting",
        old_object_id="waiting",
        old_object_type="image",
        status="fgui_only",
        legacy_state="REMOVE_CANDIDATE",
    )
    repaired = normalize_legacy_states([pending])
    assert repaired[0].legacy_state == "REMOVE_CANDIDATE"
    assert repaired[0].action is None


# ---------------------------------------------------------------------------
# Variant-clone shared-template semantics
# ---------------------------------------------------------------------------


def _shared_project(tmp_path: Path, files: dict[str, str], name: str) -> Path:
    root = tmp_path / name
    panel = root / "assets" / "Pkg" / "Panel"
    panel.mkdir(parents=True)
    (root / "assets" / "Pkg" / "package.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?><package id="pkgaa1" name="Pkg">'
        "<resources></resources></package>",
        encoding="utf-8",
    )
    for name, body in files.items():
        (panel / name).write_text(body, encoding="utf-8")
    return root


_LIST_TPL = (
    '<component size="400,520"><displayList>'
    '<list id="rows" xy="0,120" size="360,240" defaultItem="ui://pkgaa1rowtpl"/>'
    "</displayList></component>"
)


def test_variant_clone_references_do_not_flip_shared_templates(tmp_path) -> None:
    """Regression for hifi_nested_geometry_unverified: clone_instance_
    definition copies carry the original defaultItem reference; counting
    them as sharing blocked the row-template objects the clone was created
    to isolate."""
    from figma_to_fgui.hifi_nested import _shared_list_templates

    root = _shared_project(
        tmp_path,
        {
            "Panel_A.xml": _LIST_TPL,
            "Panel_A__hifi_0123456789abcdef.xml": _LIST_TPL,
        },
        "proj-clone-only",
    )
    assert _shared_list_templates(root) == set()

    genuinely_shared = _shared_project(
        tmp_path,
        {
            "Panel_A.xml": _LIST_TPL,
            "Panel_B.xml": _LIST_TPL,
        },
        "proj-real-shared",
    )
    assert _shared_list_templates(genuinely_shared) == {"ui://pkgaa1rowtpl"}

    mixed = _shared_project(
        tmp_path,
        {
            "Panel_A.xml": _LIST_TPL,
            "Panel_A__hifi_0123456789abcdef.xml": _LIST_TPL,
            "Panel_B.xml": _LIST_TPL,
        },
        "proj-mixed",
    )
    # A real second user still makes the template shared; the clone adds
    # nothing to the user-facing count.
    assert _shared_list_templates(mixed) == {"ui://pkgaa1rowtpl"}


# ---------------------------------------------------------------------------
# Bundle conservation regressions (old:n16:n0_kdwn family)
# ---------------------------------------------------------------------------


def _bundle_inventory() -> FguiComponentInventory:
    return _inventory(
        _old("card", "component"),
        _old("skin", "loader", parent_id="card", child_index=1),
    )


def test_golden_heavy_decoration_bundle_survives_semantic_normalize() -> None:
    """The raw allocator bakes a 22-leaf owned bundle (old:n16:n0_kdwn).
    A proven component-group pair keeps every leaf owned through the
    semantic normalization pass, and the ledger proves zero loss."""
    inventory = _bundle_inventory()
    manifest = _bundle_manifest(22)
    leaves = _bundle_ids(22)
    draft = _draft(
        _item(
            "old:card",
            old_object_id="card",
            old_object_type="component",
            node_id="deco-bundle",
            status="matched",
            action="accept",
            score=1.0,
        ),
        _item(
            "old:skin",
            old_object_id="skin",
            old_object_type="loader",
            node_id=leaves[0],
            status="matched",
            action="accept",
            owned=leaves,
            owned_group_id="deco-bundle",
            score=1.0,
        ),
    )
    mapping = normalize_psd_semantic_reskin(
        inventory,
        manifest,
        draft,
        proven_pairs=frozenset({("card", "deco-bundle")}),
    )
    owned = _owned_union(mapping)
    assert len(owned) == 22
    _, gaps = _psd_coverage(mapping, manifest)
    assert gaps == set()
    assert mapping.stage_ledger
    assert all(entry.lost_source_ids == () for entry in mapping.stage_ledger)


def test_golden_bundle_is_restored_when_semantic_engine_finds_no_pair() -> None:
    """Regression for the early-exit hole: with no component-group pair the
    semantic engine never took authority, so the renderer-proven raw bundle
    is restored whole instead of being dropped on an early return."""
    inventory = _bundle_inventory()
    manifest = _bundle_manifest(22)
    leaves = _bundle_ids(22)
    draft = _draft(
        _item(
            "old:skin",
            old_object_id="skin",
            old_object_type="loader",
            node_id=leaves[0],
            status="matched",
            action="accept",
            owned=leaves,
            owned_group_id="deco-bundle",
            score=1.0,
        )
    )
    mapping = normalize_psd_semantic_reskin(inventory, manifest, draft)
    owned = _owned_union(mapping)
    assert len(owned) == 22
    skin = next(i for i in mapping.items if i.old_object_id == "skin")
    assert skin.action == "accept"
    assert len(skin.owned_source_ids) == 22


def test_golden_two_normalize_passes_conserve_ownership() -> None:
    """B/D regression: both normalize passes prove
    before ownership = after ownership + explicit release."""
    inventory = _bundle_inventory()
    manifest = _bundle_manifest(22)
    leaves = _bundle_ids(22)
    draft = _draft(
        _item(
            "old:card",
            old_object_id="card",
            old_object_type="component",
            node_id="deco-bundle",
            status="matched",
            action="accept",
            score=1.0,
        ),
        _item(
            "old:skin",
            old_object_id="skin",
            old_object_type="loader",
            node_id=leaves[0],
            status="matched",
            action="accept",
            owned=leaves,
            owned_group_id="deco-bundle",
            score=1.0,
        ),
    )
    first = normalize_psd_semantic_reskin(
        inventory, manifest, draft,
        proven_pairs=frozenset({("card", "deco-bundle")}),
    )
    second = normalize_psd_semantic_reskin(
        inventory, manifest, first,
        proven_pairs=frozenset({("card", "deco-bundle")}),
    )
    assert len(_owned_union(second)) == 22
    assert len(second.stage_ledger) >= 2
    assert all(entry.lost_source_ids == () for entry in second.stage_ledger)


# ---------------------------------------------------------------------------
# Mapping-level golden corpus (real project XML + real build pipeline)
# ---------------------------------------------------------------------------


def _panel(tmp_path, panel_xml: str = PANEL):
    from figma_to_fgui.hifi_nested import inspect_component_tree

    root = tmp_path / "proj-golden"
    _write_package(root, panel_xml)
    target = _panel_target()
    inventory = inspect_component_tree(root, target)
    return root, target, inventory


def _card_manifest() -> SelectionManifest:
    card = SelectionNode(
        id="psd-card",
        name="card",
        type="RECTANGLE",
        bounds=Bounds(x=0, y=0, width=360, height=110),
        properties={
            "psdKind": "shape",
            "fguiGraph": {"shape": "rect", "fillColor": "#fff0e0d0"},
        },
    )
    group = SelectionNode(
        id="card-group",
        name="Card",
        type="GROUP",
        bounds=Bounds(x=0, y=0, width=400, height=520),
        children=(card,),
    )
    root = SelectionNode(
        id="psd-root:" + "a" * 64,
        name="PSD",
        type="FRAME",
        bounds=Bounds(x=0, y=0, width=400, height=520),
        children=(group,),
    )
    return SelectionManifest(version=1, display_name="PSD", top_level_nodes=(root,))


def test_golden_simple_button_is_restyled_with_complete_psd_closure(tmp_path) -> None:
    root, target, inventory = _panel(tmp_path)
    manifest = _card_manifest()
    draft = build_mapping(inventory, manifest)
    mapping = normalize_psd_semantic_reskin(inventory, manifest, draft)
    card = next(i for i in mapping.items if i.old_object_id == "bg")
    assert card.action == "accept"
    assert card.legacy_state == "RESTYLE"
    closure = visual_closure(mapping, manifest)
    assert closure.psd_closure == 1.0


def test_golden_removed_legacy_routes_to_removal_review(tmp_path) -> None:
    """Regression for the n30_gm65 escape: an unmatched legacy visual must
    land as a pending REMOVE_CANDIDATE that the removal review owns."""
    root, target, inventory = _panel(tmp_path)
    manifest = _card_manifest()
    draft = build_mapping(inventory, manifest)
    mapping = normalize_psd_semantic_reskin(inventory, manifest, draft)
    candidates = [
        item for item in mapping.items
        if item.legacy_state == "REMOVE_CANDIDATE"
    ]
    assert candidates
    assert all(item.action is None for item in candidates)
    review = build_removal_review(mapping, inventory)
    assert review.pending
    assert review.total_candidate_count == len(candidates)


def test_golden_runtime_bound_objects_are_recommended_preserved(tmp_path) -> None:
    """Reference integrity: transition/relation bound candidates are never
    recommended for removal; only the review can decide their fate."""
    root, target, inventory = _panel(tmp_path)
    manifest = _card_manifest()
    draft = build_mapping(inventory, manifest)
    mapping = normalize_psd_semantic_reskin(inventory, manifest, draft)
    review = build_removal_review(mapping, inventory)
    runtime_bound = {
        member.object_id
        for group in (*review.groups, *review.auto_resolved_groups)
        for member in group.objects
        if member.runtime_bound or member.controller_refs
    }
    for group in (*review.groups, *review.auto_resolved_groups):
        if any(member.object_id in runtime_bound for member in group.objects):
            assert group.recommendation == "preserve"
    assert runtime_bound


def test_golden_decided_legacy_objects_carry_action_fates(tmp_path) -> None:
    root, target, inventory = _panel(tmp_path)
    manifest = _card_manifest()
    draft = build_mapping(inventory, manifest)
    mapping = normalize_psd_semantic_reskin(inventory, manifest, draft)
    for item in mapping.items:
        if item.old_object_id is None or item.out_of_scope:
            continue
        if item.action in {"accept", "retarget"}:
            assert item.legacy_state in {"REPLACE", "RESTYLE"}, item.item_id
        elif item.action == "remove_old":
            assert item.legacy_state == "REMOVE_CANDIDATE", item.item_id
        elif item.action in {"keep_old", "preserve_structure"}:
            assert item.legacy_state is not None, item.item_id


def test_golden_legacy_closure_rejects_pending_candidates(tmp_path) -> None:
    root, target, inventory = _panel(tmp_path)
    manifest = _card_manifest()
    draft = build_mapping(inventory, manifest)
    mapping = normalize_psd_semantic_reskin(inventory, manifest, draft)
    closure = visual_closure(mapping, manifest)
    assert closure.legacy_closure < 1.0
    assert closure.complete is False


def test_golden_psd_added_visual_is_proven_novel(tmp_path) -> None:
    """PSD Added UI: an unmatched leaf painting where no legacy visual ever
    rendered is a Proven New Visual (§14) and closes the PSD side."""
    root, target, inventory = _panel(tmp_path)
    extra = SelectionNode(
        id="psd-extra",
        name="novel",
        type="RECTANGLE",
        bounds=Bounds(x=300, y=430, width=60, height=60),
        properties={"psdKind": "shape"},
    )
    card = SelectionNode(
        id="psd-card",
        name="card",
        type="RECTANGLE",
        bounds=Bounds(x=0, y=0, width=360, height=110),
        properties={
            "psdKind": "shape",
            "fguiGraph": {"shape": "rect", "fillColor": "#fff0e0d0"},
        },
    )
    group = SelectionNode(
        id="card-group",
        name="Card",
        type="GROUP",
        bounds=Bounds(x=0, y=0, width=400, height=520),
        children=(card, extra),
    )
    root = SelectionNode(
        id="psd-root:" + "a" * 64,
        name="PSD",
        type="FRAME",
        bounds=Bounds(x=0, y=0, width=400, height=520),
        children=(group,),
    )
    manifest = SelectionManifest(
        version=1, display_name="PSD", top_level_nodes=(root,)
    )
    draft = build_mapping(inventory, manifest)
    mapping = normalize_psd_semantic_reskin(inventory, manifest, draft)
    added = [item for item in mapping.items if item.old_object_id is None]
    assert added
    assert all(item.novelty_proven is True for item in added)
    assert all(item.action == "add_visual" for item in added)
    closure = visual_closure(mapping, manifest)
    assert closure.psd_closure == 1.0


def test_golden_text_reuse_explains_source_leaf(tmp_path) -> None:
    text_panel = (
        '<component size="400,520"><displayList>'
        '<graph id="bg" name="card" xy="0,0" size="360,110" type="rect" fillColor="#fff0e0d0"/>'
        '<text id="label" name="title" xy="20,20" size="200,30" text="Noble Hall"/>'
        "</displayList></component>"
    )
    root, target, inventory = _panel(tmp_path, text_panel)
    card = SelectionNode(
        id="psd-card",
        name="card",
        type="RECTANGLE",
        bounds=Bounds(x=0, y=0, width=360, height=110),
        properties={
            "psdKind": "shape",
            "fguiGraph": {"shape": "rect", "fillColor": "#fff0e0d0"},
        },
    )
    label_leaf = SelectionNode(
        id="psd-label",
        name="title",
        type="TEXT",
        text="Noble Hall",
        bounds=Bounds(x=20, y=20, width=200, height=30),
        properties={"psdKind": "type"},
    )
    group = SelectionNode(
        id="card-group",
        name="Card",
        type="GROUP",
        bounds=Bounds(x=0, y=0, width=400, height=520),
        children=(card, label_leaf),
    )
    root_node = SelectionNode(
        id="psd-root:" + "a" * 64,
        name="PSD",
        type="FRAME",
        bounds=Bounds(x=0, y=0, width=400, height=520),
        children=(group,),
    )
    manifest = SelectionManifest(
        version=1, display_name="PSD", top_level_nodes=(root_node,)
    )
    draft = build_mapping(inventory, manifest)
    mapping = normalize_psd_semantic_reskin(inventory, manifest, draft)
    label = next(i for i in mapping.items if i.old_object_id == "label")
    assert label.action == "accept"
    assert label.legacy_state == "RESTYLE"


def test_golden_glist_default_item_template_is_preserved(tmp_path) -> None:
    list_panel = (
        '<component size="400,520"><displayList>'
        '<graph id="bg" name="card" xy="0,0" size="360,110" type="rect" fillColor="#fff0e0d0"/>'
        '<list id="rows" name="rows" xy="0,120" size="360,240" overflow="scroll" '
        'defaultItem="ui://pkgaa1/rowtpl"/>'
        "</displayList></component>"
    )
    root, target, inventory = _panel(tmp_path, list_panel)
    manifest = _card_manifest()
    draft = build_mapping(inventory, manifest)
    mapping = normalize_psd_semantic_reskin(inventory, manifest, draft)
    rows = next(i for i in mapping.items if i.old_object_id == "rows")
    assert rows.legacy_state == "PRESERVE_RUNTIME"


def test_golden_controller_state_and_shared_components_settle(tmp_path) -> None:
    controller_panel = (
        '<component size="400,520">'
        '<controller name="page" pages="0,default,1,active"/>'
        "<displayList>"
        '<graph id="bg" name="card" xy="0,0" size="360,110" type="rect" fillColor="#fff0e0d0"/>'
        '<graph id="badge" name="badge" xy="0,120" size="40,40" type="rect" fillColor="#ff000000">'
        '<gearDisplay controller="page" pages="0"/>'
        "</graph>"
        "</displayList></component>"
    )
    root, target, inventory = _panel(tmp_path, controller_panel)
    manifest = _card_manifest()
    draft = build_mapping(inventory, manifest)
    mapping = normalize_psd_semantic_reskin(inventory, manifest, draft)
    badge = next(i for i in mapping.items if i.old_object_id == "badge")
    assert badge.legacy_state is not None
    review = build_removal_review(mapping, inventory)
    badge_groups = [
        group for group in (*review.groups, *review.auto_resolved_groups)
        if any(member.object_id == "badge" for member in group.objects)
    ]
    for group in badge_groups:
        assert group.recommendation == "preserve"


def test_golden_occluded_subtree_is_explained(tmp_path) -> None:
    root, target, inventory = _panel(tmp_path)
    manifest = _card_manifest()
    draft = build_mapping(inventory, manifest)
    draft = draft.model_copy(update={
        "items": tuple(
            item.model_copy(update={"occluded": True})
            if item.old_object_id == "keep1"
            else item
            for item in draft.items
        )
    })
    mapping = normalize_psd_semantic_reskin(inventory, manifest, draft)
    keep1 = next(i for i in mapping.items if i.old_object_id == "keep1")
    assert keep1.occluded is True


# ---------------------------------------------------------------------------
# API-level golden corpus (full begin_psd chain + decision gate)
# ---------------------------------------------------------------------------


def _client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            plugin_access_token=b"test-token",
        )
    )


def _upload_project(client: TestClient, tmp_path, *, full: bool = False) -> str:
    from lxml import etree

    source = FIXTURE / "old_project"
    archive = tmp_path / "OldVillage.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for path in source.rglob("*"):
            if path.is_file() and ".figma-to-fgui-preview" not in path.parts:
                relative = path.relative_to(source).as_posix()
                if not full and path.name == "Panel_MyVillage_Sketchboard.xml":
                    doc = etree.parse(str(path))
                    display = doc.getroot().find("displayList")
                    for child in tuple(display):
                        if child.get("id") != "board_bg":
                            display.remove(child)
                    for child in tuple(doc.getroot()):
                        if child.tag != "displayList":
                            doc.getroot().remove(child)
                    output.writestr(relative, etree.tostring(doc, encoding="utf-8"))
                else:
                    output.write(path, relative)
    with archive.open("rb") as content:
        response = client.post(
            "/v1/projects/uploads",
            files={"project": (archive.name, content, "application/zip")},
            headers=HEADERS,
        )
    assert response.status_code == 201, response.text
    return response.json()["project_id"]


def _target(client: TestClient, project_id: str) -> dict:
    response = client.get(f"/v1/projects/{project_id}/hifi-targets", headers=HEADERS)
    assert response.status_code == 200, response.text
    tree = response.json()
    package = next(item for item in tree["packages"] if item["name"] == "MyVillage")
    directory = next(item for item in package["directories"] if item["path"] == "Panel")
    component = next(
        item for item in directory["components"] if item["resource_id"] == "sketch01"
    )
    return {
        "version": 1,
        "project_id": project_id,
        "project_fingerprint": tree["project_fingerprint"],
        "package_id": package["package_id"],
        "package_name": package["name"],
        "directory": directory["path"],
        "component_id": component["resource_id"],
        "component_name": component["name"],
        "component_relative_path": component["relative_path"],
    }


def _upload_psd(client: TestClient, tmp_path, layers) -> str:
    document = PSDImage.new(mode="RGB", size=(750, 600), depth=8)
    for image, name, left, top in layers:
        document.create_pixel_layer(image, name=name, left=left, top=top)
    psd = tmp_path / "screen.psd"
    document.save(psd)
    with psd.open("rb") as content:
        uploaded = client.post(
            "/v1/hifi-sources/psd",
            files={"psd": (psd.name, content, "image/vnd.adobe.photoshop")},
            headers=HEADERS,
        )
    assert uploaded.status_code == 201, uploaded.text
    return uploaded.json()["source_id"]


def _begin_session(
    client: TestClient, tmp_path, layers, key: str, *, full: bool = False
) -> tuple:
    project_id = _upload_project(client, tmp_path, full=full)
    target = _target(client, project_id)
    source_id = _upload_psd(client, tmp_path, layers)
    created = client.post(
        "/v1/hifi-replacements/from-psd",
        json={
            "version": 1,
            "project_id": project_id,
            "psd_source_id": source_id,
            "target": target,
            "idempotency_key": key,
        },
        headers=HEADERS,
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    mapping = client.get(
        f"/v1/hifi-replacements/{session_id}/mapping", headers=HEADERS
    ).json()
    return session_id, mapping


def test_golden_from_psd_reports_conservation_violation(
    tmp_path, monkeypatch
) -> None:
    """The conservation BLOCK must surface with its own code and detail from
    the create-session endpoint, not masked as hifi_target_stale."""
    from figma_to_fgui.hifi_conservation import HifiConservationError
    from figma_to_fgui.hifi_replacement_workflow import HifiReplacementWorkflow

    def boom(self, *args, **kwargs):
        raise HifiConservationError(
            "hifi_ownership_conservation_violation",
            "transformation=normalize_psd_semantic_reskin lost_source_ids=['deco-1']",
        )

    monkeypatch.setattr(HifiReplacementWorkflow, "begin_psd", boom)
    client = _client(tmp_path)
    project_id = _upload_project(client, tmp_path)
    target = _target(client, project_id)
    document = PSDImage.new(mode="RGB", size=(750, 600), depth=8)
    document.create_pixel_layer(
        Image.new("RGBA", (750, 420), (255, 255, 255, 255)),
        name="BoardBg",
        left=0,
        top=0,
    )
    psd = tmp_path / "screen.psd"
    document.save(psd)
    with psd.open("rb") as content:
        uploaded = client.post(
            "/v1/hifi-sources/psd",
            files={"psd": (psd.name, content, "image/vnd.adobe.photoshop")},
            headers=HEADERS,
        )
    created = client.post(
        "/v1/hifi-replacements/from-psd",
        json={
            "version": 1,
            "project_id": project_id,
            "psd_source_id": uploaded.json()["source_id"],
            "target": target,
            "idempotency_key": "conservation-propagation",
        },
        headers=HEADERS,
    )
    assert created.status_code == 409, created.text
    detail = created.json()["detail"]
    assert detail["code"] == "hifi_ownership_conservation_violation"
    assert "deco-1" in detail["message"]


def test_golden_session_records_full_stage_ledger(tmp_path) -> None:
    client = _client(tmp_path)
    layers = [
        (Image.new("RGBA", (750, 420), (255, 255, 255, 255)), "BoardBg", 0, 0),
    ]
    session_id, mapping = _begin_session(client, tmp_path, layers, "golden-ledger")
    ledger = mapping["stage_ledger"]
    transformations = [entry["transformation"] for entry in ledger]
    assert "build_mapping_raw" in transformations
    assert "normalize_psd_semantic_reskin" in transformations
    assert "build_mapping_states" in transformations
    assert "begin_psd_final" in transformations
    assert all(entry["lost_source_ids"] == [] for entry in ledger)
    raw_entry = next(
        entry for entry in ledger if entry["transformation"] == "build_mapping_raw"
    )
    final_entry = next(
        entry for entry in ledger if entry["transformation"] == "begin_psd_final"
    )
    assert (
        final_entry["owned_source_count"] + final_entry["released_source_count"]
        >= raw_entry["owned_source_count"]
    )


GATE_PANEL = (
    '<component size="400,520">'
    '<controller name="page" pages="0,default,1,active"/>'
    '<transition name="intro">'
    '<item type="XY" target="deco_t" time="0" duration="0.3" startValue="10,170" endValue="20,170"/>'
    '<item type="Alpha" target="keep1" time="0" duration="0.3" startValue="1" endValue="0.5"/>'
    '</transition>'
    "<displayList>"
    '<loader id="bg" name="card" xy="0,0" size="360,110" url="ui://pkgaa1/card"/>'
    '<graph id="deco_p" name="old_deco_plain" xy="10,120" size="40,40" type="rect" fillColor="#ff000000"/>'
    '<graph id="deco_t" name="old_deco_animated" xy="10,170" size="40,40" type="rect" fillColor="#ff000000"/>'
    '<graph id="keep1" name="keeper" xy="200,300" size="50,50" type="rect" fillColor="#ff00ff00">'
    '<relation target="deco_t" sidePair="left-left"/>'
    "</graph>"
    "</displayList></component>"
)


def _upload_gate_project(client: TestClient, tmp_path) -> dict:
    archive = tmp_path / "GatePanel.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        output.writestr(
            "GatePanel.fairy",
            '<?xml version="1.0" encoding="utf-8"?>'
            '<projectDescription id="4bb86d1c7302417c85fcb27afad16e44" '
            'type="Unity" version="5.0"/>',
        )
        output.writestr(
            "assets/Pkg/package.xml",
            '<?xml version="1.0" encoding="utf-8"?><package id="pkgaa1" name="Pkg">'
            "<resources>"
            '<component id="panel1" name="Panel_One.xml" path="/Panel/"/>'
            "</resources></package>",
        )
        output.writestr("assets/Pkg/Panel/Panel_One.xml", GATE_PANEL)
    with archive.open("rb") as content:
        response = client.post(
            "/v1/projects/uploads",
            files={"project": (archive.name, content, "application/zip")},
            headers=HEADERS,
        )
    assert response.status_code == 201, response.text
    project_id = response.json()["project_id"]
    tree = client.get(
        f"/v1/projects/{project_id}/hifi-targets", headers=HEADERS
    ).json()
    package = next(item for item in tree["packages"] if item["name"] == "Pkg")
    directory = next(
        item for item in package["directories"] if item["path"] == "Panel"
    )
    component = next(
        item for item in directory["components"] if item["resource_id"] == "panel1"
    )
    return {
        "version": 1,
        "project_id": project_id,
        "project_fingerprint": tree["project_fingerprint"],
        "package_id": package["package_id"],
        "package_name": package["name"],
        "directory": directory["path"],
        "component_id": component["resource_id"],
        "component_name": component["name"],
        "component_relative_path": component["relative_path"],
    }


def test_golden_removal_review_gate_blocks_build_until_decided(tmp_path) -> None:
    """gm65 regression: after auto-resolve the unmatched legacy visuals stay
    pending REMOVE_CANDIDATE (never auto-adopted); the build is blocked; and
    only an explicit removal-review decision releases it."""
    client = _client(tmp_path)
    target = _upload_gate_project(client, tmp_path)
    document = PSDImage.new(mode="RGB", size=(400, 520), depth=8)
    document.create_pixel_layer(
        Image.new("RGBA", (360, 110), (255, 240, 224, 255)),
        name="BoardBg",
        left=0,
        top=0,
    )
    psd = tmp_path / "gate.psd"
    document.save(psd)
    with psd.open("rb") as content:
        uploaded = client.post(
            "/v1/hifi-sources/psd",
            files={"psd": (psd.name, content, "image/vnd.adobe.photoshop")},
            headers=HEADERS,
        )
    assert uploaded.status_code == 201, uploaded.text
    created = client.post(
        "/v1/hifi-replacements/from-psd",
        json={
            "version": 1,
            "project_id": target["project_id"],
            "psd_source_id": uploaded.json()["source_id"],
            "target": target,
            "idempotency_key": "golden-gate",
        },
        headers=HEADERS,
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    resolved = client.post(
        f"/v1/hifi-replacements/{session_id}/mapping-auto-resolve",
        headers=HEADERS,
    )
    assert resolved.status_code == 200, resolved.text
    after = client.get(
        f"/v1/hifi-replacements/{session_id}/mapping", headers=HEADERS
    ).json()
    candidates = [
        item for item in after["items"]
        if item.get("legacy_state") == "REMOVE_CANDIDATE"
    ]
    assert candidates
    assert all(item["action"] is None for item in candidates)
    review = client.get(
        f"/v1/hifi-replacements/{session_id}/removal-review", headers=HEADERS
    ).json()
    assert review["pending"] is True
    assert review["total_candidate_count"] == len(candidates)
    blocked = client.post(
        f"/v1/hifi-replacements/{session_id}/build",
        json={"version": 1, "mapping_revision": after["mapping_revision"]},
        headers=HEADERS,
    )
    assert blocked.status_code == 409
    # Gate order is deterministic: the store blocks undecided mappings
    # before the workflow re-checks the removal review itself.
    assert blocked.json()["detail"]["code"] == "hifi_mapping_incomplete"
    decided = client.post(
        f"/v1/hifi-replacements/{session_id}/removal-review/decide",
        json={
            "version": 1,
            "mapping_revision": after["mapping_revision"],
            "decisions": [
                {
                    "version": 1,
                    "group_id": group["group_id"],
                    "decision": group["recommendation"],
                }
                for group in review["groups"]
            ],
        },
        headers=HEADERS,
    )
    assert decided.status_code == 200, decided.text
    final = client.get(
        f"/v1/hifi-replacements/{session_id}/mapping", headers=HEADERS
    ).json()
    decided_ids = {
        item["item_id"]
        for item in final["items"]
        if item["action"] in {"remove_old", "keep_old"}
    }
    assert {item["item_id"] for item in candidates} <= decided_ids
    assert final["unresolved_count"] == 0
    built = client.post(
        f"/v1/hifi-replacements/{session_id}/build",
        json={"version": 1, "mapping_revision": final["mapping_revision"]},
        headers=HEADERS,
    )
    assert built.status_code == 200, built.text
    assert built.json()["status"] == "review_ready"
