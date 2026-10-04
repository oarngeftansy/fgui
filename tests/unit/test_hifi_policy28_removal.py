"""Policy 28 §8-§11: Legacy Removal Review, confirmed removal with
Reference Closure, and the preserve-stops-visual-contribution path."""
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
from figma_to_fgui.hifi_patch import build_hifi_change_bundle, validate_hifi_candidate
from figma_to_fgui.hifi_removal_review import build_removal_review
from figma_to_fgui.hifi_replacement_models import HifiMappingDecision, HifiTargetRef
from figma_to_fgui.models import Bounds

SESSION_ID = "a" * 32

# gA is an advanced group; deco_p is a plain member, deco_g is controller/gear
# bound, deco_t is a transition target, keep1 owns a relation to deco_t and is
# also animated. bg (card) is replaced by the PSD, satisfying the reskin guard.
PANEL = (
    '<component size="400,520">'
    '<controller name="page" pages="0,default,1,active"/>'
    '<transition name="intro">'
    '<item type="XY" target="deco_t" time="0" duration="0.3" startValue="10,170" endValue="20,170"/>'
    '<item type="Alpha" target="keep1" time="0" duration="0.3" startValue="1" endValue="0.5"/>'
    '</transition>'
    "<displayList>"
    '<graph id="bg" name="card" xy="0,0" size="360,110" type="rect" fillColor="#fff0e0d0"/>'
    '<group id="gA" name="deco_region" xy="10,120" size="120,120" advanced="true"/>'
    '<graph id="deco_p" name="old_deco_plain" xy="10,120" size="40,40" type="rect" fillColor="#ff000000" group="gA"/>'
    '<graph id="deco_g" name="old_deco_gear" xy="60,120" size="40,40" type="rect" fillColor="#ff000000" group="gA">'
    '<gearDisplay controller="page" pages="0"/>'
    "</graph>"
    '<graph id="deco_t" name="old_deco_animated" xy="10,170" size="40,40" type="rect" fillColor="#ff000000" group="gA"/>'
    '<graph id="keep1" name="keeper" xy="200,300" size="50,50" type="rect" fillColor="#ff00ff00">'
    '<relation target="deco_t" sidePair="left-left"/>'
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


def _write_package(root: Path, panel_xml: str) -> None:
    (root / "assets" / "Pkg" / "Panel").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "Pkg" / "package.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?><package id="pkgaa1" name="Pkg">'
        "<resources>"
        '<component id="panel1" name="Panel_One.xml" path="/Panel/"/>'
        "</resources></package>",
        encoding="utf-8",
    )
    (root / "assets" / "Pkg" / "Panel" / "Panel_One.xml").write_text(
        panel_xml, encoding="utf-8"
    )


def _reskin_manifest() -> SelectionManifest:
    """The card shape replaces bg; the decorations have no PSD counterpart."""
    return SelectionManifest(
        version=1,
        display_name="PSD",
        top_level_nodes=(
            SelectionNode(
                id="psd-root:t", name="PSD", type="FRAME",
                bounds=Bounds(x=0, y=0, width=400, height=520),
                children=(
                    SelectionNode(
                        id="psd-card", name="card", type="RECTANGLE",
                        bounds=Bounds(x=0, y=0, width=360, height=110),
                        properties={
                            "psdKind": "shape", "blendMode": "normal",
                            "fguiGraph": {
                                "shape": "rect",
                                "fillColor": "#fff0e0d0",
                                "lineSize": 0,
                            },
                        },
                    ),
                ),
            ),
        ),
    )


def _empty_psd_manifest() -> SelectionManifest:
    return SelectionManifest(
        version=1,
        display_name="PSD",
        top_level_nodes=(
            SelectionNode(
                id="psd-root:t", name="PSD", type="FRAME",
                bounds=Bounds(x=0, y=0, width=400, height=520),
            ),
        ),
    )


def _draft(tmp_path):
    root = tmp_path / "proj"
    _write_package(root, PANEL)
    target = _target()
    inventory = inspect_component_tree(root, target)
    manifest = _reskin_manifest()
    return root, target, inventory, manifest, build_mapping(inventory, manifest)


# The e2e build path exercises the nested bundle. A flat panel (no advanced
# group) keeps the removal surgery isolated from group-bounds re-sync, which
# is a separate geometry concern from Reference Closure.
E2E_PANEL = (
    '<component size="400,520">'
    '<controller name="page" pages="0,default,1,active"/>'
    '<transition name="intro">'
    '<item type="XY" target="deco_t" time="0" duration="0.3" startValue="10,170" endValue="20,170"/>'
    '<item type="Alpha" target="keep1" time="0" duration="0.3" startValue="1" endValue="0.5"/>'
    '</transition>'
    "<displayList>"
    '<graph id="bg" name="card" xy="0,0" size="360,110" type="rect" fillColor="#fff0e0d0"/>'
    '<graph id="deco_p" name="old_deco_plain" xy="10,120" size="40,40" type="rect" fillColor="#ff000000"/>'
    '<graph id="deco_t" name="old_deco_animated" xy="10,170" size="40,40" type="rect" fillColor="#ff000000"/>'
    '<graph id="keep1" name="keeper" xy="200,300" size="50,50" type="rect" fillColor="#ff00ff00">'
    '<relation target="deco_t" sidePair="left-left"/>'
    "</graph>"
    "</displayList></component>"
)


def _e2e_draft(tmp_path):
    root = tmp_path / "proj-e2e"
    _write_package(root, E2E_PANEL)
    target = _target()
    inventory = inspect_component_tree(root, target)
    manifest = _reskin_manifest()
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


def test_candidates_are_grouped_with_references_and_recommendation(tmp_path):
    _, _, inventory, _, draft = _draft(tmp_path)

    review = build_removal_review(draft, inventory)

    assert review.pending
    assert review.total_candidate_count == 4
    assert review.auto_resolved_groups == ()
    by_region = {group.region: group for group in review.groups}
    assert set(by_region) == {"gA", ""}

    deco = by_region["gA"]
    assert deco.risk_tier == 1
    assert deco.recommendation == "preserve"
    members = {member.object_id: member for member in deco.objects}
    assert set(members) == {"deco_p", "deco_g", "deco_t"}
    # §9: affected runtime references are disclosed per object.
    assert members["deco_g"].controller_refs == ("page",)
    assert members["deco_g"].runtime_bound  # gearDisplay is an instance parameter
    assert members["deco_g"].risk_tier == 1
    assert members["deco_t"].transition_refs == ("intro",)
    assert members["deco_t"].referenced_by == ("keep1",)
    assert members["deco_t"].runtime_bound
    assert not members["deco_p"].runtime_bound
    assert members["deco_p"].risk_tier == 4
    assert "REMOVE_CANDIDATE" in members["deco_p"].reason

    keeper = by_region[""]
    assert [member.object_id for member in keeper.objects] == ["keep1"]
    assert keeper.recommendation == "preserve"
    assert keeper.objects[0].relation_refs == ("deco_t",)


def test_other_state_visual_is_preserved_not_a_removal_candidate(tmp_path):
    # §8: an object hidden in the default controller state serves another
    # state; it is preserved automatically and never offered for removal.
    panel = PANEL.replace(
        '<gearDisplay controller="page" pages="0"/>',
        '<gearDisplay controller="page" pages="1"/>',
    )
    root = tmp_path / "proj-hidden"
    _write_package(root, panel)
    inventory = inspect_component_tree(root, _target())
    draft = build_mapping(inventory, _reskin_manifest())

    deco_g = next(i for i in draft.items if i.old_object_id == "deco_g")
    assert deco_g.legacy_state == "PRESERVE_OTHER_STATE"
    review = build_removal_review(draft, inventory)
    assert "deco_g" not in {
        member.object_id
        for group in review.groups
        for member in group.objects
    }


def test_more_than_five_groups_caps_user_review_and_records_auto_resolution(tmp_path):
    rows = []
    for index in range(1, 8):
        rows.append(
            f'<group id="g{index}" name="region{index}" xy="0,{120 + index * 50}" size="50,40" advanced="true"/>'
            f'<graph id="d{index}" name="old_deco_{index}" xy="0,{120 + index * 50}" size="40,40" '
            f'type="rect" fillColor="#ff000000" group="g{index}"/>'
        )
    root = tmp_path / "proj-cap"
    _write_package(
        root,
        '<component size="400,600"><displayList>' + "".join(rows) + "</displayList></component>",
    )
    inventory = inspect_component_tree(root, _target())
    draft = build_mapping(inventory, _empty_psd_manifest())

    review = build_removal_review(draft, inventory)

    assert review.total_candidate_count == 7  # d1..d7, one region group each
    assert len(review.groups) == 5
    assert len(review.auto_resolved_groups) == 2
    assert all(group.auto_resolved for group in review.auto_resolved_groups)
    assert not any(group.auto_resolved for group in review.groups)
    # Pure low-risk visuals: the recorded recommendation is removal, and no
    # runtime-bound object is ever inside an auto-resolved group.
    assert all(
        group.recommendation == "remove" for group in review.auto_resolved_groups
    )
    assert all(
        not member.runtime_bound
        for group in review.auto_resolved_groups
        for member in group.objects
    )


def test_remove_old_requires_a_removal_candidate(tmp_path):
    _, _, _, manifest, draft = _draft(tmp_path)
    group_item = next(item for item in draft.items if item.old_object_id == "gA")
    assert group_item.legacy_state != "REMOVE_CANDIDATE"

    with pytest.raises(HifiMappingError) as error:
        _decide(draft, manifest, group_item.item_id, "remove_old")
    assert error.value.code == "hifi_removal_requires_candidate"


def test_confirmed_removal_closes_references_and_passes_validation(tmp_path):
    root, target, inventory, manifest, draft = _e2e_draft(tmp_path)
    mapping = draft
    for object_id in ("deco_p", "deco_t"):
        mapping = _decide(mapping, manifest, f"old:{object_id}", "remove_old")
    mapping = _decide(mapping, manifest, "old:keep1", "keep_old", "retire")
    assert mapping.unresolved_count == 0

    report = visual_closure(mapping, manifest)
    assert report.complete
    require_visual_closure(mapping, manifest)

    bundle = build_hifi_change_bundle(
        root, inventory, manifest, mapping, job_id="j" * 32
    )
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    apply_bundle(candidate, bundle)

    after = etree.parse(str(candidate / target.component_relative_path))
    remaining = {
        str(element.attrib["id"])
        for element in after.xpath("./displayList/*[@id]")
    }
    assert remaining == {"bg", "keep1"}
    # §8 Reference Closure: the survivor lost its relation to the removed
    # object, and the transition lost only the keyframe targeting it.
    keeper = after.xpath('./displayList/*[@id="keep1"]')[0]
    assert keeper.findall("relation") == []
    assert keeper.attrib.get("visible") == "false"
    intro = after.xpath('./transition[@name="intro"]')[0]
    targets = [str(item.attrib["target"]) for item in intro.xpath(".//*[@target]")]
    assert targets == ["keep1"]

    review = validate_hifi_candidate(
        root, candidate, inventory, mapping, session_id=SESSION_ID
    )
    assert review.protected_checks_passed
    removal_diffs = {
        diff.old_object_id: diff.summary
        for diff in review.object_diffs
        if diff.action == "remove_old"
    }
    assert set(removal_diffs) == {"deco_p", "deco_t"}
    assert any("闭合" in summary for summary in removal_diffs.values())


def test_preserve_keeps_identity_and_stops_target_state_contribution(tmp_path):
    root, target, inventory, manifest, draft = _e2e_draft(tmp_path)
    mapping = _decide(draft, manifest, "old:deco_p", "keep_old", "retire")

    kept = next(item for item in mapping.items if item.old_object_id == "deco_p")
    assert kept.action == "keep_old"
    assert kept.visual_disposition == "retire"
    assert kept.legacy_state == "RETIRE"

    for object_id in ("deco_t", "keep1"):
        mapping = _decide(mapping, manifest, f"old:{object_id}", "remove_old")
    assert mapping.unresolved_count == 0
    assert visual_closure(mapping, manifest).complete

    bundle = build_hifi_change_bundle(
        root, inventory, manifest, mapping, job_id="j" * 32
    )
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    apply_bundle(candidate, bundle)
    after = etree.parse(str(candidate / target.component_relative_path))
    remaining = {
        str(element.attrib["id"])
        for element in after.xpath("./displayList/*[@id]")
    }
    assert remaining == {"bg", "deco_p"}
    deco_p = after.xpath('./displayList/*[@id="deco_p"]')[0]
    # §11: identity, gears and relations stay; only the default pixel
    # contribution stops.
    assert deco_p.attrib.get("visible") == "false"
    review = validate_hifi_candidate(
        root, candidate, inventory, mapping, session_id=SESSION_ID
    )
    assert review.protected_checks_passed
