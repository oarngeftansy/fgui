from __future__ import annotations

from pathlib import Path

import pytest

from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.hifi_mapping import HifiMappingError, apply_mapping_decision, build_mapping
from figma_to_fgui.hifi_project_inspector import (
    inspect_component,
    inspect_hifi_targets,
    target_from_option,
)
from figma_to_fgui.hifi_replacement_models import HifiMappingDecision
from figma_to_fgui.models import Bounds
from figma_to_fgui.uploaded_project import index_uploaded_project

FIXTURE = Path(__file__).parents[1] / "fixtures/hifi_replacement"


def _inputs():
    root = FIXTURE / "old_project"
    project = index_uploaded_project(root, "old.zip")
    tree = inspect_hifi_targets(root, project)
    package = tree.packages[0]
    directory = next(item for item in package.directories if item.path == "Panel")
    component = next(item for item in directory.components if item.resource_id == "sketch01")
    inventory = inspect_component(root, target_from_option(project, package, directory, component))
    manifest = SelectionManifest.model_validate_json(
        (FIXTURE / "hifi-selection.json").read_text("utf-8")
    )
    return inventory, manifest


def test_mapping_classifies_matched_added_missing_and_uncertain() -> None:
    inventory, manifest = _inputs()
    draft = build_mapping(inventory, manifest)
    by_old = {item.old_object_id: item for item in draft.items if item.old_object_id}
    by_figma = {item.figma_node_id: item for item in draft.items if item.figma_node_id}
    assert by_old["silhouette_01"].status == "matched"
    assert by_old["silhouette_01"].old_object_type is not None
    assert by_figma["progress-bubble"].status == "hifi_added"
    assert by_figma["progress-bubble"].action is None
    assert by_old["btn_reset"].status == "fgui_only"
    assert by_old["old_badge"].status == "uncertain"
    assert draft.model_dump_json() == build_mapping(inventory, manifest).model_dump_json()


def test_decision_advances_revision_and_rejects_stale_or_duplicate_target() -> None:
    inventory, manifest = _inputs()
    draft = build_mapping(inventory, manifest)
    uncertain = next(item for item in draft.items if item.status == "uncertain")
    candidate = uncertain.candidates[0]
    updated = apply_mapping_decision(
        draft,
        HifiMappingDecision(
            version=1,
            mapping_revision=draft.mapping_revision,
            item_id=uncertain.item_id,
            action="retarget",
            figma_node_id=candidate,
        ),
        manifest,
    )
    assert updated.mapping_revision == draft.mapping_revision + 1
    with pytest.raises(HifiMappingError, match="stale_mapping"):
        apply_mapping_decision(
            updated,
            HifiMappingDecision(
                version=1,
                mapping_revision=draft.mapping_revision,
                item_id=uncertain.item_id,
                action="keep_old",
            ),
            manifest,
        )


def test_mapping_normalizes_absolute_figma_canvas_coordinates() -> None:
    inventory, manifest = _inputs()

    def move(node):
        return node.model_copy(
            update={
                "bounds": Bounds(
                    x=node.bounds.x + 1000,
                    y=node.bounds.y + 500,
                    width=node.bounds.width,
                    height=node.bounds.height,
                ),
                "children": tuple(move(child) for child in node.children),
            }
        )

    shifted = manifest.model_copy(update={"top_level_nodes": tuple(move(node) for node in manifest.top_level_nodes)})
    original = build_mapping(inventory, manifest)
    moved = build_mapping(inventory, shifted)
    original_silhouette = next(item for item in original.items if item.old_object_id == "silhouette_01")
    moved_silhouette = next(item for item in moved.items if item.old_object_id == "silhouette_01")
    assert moved_silhouette.status == original_silhouette.status
    assert moved_silhouette.figma_bounds == original_silhouette.figma_bounds


def test_mapping_blocks_unsupported_added_container_until_user_marks_exception() -> None:
    inventory, manifest = _inputs()
    selection_root = manifest.top_level_nodes[0]
    unsupported = SelectionNode(
        id="hifi-dialog",
        name="InteractiveDialog",
        type="FRAME",
        bounds=Bounds(x=100, y=100, width=200, height=120),
        children=(
            SelectionNode(
                id="hifi-dialog-button",
                name="DialogButton",
                type="INSTANCE",
                bounds=Bounds(x=120, y=180, width=80, height=30),
            ),
        ),
    )
    manifest = manifest.model_copy(
        update={
            "top_level_nodes": (
                selection_root.model_copy(
                    update={"children": (*selection_root.children, unsupported)}
                ),
            )
        }
    )

    mapping = build_mapping(inventory, manifest)

    blocked = next(item for item in mapping.items if item.figma_node_id == "hifi-dialog")
    assert blocked.status == "blocked"
    assert blocked.action is None
    assert mapping.unresolved_count >= 1
    with pytest.raises(HifiMappingError, match="mapping_action_not_allowed"):
        apply_mapping_decision(
            mapping,
            HifiMappingDecision(
                version=1,
                mapping_revision=mapping.mapping_revision,
                item_id=blocked.item_id,
                action="add_visual",
            ),
            manifest,
        )


def test_mapping_allows_psd_image_leaf_to_be_added_as_visual() -> None:
    inventory, manifest = _inputs()
    selection_root = manifest.top_level_nodes[0]
    psd_image = SelectionNode(
        id="psd-layer:image-leaf",
        name="Rendered smart object",
        type="IMAGE",
        bounds=Bounds(x=40, y=60, width=320, height=180),
        properties={"psdKind": "smartobject"},
    )
    manifest = manifest.model_copy(
        update={
            "top_level_nodes": (
                selection_root.model_copy(
                    update={"children": (*selection_root.children, psd_image)}
                ),
            )
        }
    )

    mapping = build_mapping(inventory, manifest)

    added = next(item for item in mapping.items if item.figma_node_id == psd_image.id)
    assert added.status == "hifi_added"
    assert added.action is None


def test_mapping_does_not_add_zero_area_psd_image() -> None:
    inventory, manifest = _inputs()
    selection_root = manifest.top_level_nodes[0]
    empty_image = SelectionNode(
        id="psd-layer:empty-image",
        name="Empty pixel layer",
        type="IMAGE",
        bounds=Bounds(x=0, y=0, width=0, height=0),
        properties={"psdKind": "pixel"},
    )
    manifest = manifest.model_copy(
        update={
            "top_level_nodes": (
                selection_root.model_copy(
                    update={"children": (*selection_root.children, empty_image)}
                ),
            )
        }
    )

    mapping = build_mapping(inventory, manifest)

    empty = next(item for item in mapping.items if item.figma_node_id == empty_image.id)
    assert empty.status == "blocked"


def test_component_instance_prefers_same_bounds_psd_group_as_its_visual_section() -> None:
    inventory, _ = _inputs()
    button = next(item for item in inventory.objects if item.object_id == "btn_next")
    focused_inventory = inventory.model_copy(update={"objects": (button,)})
    manifest = SelectionManifest(
        version=1,
        display_name="PSD",
        top_level_nodes=(
            SelectionNode(
                id="psd-root:" + "d" * 64,
                name="PSD",
                type="FRAME",
                bounds=Bounds(x=0, y=0, width=inventory.width, height=inventory.height),
                children=(
                    SelectionNode(
                        id="psd-button-group",
                        name="Primary action",
                        type="GROUP",
                        bounds=Bounds(
                            x=button.x,
                            y=button.y,
                            width=button.width,
                            height=button.height,
                        ),
                    ),
                ),
            ),
        ),
    )

    mapping = build_mapping(focused_inventory, manifest)

    item = next(item for item in mapping.items if item.old_object_id == button.object_id)
    assert item.figma_node_id == "psd-button-group"
    assert item.status == "suggested"


def test_tentative_matches_are_unique_and_not_listed_again_as_new() -> None:
    inventory, _ = _inputs()
    button = next(item for item in inventory.objects if item.object_id == "btn_next")
    duplicate = button.model_copy(update={"object_id": "other_button", "name": "other_button"})
    focused_inventory = inventory.model_copy(update={"objects": (button, duplicate)})
    node = SelectionNode(id="psd-button", name="Primary action", type="GROUP", bounds=Bounds(x=button.x, y=button.y, width=button.width, height=button.height))
    manifest = SelectionManifest(version=1, display_name="PSD", top_level_nodes=(SelectionNode(id="root", name="PSD", type="FRAME", bounds=Bounds(x=0, y=0, width=inventory.width, height=inventory.height), children=(node,)),))

    mapping = build_mapping(focused_inventory, manifest)

    assert sum(item.figma_node_id == node.id for item in mapping.items) == 1
    assert not any(item.status == "hifi_added" for item in mapping.items)


def test_unmatched_group_is_one_review_unit_instead_of_each_descendant() -> None:
    inventory, _ = _inputs()
    group = SelectionNode(id="new-group", name="New section", type="GROUP", bounds=Bounds(x=0, y=0, width=100, height=100), children=(SelectionNode(id="new-leaf", name="Artwork", type="IMAGE", bounds=Bounds(x=0, y=0, width=100, height=100)),))
    manifest = SelectionManifest(version=1, display_name="PSD", top_level_nodes=(SelectionNode(id="root", name="PSD", type="FRAME", bounds=Bounds(x=0, y=0, width=inventory.width, height=inventory.height), children=(group,)),))
    empty_inventory = inventory.model_copy(update={"objects": ()})

    mapping = build_mapping(empty_inventory, manifest)

    assert [item.figma_node_id for item in mapping.items] == ["new-group"]


def test_retargeting_an_old_object_resolves_the_same_psd_branch_as_new() -> None:
    inventory, manifest = _inputs()
    mapping = build_mapping(inventory, manifest)
    old = next(item for item in mapping.items if item.old_object_id == "btn_reset")
    new = next(item for item in mapping.items if item.figma_node_id == "progress-bubble")

    updated = apply_mapping_decision(mapping, HifiMappingDecision(version=1, mapping_revision=mapping.mapping_revision, item_id=old.item_id, action="retarget", figma_node_id=new.figma_node_id), manifest)

    assert next(item for item in updated.items if item.item_id == old.item_id).action == "retarget"
    assert next(item for item in updated.items if item.item_id == new.item_id).action == "exception"
    assert updated.unresolved_count == mapping.unresolved_count - 1
