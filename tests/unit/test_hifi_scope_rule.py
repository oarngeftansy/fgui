"""Cross-package component references are outside one HIFI replacement round.

A FairyGUI panel may reference components that live in another package. Their
visual definitions are shared by every screen that references them, so writing
new visuals there would change unrelated screens. The replacement scope is the
target package: cross-package instance subtrees are marked out of scope, are
not offered for correspondence, and do not occupy the human review budget.
Generated state visuals still bind to their owner, because that mechanism is
driven by controller evidence rather than by package reachability.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.hifi_mapping import (
    HifiMappingError,
    apply_mapping_decision,
    build_mapping,
    require_psd_coverage,
)
from figma_to_fgui.hifi_project_inspector import (
    inspect_hifi_targets,
    target_from_option,
)
from figma_to_fgui.hifi_replacement_models import HifiMappingDecision
from figma_to_fgui.models import Bounds
from figma_to_fgui.uploaded_project import index_uploaded_project

PANEL = """<?xml version="1.0" encoding="utf-8"?>
<component size="1000,800">
  <displayList>
    <image id="n_bg" name="bg" src="imgbg" fileName="Img/Bg.png" xy="0,0" size="1000,800"/>
    <component id="n_win" name="win" src="win01" fileName="Window/Shared_Window.xml" pkg="labshare" xy="400,100"/>
    <component id="n_btn" name="btn" src="btn01" fileName="Button/Btn_L.xml" xy="50,500"/>
    <graph id="n_bar" name="bar" xy="700,600" size="90,40" type="rect" lineSize="0" fillColor="#ff112233"/>
    <text id="n_txt" name="txt" xy="100,700" size="80,30" font="ui://lablocallab01fnt" fontSize="20" text="LocalTitle"/>
  </displayList>
</component>
"""
SHARED_WINDOW = """<?xml version="1.0" encoding="utf-8"?>
<component size="200,300">
  <displayList>
    <text id="n_title" name="title" xy="20,20" size="160,30" font="ui://labsharefnt01" fontSize="20" text="SharedTitle"/>
    <loader id="n_icon" name="icon" xy="20,60" size="48,48" url="ui://labshareicon01" fill="scale"/>
  </displayList>
</component>
"""
LOCAL_BUTTON = """<?xml version="1.0" encoding="utf-8"?>
<component size="140,60">
  <displayList>
    <graph id="n_lbar" name="lbar" xy="0,0" size="140,60" type="rect" lineSize="0" fillColor="#ff445566"/>
    <text id="n_ltitle" name="ltitle" xy="10,10" size="100,30" font="ui://lablocallab01fnt" fontSize="20" text="LocalBtn"/>
  </displayList>
</component>
"""


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "assets/LabP/Panel").mkdir(parents=True)
    (root / "assets/LabP/Button").mkdir(parents=True)
    (root / "assets/LabP/Img").mkdir(parents=True)
    (root / "assets/Shared/Window").mkdir(parents=True)
    (root / "Lab.fairy").write_text(
        '<projectDescription id="1234567890abcdef1234567890abcdef" type="Unity" version="5.0"/>',
        "utf-8",
    )
    (root / "assets/LabP/package.xml").write_text(
        '<packageDescription id="lablocal"><resources>'
        '<image id="imgbg" name="Bg.png" path="/Img/"/>'
        '<component id="btn01" name="Btn_L.xml" path="/Button/"/>'
        '<component id="panel01" name="Panel_S.xml" path="/Panel/"/>'
        "</resources><publish/></packageDescription>",
        "utf-8",
    )
    (root / "assets/Shared/package.xml").write_text(
        '<packageDescription id="labshare"><resources>'
        '<component id="win01" name="Shared_Window.xml" path="/Window/"/>'
        "</resources><publish/></packageDescription>",
        "utf-8",
    )
    (root / "assets/LabP/Img/Bg.png").write_bytes(
        # 1x1 transparent PNG
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c6260010000050001"
            "0d0a2db40000000049454e44ae426082"
        )
    )
    (root / "assets/LabP/Panel/Panel_S.xml").write_text(PANEL, "utf-8")
    (root / "assets/LabP/Button/Btn_L.xml").write_text(LOCAL_BUTTON, "utf-8")
    (root / "assets/Shared/Window/Shared_Window.xml").write_text(SHARED_WINDOW, "utf-8")
    return root


def _inventory(root: Path):
    from figma_to_fgui.hifi_nested import inspect_component_tree

    project = index_uploaded_project(root, "lab.zip")
    tree = inspect_hifi_targets(root, project)
    package = next(item for item in tree.packages if item.name == "LabP")
    directory = next(item for item in package.directories if item.path == "Panel")
    component = next(item for item in directory.components if item.resource_id == "panel01")
    return inspect_component_tree(root, target_from_option(project, package, directory, component))


def _manifest(children: tuple[SelectionNode, ...]) -> SelectionManifest:
    return SelectionManifest(
        version=1,
        display_name="PSD",
        top_level_nodes=(
            SelectionNode(
                id="psd-root:lab",
                name="PSD",
                type="FRAME",
                bounds=Bounds(x=0, y=0, width=1000, height=800),
                properties={"psdKind": "group"},
                children=children,
            ),
        ),
    )


def _leaf(node_id: str, name: str, x: float, y: float, *, kind: str = "shape",
          text: str | None = None) -> SelectionNode:
    return SelectionNode(
        id=node_id,
        name=name,
        type="TEXT" if kind == "type" else "RECTANGLE",
        bounds=Bounds(x=x, y=y, width=80, height=30),
        text=text,
        properties={"psdKind": kind},
    )


def test_cross_package_subtree_is_marked_out_of_scope(tmp_path: Path) -> None:
    objects = {o.object_id: o for o in _inventory(_project(tmp_path)).objects}
    assert objects["n_win"].out_of_scope is True
    assert objects["n_win:n_title"].out_of_scope is True
    assert objects["n_win:n_icon"].out_of_scope is True
    assert objects["n_btn"].out_of_scope is False
    assert objects["n_btn:n_lbar"].out_of_scope is False
    assert objects["n_btn:n_ltitle"].out_of_scope is False
    assert objects["n_bar"].out_of_scope is False
    assert objects["n_txt"].out_of_scope is False


def test_out_of_scope_objects_leave_the_review_queue(tmp_path: Path) -> None:
    inventory = _inventory(_project(tmp_path))
    # The shared title has a unique text that would otherwise be proven.
    draft = build_mapping(inventory, _manifest((
        _leaf("psd:shared", "SharedTitle", 410, 110, kind="type", text="SharedTitle"),
        _leaf("psd:bar", "Bar", 695, 595),
    )))
    title = next(i for i in draft.items if i.old_object_id == "n_win:n_title")
    assert title.status == "out_of_scope"
    assert title.action == "preserve_structure"
    assert title.out_of_scope is True
    # A unique text match must not be claimed for an object outside the scope.
    assert title.figma_node_id is None
    loader = next(i for i in draft.items if i.old_object_id == "n_win:n_icon")
    assert loader.status == "out_of_scope"
    assert loader.action == "preserve_structure"
    unresolved = [i for i in draft.items if i.action is None]
    assert all(i.old_object_id != "n_win:n_title" for i in unresolved)


def test_psd_leaf_over_shared_component_is_out_of_scope(tmp_path: Path) -> None:
    inventory = _inventory(_project(tmp_path))
    draft = build_mapping(inventory, _manifest((
        _leaf("psd:shared", "SharedTitle", 410, 110, kind="type", text="SharedTitle"),
        _leaf("psd:bar", "Bar", 695, 595),
    )))
    shared = next(i for i in draft.items if i.figma_node_id == "psd:shared")
    assert shared.status == "out_of_scope"
    assert shared.action == "preserve_structure"
    assert shared.out_of_scope is True
    bar = next(i for i in draft.items if i.figma_node_id == "psd:bar")
    assert bar.status == "hifi_added"


def test_out_of_scope_psd_leaf_counts_as_covered(tmp_path: Path) -> None:
    inventory = _inventory(_project(tmp_path))
    manifest = _manifest((
        _leaf("psd:shared", "SharedTitle", 410, 110, kind="type", text="SharedTitle"),
    ))
    draft = build_mapping(inventory, manifest)
    # Scope records are decided; only genuinely unmatched in-scope objects
    # stay pending for a human.
    assert all(i.action is not None for i in draft.items if i.out_of_scope)
    assert not any(i.out_of_scope for i in draft.items if i.action is None)
    require_psd_coverage(draft, manifest)


def test_out_of_scope_item_rejects_user_decisions(tmp_path: Path) -> None:
    inventory = _inventory(_project(tmp_path))
    manifest = _manifest((
        _leaf("psd:shared", "SharedTitle", 410, 110, kind="type", text="SharedTitle"),
    ))
    draft = build_mapping(inventory, manifest)
    item = next(i for i in draft.items if i.old_object_id == "n_win:n_title")
    with pytest.raises(HifiMappingError):
        apply_mapping_decision(draft, HifiMappingDecision(
            version=1, item_id=item.item_id, action="accept",
            mapping_revision=draft.mapping_revision,
        ), manifest)


def test_generated_state_still_binds_to_out_of_scope_owner(tmp_path: Path) -> None:
    inventory = _inventory(_project(tmp_path))
    derived = SelectionNode(
        id="derived-state:probe",
        name="Num",
        type="RECTANGLE",
        bounds=Bounds(x=20, y=200, width=80, height=30),
        properties={"psdKind": "shape", "generatedStateOwner": "n_win:n_icon"},
    )
    draft = build_mapping(inventory, _manifest((derived,)))
    item = next(i for i in draft.items if i.old_object_id == "n_win:n_icon")
    assert item.status == "matched"
    assert item.action == "accept"
    assert item.generated_state is True
    assert item.out_of_scope is True


def test_owned_promotion_fires_without_position_evidence(tmp_path) -> None:
    from test_hifi_nested import nested_case

    _, inventory, _, _ = nested_case(tmp_path)
    selected = tuple(
        o.model_copy(update={"raster_conversion_allowed": True,
                             "position_runtime_bound": True,
                             "name": "Panel Art"})
        if o.object_id == "a:bg" else o
        for o in inventory.objects if o.object_id in {"a:bg", "a:title"}
    )
    inventory = inventory.model_copy(update={"objects": selected})
    visual = (
        SelectionNode(id="body", name="Background", type="RECTANGLE",
                      bounds=Bounds(x=10, y=20, width=120, height=44),
                      properties={"psdKind": "shape"}),
        SelectionNode(id="stroke", name="Stroke", type="VECTOR",
                      bounds=Bounds(x=10, y=20, width=120, height=44),
                      properties={"psdKind": "shape"}),
    )
    # The retained text sits far from the legacy title and carries a different
    # name, so it has no tentative match and must be paired with the sole
    # title child of the button definition by the partition itself.
    title = SelectionNode(id="label", name="Renamed", type="TEXT", text="New",
                          bounds=Bounds(x=500, y=300, width=90, height=24),
                          properties={"psdKind": "type"})
    group = SelectionNode(id="button", name="Button", type="GROUP",
                          bounds=Bounds(x=10, y=20, width=120, height=44),
                          properties={"psdKind": "group"}, children=(*visual, title))
    source = SelectionManifest(version=1, display_name="PSD", top_level_nodes=(
        SelectionNode(id="psd-root:synthetic", name="PSD", type="FRAME",
                      bounds=Bounds(x=0, y=0, width=750, height=420), children=(group,)),
    ))
    draft = build_mapping(inventory, source, owned_visual_validator=lambda *_: True)
    body = next(i for i in draft.items if i.old_object_id == "a:bg")
    # The unrelated name proves the promotion rides on the scaled gate, not on
    # a lucky name match lifting the score above the unscaled threshold.
    assert body.score < 0.55
    assert body.owned_source_ids == ("body", "stroke")
    assert body.action == "accept"
    promoted_title = next(i for i in draft.items if i.old_object_id == "a:title")
    assert promoted_title.action == "accept"
    assert promoted_title.figma_node_id == "label"
    assert promoted_title.status == "matched"