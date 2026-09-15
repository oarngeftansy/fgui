from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from figma_to_fgui.figma_selection import SelectionManifest
from figma_to_fgui.hifi_mapping import build_mapping
from figma_to_fgui.hifi_project_inspector import (
    inspect_component,
    inspect_hifi_targets,
    target_from_option,
)
from figma_to_fgui.hifi_replacement_store import HifiReplacementStore, HifiReplacementStoreError
from figma_to_fgui.uploaded_project import index_uploaded_project

FIXTURE = Path(__file__).parents[1] / "fixtures/hifi_replacement"


def _values():
    root = FIXTURE / "old_project"
    project = index_uploaded_project(root, "old.zip")
    tree = inspect_hifi_targets(root, project)
    package = tree.packages[0]
    directory = next(item for item in package.directories if item.path == "Panel")
    component = next(item for item in directory.components if item.resource_id == "sketch01")
    target = target_from_option(project, package, directory, component)
    inventory = inspect_component(root, target)
    manifest = SelectionManifest.model_validate_json((FIXTURE / "hifi-selection.json").read_text("utf-8"))
    return target, build_mapping(inventory, manifest)


def test_store_is_idempotent_and_isolates_owner(tmp_path: Path) -> None:
    store = HifiReplacementStore(tmp_path)
    target, mapping = _values()
    selection_id = uuid.uuid4().hex
    first = store.begin("owner-a", selection_id, target, mapping, "same-request")
    second = store.begin("owner-a", selection_id, target, mapping, "same-request")
    assert first.view.session_id == second.view.session_id
    with pytest.raises(HifiReplacementStoreError, match="not_found"):
        store.get(first.view.session_id, "owner-b")


def test_new_mapping_supersedes_in_flight_candidate_without_failed_overwrite(
    tmp_path: Path,
) -> None:
    store = HifiReplacementStore(tmp_path)
    target, draft = _values()
    confirmed = draft.model_copy(update={"unresolved_count": 0})
    session = store.begin(
        "owner-a", uuid.uuid4().hex, target, confirmed, "supersede-request"
    )
    store.mark_building(
        session.view.session_id, "owner-a", confirmed.mapping_revision
    )
    revised = confirmed.model_copy(
        update={"mapping_revision": confirmed.mapping_revision + 1}
    )
    changed = store.save_mapping(
        session.view.session_id,
        "owner-a",
        confirmed.mapping_revision,
        revised,
    )
    assert changed.view.status == "mapping"
    after_old_failure = store.mark_failed(
        session.view.session_id,
        "owner-a",
        confirmed.mapping_revision,
    )
    assert after_old_failure.view.status == "mapping"
    assert after_old_failure.mapping.mapping_revision == revised.mapping_revision
