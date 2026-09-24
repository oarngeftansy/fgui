from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from figma_to_fgui.apply import apply_bundle
from figma_to_fgui.figma_selection import SelectionManifest
from figma_to_fgui.hifi_mapping import apply_mapping_decision, build_mapping
from figma_to_fgui.hifi_patch import build_hifi_change_bundle, validate_hifi_candidate
from figma_to_fgui.hifi_project_inspector import inspect_component, inspect_hifi_targets
from figma_to_fgui.hifi_replacement_models import (
    FguiComponentInventory,
    HifiMappingDecision,
    HifiTargetRef,
)
from figma_to_fgui.hifi_replacement_store import (
    HifiReplacementStore,
    HifiReplacementStoreError,
    StoredHifiReplacement,
)
from figma_to_fgui.models import Bounds
from figma_to_fgui.project_package import build_project_package
from figma_to_fgui.project_store import ProjectStore
from figma_to_fgui.psd_hifi_adapter import psd_source_manifest
from figma_to_fgui.psd_source_store import PsdSourceStore, PsdSourceStoreError
from figma_to_fgui.selection_store import SelectionStore


class HifiReplacementWorkflow:
    def __init__(
        self,
        data_dir: Path,
        project_store: ProjectStore,
        selection_store: SelectionStore,
        psd_source_store: PsdSourceStore,
        store: HifiReplacementStore,
    ) -> None:
        self._data_dir = data_dir
        self._projects = project_store
        self._selections = selection_store
        self._psd_sources = psd_source_store
        self._store = store

    def _inventory(self, target: HifiTargetRef) -> tuple[Path, FguiComponentInventory]:
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
        return root, inspect_component(root, target)

    def _manifest(
        self,
        source_id: str,
        owner_device_id: str,
        *,
        raster_layer_ids: tuple[str, ...] = (),
        inventory: FguiComponentInventory | None = None,
    ) -> tuple[SelectionManifest, Path | None, tuple[str, ...]]:
        if len(source_id) == 64:
            try:
                source = self._psd_sources.get(source_id)
            except PsdSourceStoreError as error:
                raise HifiReplacementStoreError("psd_source_unavailable") from error
            resources = self._psd_sources.raster_resources(source_id, raster_layer_ids)
            manifest = psd_source_manifest(source, raster_resources=resources)
            if inventory is not None:
                width = round(inventory.width)
                height = round(inventory.height)
                if (
                    abs(inventory.width - width) > 0.001
                    or abs(inventory.height - height) > 0.001
                    or width > source.inspection.width
                    or height > source.inspection.height
                ):
                    raise HifiReplacementStoreError("psd_viewport_dimensions_invalid")
                root = manifest.top_level_nodes[0]
                left, top, _, _ = self._psd_sources.effective_viewport_bounds(
                    source_id, width, height
                )
                manifest = manifest.model_copy(
                    update={
                        "top_level_nodes": (
                            root.model_copy(
                                update={
                                    "bounds": Bounds(
                                        x=left,
                                        y=top,
                                        width=width,
                                        height=height,
                                    )
                                }
                            ),
                        )
                    }
                )
            return (
                manifest,
                self._psd_sources.artifact_path(source_id),
                source.inspection.blocking_issues,
            )
        selection = self._selections.get(source_id, owner_device_id)
        return selection.manifest, self._selections.artifact_path(source_id), ()

    def begin(
        self,
        owner_device_id: str,
        selection_id: str,
        target: HifiTargetRef,
        idempotency_key: str,
    ) -> StoredHifiReplacement:
        _, inventory = self._inventory(target)
        selection = self._selections.get(selection_id, owner_device_id)
        if len(selection.manifest.top_level_nodes) != 1:
            raise HifiReplacementStoreError("hifi_selection_requires_single_root")
        mapping = build_mapping(inventory, selection.manifest)
        return self._store.begin(
            owner_device_id, selection_id, target, mapping, idempotency_key
        )

    def begin_psd(
        self,
        owner_device_id: str,
        source_id: str,
        target: HifiTargetRef,
        idempotency_key: str,
    ) -> StoredHifiReplacement:
        _, inventory = self._inventory(target)
        manifest, _, _ = self._manifest(source_id, owner_device_id, inventory=inventory)
        mapping = build_mapping(inventory, manifest)
        return self._store.begin(
            owner_device_id, source_id, target, mapping, idempotency_key
        )

    def save_decision(
        self,
        session_id: str,
        owner_device_id: str,
        decision: HifiMappingDecision,
    ) -> StoredHifiReplacement:
        current = self._store.get(session_id, owner_device_id)
        _, inventory = self._inventory(current.view.target)
        manifest, _, _ = self._manifest(
            current.view.selection_id,
            owner_device_id,
            inventory=inventory,
        )
        try:
            mapping = apply_mapping_decision(current.mapping, decision, manifest)
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
            inventory = inspect_component(root, current.view.target)
            raster_layer_ids: tuple[str, ...] = ()
            if len(current.view.selection_id) == 64:
                source = self._psd_sources.get(current.view.selection_id)
                rasterizable = {
                    layer.id
                    for layer in source.layers
                    if layer.kind.casefold() in {"pixel", "shape", "smartobject"}
                    and layer.bounds[2] > layer.bounds[0]
                    and layer.bounds[3] > layer.bounds[1]
                }
                raster_layer_ids = tuple(
                    sorted(
                        {
                            item.figma_node_id
                            for item in current.mapping.items
                            if item.action in {"accept", "retarget", "add_visual"}
                            and item.figma_node_id in rasterizable
                        }
                    )
                )
            manifest, source_root, blocking_issues = self._manifest(
                current.view.selection_id,
                owner_device_id,
                raster_layer_ids=raster_layer_ids,
                inventory=inventory,
            )
            bundle = build_hifi_change_bundle(
                root,
                inventory,
                manifest,
                current.mapping,
                job_id=current.view.session_id,
                selection_root=source_root,
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
                    lossless_blockers=blocking_issues,
                )
            package = build_project_package(
                root,
                bundle,
                "update",
                current.view.target.component_name,
                self._data_dir / "hifi-replacements" / "artifacts",
            )
            review = review.model_copy(update={"candidate_sha256": package.sha256})
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
