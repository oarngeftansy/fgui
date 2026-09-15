from __future__ import annotations

from pathlib import Path

import pytest

from figma_to_fgui.figma_selection import SelectionManifest
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
    assert by_figma["progress-bubble"].status == "hifi_added"
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
