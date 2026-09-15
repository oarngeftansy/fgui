from __future__ import annotations

import math
import re

from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.hifi_replacement_models import (
    FguiComponentInventory,
    FguiObjectRef,
    HifiMappingDecision,
    HifiMappingDraft,
    HifiMappingEvidence,
    HifiMappingItem,
    HifiMappingStatus,
)


class HifiMappingError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _normalized_name(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _nodes(manifest: SelectionManifest) -> tuple[SelectionNode, ...]:
    result: list[SelectionNode] = []
    pending = list(reversed(manifest.top_level_nodes))
    while pending:
        node = pending.pop()
        result.append(node)
        pending.extend(reversed(node.children))
    if len(manifest.top_level_nodes) == 1 and result[0].type.upper() in {"FRAME", "COMPONENT", "GROUP"}:
        return tuple(result[1:])
    return tuple(result)


def _figma_parents(manifest: SelectionManifest) -> dict[str, str | None]:
    parents: dict[str, str | None] = {}
    root_ids = {node.id for node in manifest.top_level_nodes}
    pending: list[tuple[SelectionNode, str | None]] = [
        (node, None) for node in reversed(manifest.top_level_nodes)
    ]
    while pending:
        node, parent_id = pending.pop()
        parents[node.id] = None if parent_id in root_ids else parent_id
        pending.extend((child, node.id) for child in reversed(node.children))
    return parents


def _old_bounds(
    old: FguiObjectRef, inventory: FguiComponentInventory
) -> tuple[float, float, float, float]:
    return (
        max(0.0, min(1.0, old.x / inventory.width)),
        max(0.0, min(1.0, old.y / inventory.height)),
        max(0.0, min(1.0, old.width / inventory.width)),
        max(0.0, min(1.0, old.height / inventory.height)),
    )


def _selection_box(
    manifest: SelectionManifest,
    node: SelectionNode,
    inventory: FguiComponentInventory,
) -> tuple[float, float, float, float]:
    if len(manifest.top_level_nodes) != 1:
        raise HifiMappingError("hifi_selection_requires_single_root")
    root = manifest.top_level_nodes[0]
    if root.bounds.width <= 0 or root.bounds.height <= 0:
        raise HifiMappingError("hifi_selection_root_invalid")
    scale_x = inventory.width / root.bounds.width
    scale_y = inventory.height / root.bounds.height
    return (
        (node.bounds.x - root.bounds.x) * scale_x,
        (node.bounds.y - root.bounds.y) * scale_y,
        node.bounds.width * scale_x,
        node.bounds.height * scale_y,
    )


def _figma_bounds(
    manifest: SelectionManifest,
    node: SelectionNode,
    inventory: FguiComponentInventory,
) -> tuple[float, float, float, float]:
    x, y, width, height = _selection_box(manifest, node, inventory)
    return (
        max(0.0, min(1.0, x / inventory.width)),
        max(0.0, min(1.0, y / inventory.height)),
        max(0.0, min(1.0, width / inventory.width)),
        max(0.0, min(1.0, height / inventory.height)),
    )


def _compatible(old_type: str, figma_type: str) -> float:
    old = old_type.casefold()
    figma = figma_type.casefold()
    if old == "text":
        return 1.0 if figma == "text" else 0.0
    if old == "component":
        return 1.0 if figma in {"instance", "component", "component_set"} else 0.25
    if old == "image":
        return 1.0 if figma in {"rectangle", "vector", "image"} else 0.25
    if old in {"graph", "mystery"}:
        return 1.0 if figma in {"rectangle", "ellipse", "vector", "line", "polygon", "star"} else 0.25
    return 0.5


def _score(
    old: FguiObjectRef,
    node: SelectionNode,
    inventory: FguiComponentInventory,
    old_count: int,
    figma_count: int,
    parent_score: float,
    selection_box: tuple[float, float, float, float],
) -> tuple[float, HifiMappingEvidence]:
    name_score = 1.0 if _normalized_name(old.name) == _normalized_name(node.name) else 0.0
    old_center = (
        (old.x + old.width / 2) / inventory.width,
        (old.y + old.height / 2) / inventory.height,
    )
    node_x, node_y, node_width, node_height = selection_box
    node_center = (
        (node_x + node_width / 2) / inventory.width,
        (node_y + node_height / 2) / inventory.height,
    )
    position_score = max(0.0, 1.0 - math.dist(old_center, node_center) / math.sqrt(2))
    old_area = max(1.0, old.width * old.height)
    new_area = max(1.0, node_width * node_height)
    size_score = min(old_area, new_area) / max(old_area, new_area)
    type_score = _compatible(old.object_type, node.type)
    order_score = 1.0 - abs(
        old.child_index / max(1, old_count - 1) - node.source_order / max(1, figma_count - 1)
    )
    evidence = HifiMappingEvidence(
        version=1,
        name_score=name_score,
        position_score=position_score,
        size_score=size_score,
        type_score=type_score,
        parent_score=parent_score,
        order_score=max(0.0, order_score),
    )
    weighted = (
        name_score * 0.36
        + position_score * 0.24
        + size_score * 0.14
        + type_score * 0.14
        + parent_score * 0.06
        + max(0.0, order_score) * 0.06
    )
    return round(weighted, 6), evidence


def build_mapping(
    inventory: FguiComponentInventory,
    manifest: SelectionManifest,
) -> HifiMappingDraft:
    nodes = _nodes(manifest)
    figma_parents = _figma_parents(manifest)
    old_names = {item.object_id: _normalized_name(item.name) for item in inventory.objects}
    figma_names = {item.id: _normalized_name(item.name) for item in nodes}
    ranked: dict[str, list[tuple[float, SelectionNode, HifiMappingEvidence]]] = {}
    for old in inventory.objects:
        candidates: list[tuple[float, SelectionNode, HifiMappingEvidence]] = []
        for node in nodes:
            figma_parent = figma_parents.get(node.id)
            if old.parent_id is None and figma_parent is None:
                parent_score = 1.0
            elif old.parent_id is not None and figma_parent is not None:
                parent_score = (
                    1.0
                    if old_names.get(old.parent_id) == figma_names.get(figma_parent)
                    else 0.5
                )
            else:
                parent_score = 0.0
            score, evidence = _score(
                old,
                node,
                inventory,
                len(inventory.objects),
                len(nodes),
                parent_score,
                _selection_box(manifest, node, inventory),
            )
            candidates.append((score, node, evidence))
        ranked[old.object_id] = sorted(candidates, key=lambda item: (-item[0], item[1].id))

    claimed: set[str] = set()
    items: list[HifiMappingItem] = []
    for old in inventory.objects:
        candidates = [item for item in ranked[old.object_id] if item[1].id not in claimed]
        top = candidates[0] if candidates else None
        second = candidates[1] if len(candidates) > 1 else None
        if top is None or top[0] < 0.55:
            evidence = top[2] if top else HifiMappingEvidence(
                version=1, name_score=0.0, position_score=0.0, size_score=0.0,
                type_score=0.0, parent_score=0.0, order_score=0.0,
            )
            items.append(
                HifiMappingItem(
                    version=1,
                    item_id=f"old:{old.object_id}",
                    old_object_id=old.object_id,
                    old_name=old.name,
                    status="fgui_only",
                    score=top[0] if top else 0.0,
                    evidence=evidence,
                    action="keep_old",
                    candidates=tuple(item[1].id for item in candidates[:3]),
                    old_bounds=_old_bounds(old, inventory),
                )
            )
            continue
        ambiguous = second is not None and top[0] - second[0] < 0.08
        exact_name = top[2].name_score == 1.0
        status: HifiMappingStatus = (
            "uncertain"
            if ambiguous
            else "matched"
            if exact_name and top[0] >= 0.78
            else "suggested"
        )
        if status == "matched":
            claimed.add(top[1].id)
        items.append(
            HifiMappingItem(
                version=1,
                item_id=f"old:{old.object_id}",
                old_object_id=old.object_id,
                old_name=old.name,
                figma_node_id=top[1].id,
                figma_name=top[1].name,
                status=status,
                score=top[0],
                evidence=top[2],
                action="accept" if status == "matched" else None,
                candidates=tuple(item[1].id for item in candidates[:3]),
                old_bounds=_old_bounds(old, inventory),
                figma_bounds=_figma_bounds(manifest, top[1], inventory),
            )
        )
    for node in nodes:
        if node.id in claimed:
            continue
        evidence = HifiMappingEvidence(
            version=1, name_score=0.0, position_score=0.0, size_score=0.0,
            type_score=1.0, parent_score=1.0, order_score=1.0,
        )
        items.append(
            HifiMappingItem(
                version=1,
                item_id=f"new:{re.sub(r'[^A-Za-z0-9_.:-]', '_', node.id)}",
                figma_node_id=node.id,
                figma_name=node.name,
                status="hifi_added",
                score=1.0,
                evidence=evidence,
                action="add_visual",
                figma_bounds=_figma_bounds(manifest, node, inventory),
            )
        )
    unresolved = sum(item.action is None for item in items)
    return HifiMappingDraft(
        version=1,
        mapping_revision=1,
        items=tuple(items),
        unresolved_count=unresolved,
    )


def apply_mapping_decision(
    draft: HifiMappingDraft,
    decision: HifiMappingDecision,
    manifest: SelectionManifest,
) -> HifiMappingDraft:
    if decision.mapping_revision != draft.mapping_revision:
        raise HifiMappingError("stale_mapping")
    by_id = {item.item_id: item for item in draft.items}
    if decision.item_id not in by_id:
        raise HifiMappingError("mapping_item_not_found")
    node_ids = {node.id for node in _nodes(manifest)}
    if decision.figma_node_id is not None and decision.figma_node_id not in node_ids:
        raise HifiMappingError("figma_node_not_found")
    if decision.action == "retarget":
        occupied = {
            item.figma_node_id
            for item in draft.items
            if item.item_id != decision.item_id and item.action in {"accept", "retarget"}
        }
        if decision.figma_node_id in occupied:
            raise HifiMappingError("figma_node_already_mapped")
    selected_figma_id = (
        decision.figma_node_id
        if decision.action == "retarget"
        else by_id[decision.item_id].figma_node_id
    )
    selected_node = next((node for node in _nodes(manifest) if node.id == selected_figma_id), None)
    selected_bounds = next(
        (
            item.figma_bounds
            for item in draft.items
            if item.figma_node_id == selected_figma_id and item.figma_bounds is not None
        ),
        None,
    )
    updated_items: list[HifiMappingItem] = []
    for item in draft.items:
        if item.item_id == decision.item_id:
            updated_items.append(
                item.model_copy(
                    update={
                        "action": decision.action,
                        "figma_node_id": selected_figma_id,
                        "figma_name": selected_node.name if selected_node else item.figma_name,
                        "figma_bounds": selected_bounds or item.figma_bounds,
                    }
                )
            )
        elif (
            decision.action in {"accept", "retarget"}
            and item.status == "hifi_added"
            and item.figma_node_id == selected_figma_id
        ):
            updated_items.append(item.model_copy(update={"action": "exception"}))
        else:
            updated_items.append(item)
    items = tuple(updated_items)
    return HifiMappingDraft(
        version=1,
        mapping_revision=draft.mapping_revision + 1,
        items=items,
        unresolved_count=sum(item.action is None for item in items),
    )
