from __future__ import annotations

import hashlib
import logging
import shutil
import tempfile
from pathlib import Path

from figma_to_fgui.apply import apply_bundle
from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.hifi_mapping import apply_mapping_decision, auto_legacy_state, build_mapping, require_visual_closure, visual_closure
from figma_to_fgui.hifi_nested import inspect_component_tree
from figma_to_fgui.hifi_patch import build_hifi_change_bundle, validate_hifi_candidate
from figma_to_fgui.hifi_project_inspector import inspect_component, inspect_hifi_targets
from figma_to_fgui.hifi_removal_review import (
    HifiRemovalDecisionRequest,
    HifiRemovalReview,
    build_removal_review,
)
from figma_to_fgui.hifi_replacement_models import (
    HIFI_MAPPING_POLICY_REVISION,
    FguiComponentInventory,
    FguiObjectRef,
    HifiMappingDecision,
    HifiMappingDraft,
    HifiTargetRef,
    HifiVisualClosureReport,
)
from figma_to_fgui.hifi_replacement_store import (
    HifiReplacementStore,
    HifiReplacementStoreError,
    StoredHifiReplacement,
)
from figma_to_fgui.hifi_semantic_reskin import normalize_psd_semantic_reskin
from figma_to_fgui.hifi_state_visuals import derive_state_nodes
from figma_to_fgui.hifi_visual_similarity import exact_visual_similarity, static_image_path
from figma_to_fgui.project_package import build_project_package, remove_generated_directories
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

logger = logging.getLogger(__name__)

# Building copies the whole project and writes a candidate zip plus review
# scratch space. Refuse to start when the data volume lacks a safe margin so
# we fail closed with a clear reason instead of emitting a truncated export
# (the "C: drive full" class of silent corruption).
_MIN_BUILD_FREE_BYTES = 1024 ** 3


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
        owned_visuals: dict[
            str, tuple[str, frozenset[str], frozenset[str], bool]
        ] | None = None,
        composite_visuals: dict[str, tuple[str, frozenset[str]]] | None = None,
        include_states: bool = False,
        inventory: FguiComponentInventory | None = None,
    ) -> tuple[SelectionManifest, Path | None, tuple[str, ...]]:
        if len(source_id) == 64:
            try:
                source = self._psd_sources.get(source_id)
            except PsdSourceStoreError as error:
                raise HifiReplacementStoreError("psd_source_unavailable") from error
            resources = self._psd_sources.raster_resources(source_id, raster_layer_ids)
            backdrop = None
            for anchor, (group, overlays) in (composite_visuals or {}).items():
                resource = self._psd_sources.composited_visual_resource(
                    source_id,
                    anchor_id=anchor,
                    group_id=group,
                    overlay_ids=overlays,
                )
                resources[anchor] = resource
                if (
                    group.startswith("psd-root:")
                    and resource.bounds is not None
                    and (
                        backdrop is None
                        or (
                        (resource.bounds[2] - resource.bounds[0])
                        * (resource.bounds[3] - resource.bounds[1])
                        > (backdrop.bounds[2] - backdrop.bounds[0])
                        * (backdrop.bounds[3] - backdrop.bounds[1])
                        )
                    )
                ):
                    backdrop = resource
            for anchor, (group, owned, retained, visual_echo) in (owned_visuals or {}).items():
                resources[anchor] = self._psd_sources.owned_visual_resource(
                    source_id, anchor_id=anchor, group_id=group,
                    owned_ids=owned, retained_ids=retained, visual_echo=visual_echo,
                    underlay=backdrop if not group.startswith("psd-root:") else None,
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
            viewport_empty: set[str] = set()
            if viewport is not None:
                source_root = self._psd_sources.artifact_path(source_id)
                probe_ids = self._viewport_probe_layer_ids(source, viewport)
                for layer_id in dict.fromkeys((*raster_layer_ids, *probe_ids)):
                    resource = resources.get(layer_id)
                    if resource is None:
                        try:
                            resource = self._psd_sources.raster_resource(source_id, layer_id)
                        except PsdSourceStoreError:
                            continue
                    if (
                        resource is not None
                        and resource.bounds is not None
                        and not self._raster_intersects_viewport(
                            source_root / "resources" / resource.key,
                            resource.bounds,
                            viewport,
                        )
                    ):
                        viewport_empty.add(layer_id)
                        resources.pop(layer_id, None)
            manifest = psd_source_manifest(
                source, raster_resources=resources, native_graphs=native,
                viewport_bounds=viewport,
            )
            if viewport_empty:
                def mark_viewport_empty(node: SelectionNode) -> SelectionNode:
                    children = tuple(mark_viewport_empty(child) for child in node.children)
                    if node.id not in viewport_empty:
                        return node.model_copy(update={"children": children})
                    return node.model_copy(update={
                        "bounds": node.bounds.model_copy(update={"width": 0, "height": 0}),
                        "children": children,
                        "properties": {**node.properties, "hifiViewportEmpty": True},
                        "resource_keys": (),
                    })

                manifest = manifest.model_copy(update={
                    "top_level_nodes": tuple(
                        mark_viewport_empty(node) for node in manifest.top_level_nodes
                    ),
                })
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
    def _raster_intersects_viewport(
        raster: Path,
        bounds: tuple[int, int, int, int],
        viewport: tuple[int, int, int, int],
    ) -> bool:
        from PIL import Image

        left, top, right, bottom = bounds
        viewport_left, viewport_top, viewport_width, viewport_height = viewport
        viewport_right = viewport_left + viewport_width
        viewport_bottom = viewport_top + viewport_height
        intersection = (
            max(left, viewport_left),
            max(top, viewport_top),
            min(right, viewport_right),
            min(bottom, viewport_bottom),
        )
        if intersection[0] >= intersection[2] or intersection[1] >= intersection[3]:
            return False
        with Image.open(raster) as image:
            alpha = image.convert("RGBA").getchannel("A")
            crop = (
                intersection[0] - left,
                intersection[1] - top,
                intersection[2] - left,
                intersection[3] - top,
            )
            return alpha.crop(crop).getbbox() is not None

    @staticmethod
    def _viewport_probe_layer_ids(
        source: object,
        viewport: tuple[int, int, int, int],
    ) -> tuple[str, ...]:
        """Return full-viewport rasters whose logical bounds may hide empty alpha."""
        left, top, width, height = viewport
        right, bottom = left + width, top + height
        return tuple(
            layer.id
            for layer in source.layers  # type: ignore[attr-defined]
            if layer.kind.casefold() in {"pixel", "shape", "smartobject"}
            and layer.effective_visible
            and layer.bounds[0] <= left
            and layer.bounds[1] <= top
            and layer.bounds[2] >= right
            and layer.bounds[3] >= bottom
        )

    @staticmethod
    def _exclude_native_graph_rasters(
        raster_layer_ids: tuple[str, ...],
        native_graphs: dict[str, dict[str, object]],
    ) -> tuple[str, ...]:
        return tuple(layer_id for layer_id in raster_layer_ids if layer_id not in native_graphs)

    @staticmethod
    def _restore_source_geometry(
        manifest: SelectionManifest,
        source_geometry: SelectionManifest,
    ) -> SelectionManifest:
        """Keep generated resources/states without remapping from their cropped bounds."""
        original: dict[str, object] = {}

        def remember(node: SelectionNode) -> None:
            original[node.id] = node.bounds
            for child in node.children:
                remember(child)

        for root in source_geometry.top_level_nodes:
            remember(root)

        def restore(node: SelectionNode) -> SelectionNode:
            children = tuple(restore(child) for child in node.children)
            updates: dict[str, object] = {"children": children}
            if node.id in original:
                updates["bounds"] = original[node.id]
            return node.model_copy(update=updates)

        return manifest.model_copy(update={
            "top_level_nodes": tuple(restore(root) for root in manifest.top_level_nodes),
        })

    @staticmethod
    def _owned_visuals(
        mapping: HifiMappingDraft,
    ) -> dict[str, tuple[str, frozenset[str], frozenset[str], bool]]:
        return {
            item.figma_node_id: (
                item.owned_group_id, frozenset(item.owned_source_ids),
                frozenset(item.retained_source_ids), item.visual_echo,
            )
            for item in mapping.items
            if (
                item.figma_node_id
                and item.owned_group_id
                and item.owned_source_ids
            )
        }

    @staticmethod
    def _composite_visuals(
        mapping: HifiMappingDraft,
    ) -> dict[str, tuple[str, frozenset[str]]]:
        return {
            item.figma_node_id: (
                item.composite_group_id,
                frozenset(item.composite_source_ids),
            )
            for item in mapping.items
            if item.figma_node_id and item.composite_group_id and item.composite_source_ids
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
        source_geometry = manifest
        def validate_owned(group: str, owned: frozenset[str], retained: frozenset[str]) -> bool:
            try:
                if group.startswith("psd-root:"):
                    retained = self._psd_sources.root_retained_layer_ids(source_id, owned)
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
                if node.children or node.properties.get("fguiGraph") is None:
                    # Only native PSD vector geometry can re-skin a GGraph;
                    # raster leaves are forbidden display-type changes.
                    return False
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
        preliminary = normalize_psd_semantic_reskin(
            inventory,
            manifest,
            preliminary,
            owned_visual_validator=validate_owned,
        )
        manifest, _, _ = self._manifest(
            source_id, owner_device_id, inventory=inventory,
            owned_visuals=self._owned_visuals(preliminary),
            composite_visuals=self._composite_visuals(preliminary),
            include_states=True,
        )
        mapping_manifest = self._restore_source_geometry(manifest, source_geometry)
        proven_owners = {
            item.old_object_id: item.figma_node_id
            for item in preliminary.items
            if item.old_object_id
            and item.figma_node_id
            and item.action == "accept"
        }
        mapping = build_mapping(
            inventory, mapping_manifest, owned_visual_validator=validate_owned,
            occlusion_validator=confirm_opaque_cover,
            full_bleed_visual_validator=validate_background,
            graph_raster_validator=graph_raster_available,
            # The second pass adds generated controller states and cropped
            # resources. Those additions must not dislodge any correspondence
            # already accepted from the original PSD geometry; otherwise a
            # real PSD leaf reappears as "hifi_added" and the old object keeps
            # its obsolete visual. Preserve every accepted first-pass owner,
            # not only owned/composite bundle anchors.
            proven_source_owners=proven_owners,
        )
        mapping = normalize_psd_semantic_reskin(
            inventory,
            mapping_manifest,
            mapping,
            owned_visual_validator=validate_owned,
            proven_pairs=frozenset(proven_owners.items()),
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
        if current.mapping.policy_revision != HIFI_MAPPING_POLICY_REVISION:
            raise HifiReplacementStoreError("hifi_mapping_policy_stale")
        root, inventory = self._inventory(current.view.target)
        if len(current.view.selection_id) == 64:
            inventory = inspect_component_tree(root, current.view.target)
        owned_visuals = dict(self._owned_visuals(current.mapping))
        if decision.action == "retarget" and (decision.figma_node_id or "").startswith(
            "psd-layer:"
        ):
            # A pinned human pair must exist in the decision manifest. Vector
            # masked shape leaves have no single-layer raster, so the pin is
            # materialised through the owned-bundle renderer instead.
            source = self._psd_sources.get(current.view.selection_id)
            by_id = {layer.id: layer for layer in source.layers}
            cursor = by_id.get(decision.figma_node_id)
            while (
                cursor is not None
                and cursor.kind != "group"
                and cursor.parent_id
            ):
                cursor = by_id.get(cursor.parent_id)
            if cursor is not None and cursor.kind == "group":
                pending = [cursor.id]
                leaf_ids: set[str] = set()
                while pending:
                    parent = pending.pop()
                    for layer in source.layers:
                        if layer.parent_id == parent:
                            if layer.kind == "group":
                                pending.append(layer.id)
                            elif layer.visible:
                                leaf_ids.add(layer.id)
                owned_visuals[decision.figma_node_id] = (
                    cursor.id,
                    frozenset({decision.figma_node_id}),
                    frozenset(leaf_ids - {decision.figma_node_id}),
                    False,
                )
        manifest, _, _ = self._manifest(
            current.view.selection_id,
            owner_device_id,
            owned_visuals=owned_visuals,
            composite_visuals=self._composite_visuals(current.mapping),
            include_states=len(current.view.selection_id) == 64,
            inventory=inventory,
        )
        selected_item = next(
            (item for item in current.mapping.items if item.item_id == decision.item_id),
            None,
        )
        try:
            if decision.action == "keep_old" and decision.visual_disposition is not None:
                # Human visual alignment authority: a kept object may stop
                # contributing its legacy pixels to the PSD target state while
                # keeping identity, gears and relations for runtime code.
                if selected_item is None or selected_item.action != "keep_old":
                    raise HifiReplacementStoreError(
                        "hifi_visual_disposition_requires_keep_old"
                    )
                mapping = current.mapping.model_copy(update={
                    "items": tuple(
                        item.model_copy(
                            update={"visual_disposition": decision.visual_disposition}
                        )
                        if item.item_id == decision.item_id
                        else item
                        for item in current.mapping.items
                    ),
                    "mapping_revision": current.mapping.mapping_revision + 1,
                })
            # ``keep_old`` is a runtime-identity decision. the current mapping policy may have
            # already classified the object's target-state pixels as retired
            # (or as another-state/structural). Re-confirming keep_old in the
            # review UI must not turn that policy result back into visible
            # legacy paint.
            elif (
                selected_item is not None
                and decision.action == "keep_old"
                and selected_item.action == "keep_old"
                and selected_item.visual_disposition != "preserve"
            ):
                mapping = current.mapping.model_copy(update={
                    "mapping_revision": current.mapping.mapping_revision + 1,
                })
            else:
                mapping = apply_mapping_decision(current.mapping, decision, manifest,
                    conversion_object_ids=self._conversion_object_ids(
                        current.view.selection_id, inventory))
        except ValueError as error:
            code = getattr(error, "code", "invalid_mapping")
            raise HifiReplacementStoreError(code) from error
        if decision.action == "retarget":
            # A pinned human pair is ownership evidence: re-run the Policy 27
            # allocator so bundle hosts and dispositions respect it.
            mapping = normalize_psd_semantic_reskin(
                inventory,
                manifest,
                mapping,
                owned_visual_validator=self._owned_visual_validator(
                    current.view.selection_id
                ),
                renormalize=True,
            )
        return self._store.save_mapping(
            session_id,
            owner_device_id,
            decision.mapping_revision,
            mapping,
        )

    def _conversion_object_ids(
        self, selection_id: str, inventory: FguiComponentInventory
    ) -> frozenset[str]:
        """Type-conversion grants apply only to the Figma flow.

        A PSD reskin never changes display types, so a granted graph must
        not become convertible here; otherwise the mapping could accept
        pairs the PSD patcher unconditionally rejects at build time.
        """
        if len(selection_id) == 64:
            return frozenset()
        return frozenset(
            o.object_id for o in inventory.objects if o.raster_conversion_allowed
        )

    def auto_resolve(
        self, session_id: str, owner_device_id: str
    ) -> StoredHifiReplacement:
        """Decide every pending item that has an unambiguous machine answer.

        A PSD reskin only admits two automatic decisions: accept the
        best-ranked candidate for a suggested/uncertain pairing, and keep the
        old object when the PSD did not draw it. Everything else (extra PSD
        visuals, type-incompatible pairings, blocked items) is left pending
        for a human or a PSD fix; the build gate stays fail-closed.
        """
        current = self._store.get(session_id, owner_device_id)
        if current.view.status != "mapping":
            raise HifiReplacementStoreError("hifi_candidate_stale")
        if current.mapping.policy_revision != HIFI_MAPPING_POLICY_REVISION:
            raise HifiReplacementStoreError("hifi_mapping_policy_stale")
        root, inventory = self._inventory(current.view.target)
        if len(current.view.selection_id) == 64:
            inventory = inspect_component_tree(root, current.view.target)
        manifest, _, _ = self._manifest(
            current.view.selection_id,
            owner_device_id,
            owned_visuals=dict(self._owned_visuals(current.mapping)),
            composite_visuals=self._composite_visuals(current.mapping),
            include_states=len(current.view.selection_id) == 64,
            inventory=inventory,
        )
        conversion_object_ids = self._conversion_object_ids(
            current.view.selection_id, inventory
        )
        mapping = current.mapping
        resolved = 0
        for item in tuple(current.mapping.items):
            if item.action is not None:
                continue
            if item.status in {"suggested", "uncertain"} and item.figma_node_id:
                action = "accept"
            elif item.status == "fgui_only" and item.old_object_id:
                action = "keep_old"
            else:
                continue
            try:
                mapping = apply_mapping_decision(
                    mapping,
                    HifiMappingDecision(
                        version=1,
                        mapping_revision=mapping.mapping_revision,
                        item_id=item.item_id,
                        action=action,
                    ),
                    manifest,
                    conversion_object_ids=conversion_object_ids,
                )
                resolved += 1
            except ValueError:
                continue
        logger.info(
            "auto-resolved HIFI mapping session=%s decided=%s", session_id, resolved
        )
        return self._store.save_mapping(
            session_id,
            owner_device_id,
            current.mapping.mapping_revision,
            mapping,
        )

    def _owned_visual_validator(self, source_id: str):
        def validate_owned(group: str, owned: frozenset[str], retained: frozenset[str]) -> bool:
            try:
                if group.startswith("psd-root:"):
                    retained = self._psd_sources.root_retained_layer_ids(source_id, owned)
                self._psd_sources.owned_visual_resource(
                    source_id, anchor_id=min(owned), group_id=group,
                    owned_ids=owned, retained_ids=retained,
                )
                return True
            except PsdSourceStoreError:
                return False
        return validate_owned

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
        raster_layer_ids = tuple(
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
        native_graphs = read_native_graphs(
            self._psd_sources.artifact_path(current.view.selection_id) / "source.psd",
            current.view.selection_id,
        )
        graph_native = {
            layer_id: native_graphs[layer_id]
            for item in current.mapping.items
            for layer_id in (item.figma_node_id,)
            if item.old_object_type == "graph"
            and layer_id is not None
            and layer_id in native_graphs
        }
        return self._exclude_native_graph_rasters(raster_layer_ids, graph_native)

    def fidelity_report(
        self, session_id: str, owner_device_id: str
    ) -> dict[str, object]:
        """Per-owned-bundle fidelity of the baked skins vs the designer effect image."""
        from PIL import Image

        from figma_to_fgui.psd_source_store import fidelity_metrics

        current = self._store.get(session_id, owner_device_id)
        source_id = current.view.selection_id
        if len(source_id) != 64:
            raise HifiReplacementStoreError("hifi_review_unavailable")
        manifest = self._psd_sources.design_assets(source_id) or {}
        effect = manifest.get("effect_image")
        owned_visuals = self._owned_visuals(current.mapping)
        backdrop = None
        try:
            for anchor, (group, overlays) in self._composite_visuals(current.mapping).items():
                resource = self._psd_sources.composited_visual_resource(
                    source_id, anchor_id=anchor, group_id=group, overlay_ids=overlays,
                )
                if (
                    group.startswith("psd-root:")
                    and resource.bounds is not None
                    and (
                        backdrop is None
                        or (
                            (resource.bounds[2] - resource.bounds[0])
                            * (resource.bounds[3] - resource.bounds[1])
                            > (backdrop.bounds[2] - backdrop.bounds[0])
                            * (backdrop.bounds[3] - backdrop.bounds[1])
                        )
                    )
                ):
                    backdrop = resource
        except PsdSourceStoreError:
            backdrop = None
        units: list[dict[str, object]] = []
        for anchor in sorted(owned_visuals):
            group, owned, retained, echo = owned_visuals[anchor]
            entry: dict[str, object] = {
                "anchor_id": anchor,
                "group_id": group,
                "resource_key": None,
                "bounds": None,
                "provenance": None,
                "mean_diff": None,
                "coverage_iou": None,
                "pass": None,
            }
            try:
                resource = self._psd_sources.owned_visual_resource(
                    source_id, anchor_id=anchor, group_id=group,
                    owned_ids=owned, retained_ids=retained, visual_echo=echo,
                    underlay=backdrop if not group.startswith("psd-root:") else None,
                )
            except PsdSourceStoreError:
                logger.exception(
                    "fidelity: owned_visual_resource failed anchor=%s group=%s",
                    anchor, group,
                )
                units.append(entry)
                continue
            entry["resource_key"] = resource.key
            entry["bounds"] = list(resource.bounds) if resource.bounds is not None else None
            metadata = self._psd_sources.resource_metadata(source_id, resource.key)
            entry["provenance"] = metadata.get("provenance", "engine")
            if effect and resource.bounds is not None:
                try:
                    crop = self._psd_sources.effect_crop_path(source_id, resource.bounds)
                    with Image.open(crop) as truth, Image.open(
                        self._psd_sources.resource_path(source_id, resource.key)
                    ) as rendered:
                        entry.update(
                            fidelity_metrics(rendered.convert("RGBA"), truth.convert("RGB"))
                        )
                except (PsdSourceStoreError, OSError, ValueError, KeyError):
                    logger.warning(
                        "fidelity: effect comparison unavailable anchor=%s group=%s",
                        anchor, group, exc_info=True,
                    )
            units.append(entry)
        passed = sum(1 for unit in units if unit.get("pass") is True)
        logger.info(
            "fidelity report session=%s units=%d passed=%d effect_linked=%s",
            session_id, len(units), passed, bool(effect),
        )
        return {
            "session_id": session_id,
            "source_id": source_id,
            "design_assets_linked": bool(manifest),
            "effect_image": Path(effect).name if effect else None,
            "cutout_count": len(manifest.get("cutouts", [])),
            "units": units,
            "summary": {"total": len(units), "passed": passed},
        }

    def build(
        self,
        session_id: str,
        owner_device_id: str,
        mapping_revision: int,
    ) -> StoredHifiReplacement:
        logger.info(
            "building HIFI candidate session=%s revision=%s", session_id, mapping_revision
        )
        try:
            free_bytes = shutil.disk_usage(self._data_dir).free
        except OSError:
            free_bytes = None
        if free_bytes is not None and free_bytes < _MIN_BUILD_FREE_BYTES:
            logger.error(
                "insufficient disk space to build: %d bytes free on %s",
                free_bytes, self._data_dir,
            )
            raise HifiReplacementStoreError("insufficient_disk_space")
        current = self._store.mark_building(session_id, owner_device_id, mapping_revision)
        try:
            project = self._projects.get(current.view.target.project_id)
            if project.fingerprint != current.view.target.project_fingerprint:
                raise HifiReplacementStoreError("hifi_target_stale")
            root = self._projects.artifact_path(project.project_id)
            inventory = (inspect_component_tree(root, current.view.target) if len(current.view.selection_id) == 64
                         else inspect_component(root, current.view.target))
            raster_layer_ids = self._psd_raster_layer_ids(current, inventory)
            owned_visuals: dict[
                str, tuple[str, frozenset[str], frozenset[str], bool]
            ] = {}
            if len(current.view.selection_id) == 64:
                owned_visuals = self._owned_visuals(current.mapping)
            composite_visuals = (
                self._composite_visuals(current.mapping)
                if len(current.view.selection_id) == 64
                else {}
            )
            manifest, source_root, blocking_issues = self._manifest(
                current.view.selection_id,
                owner_device_id,
                raster_layer_ids=raster_layer_ids,
                owned_visuals=owned_visuals,
                composite_visuals=composite_visuals,
                include_states=len(current.view.selection_id) == 64,
                inventory=inventory,
            )
            try:
                closure = require_visual_closure(current.mapping, manifest)
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
                lossless_notes: tuple[str, ...] = ()
                if len(current.view.selection_id) == 64:
                    blocking_issues, lossless_notes = self._lossless_evidence(
                        current.view.selection_id,
                        manifest,
                        current.mapping,
                        candidate,
                        blocking_issues,
                        current.view.target.component_relative_path,
                    )
                review = validate_hifi_candidate(
                    root,
                    candidate,
                    inventory,
                    current.mapping,
                    session_id=current.view.session_id,
                    lossless_blockers=blocking_issues,
                    lossless_notes=lossless_notes,
                )
            package = build_project_package(
                root,
                bundle,
                "update",
                current.view.target.component_name,
                self._data_dir / "hifi-replacements" / "artifacts",
            )
            updates: dict[str, object] = {"candidate_sha256": package.sha256}
            if len(current.view.selection_id) == 64:
                updates["warnings"] = (
                    *review.warnings,
                    "Policy 28 双向 Visual Closure：PSD "
                    f"{closure.psd_explained}/{closure.psd_required}，Legacy 目标态 "
                    f"{closure.legacy_settled}/{closure.legacy_required}，均 100% 闭合。",
                )
            review = review.model_copy(update=updates)
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

    def closure_report(
        self, session_id: str, owner_device_id: str
    ) -> HifiVisualClosureReport:
        """Policy 28 §14: on-demand bidirectional closure for the UI gate."""
        current = self._store.get(session_id, owner_device_id)
        project = self._projects.get(current.view.target.project_id)
        if project.fingerprint != current.view.target.project_fingerprint:
            raise HifiReplacementStoreError("hifi_target_stale")
        root = self._projects.artifact_path(project.project_id)
        inventory = (inspect_component_tree(root, current.view.target)
                     if len(current.view.selection_id) == 64
                     else inspect_component(root, current.view.target))
        raster_layer_ids = self._psd_raster_layer_ids(current, inventory)
        owned_visuals = (
            self._owned_visuals(current.mapping)
            if len(current.view.selection_id) == 64
            else {}
        )
        composite_visuals = (
            self._composite_visuals(current.mapping)
            if len(current.view.selection_id) == 64
            else {}
        )
        manifest, _source_root, _blocking = self._manifest(
            current.view.selection_id,
            owner_device_id,
            raster_layer_ids=raster_layer_ids,
            owned_visuals=owned_visuals,
            composite_visuals=composite_visuals,
            include_states=len(current.view.selection_id) == 64,
            inventory=inventory,
        )
        return visual_closure(current.mapping, manifest)

    def removal_review(
        self, session_id: str, owner_device_id: str
    ) -> HifiRemovalReview:
        """Policy 28 §9/§10: the Legacy Removal Review for this session."""
        current = self._store.get(session_id, owner_device_id)
        root, inventory = self._inventory(current.view.target)
        if len(current.view.selection_id) == 64:
            inventory = inspect_component_tree(root, current.view.target)
        return build_removal_review(current.mapping, inventory)

    def decide_removal(
        self,
        session_id: str,
        owner_device_id: str,
        request: HifiRemovalDecisionRequest,
    ) -> StoredHifiReplacement:
        """Apply user decisions for every user-facing group plus the recorded
        recommendations for overflow groups (§10) in a single revision."""
        current = self._store.get(session_id, owner_device_id)
        if current.mapping.policy_revision != HIFI_MAPPING_POLICY_REVISION:
            raise HifiReplacementStoreError("hifi_mapping_policy_stale")
        if current.mapping.mapping_revision != request.mapping_revision:
            raise HifiReplacementStoreError("stale_mapping")
        root, inventory = self._inventory(current.view.target)
        if len(current.view.selection_id) == 64:
            inventory = inspect_component_tree(root, current.view.target)
        review = build_removal_review(current.mapping, inventory)
        if not review.pending:
            raise HifiReplacementStoreError("hifi_removal_review_empty")
        chosen = {
            decision.group_id: decision.decision for decision in request.decisions
        }
        if set(chosen) != {group.group_id for group in review.groups}:
            raise HifiReplacementStoreError("hifi_removal_decision_incomplete")
        manifest, _, _ = self._manifest(
            current.view.selection_id,
            owner_device_id,
            owned_visuals=dict(self._owned_visuals(current.mapping)),
            composite_visuals=self._composite_visuals(current.mapping),
            include_states=len(current.view.selection_id) == 64,
            inventory=inventory,
        )
        mapping = current.mapping
        try:
            for group in (*review.groups, *review.auto_resolved_groups):
                outcome = chosen.get(group.group_id) or group.recommendation
                for member in group.objects:
                    mapping = apply_mapping_decision(
                        mapping,
                        HifiMappingDecision(
                            version=1,
                            mapping_revision=mapping.mapping_revision,
                            item_id=member.item_id,
                            action="remove_old" if outcome == "remove" else "keep_old",
                            visual_disposition=(
                                None if outcome == "remove" else "retire"
                            ),
                        ),
                        manifest,
                    )
        except ValueError as error:
            raise HifiReplacementStoreError(
                getattr(error, "code", "invalid_mapping")
            ) from error
        return self._store.save_mapping(
            session_id, owner_device_id, request.mapping_revision, mapping
        )

    def _text_style_residuals(
        self,
        manifest,
        mapping,
        candidate: Path,
        target_relative_path: str,
        package_ids: dict,
        resources: dict,
    ) -> list[str]:
        """Re-derive PSD text styles and diff them against candidate fields."""
        from lxml import etree

        from figma_to_fgui.hifi_patch import _apply_psd_text_style

        nodes = {}
        pending = list(manifest.top_level_nodes)
        while pending:
            node = pending.pop()
            nodes[node.id] = node
            pending.extend(node.children)
        elements: dict[str, object] = {}
        seen: set[Path] = set()
        stack: list[tuple[Path, tuple[str, ...]]] = [
            (candidate / target_relative_path, ())
        ]
        while stack:
            xml_path, prefix = stack.pop()
            resolved = xml_path.resolve()
            if resolved in seen or not xml_path.is_file():
                continue
            seen.add(resolved)
            doc = etree.parse(str(xml_path))
            for element in doc.xpath("./displayList/*[@id]"):
                qualified = ":".join((*prefix, str(element.get("id"))))
                elements[qualified] = element
                if element.tag == "component":
                    file_name = element.get("fileName") or ""
                    local_package = element.get("pkg") or next(
                        (
                            pid
                            for pth, pid in package_ids.items()
                            if xml_path.parent.resolve().is_relative_to(pth)
                        ),
                        "",
                    )
                    if "__hifi_" in Path(file_name).stem:
                        child = resources.get(
                            (local_package, str(element.get("src") or ""))
                        )
                    else:
                        child = resources.get(
                            (local_package, str(element.get("src") or ""))
                        )
                    if child is not None:
                        stack.append((child, (*prefix, str(element.get("id")))))
        style_keys = (
            "fontSize",
            "leading",
            "letterSpacing",
            "align",
            "bold",
            "italic",
            "color",
            "strokeColor",
            "strokeSize",
        )
        residual: list[str] = []
        checked = 0
        for item in mapping.items:
            if item.action not in {"accept", "retarget"} or not item.old_object_id:
                continue
            node = nodes.get(item.figma_node_id or "")
            style = (node.style.get("psdTextStyle") if node else None)
            if not isinstance(style, dict):
                continue
            element = elements.get(item.old_object_id)
            if element is None or element.tag not in {"text", "richtext"}:
                continue
            checked += 1
            bare = etree.Element("text")
            _apply_psd_text_style(bare, node, {})
            diffs = []
            for key in style_keys:
                expected = bare.attrib.get(key)
                actual = element.attrib.get(key)
                if expected is None:
                    if actual is not None and key in {
                        "bold",
                        "italic",
                        "strokeColor",
                        "strokeSize",
                    }:
                        diffs.append(f"{key}={actual}(legacy)")
                    continue
                if actual != expected:
                    diffs.append(f"{key}:{actual}!={expected}")
            if diffs:
                residual.append(f"{item.old_object_id}[{','.join(diffs)}]")
        if checked == 0:
            return ["no_mapped_text_objects"]
        return residual

    def _lossless_evidence(
        self,
        selection_id: str,
        manifest,
        mapping,
        candidate: Path,
        blocking_issues: tuple[str, ...],
        target_relative_path: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        try:
            return self._lossless_evidence_impl(
                selection_id,
                manifest,
                mapping,
                candidate,
                blocking_issues,
                target_relative_path,
            )
        except Exception as error:
            return blocking_issues, (
                f"PSD 无损证据探针异常（不影响候选，保守保留人工闸门）："
                f"{type(error).__name__}: {error}",
            )

    def _lossless_evidence_impl(
        self,
        selection_id: str,
        manifest,
        mapping,
        candidate: Path,
        blocking_issues: tuple[str, ...],
        target_relative_path: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Machine-verify PSD lossless equivalence per bundle raster."""
        from lxml import etree

        from PIL import Image

        from figma_to_fgui.psd_lossless_evidence import (
            BundleRasterProbe,
            probe_lossless_evidence,
        )

        source = self._psd_sources.get(selection_id)
        nodes = {}
        pending = list(manifest.top_level_nodes)
        while pending:
            node = pending.pop()
            nodes[node.id] = node
            pending.extend(node.children)
        viewport = manifest.top_level_nodes[0].properties.get("psdViewportBounds")
        viewport_offset = (viewport[0], viewport[1]) if viewport else (0, 0)
        groups: dict[str, tuple[str, ...]] = {}
        for item in mapping.items:
            group_id = item.owned_group_id or item.composite_group_id
            if not group_id:
                continue
            leaves = tuple(item.owned_source_ids or ()) + tuple(
                item.composite_source_ids or ()
            )
            if leaves:
                groups[group_id] = leaves
        order = {layer.id: index for index, layer in enumerate(source.layers)}
        package_ids: dict[Path, str] = {}
        resources: dict[tuple[str, str], Path] = {}
        for manifest_path in sorted(candidate.glob("assets/*/package.xml")):
            package = etree.parse(str(manifest_path))
            package_id = str(package.getroot().get("id", ""))
            package_ids[manifest_path.parent.resolve()] = package_id
            for res in package.getroot().xpath("./resources/*[@id][@name][@path]"):
                relative = Path(str(res.get("path", "/")).strip("/")) / str(
                    res.get("name")
                )
                resources[(package_id, str(res.get("id")))] = manifest_path.parent / relative
        probes: list[BundleRasterProbe] = []
        seen: set[Path] = set()
        stack: list[tuple[Path, tuple[float, float], tuple[str, ...]]] = [
            (candidate / target_relative_path, (0.0, 0.0), ())
        ]
        while stack:
            xml_path, origin, prefix = stack.pop()
            resolved = xml_path.resolve()
            if resolved in seen or not xml_path.is_file():
                continue
            seen.add(resolved)
            doc = etree.parse(str(xml_path))
            for element in doc.xpath("./displayList/*[@id]"):
                if element.tag != "component":
                    continue
                local_id = str(element.get("id"))
                qualified = (*prefix, local_id)
                xy = str(element.get("xy") or "0,0").split(",")
                child_origin = (origin[0] + float(xy[0]), origin[1] + float(xy[1]))
                file_name = element.get("fileName") or ""
                local_package = element.get("pkg") or next(
                    (
                        pid
                        for pth, pid in package_ids.items()
                        if xml_path.parent.resolve().is_relative_to(pth)
                    ),
                    "",
                )
                if "__hifi_" in Path(file_name).stem:
                    resolved_variant = resources.get((local_package, str(element.get("src") or "")))
                    if resolved_variant is None or not resolved_variant.is_file():
                        continue
                    variant_path = resolved_variant.resolve()
                    variant_doc = etree.parse(str(variant_path))
                    qualified_id = ":".join(qualified)
                    group_id = next(
                        (
                            item.owned_group_id or item.composite_group_id
                            for item in mapping.items
                            if (
                                item.old_object_id == qualified_id
                                or (item.old_object_id or "").startswith(
                                    qualified_id + ":"
                                )
                            )
                            and (item.owned_group_id or item.composite_group_id)
                        ),
                        None,
                    )
                    if group_id is not None and group_id in groups:
                        raster_elements = variant_doc.xpath(
                            "./displayList/image[@src] | ./displayList/loader[@url]"
                        )
                        for image in raster_elements:
                            img_pkg = image.get("pkg") or next(
                                (
                                    pid
                                    for pth, pid in package_ids.items()
                                    if variant_path.parent.is_relative_to(pth)
                                ),
                                "",
                            )
                            if image.tag == "loader":
                                url = str(image.get("url") or "")
                                if not url.startswith("ui://"):
                                    continue
                                payload = url[5:]
                                resolved_raster = next(
                                    (
                                        p
                                        for (pid, rid), p in resources.items()
                                        if payload == pid + rid
                                    ),
                                    None,
                                )
                            else:
                                resolved_raster = resources.get(
                                    (img_pkg, str(image.get("src") or ""))
                                )
                            if (
                                resolved_raster is None
                                or not resolved_raster.is_file()
                                or "/Img/HIFI/" not in resolved_raster.resolve().as_posix()
                            ):
                                continue
                            raster_file = resolved_raster.resolve()
                            img_xy = str(image.get("xy") or "0,0").split(",")
                            raster_origin = (
                                int(round(child_origin[0] + float(img_xy[0]) + viewport_offset[0])),
                                int(round(child_origin[1] + float(img_xy[1]) + viewport_offset[1])),
                            )
                            with Image.open(raster_file) as handle:
                                raster = handle.convert("RGBA").copy()
                            leaves = tuple(
                                sorted(groups[group_id], key=lambda lid: order.get(lid, 0))
                            )
                            extra_exclude = tuple(
                                (
                                    int(child.bounds.x),
                                    int(child.bounds.y),
                                    int(child.bounds.x + child.bounds.width),
                                    int(child.bounds.y + child.bounds.height),
                                )
                                for child in nodes[group_id].children
                                if child.id not in groups[group_id]
                            )
                            gbounds = nodes[group_id].bounds
                            probes.append(
                                BundleRasterProbe(
                                    (
                                        int(gbounds.x),
                                        int(gbounds.y),
                                        int(gbounds.x + gbounds.width),
                                        int(gbounds.y + gbounds.height),
                                    ),
                                    raster,
                                    leaves,
                                    raster_origin,
                                    group_id,
                                    extra_exclude,
                                )
                            )
                    stack.append((variant_path, child_origin, qualified))
                    continue
                package_id = element.get("pkg") or next(
                    (
                        pid
                        for pth, pid in package_ids.items()
                        if xml_path.parent.resolve().is_relative_to(pth)
                    ),
                    "",
                )
                child_path = resources.get((package_id, str(element.get("src") or "")))
                if child_path is not None:
                    stack.append((child_path, child_origin, qualified))
        seen_groups: set[str] = set()
        unique_probes: list = []
        for probe in probes:
            if probe.group_bounds in seen_groups:
                continue
            seen_groups.add(probe.group_bounds)
            unique_probes.append(probe)
        probes = unique_probes
        if not probes:
            return blocking_issues, ("PSD 无损证据探针诊断：未匹配到 bundle 栅格。",)
        composite_proven = True
        composite_stats: list[str] = []

        def loader(layer_id: str):
            try:
                resource = self._psd_sources.raster_resource(selection_id, layer_id)
            except Exception:
                return None
            path = self._psd_sources.resource_path(selection_id, resource.key)
            return path if path.is_file() else None

        from figma_to_fgui.psd_lossless_evidence import (
            probe_bundle_against_composite,
        )

        layer_by_id = {layer.id: layer for layer in source.layers}
        for probe in probes:
            reference = Image.new("RGBA", probe.raster.size, (0, 0, 0, 0))
            ok_ref = True
            for leaf in probe.leaf_ids:
                layer = layer_by_id.get(leaf)
                if layer is None:
                    continue
                leaf_path = loader(leaf)
                if leaf_path is None:
                    ok_ref = False
                    break
                with Image.open(leaf_path) as leaf_file:
                    leaf_image = leaf_file.convert("RGBA")
                dx = layer.bounds[0] - probe.origin[0]
                dy = layer.bounds[1] - probe.origin[1]
                sx = max(0, -dx)
                sy = max(0, -dy)
                if sx >= leaf_image.size[0] or sy >= leaf_image.size[1]:
                    continue
                leaf_image = leaf_image.crop(
                    (sx, sy, leaf_image.size[0], leaf_image.size[1])
                )
                reference.alpha_composite(leaf_image, dest=(max(0, dx), max(0, dy)))
            if not ok_ref:
                composite_proven = False
                composite_stats.append(f"{probe.group_id}:no_leaf_export")
                continue
            exclude_boxes = tuple(
                layer_by_id[leaf].bounds
                for leaf in probe.leaf_ids
                if leaf in layer_by_id
                and (
                    layer_by_id[leaf].has_effects
                    or layer_by_id[leaf].kind == "smartobject"
                    or layer_by_id[leaf].opacity != 255
                )
            )
            proven, mean, worst = probe_bundle_against_composite(
                probe.raster,
                probe.origin,
                reference,
                probe.origin,
                exclude_boxes=exclude_boxes,
            )
            composite_stats.append(
                f"{probe.raster.size[0]}x{probe.raster.size[1]}:mean{mean:.3f}/max{worst}"
            )
            if not proven:
                composite_proven = False
        evidence = probe_lossless_evidence(
            layers=source.layers,
            bundles=probes,
            document_size=(source.inspection.width, source.inspection.height),
            raster_resource=loader,
        )
        notes: list[str] = []
        cleared = set(evidence.cleared_codes(blocking_issues, False))
        if composite_proven:
            cleared.add("pixel_layers_require_equivalence_check")
        text_residual = self._text_style_residuals(
            manifest, mapping, candidate, target_relative_path, package_ids, resources
        )
        if "text_styles_require_equivalence_check" in blocking_issues:
            if text_residual:
                notes.append(
                    "PSD 无损证据残留人工核验：text_styles: " + "; ".join(text_residual[:6])
                )
            else:
                cleared.add("text_styles_require_equivalence_check")
                notes.append(
                    "PSD 无损证据已机器核验：text_styles 全部映射文本对象参数与 PSD 文字样式逐字段等价。"
                )
        cleared = {code for code in cleared if code in blocking_issues}
        unused_by_class = dict(evidence.unused_by_class)
        for code in blocking_issues:
            if code == "text_styles_require_equivalence_check":
                continue
            if code in cleared:
                proven = [r for r in evidence.records if r.code == code and r.proven]
                if code == "outside_canvas_content_requires_equivalence_check":
                    notes.append(
                        "PSD 无损证据已机器核验：outside_canvas（"
                        + evidence.outside_reason
                        + "）。"
                    )
                elif composite_proven and code == "pixel_layers_require_equivalence_check":
                    notes.append(
                        f"PSD 无损证据已机器核验：{code} 全部 bundle 栅格与 psd-tools 独立合成图在"
                        f"排除效果/智能对象/半透明区域后的不透明核心逐点比对通过（"
                        + "; ".join(composite_stats)
                        + "）。"
                    )
                else:
                    notes.append(
                        f"PSD 无损证据已机器核验：{code} {len(proven)} 层与源层导出逐点等价（max Δ0）；"
                        f"另有 {unused_by_class.get(code, 0)} 层未进入候选、无转换风险。"
                    )
            else:
                if code == "outside_canvas_content_requires_equivalence_check":
                    if not evidence.outside_proven:
                        notes.append(
                            "PSD 无损证据残留人工核验：outside_canvas（"
                            + evidence.outside_reason
                            + "）。"
                        )
                    continue
                residuals = evidence.residual_records(code)
                if residuals:
                    detail = "; ".join(
                        f"{r.name}{r.bounds}:{r.reason}" for r in residuals[:6]
                    )
                    notes.append(f"PSD 无损证据残留人工裁剪核验：{code}: {detail}")
        notes.append(
            "PSD 无损证据合成比对："
            + ("通过" if composite_proven else "未通过")
            + "（不透明核心逐点比对，半透明校准边缘计入覆盖率）："
            + "; ".join(composite_stats)
            + "。"
        )
        return tuple(c for c in blocking_issues if c not in cleared), tuple(notes)

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
        owned_visuals: dict[
            str, tuple[str, frozenset[str], frozenset[str], bool]
        ] = {}
        if len(current.view.selection_id) == 64:
            owned_visuals = self._owned_visuals(current.mapping)
        composite_visuals = (
            self._composite_visuals(current.mapping)
            if len(current.view.selection_id) == 64
            else {}
        )
        manifest, source_root, blocking_issues = self._manifest(
            current.view.selection_id,
            owner_device_id,
            raster_layer_ids=raster_layer_ids,
            owned_visuals=owned_visuals,
            composite_visuals=composite_visuals,
            include_states=len(current.view.selection_id) == 64,
            inventory=inventory,
        )
        require_visual_closure(current.mapping, manifest)
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
            remove_generated_directories(candidate)
            version = index_uploaded_project(candidate, project.original_name)
            version = version.model_copy(update={"project_id": project.project_id})
            self._projects.replace_version(version, candidate)
        return self._store.get(session_id, owner_device_id)
