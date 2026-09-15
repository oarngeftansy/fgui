from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from lxml import etree

from figma_to_fgui.apply import apply_bundle
from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode, SelectionResource
from figma_to_fgui.hifi_mapping import apply_mapping_decision, build_mapping
from figma_to_fgui.hifi_patch import build_hifi_change_bundle, validate_hifi_candidate
from figma_to_fgui.hifi_project_inspector import (
    inspect_component,
    inspect_hifi_targets,
    target_from_option,
)
from figma_to_fgui.hifi_replacement_models import HifiMappingDecision
from figma_to_fgui.models import Bounds
from figma_to_fgui.uploaded_project import index_uploaded_project

FIXTURE = Path(__file__).parents[1] / "fixtures/hifi_replacement"


def _confirmed():
    root = FIXTURE / "old_project"
    project = index_uploaded_project(root, "old.zip")
    tree = inspect_hifi_targets(root, project)
    package = tree.packages[0]
    directory = next(item for item in package.directories if item.path == "Panel")
    component = next(item for item in directory.components if item.resource_id == "sketch01")
    inventory = inspect_component(root, target_from_option(project, package, directory, component))
    manifest = SelectionManifest.model_validate_json((FIXTURE / "hifi-selection.json").read_text("utf-8"))
    mapping = build_mapping(inventory, manifest)
    for item in tuple(mapping.items):
        current = next(current for current in mapping.items if current.item_id == item.item_id)
        if current.action is None:
            action = "retarget" if current.status in {"uncertain", "suggested"} else "keep_old"
            mapping = apply_mapping_decision(
                mapping,
                HifiMappingDecision(
                    version=1,
                    mapping_revision=mapping.mapping_revision,
                    item_id=current.item_id,
                    action=action,
                    figma_node_id=current.candidates[0] if action == "retarget" else None,
                ),
                manifest,
            )
    return root, inventory, manifest, mapping


def test_patch_changes_visuals_without_rebuilding_or_deleting_old_objects(tmp_path: Path) -> None:
    root, inventory, manifest, mapping = _confirmed()
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    bundle = build_hifi_change_bundle(candidate, inventory, manifest, mapping, job_id=uuid.uuid4().hex)
    apply_bundle(candidate, bundle)
    relative = inventory.target.component_relative_path
    before = etree.parse(str(root / relative))
    after = etree.parse(str(candidate / relative))
    before_ids = {str(node.attrib["id"]) for node in before.xpath("./displayList/*[@id]")}
    after_ids = {str(node.attrib["id"]) for node in after.xpath("./displayList/*[@id]")}
    assert before_ids <= after_ids
    assert after.xpath("./displayList/*[starts-with(@id, 'hifi_')]")
    reset_before = before.xpath("./displayList/*[@id='btn_reset']")[0]
    reset_after = after.xpath("./displayList/*[@id='btn_reset']")[0]
    assert etree.tostring(reset_before) == etree.tostring(reset_after)
    review = validate_hifi_candidate(
        root, candidate, inventory, mapping, session_id=uuid.uuid4().hex
    )
    assert review.protected_checks_passed is True
    assert [item.relative_path for item in review.changed_files] == [relative]
    assert review.editor_check_required is True


def test_patch_registers_uploaded_hifi_image_and_retargets_private_image(tmp_path: Path) -> None:
    root, inventory, manifest, _ = _confirmed()
    png = (Path(__file__).parents[1] / "fixtures/fgui-new-project/resources/one-pixel.png").read_bytes()
    board = SelectionNode(
        id="hifi-board",
        name="BoardBg",
        type="RECTANGLE",
        bounds=Bounds(x=0, y=0, width=750, height=420),
        resource_keys=("board-hifi",),
    )
    selection_root = tmp_path / "selection"
    (selection_root / "resources").mkdir(parents=True)
    (selection_root / "resources/board-hifi").write_bytes(png)
    root_node = manifest.top_level_nodes[0]
    manifest = manifest.model_copy(
        update={
            "top_level_nodes": (
                root_node.model_copy(update={"children": (board, *root_node.children)}),
            ),
            "resources": (
                SelectionResource(key="board-hifi", mime_type="image/png", size=len(png)),
            ),
        }
    )
    mapping = build_mapping(inventory, manifest)
    for original in tuple(mapping.items):
        item = next(entry for entry in mapping.items if entry.item_id == original.item_id)
        if item.action is None:
            action = "retarget" if item.candidates else "keep_old"
            mapping = apply_mapping_decision(
                mapping,
                HifiMappingDecision(
                    version=1,
                    mapping_revision=mapping.mapping_revision,
                    item_id=item.item_id,
                    action=action,
                    figma_node_id=item.candidates[0] if action == "retarget" else None,
                ),
                manifest,
            )
    candidate = tmp_path / "candidate-with-image"
    shutil.copytree(root, candidate)
    bundle = build_hifi_change_bundle(
        candidate,
        inventory,
        manifest,
        mapping,
        job_id=uuid.uuid4().hex,
        selection_root=selection_root,
    )
    apply_bundle(candidate, bundle)
    component = etree.parse(str(candidate / inventory.target.component_relative_path))
    board_after = component.xpath("./displayList/*[@id='board_bg']")[0]
    assert str(board_after.attrib["src"]).startswith("h")
    package = etree.parse(str(candidate / "assets/MyVillage/package.xml"))
    resource = package.xpath(f"./resources/image[@id='{board_after.attrib['src']}']")
    assert len(resource) == 1
    created = candidate / "assets/MyVillage" / resource[0].attrib["path"].strip("/") / resource[0].attrib["name"]
    assert created.read_bytes() == png
    review = validate_hifi_candidate(
        root, candidate, inventory, mapping, session_id=uuid.uuid4().hex
    )
    assert any(item.operation == "create" for item in review.changed_files)
