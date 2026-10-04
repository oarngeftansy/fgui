from __future__ import annotations

from collections.abc import Callable

from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.hifi_replacement_models import (
    FguiComponentInventory,
    FguiObjectRef,
    HifiMappingDraft,
    HifiMappingItem,
)
from figma_to_fgui.hifi_semantic_pairing import recover_semantic_component_pairs

OwnedVisualValidator = Callable[[str, frozenset[str], frozenset[str]], bool]

_VISUAL_OLD_TYPES = {"graph", "image", "loader"}
_VISUAL_PSD_KINDS = {"shape", "pixel", "smartobject"}
_STATE_DRIVEN_ROLES = {
    "controller_driven",
    "transition_target",
    "controller_action_target",
}
_RUNTIME_VISUAL_ROLES = {
    "runtime_data",
    "runtime_object",
    "nested_behavior",
    "instance_parameterized",
    "unresolved_component_reference",
}
_UNSAFE_BUNDLE_HOST_PROPERTIES = {
    "xy",
    "size",
    "scale",
    "alpha",
    "rotation",
    "color",
    "strokeColor",
    "frame",
    "playing",
    "grayed",
    "touchable",
}

# Color gears tint the base raster per controller page. The PSD raster writer
# neutralizes exactly the value applied to the runtime-initial page while
# keeping controller wiring and inactive-page values, so a color-only gear is
# proven state-specific ownership evidence instead of a blocking property.
_NEUTRALIZED_BUNDLE_PROPERTIES = {"color", "strokeColor"}

# GearLook pages apply alpha/rotation/grayed/touchable on top of whatever
# the host renders, and the writer keeps the gear verbatim. Every controller
# state therefore still composes over the replaced bundle by construction,
# so look-only gears are state-specific ownership evidence, not a block.
_STATE_COMPOSED_BUNDLE_PROPERTIES = {
    "alpha",
    "rotation",
    "grayed",
    "touchable",
}


def _flatten(manifest: SelectionManifest) -> dict[str, SelectionNode]:
    result: dict[str, SelectionNode] = {}
    pending = list(manifest.top_level_nodes)
    while pending:
        node = pending.pop()
        result[node.id] = node
        pending.extend(node.children)
    return result


def _parent_ids(manifest: SelectionManifest) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    pending: list[tuple[SelectionNode, str | None]] = [
        (root, None) for root in manifest.top_level_nodes
    ]
    while pending:
        node, parent_id = pending.pop()
        result[node.id] = parent_id
        pending.extend((child, node.id) for child in node.children)
    return result


def _is_descendant(node_id: str, ancestor_id: str, parents: dict[str, str | None]) -> bool:
    current = parents.get(node_id)
    seen: set[str] = set()
    while current is not None and current not in seen:
        if current == ancestor_id:
            return True
        seen.add(current)
        current = parents.get(current)
    return False


def _descendant_leaves(node: SelectionNode) -> tuple[SelectionNode, ...]:
    leaves: list[SelectionNode] = []
    pending = list(node.children)
    while pending:
        child = pending.pop()
        if not child.visible:
            continue
        if child.children:
            pending.extend(child.children)
        elif child.bounds.width > 0 and child.bounds.height > 0:
            leaves.append(child)
    return tuple(leaves)


def _bundle_children(
    component_id: str,
    children_by_parent: dict[str, list[FguiObjectRef]],
) -> tuple[FguiObjectRef, ...]:
    """Return the local legacy bundle, crossing FGUI groups but not components."""
    result: list[FguiObjectRef] = []
    pending = list(children_by_parent.get(component_id, ()))
    while pending:
        child = pending.pop()
        result.append(child)
        if child.object_type.casefold() == "component":
            continue
        if child.object_type.casefold() == "group" or child.structural_only:
            pending.extend(children_by_parent.get(child.object_id, ()))
    return tuple(result)


def _state_driven(old: FguiObjectRef) -> bool:
    return bool(
        old.dynamic_properties
        or old.controller_refs
        or old.transition_refs
        or _STATE_DRIVEN_ROLES.intersection(old.behavior_roles)
    )


def _runtime_visual(old: FguiObjectRef) -> bool:
    return bool(_RUNTIME_VISUAL_ROLES.intersection(old.behavior_roles))


def _runtime_content_host(old: FguiObjectRef) -> bool:
    """Loaders carry runtime-assigned content; their base skin is an icon slot.

    Policy 27 rule 1 lets proven runtime/state hosts keep exactly one directly
    proven PSD leaf. A loader's default url is only a placeholder for whatever
    the runtime assigns, so its directly matched leaf must stay dedicated to it
    instead of being absorbed by a neighbouring bundle host.
    """
    return old.object_type.casefold() == "loader" or _runtime_visual(old)


def _can_own_raster(old: FguiObjectRef) -> bool:
    # Policy 27: the PSD patcher never converts a GGraph to a raster
    # object, so a graph cannot own a raster bundle regardless of any
    # type-conversion grant recorded for the Figma flow.
    kind = old.object_type.casefold()
    return kind in {"image", "loader"}


def _can_own_target_bundle(old: FguiObjectRef) -> bool:
    """Reject hosts whose other controller pages own geometry/style state.

    GearDisplay/GearIcon are compatible with replacing the base target skin:
    visibility/icon pages can still override it. GearColor and GearLook are
    proven state-specific evidence: the writer neutralizes target-state tint
    and look transforms compose verbatim over the new bundle. Geometry and
    animation gears remain incompatible with one whole-bundle raster because
    rewriting the base visual could silently alter another page's contract.
    """
    unsafe = (
        _UNSAFE_BUNDLE_HOST_PROPERTIES
        - _NEUTRALIZED_BUNDLE_PROPERTIES
        - _STATE_COMPOSED_BUNDLE_PROPERTIES
    )
    return _can_own_raster(old) and not unsafe.intersection(old.dynamic_properties)


def _same_region_replaced(
    inner: tuple[float, float, float, float] | None,
    outer: tuple[float, float, float, float] | None,
) -> bool:
    """True when an old region and a new bundle region describe one visual.

    The new region must cover >=80% of the old one and their areas must be
    comparable (>=0.5), so a lost host is a replaced background rather than
    a distinct control that merely sits inside the bundle region.
    """
    if not inner or not outer:
        return False
    ix = max(inner[0], outer[0])
    iy = max(inner[1], outer[1])
    ir = min(inner[0] + inner[2], outer[0] + outer[2])
    ib = min(inner[1] + inner[3], outer[1] + outer[3])
    if ir <= ix or ib <= iy or inner[2] <= 0 or inner[3] <= 0:
        return False
    covered = (ir - ix) * (ib - iy) / (inner[2] * inner[3])
    return covered >= 0.8 and inner[2] * inner[3] >= outer[2] * outer[3] * 0.5


def _safe_static_retire(old: FguiObjectRef, old_by_id: dict[str, FguiObjectRef]) -> bool:
    """Retire only static target-state paint; never retire runtime/state mechanics."""
    if (
        not old.default_visible
        or old.structural_only
        or old.object_type.casefold() not in {"graph", "image"}
        or _state_driven(old)
        or _runtime_visual(old)
    ):
        return False
    parent = old_by_id.get(old.parent_id or "")
    return not (
        parent is not None
        and parent.auto_layout is not None
        and parent.layout_excludes_invisible
    )


def _psd_visual_leaf(node: SelectionNode) -> bool:
    return (
        node.visible
        and node.bounds.width > 0
        and node.bounds.height > 0
        and node.properties.get("psdKind", "").casefold() in _VISUAL_PSD_KINDS
    )


def _normalized_text(value: str | None) -> str:
    return "".join((value or "").casefold().split())


def _strip_legacy_owned_visuals(
    draft: HifiMappingDraft,
    nodes: dict[str, SelectionNode],
    proven_pairs: frozenset[tuple[str, str]] = frozenset(),
    inventory: FguiComponentInventory | None = None,
) -> HifiMappingDraft:
    """Remove compatibility-era ownership before Policy 27 recomputes it.

    `build_mapping` is shared with older/direct workflows and still contains
    leaf/group promotion heuristics. In PSD semantic-reskin mode those results
    are evidence at most, never authority. Group/component pairings and visual
    items that were already promoted into an owned/composite bundle are reset so
    the semantic layer starts from one deterministic ownership model.
    """
    old_by_id = (
        {old.object_id: old for old in inventory.objects}
        if inventory is not None
        else {}
    )
    normalized: list[HifiMappingItem] = []
    for item in draft.items:
        source = nodes.get(item.figma_node_id or "")
        had_legacy_ownership = bool(
            item.owned_group_id
            or item.owned_source_ids
            or item.composite_group_id
            or item.composite_source_ids
        )
        reset_component_group = bool(
            item.old_object_type == "component"
            and source is not None
            and source.type.upper() in {"GROUP", "COMPONENT", "INSTANCE"}
            and source.children
            # A component-group pair already accepted by a previous Policy 27
            # pass is authority, not legacy evidence; stripping it would drop
            # anchored pairs the recovery pass cannot re-prove (e.g. repeated
            # panels distinguished only by their matched leaf anchors).
            and (item.old_object_id, item.figma_node_id) not in proven_pairs
        )
        # Page-level images/loaders sit outside every component bundle, so
        # the semantic ownership engine never re-decides them. Their
        # backdrop/composite promotion is the designed full-bleed path;
        # stripping it would orphan the backdrop stack with no way back.
        strip_old = old_by_id.get(item.old_object_id or "")
        page_level_visual = strip_old is not None and strip_old.parent_id is None
        if (
            not page_level_visual
            and strip_old is not None
            and inventory is not None
            and strip_old.object_type.casefold() in {"image", "loader"}
            and strip_old.width >= inventory.width * 0.9
            and strip_old.height >= inventory.height * 0.9
        ):
            # A full-canvas visual nested in backdrop window components is
            # equally outside every semantic bundle: its parent components
            # only mount the backdrop stack, so the composite promotion is
            # authority exactly like the page-level case.
            lineage = old_by_id.get(strip_old.parent_id or "")
            while lineage is not None:
                if lineage.object_type.casefold() != "component":
                    break
                lineage = old_by_id.get(lineage.parent_id or "")
            else:
                page_level_visual = True
        if (
            page_level_visual
            and had_legacy_ownership
            and (item.old_object_type or "").casefold() in _VISUAL_OLD_TYPES
        ):
            # The full-bleed backdrop composite is validator-proven evidence
            # and the semantic engine never re-decides page-level hosts, so
            # the item survives the strip whole, composite fields included.
            normalized.append(item)
            continue
        reset_visual_promotion = bool(
            had_legacy_ownership
            and (item.old_object_type or "").casefold() in _VISUAL_OLD_TYPES
            and not page_level_visual
        )
        updates: dict[str, object] = {
            "owned_source_ids": (),
            "owned_group_id": None,
            "retained_source_ids": (),
            "visual_echo": False,
            "composite_group_id": None,
            "composite_source_ids": (),
        }
        if reset_component_group or reset_visual_promotion:
            updates.update({
                "figma_node_id": None,
                "figma_name": None,
                "figma_bounds": None,
                "status": "fgui_only",
                "action": "keep_old",
                "graph_conversion_proven": False,
            })
        normalized.append(item.model_copy(update=updates))
    return draft.model_copy(update={"items": tuple(normalized)})


def _component_pairs(
    draft: HifiMappingDraft,
    nodes: dict[str, SelectionNode],
    old_by_id: dict[str, FguiObjectRef],
) -> tuple[tuple[int, HifiMappingItem, FguiObjectRef, SelectionNode], ...]:
    pairs: list[tuple[int, HifiMappingItem, FguiObjectRef, SelectionNode]] = []
    for index, item in enumerate(draft.items):
        if (
            item.action not in {"accept", "retarget"}
            or not item.old_object_id
            or not item.figma_node_id
        ):
            continue
        old = old_by_id.get(item.old_object_id)
        node = nodes.get(item.figma_node_id)
        if old is None or node is None:
            continue
        if (
            old.object_type.casefold() != "component"
            or node.type.upper() not in {"GROUP", "COMPONENT", "INSTANCE"}
            or not node.children
        ):
            continue
        pairs.append((index, item, old, node))
    return tuple(pairs)


def _match_text_children(
    items: list[HifiMappingItem],
    bundle_children: tuple[FguiObjectRef, ...],
    leaves: tuple[SelectionNode, ...],
) -> set[str]:
    """Keep native FairyGUI text and remap unique exact PSD text in-place."""
    old_texts = [
        old
        for old in bundle_children
        if old.object_type.casefold() in {"text", "richtext"}
    ]
    source_texts = [
        node
        for node in leaves
        if node.type.upper() == "TEXT" and _normalized_text(node.text)
    ]
    matched_ids: set[str] = set()
    if not old_texts or not source_texts:
        return matched_ids

    item_index = {
        item.old_object_id: index
        for index, item in enumerate(items)
        if item.old_object_id
    }
    for old in old_texts:
        key = _normalized_text(old.effective_text)
        if not key:
            continue
        matches = [node for node in source_texts if _normalized_text(node.text) == key]
        if len(matches) != 1:
            continue
        index = item_index.get(old.object_id)
        if index is None:
            continue
        item = items[index]
        node = matches[0]
        # Semantic exact-text evidence outranks an earlier raw leaf match. The
        # initial PSD normalization happens before user review, so overriding a
        # raw correspondence here cannot discard an explicit user decision.
        items[index] = item.model_copy(update={
            "figma_node_id": node.id,
            "figma_name": node.name,
            "status": "matched",
            "action": "accept",
            "visual_disposition": "preserve",
            "preserve_runtime_text": old.runtime_text_override,
        })
        matched_ids.add(node.id)
    return matched_ids


def _host_priority(old: FguiObjectRef, item: HifiMappingItem) -> tuple[int, int, int, float, float]:
    """Prefer static raster hosts, then clean raw correspondence, then z/area."""
    kind = old.object_type.casefold()
    static = not _state_driven(old) and not _runtime_visual(old)
    raster_host = kind in {"image", "loader"}
    return (
        1 if old.width > 0 and old.height > 0 else 0,
        1 if static else 0,
        1 if raster_host else 0,
        1 if item.figma_node_id else 0,
        item.score,
        old.child_index + old.width * old.height / 1_000_000_000,
    )


def _anchor_node(
    visual_nodes: tuple[SelectionNode, ...],
    preferred_id: str | None,
) -> SelectionNode:
    for node in visual_nodes:
        if node.id == preferred_id:
            return node
    return max(
        visual_nodes,
        key=lambda node: (
            node.bounds.width * node.bounds.height,
            node.source_order,
            node.id,
        ),
    )


def normalize_psd_semantic_reskin(
    inventory: FguiComponentInventory,
    manifest: SelectionManifest,
    draft: HifiMappingDraft,
    *,
    owned_visual_validator: OwnedVisualValidator | None = None,
    renormalize: bool = False,
    proven_pairs: frozenset[tuple[str, str]] = frozenset(),
) -> HifiMappingDraft:
    """Policy 27: Component -> Visual Bundle -> PSD Group is the PSD default.

    The runtime Component remains the same object. A matched PSD Group replaces
    its current visual bundle as one semantic operation. Leaf correspondences
    are implementation evidence only; decorative leaves cannot become business
    ADD objects inside an already matched component.
    """
    if (
        not manifest.top_level_nodes
        or not manifest.top_level_nodes[0].id.startswith("psd-root:")
    ):
        return draft

    nodes = _flatten(manifest)
    parents = _parent_ids(manifest)
    # Raw bundles below are validator-proven by the first-pass allocator.
    # The semantic re-proposal below can legitimately fail its stricter
    # partition; in that case the raw bundle is restored instead of
    # orphaning the group's PSD leaves out of visual closure.
    raw_bundles: dict[
        str,
        tuple[str, str | None, tuple[str, ...], tuple[str, ...], str | None, str | None],
    ] = {}
    for item in draft.items:
        if item.owned_group_id and item.owned_source_ids:
            raw_bundles[item.owned_group_id] = (
                item.item_id,
                item.old_object_id,
                item.owned_source_ids,
                item.retained_source_ids,
                item.figma_node_id,
                item.figma_name,
            )
    if not renormalize:
        # A renormalize pass receives this function's own output plus pinned
        # human evidence. Stripping here would erase the component-group
        # pairs this pass produced, and the recovery pass cannot rebuild them
        # from weak geometry alone.
        draft = _strip_legacy_owned_visuals(draft, nodes, proven_pairs, inventory)
    draft = recover_semantic_component_pairs(inventory, manifest, draft)

    old_by_id = {old.object_id: old for old in inventory.objects}
    children_by_parent: dict[str, list[FguiObjectRef]] = {}
    for old in inventory.objects:
        if old.parent_id:
            children_by_parent.setdefault(old.parent_id, []).append(old)

    items = list(draft.items)
    component_pairs = _component_pairs(draft, nodes, old_by_id)
    if not component_pairs:
        return draft

    pair_by_old = {old.object_id: group.id for _, _, old, group in component_pairs}
    matched_group_leaf_ids: set[str] = set()
    absorbed_source_ids: set[str] = set()
    bundle_owner_ids: set[str] = set()
    reused_text_ids: set[str] = set()

    depth: dict[str, int] = {}
    for group_id in pair_by_old.values():
        value = 0
        current = parents.get(group_id)
        while current is not None:
            value += 1
            current = parents.get(current)
        depth[group_id] = value

    for component_index, component_item, old_component, group in sorted(
        component_pairs,
        key=lambda pair: depth[pair[3].id],
        reverse=True,
    ):
        # Root Component is the semantic MODIFY owner; child host carries pixels.
        items[component_index] = component_item.model_copy(update={
            "owned_group_id": group.id,
            "status": "matched",
            "action": "accept",
        })

        bundle_children = _bundle_children(old_component.object_id, children_by_parent)
        if not bundle_children:
            continue

        leaves = _descendant_leaves(group)
        # Delegate leaves to every matched group nested anywhere below this
        # group, not only to groups paired with direct component children.
        # Real projects pair an inner card component that is not a direct
        # child of the outer popup component; without the generalized rule
        # the same inner leaves land in both bundles and the duplicate-
        # ownership gate blocks every host involved.
        nested_group_ids = {
            source_group_id
            for source_group_id in pair_by_old.values()
            if source_group_id != group.id
            and _is_descendant(source_group_id, group.id, parents)
        }
        delegated_ids = {
            leaf.id
            for leaf in leaves
            if any(
                leaf.id == nested_id or _is_descendant(leaf.id, nested_id, parents)
                for nested_id in nested_group_ids
            )
        }
        local_leaves = tuple(leaf for leaf in leaves if leaf.id not in delegated_ids)
        if not local_leaves:
            continue

        local_ids = {leaf.id for leaf in local_leaves}
        matched_group_leaf_ids.update(local_ids)
        reused_text_ids.update(_match_text_children(items, bundle_children, local_leaves))

        visual_nodes = tuple(leaf for leaf in local_leaves if _psd_visual_leaf(leaf))
        visual_ids = {node.id for node in visual_nodes}
        if not visual_ids:
            continue

        item_index = {
            item.old_object_id: index
            for index, item in enumerate(items)
            if item.old_object_id
        }
        visual_hosts = [
            old
            for old in bundle_children
            if (
                old.object_type.casefold() in _VISUAL_OLD_TYPES
                and not old.structural_only
                and not old.out_of_scope
            )
        ]
        current_hosts = [
            old
            for old in visual_hosts
            if old.default_visible and _can_own_target_bundle(old)
        ]

        # Policy 27 uses a deterministic hybrid ownership model:
        # - proven runtime/state hosts may keep exactly their directly matched
        #   PSD leaf when that host is safe for target-bundle replacement;
        # - exactly one primary host owns every residual decorative leaf;
        # - free hosts are never assigned arbitrary leaves merely to reduce ADD.
        # This preserves runtime-specific icon/state contracts without reviving
        # the compatibility-era per-leaf partitioner.
        candidates: list[tuple[FguiObjectRef, int, HifiMappingItem]] = []
        for old in current_hosts:
            index = item_index.get(old.object_id)
            if index is not None:
                candidates.append((old, index, items[index]))

        direct_runtime: list[tuple[FguiObjectRef, int, HifiMappingItem]] = []
        direct_source_ids: set[str] = set()
        ambiguous_direct_ids: set[str] = set()
        for candidate in candidates:
            old, _, item = candidate
            source_id = item.figma_node_id
            if (
                source_id in visual_ids
                and item.action in {"accept", "retarget"}
                and (_runtime_content_host(old) or _state_driven(old))
            ):
                if source_id in direct_source_ids:
                    ambiguous_direct_ids.add(source_id)
                direct_source_ids.add(source_id)
                direct_runtime.append(candidate)

        if ambiguous_direct_ids:
            # Two runtime/state objects claiming one PSD leaf is not a stable
            # partition. Leave both unresolved instead of selecting by order.
            for old, index, item in direct_runtime:
                if item.figma_node_id in ambiguous_direct_ids:
                    items[index] = item.model_copy(update={
                        "figma_node_id": None,
                        "figma_name": None,
                        "figma_bounds": None,
                        "status": "blocked",
                        "action": None,
                    })
            direct_runtime = [
                entry for entry in direct_runtime
                if entry[2].figma_node_id not in ambiguous_direct_ids
            ]

        dedicated_ids = {old.object_id for old, _, _ in direct_runtime}
        residual_ids = visual_ids - {
            item.figma_node_id
            for _, _, item in direct_runtime
            if item.figma_node_id is not None
        }

        primary_candidates = [
            entry for entry in candidates if entry[0].object_id not in dedicated_ids
        ]
        if not primary_candidates and direct_runtime:
            # A component with only one safe runtime visual host (common for
            # button skins) may use that host as both dedicated and primary.
            primary_candidates = direct_runtime
        primary = max(
            primary_candidates,
            key=lambda entry: _host_priority(entry[0], entry[2]),
            default=None,
        )

        proposed: list[tuple[FguiObjectRef, int, HifiMappingItem, set[str]]] = []
        for old, index, item in direct_runtime:
            source_id = item.figma_node_id
            owned = {source_id} if source_id in visual_ids else set()
            if owned:
                proposed.append((old, index, item, owned))

        if primary is not None and residual_ids:
            old, index, item = primary
            existing = next(
                (owned for candidate_old, _, _, owned in proposed
                 if candidate_old.object_id == old.object_id),
                None,
            )
            if existing is not None:
                existing.update(residual_ids)
            else:
                proposed.append((old, index, item, set(residual_ids)))

        # If no dedicated partition exists, the primary host owns the complete
        # target bundle. This is the normal pure-reskin path.
        if not proposed and primary is not None:
            old, index, item = primary
            proposed.append((old, index, item, set(visual_ids)))

        valid_proposal = bool(proposed)
        # The renderer validates against every recursive visible leaf of the
        # group. Leaves delegated to nested semantic boundaries are never
        # baked into this bundle, but they must appear in the partition as
        # retained so the completeness gate sees the whole group.
        group_leaf_ids = {leaf.id for leaf in leaves}
        if valid_proposal and owned_visual_validator is not None:
            valid_proposal = all(
                owned_visual_validator(
                    group.id,
                    frozenset(owned_ids),
                    frozenset(group_leaf_ids - owned_ids),
                )
                for _, _, _, owned_ids in proposed
            )

        owner_ids: set[str] = set()
        if not valid_proposal:
            raw = raw_bundles.get(group.id)
            if raw is not None:
                (
                    raw_item_id,
                    raw_old_id,
                    raw_owned,
                    raw_retained,
                    raw_node_id,
                    raw_node_name,
                ) = raw
                for position, candidate in enumerate(items):
                    if candidate.item_id != raw_item_id:
                        continue
                    items[position] = candidate.model_copy(update={
                        "figma_node_id": raw_node_id or candidate.figma_node_id,
                        "figma_name": raw_node_name or candidate.figma_name,
                        "owned_source_ids": raw_owned,
                        "owned_group_id": group.id,
                        "retained_source_ids": raw_retained,
                        "status": "matched",
                        "action": "accept",
                    })
                    break
                # The raw partition was already renderer-proven by the
                # first-pass allocator; keep its pixels out of every reuse
                # and duplicate-ownership gate below.
                absorbed_source_ids.update(raw_owned)
                if raw_old_id:
                    owner_ids.add(raw_old_id)
                    bundle_owner_ids.add(raw_old_id)
        if valid_proposal:
            bundle_owner_ids.update(entry[0].object_id for entry in proposed)
            for old_owner, owner_index, owner_item, owned_ids in proposed:
                owned_nodes = tuple(node for node in visual_nodes if node.id in owned_ids)
                anchor = _anchor_node(owned_nodes, owner_item.figma_node_id)
                items[owner_index] = owner_item.model_copy(update={
                    "figma_node_id": anchor.id,
                    "figma_name": anchor.name,
                    "owned_source_ids": tuple(sorted(owned_ids)),
                    "owned_group_id": group.id,
                    "retained_source_ids": tuple(
                        sorted(group_leaf_ids - owned_ids)
                    ),
                    "status": "matched",
                    "action": "accept",
                    "visual_disposition": "preserve",
                    "graph_conversion_proven": owner_item.graph_conversion_proven,
                })
                absorbed_source_ids.update(owned_ids)
                owner_ids.add(old_owner.object_id)

        # Every old visual gets an explicit target-state disposition. A raw
        # generated-state or legacy match outside this PSD group is not allowed
        # to escape this decision and silently repaint the current state.
        for old in visual_hosts:
            if old.object_id in owner_ids:
                continue
            index = item_index.get(old.object_id)
            if index is None:
                continue
            item = items[index]

            if not old.default_visible:
                items[index] = item.model_copy(update={
                    "figma_node_id": None,
                    "figma_name": None,
                    "figma_bounds": None,
                    "owned_source_ids": (),
                    "owned_group_id": None,
                    "retained_source_ids": (),
                    "status": "fgui_only",
                    "action": "keep_old",
                    "visual_disposition": "other_state",
                    "graph_conversion_proven": False,
                })
                continue

            if _safe_static_retire(old, old_by_id):
                items[index] = item.model_copy(update={
                    "figma_node_id": None,
                    "figma_name": None,
                    "figma_bounds": None,
                    "owned_source_ids": (),
                    "owned_group_id": None,
                    "retained_source_ids": (),
                    "status": "fgui_only",
                    "action": "keep_old",
                    "visual_disposition": "retire",
                    "graph_conversion_proven": False,
                })
                continue

            root_node = manifest.top_level_nodes[0]
            canvas_width = max(root_node.bounds.width, 1.0)
            canvas_height = max(root_node.bounds.height, 1.0)
            group_region = (
                max(0.0, min(1.0, (group.bounds.x - root_node.bounds.x) / canvas_width)),
                max(0.0, min(1.0, (group.bounds.y - root_node.bounds.y) / canvas_height)),
                max(0.0, min(1.0, group.bounds.width / canvas_width)),
                max(0.0, min(1.0, group.bounds.height / canvas_height)),
            )
            if _same_region_replaced(item.old_bounds, group_region):
                # The losing host's whole region is the winning bundle's
                # region: it is the same visual, replaced. State-driven
                # hosts keep their object and gears (merely hidden) while
                # the bundle repaints the region, so retiring beats
                # blocking the whole mapping on a legacy background.
                items[index] = item.model_copy(update={
                    "figma_node_id": None,
                    "figma_name": None,
                    "figma_bounds": None,
                    "owned_source_ids": (),
                    "owned_group_id": None,
                    "retained_source_ids": (),
                    "status": "fgui_only",
                    "action": "keep_old",
                    "visual_disposition": "retire",
                    "graph_conversion_proven": False,
                })
                continue
            items[index] = item.model_copy(update={
                "figma_node_id": None,
                "figma_name": None,
                "figma_bounds": None,
                "owned_source_ids": (),
                "owned_group_id": None,
                "retained_source_ids": (),
                "status": "blocked",
                "action": None,
                "visual_disposition": "preserve",
            })

    # Raw bundles that the semantic partition did not fully re-absorb leave
    # their leaves explained by nobody: the raw allocator had claimed them
    # (so no hifi_added item exists), the semantic partition assigned other
    # hosts or fewer leaves, and visual closure correctly refuses the gap.
    # The raw partition was renderer-proven, so restore it whole.
    semantic_group_ids = set(pair_by_old.values())
    for raw_group_id, raw in raw_bundles.items():
        raw_item_id, raw_old_id, raw_owned, raw_retained, raw_node_id, raw_node_name = raw
        if raw_group_id not in semantic_group_ids:
            # The semantic engine re-paired this component elsewhere and
            # rejected the legacy group; its bundle stays discarded.
            continue
        if not (set(raw_owned) - absorbed_source_ids - reused_text_ids):
            continue
        for position, candidate in enumerate(items):
            if candidate.item_id != raw_item_id:
                continue
            items[position] = candidate.model_copy(update={
                "figma_node_id": raw_node_id or candidate.figma_node_id,
                "figma_name": raw_node_name or candidate.figma_name,
                "owned_source_ids": raw_owned,
                "owned_group_id": raw_group_id,
                "retained_source_ids": raw_retained,
                "status": "matched",
                "action": "accept",
            })
            break
        absorbed_source_ids.update(raw_owned)
        if raw_old_id:
            bundle_owner_ids.add(raw_old_id)

    reused_source_ids = absorbed_source_ids | reused_text_ids
    if reused_source_ids:
        items = [
            item
            for item in items
            if not (
                item.old_object_id is None
                and item.status == "hifi_added"
                and item.figma_node_id in reused_source_ids
            )
        ]

    normalized: list[HifiMappingItem] = []
    for item in items:
        if (
            item.old_object_id is None
            and item.status == "hifi_added"
            and item.figma_node_id in matched_group_leaf_ids
            and item.figma_node_id not in reused_source_ids
        ):
            normalized.append(item.model_copy(update={
                "status": "blocked",
                "action": None,
            }))
        else:
            normalized.append(item)

    # Any raw accepted item that still points at a visual leaf now owned by a
    # semantic bundle is a stale competing correspondence. Its raw ownership
    # record must be released too, otherwise the duplicate-ownership gate
    # later blocks the legitimate bundle host together with the stale one.
    # When the new bundle region covers a static old object, the old paint is
    # retired instead of blocking the mapping for a human decision.
    semantic_visual_ids = set(absorbed_source_ids)

    revised: list[HifiMappingItem] = []
    for item in normalized:
        stale = (
            item.action in {"accept", "retarget"}
            and item.figma_node_id in semantic_visual_ids
            and item.old_object_id not in bundle_owner_ids
            and (item.old_object_type or "").casefold() not in {"text", "richtext"}
        )
        if not stale:
            revised.append(item)
            continue
        old = old_by_id.get(item.old_object_id or "")
        if (
            old is not None
            and _safe_static_retire(old, old_by_id)
            and _same_region_replaced(item.old_bounds, item.figma_bounds)
        ):
            revised.append(item.model_copy(update={
                "figma_node_id": None,
                "figma_name": None,
                "figma_bounds": None,
                "owned_source_ids": (),
                "owned_group_id": None,
                "retained_source_ids": (),
                "status": "fgui_only",
                "action": "keep_old",
                "visual_disposition": "retire",
                "graph_conversion_proven": False,
            }))
        else:
            revised.append(item.model_copy(update={
                "figma_node_id": None,
                "figma_name": None,
                "figma_bounds": None,
                "owned_source_ids": (),
                "owned_group_id": None,
                "retained_source_ids": (),
                "status": "blocked",
                "action": None,
            }))
    normalized = revised

    # Defensive uniqueness gate for all semantic bundle pixels.
    seen_source_ids: set[str] = set()
    duplicate_source_ids: set[str] = set()
    for item in normalized:
        if item.action not in {"accept", "retarget"}:
            continue
        for source_id in item.owned_source_ids:
            if source_id in seen_source_ids:
                duplicate_source_ids.add(source_id)
            seen_source_ids.add(source_id)
    if duplicate_source_ids:
        normalized = [
            item.model_copy(update={"status": "blocked", "action": None})
            if set(item.owned_source_ids).intersection(duplicate_source_ids)
            else item
            for item in normalized
        ]

    # Policy 28 §9/§16: the mechanical strip above can park an unmatched
    # legacy visual as keep_old while its classification still says
    # REMOVE_CANDIDATE. That combination is an unexplained KEEP_OLD; return
    # it to the undecided pool so the Legacy Removal Review decides its fate.
    normalized = [
        item.model_copy(update={"action": None})
        if item.action == "keep_old"
        and item.status == "fgui_only"
        and item.legacy_state == "REMOVE_CANDIDATE"
        else item
        for item in normalized
    ]

    unresolved = sum(1 for item in normalized if item.action is None)
    return draft.model_copy(update={
        "items": tuple(normalized),
        "unresolved_count": unresolved,
    })
