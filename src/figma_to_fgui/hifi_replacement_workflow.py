from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

from figma_to_fgui.apply import apply_bundle
from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.hifi_mapping import apply_mapping_decision, build_mapping, require_psd_coverage
from figma_to_fgui.hifi_nested import inspect_component_tree
from figma_to_fgui.hifi_patch import build_hifi_change_bundle, validate_hifi_candidate
from figma_to_fgui.hifi_project_inspector import inspect_component, inspect_hifi_targets
from figma_to_fgui.hifi_replacement_models import (
    FguiComponentInventory,
    FguiObjectRef,
    HifiMappingDecision,
    HifiMappingDraft,
    HifiTargetRef,
)
from figma_to_fgui.hifi_replacement_store import (
    HifiReplacementStore,
    HifiReplacementStoreError,
    StoredHifiReplacement,
)
from figma_to_fgui.hifi_state_visuals import derive_state_nodes
from figma_to_fgui.hifi_visual_similarity import exact_visual_similarity, static_image_path
from figma_to_fgui.project_package import build_project_package
from figma_to_fgui.project_store import ProjectStore
from figma_to_fgui.psd_hifi_adapter import (
    psd_composite_group_ids,
    psd_lossless_blockers,
    psd_source_manifest,
)
from figma_to_fgui.psd_native_graphs import read_native_graphs
from figma_to_fgui.psd_source_store import PsdSourceStore, PsdSourceStoreError
from figma_to_fgui.selection_store import SelectionStore
from figma_to_fgui.uploaded_project import index_uploaded_project


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
        owned_visuals: dict[str, tuple[str, frozenset[str], frozenset[str]]] | None = None,
        include_states: bool = False,
        inventory: FguiComponentInventory | None = None,
    ) -> tuple[SelectionManifest, Path | None, tuple[str, ...]]:
        if len(source_id) == 64:
            try:
                source = self._psd_sources.get(source_id)
            except PsdSourceStoreError as error:
                raise HifiReplacementStoreError("psd_source_unavailable") from error
            resources = self._psd_sources.raster_resources(source_id, raster_layer_ids)
            for anchor, (group, owned, retained) in (owned_visuals or {}).items():
                resources[anchor] = self._psd_sources.owned_visual_resource(
                    source_id, anchor_id=anchor, group_id=group,
                    owned_ids=owned, retained_ids=retained,
                )
            native = read_native_graphs(self._psd_sources.artifact_path(source_id) / "source.psd", source_id)
            viewport = (
                self._psd_sources.effective_viewport_bounds(
                    source_id, round(inventory.width), round(inventory.height)
                )
                if inventory is not None
                and inventory.width <= source.inspection.width
                and inventory.height <= source.inspection.height
                else None
            )
            manifest = psd_source_manifest(
                source, raster_resources=resources, native_graphs=native,
                viewport_bounds=viewport,
            )
            if include_states and inventory is not None and inventory.expanded_instances:
                try:
                    source_root = self._psd_sources.artifact_path(source_id)
                    state_nodes, state_resources = derive_state_nodes(
                        self._projects.artifact_path(inventory.target.project_id), inventory,
                        self._psd_sources.composite_path(source_id), source_root / "resources",
                        viewport_offset=(viewport[0], viewport[1]) if viewport else (0, 0),
                        style_images=tuple(source_root / "resources" / value.key
                                           for value in resources.values()
                                           if value.key.startswith("psd-owned-")),
                    )
                except (OSError, ValueError):
                    state_nodes, state_resources = (), ()
                if state_nodes:
                    frame = manifest.top_level_nodes[0]
                    manifest = manifest.model_copy(update={
                        "top_level_nodes": (frame.model_copy(update={
                            "children": (*frame.children, *state_nodes),
                        }),),
                        "resources": (*manifest.resources, *state_resources),
                    })
            return (
                manifest,
                self._psd_sources.artifact_path(source_id),
                psd_lossless_blockers(source),
            )
        selection = self._selections.get(source_id, owner_device_id)
        return selection.manifest, self._selections.artifact_path(source_id), ()

    @staticmethod
    def _owned_visuals(mapping: HifiMappingDraft) -> dict[str, tuple[str, frozenset[str], frozenset[str]]]:
        return {
            item.figma_node_id: (
                item.owned_group_id, frozenset(item.owned_source_ids),
                frozenset(item.retained_source_ids),
            )
            for item in mapping.items
            if item.figma_node_id and item.owned_group_id and item.owned_source_ids
        }

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
        root, _ = self._inventory(target)
        inventory = inspect_component_tree(root, target)
        manifest, _, _ = self._manifest(source_id, owner_device_id, inventory=inventory)
        def validate_owned(group: str, owned: frozenset[str], retained: frozenset[str]) -> bool:
            try:
                self._psd_sources.owned_visual_resource(
                    source_id, anchor_id=min(owned), group_id=group,
                    owned_ids=owned, retained_ids=retained,
                )
                return True
            except PsdSourceStoreError:
                return False

        similarity_cache: dict[tuple[str, str], float] = {}

        def graph_raster_available(node: SelectionNode) -> bool:
            try:
                return node.id in self._psd_sources.raster_resources(source_id, (node.id,))
            except (OSError, ValueError, KeyError, PsdSourceStoreError):
                return False

        def confirm_opaque_cover(node: SelectionNode) -> bool:
            try:
                raster = self._psd_sources.raster_resources(source_id, (node.id,))[node.id]
                from PIL import Image
                with Image.open(
                    self._psd_sources.artifact_path(source_id) / "resources" / raster.key
                ) as image:
                    alpha = image.convert("RGBA").getchannel("A")
                    extrema: tuple[int, int] = alpha.getextrema()  # type: ignore[assignment]
                    return extrema[0] >= 250
            except (OSError, ValueError, KeyError, PsdSourceStoreError):
                return False

        def validate_background(old: FguiObjectRef, node: SelectionNode) -> float:
            key = old.object_id, node.id
            if key not in similarity_cache:
                old_image = static_image_path(root, old)
                if old_image is None:
                    similarity_cache[key] = 0.0
                else:
                    try:
                        raster = self._psd_sources.raster_resources(source_id, (node.id,))[node.id]
                        new_image = self._psd_sources.artifact_path(source_id) / "resources" / raster.key
                        similarity_cache[key] = exact_visual_similarity(old_image, new_image)
                    except (OSError, ValueError, KeyError, PsdSourceStoreError):
                        similarity_cache[key] = 0.0
            return similarity_cache[key]

        preliminary = build_mapping(
            inventory, manifest, owned_visual_validator=validate_owned,
            occlusion_validator=confirm_opaque_cover,
            full_bleed_visual_validator=validate_background,
            graph_raster_validator=graph_raster_available,
        )
        manifest, _, _ = self._manifest(
            source_id, owner_device_id, inventory=inventory,
            owned_visuals=self._owned_visuals(preliminary), include_states=True,
        )
        mapping = build_mapping(
            inventory, manifest, owned_visual_validator=validate_owned,
            occlusion_validator=confirm_opaque_cover,
            full_bleed_visual_validator=validate_background,
            graph_raster_validator=graph_raster_available,
            proven_source_owners={item.old_object_id: item.figma_node_id
                                  for item in preliminary.items
                                  if item.old_object_id and item.figma_node_id
                                  and (item.owned_source_ids or any(
                                      item.figma_node_id in owner.retained_source_ids
                                      for owner in preliminary.items if owner.owned_source_ids))},
        )
        return self._store.begin(
            owner_device_id, source_id, target, mapping, idempotency_key
        )

    def begin_psd_batch(
        self,
        owner_device_id: str,
        source_id: str,
        targets: tuple[HifiTargetRef, ...],
        idempotency_key: str,
    ) -> tuple[StoredHifiReplacement, ...]:
        if not targets:
            raise HifiReplacementStoreError("hifi_target_invalid")
        self._psd_sources.get(source_id)
        for target in targets:
            self._inventory(target)
        key_seed = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]
        stored: list[StoredHifiReplacement] = []
        for target in targets:
            digest = hashlib.sha256(target.model_dump_json().encode("utf-8")).hexdigest()[:24]
            stored.append(self.begin_psd(owner_device_id, source_id, target, f"{key_seed}:{digest}"))
        return tuple(stored)

    def save_decision(
        self,
        session_id: str,
        owner_device_id: str,
        decision: HifiMappingDecision,
    ) -> StoredHifiReplacement:
        current = self._store.get(session_id, owner_device_id)
        if current.mapping.policy_revision != 24:
            raise HifiReplacementStoreError("hifi_mapping_policy_stale")
        root, inventory = self._inventory(current.view.target)
        if len(current.view.selection_id) == 64:
            inventory = inspect_component_tree(root, current.view.target)
        manifest, _, _ = self._manifest(
            current.view.selection_id,
            owner_device_id,
            owned_visuals=self._owned_visuals(current.mapping),
            include_states=len(current.view.selection_id) == 64,
            inventory=inventory,
        )
        try:
            mapping = apply_mapping_decision(current.mapping, decision, manifest,
                conversion_object_ids=frozenset(o.object_id for o in inventory.objects if o.raster_conversion_allowed))
        except ValueError as error:
            code = getattr(error, "code", "invalid_mapping")
            raise HifiReplacementStoreError(code) from error
        return self._store.save_mapping(
            session_id,
            owner_device_id,
            decision.mapping_revision,
            mapping,
        )

    def _psd_raster_layer_ids(
        self, current: StoredHifiReplacement, inventory: FguiComponentInventory
    ) -> tuple[str, ...]:
        if len(current.view.selection_id) != 64:
            return ()
        source = self._psd_sources.get(current.view.selection_id)
        rasterizable = {
            layer.id
            for layer in source.layers
            if layer.kind.casefold() in {"pixel", "shape", "smartobject"}
            and layer.bounds[2] > layer.bounds[0]
            and layer.bounds[3] > layer.bounds[1]
        }
        rasterizable.update(psd_composite_group_ids(source))
        return tuple(
            sorted(
                {
                    item.figma_node_id
                    for item in current.mapping.items
                    if item.action in {"accept", "retarget", "add_visual"}
                    and (item.old_object_type != "graph" or item.graph_conversion_proven
                         or any(o.object_id == item.old_object_id
                                and o.raster_conversion_allowed for o in inventory.objects))
                    and item.figma_node_id in rasterizable
                    and not item.owned_source_ids
                }
            )
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
            inventory = (inspect_component_tree(root, current.view.target) if len(current.view.selection_id) == 64
                         else inspect_component(root, current.view.target))
            raster_layer_ids = self._psd_raster_layer_ids(current, inventory)
            owned_visuals: dict[str, tuple[str, frozenset[str], frozenset[str]]] = {}
            if len(current.view.selection_id) == 64:
                owned_visuals = self._owned_visuals(current.mapping)
            manifest, source_root, blocking_issues = self._manifest(
                current.view.selection_id,
                owner_device_id,
                raster_layer_ids=raster_layer_ids,
                owned_visuals=owned_visuals,
                include_states=len(current.view.selection_id) == 64,
                inventory=inventory,
            )
            try:
                require_psd_coverage(current.mapping, manifest)
            except ValueError as error:
                raise HifiReplacementStoreError(getattr(error, "code", "invalid_mapping")) from error
            bundle = build_hifi_change_bundle(
                root,
                inventory,
                manifest,
                current.mapping,
                job_id=current.view.session_id,
                selection_root=source_root,
                parity_reference=(
                    self._psd_sources.composite_path(current.view.selection_id)
                    if len(current.view.selection_id) == 64
                    else None
                ),
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

    def deliver_overwrite(
        self,
        session_id: str,
        owner_device_id: str,
        candidate_sha256: str,
    ) -> StoredHifiReplacement:
        current = self._store.get(session_id, owner_device_id)
        if (
            current.view.status not in {"review_ready", "approved"}
            or current.artifact_sha256 is None
            or current.artifact_sha256 != candidate_sha256
        ):
            raise HifiReplacementStoreError("hifi_candidate_stale")
        project = self._projects.get(current.view.target.project_id)
        if project.fingerprint != current.view.target.project_fingerprint:
            raise HifiReplacementStoreError("hifi_target_stale")
        root = self._projects.artifact_path(project.project_id)
        inventory = (inspect_component_tree(root, current.view.target)
                     if len(current.view.selection_id) == 64
                     else inspect_component(root, current.view.target))
        raster_layer_ids = self._psd_raster_layer_ids(current, inventory)
        owned_visuals: dict[str, tuple[str, frozenset[str], frozenset[str]]] = {}
        if len(current.view.selection_id) == 64:
            owned_visuals = self._owned_visuals(current.mapping)
        manifest, source_root, blocking_issues = self._manifest(
            current.view.selection_id,
            owner_device_id,
            raster_layer_ids=raster_layer_ids,
            owned_visuals=owned_visuals,
            include_states=len(current.view.selection_id) == 64,
            inventory=inventory,
        )
        require_psd_coverage(current.mapping, manifest)
        bundle = build_hifi_change_bundle(
            root,
            inventory,
            manifest,
            current.mapping,
            job_id=current.view.session_id,
            selection_root=source_root,
            parity_reference=(
                self._psd_sources.composite_path(current.view.selection_id)
                if len(current.view.selection_id) == 64
                else None
            ),
        )
        with tempfile.TemporaryDirectory(prefix="hifi-deliver-", dir=self._data_dir) as temporary:
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
            # The approval gate already judged this candidate; re-deriving it
            # here only proves the bytes are unchanged. Byte equality with the
            # reviewed candidate is the whole overwrite safety argument, so a
            # lossless-evidence flag is not re-litigated in this path.
            if not review.protected_checks_passed:
                raise HifiReplacementStoreError("hifi_candidate_stale")
            package = build_project_package(
                root,
                bundle,
                "update",
                current.view.target.component_name,
                self._data_dir / "hifi-replacements" / "artifacts",
            )
            if package.sha256 != candidate_sha256:
                raise HifiReplacementStoreError("hifi_candidate_stale")
            version = index_uploaded_project(candidate, project.original_name)
            version = version.model_copy(update={"project_id": project.project_id})
            self._projects.replace_version(version, candidate)
        return self._store.get(session_id, owner_device_id)
