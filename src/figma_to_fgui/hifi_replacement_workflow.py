from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from figma_to_fgui.apply import apply_bundle
from figma_to_fgui.hifi_mapping import apply_mapping_decision, build_mapping
from figma_to_fgui.hifi_patch import build_hifi_change_bundle, validate_hifi_candidate
from figma_to_fgui.hifi_project_inspector import inspect_component, inspect_hifi_targets
from figma_to_fgui.hifi_replacement_models import (
    HifiMappingDecision,
    HifiTargetRef,
)
from figma_to_fgui.hifi_replacement_store import (
    HifiReplacementStore,
    HifiReplacementStoreError,
    StoredHifiReplacement,
)
from figma_to_fgui.project_package import build_project_package
from figma_to_fgui.project_store import ProjectStore
from figma_to_fgui.selection_store import SelectionStore


class HifiReplacementWorkflow:
    def __init__(
        self,
        data_dir: Path,
        project_store: ProjectStore,
        selection_store: SelectionStore,
        store: HifiReplacementStore,
    ) -> None:
        self._data_dir = data_dir
        self._projects = project_store
        self._selections = selection_store
        self._store = store

    def begin(
        self,
        owner_device_id: str,
        selection_id: str,
        target: HifiTargetRef,
        idempotency_key: str,
    ) -> StoredHifiReplacement:
        project = self._projects.get(target.project_id)
        if project.fingerprint != target.project_fingerprint:
            raise HifiReplacementStoreError("hifi_target_stale")
        root = self._projects.artifact_path(project.project_id)
        tree = inspect_hifi_targets(root, project)
        valid_target = any(
            package.package_id == target.package_id
            and package.name == target.package_name
            and directory.path == target.directory
            and component.resource_id == target.component_id
            and component.name == target.component_name
            and component.relative_path == target.component_relative_path
            and component.selectable
            for package in tree.packages
            for directory in package.directories
            for component in directory.components
        )
        if not valid_target:
            raise HifiReplacementStoreError("hifi_target_stale")
        selection = self._selections.get(selection_id, owner_device_id)
        if len(selection.manifest.top_level_nodes) != 1:
            raise HifiReplacementStoreError("hifi_selection_requires_single_root")
        inventory = inspect_component(root, target)
        mapping = build_mapping(inventory, selection.manifest)
        return self._store.begin(
            owner_device_id, selection_id, target, mapping, idempotency_key
        )

    def save_decision(
        self,
        session_id: str,
        owner_device_id: str,
        decision: HifiMappingDecision,
    ) -> StoredHifiReplacement:
        current = self._store.get(session_id, owner_device_id)
        selection = self._selections.get(current.view.selection_id, owner_device_id)
        try:
            mapping = apply_mapping_decision(current.mapping, decision, selection.manifest)
        except ValueError as error:
            code = getattr(error, "code", "invalid_mapping")
            raise HifiReplacementStoreError(code) from error
        return self._store.save_mapping(
            session_id,
            owner_device_id,
            decision.mapping_revision,
            mapping,
        )

    def build(
        self,
        session_id: str,
        owner_device_id: str,
        mapping_revision: int,
    ) -> StoredHifiReplacement:
        current = self._store.mark_building(session_id, owner_device_id, mapping_revision)
        try:
            project = self._projects.get(current.view.target.project_id)
            if project.fingerprint != current.view.target.project_fingerprint:
                raise HifiReplacementStoreError("hifi_target_stale")
            root = self._projects.artifact_path(project.project_id)
            selection = self._selections.get(current.view.selection_id, owner_device_id)
            inventory = inspect_component(root, current.view.target)
            bundle = build_hifi_change_bundle(
                root,
                inventory,
                selection.manifest,
                current.mapping,
                job_id=current.view.session_id,
                selection_root=self._selections.artifact_path(current.view.selection_id),
            )
            with tempfile.TemporaryDirectory(prefix="hifi-review-", dir=self._data_dir) as temporary:
                candidate = Path(temporary) / "candidate"
                shutil.copytree(root, candidate)
                apply_bundle(candidate, bundle)
                review = validate_hifi_candidate(
                    root,
                    candidate,
                    inventory,
                    current.mapping,
                    session_id=current.view.session_id,
                )
            package = build_project_package(
                root,
                bundle,
                "update",
                current.view.target.component_name,
                self._data_dir / "hifi-replacements" / "artifacts",
            )
            return self._store.publish_candidate(
                session_id,
                owner_device_id,
                mapping_revision,
                review,
                package.path,
                package.download_name,
                package.sha256,
            )
        except Exception:
            self._store.mark_failed(session_id, owner_device_id, mapping_revision)
            raise
