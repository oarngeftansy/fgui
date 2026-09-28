from __future__ import annotations

import math
import re
from collections.abc import Callable

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


def require_psd_coverage(draft: HifiMappingDraft, manifest: SelectionManifest) -> None:
    if not manifest.top_level_nodes[0].id.startswith("psd-root:"):
        return
    required = {node.id for node in _nodes(manifest) if not node.children and node.visible
                and not is_empty_psd_group(node)}
    covered = {item.figma_node_id for item in draft.items if item.action in {"accept", "retarget"}}
    # A scope decision, not a correspondence, keeps the old visuals of the
    # shared region; the layer is still accounted for.
    covered.update(item.figma_node_id for item in draft.items
                   if item.out_of_scope and item.figma_node_id)
    covered.update(node_id for item in draft.items if item.action in {"accept", "retarget"}
                   for node_id in item.owned_source_ids)
    if required - covered:
        raise HifiMappingError("hifi_mapping_coverage_incomplete")


def is_empty_psd_group(node: SelectionNode) -> bool:
    return (node.type == "GROUP" and node.properties.get("psdKind") == "group"
            and not node.children and not node.resource_keys and node.text is None
            and node.properties.get("hasEffects") is False
            and node.properties.get("hasPixelMask") is False
            and node.properties.get("hasVectorMask") is False
            and node.properties.get("clipping") is False
            and node.properties.get("blendMode") in {"normal", "pass_through"})


def _normalized_name(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _normalized_text(value: str) -> str:
    return "".join(value.casefold().split())


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
    if root.id.startswith("psd-root:"):
        viewport = root.properties.get("psdViewportBounds")
        offset_x, offset_y = (viewport[0], viewport[1]) if viewport else (0, 0)
        return (
            node.bounds.x - root.bounds.x - offset_x,
            node.bounds.y - root.bounds.y - offset_y,
            node.bounds.width,
            node.bounds.height,
        )
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
    # The UI overlays these bounds on the source composite, whose canvas is
    # independent of the legacy component's height (including PSD overflow).
    root = manifest.top_level_nodes[0]
    x, y = node.bounds.x - root.bounds.x, node.bounds.y - root.bounds.y
    return (
        max(0.0, min(1.0, x / root.bounds.width)),
        max(0.0, min(1.0, y / root.bounds.height)),
        max(0.0, min(1.0, node.bounds.width / root.bounds.width)),
        max(0.0, min(1.0, node.bounds.height / root.bounds.height)),
    )


def _compatible(old_type: str, figma_type: str) -> float:
    old = old_type.casefold()
    figma = figma_type.casefold()
    if old == "text":
        return 1.0 if figma == "text" else 0.0
    if old == "component":
        return 1.0 if figma in {"instance", "component", "component_set", "group"} else 0.25
    if old == "image":
        return 1.0 if figma in {"rectangle", "vector", "image"} else 0.25
    if old in {"graph", "mystery"}:
        return 1.0 if figma in {"rectangle", "ellipse", "vector", "line", "polygon", "star"} else 0.25
    return 0.5


def psd_types_compatible(old_type: str, node: SelectionNode, *, conversion_allowed: bool = False) -> bool:
    """Exclude impossible contracts before scoring, decisions and writing."""
    # Some PSD layers report a visible flag but have no drawable bounds. They
    # cannot supply an in-place image and must not steal an old object merely
    # because their type or name happens to score well.
    if not node.visible or node.bounds.width <= 0 or node.bounds.height <= 0:
        return False
    if old_type.casefold() == "graph":
        if conversion_allowed and not node.children and node.type.upper() in {"IMAGE", "VECTOR", "RECTANGLE"}:
            return True
        return "fguiGraph" in node.properties and not node.resource_keys
    allowed = {
        "text": {"TEXT"}, "richtext": {"TEXT"},
        "image": {"IMAGE", "VECTOR", "RECTANGLE"},
        "loader": {"IMAGE", "VECTOR", "RECTANGLE"},
        "component": {"GROUP", "COMPONENT", "INSTANCE"},
        "group": {"GROUP"},
    }
    return node.type.upper() in allowed.get(old_type.casefold(), set())


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
    # An object that FairyGUI repositions at runtime has an XML xy that is not
    # the rendered position, so its position term is evidence in neither
    # direction. The remaining weights are renormalised rather than awarding a
    # free position score.
    authoritative = not old.position_runtime_bound
    evidence = HifiMappingEvidence(
        version=1,
        name_score=name_score,
        position_score=position_score,
        position_authoritative=authoritative,
        size_score=size_score,
        type_score=type_score,
        parent_score=parent_score,
        order_score=max(0.0, order_score),
    )
    weighted = (
        name_score * 0.36
        + size_score * 0.14
        + type_score * 0.14
        + parent_score * 0.06
        + max(0.0, order_score) * 0.06
    )
    weighted = weighted / 0.76 if not authoritative else weighted + position_score * 0.24
    return round(weighted, 6), evidence


def _full_bleed_background(old: FguiObjectRef, node: SelectionNode,
                           inventory: FguiComponentInventory,
                           manifest: SelectionManifest) -> bool:
    """Identify a unique clean PSD pixel layer occupying the old backdrop."""
    if (old.object_type != "image" or old.width < inventory.width * .9
        or old.height < inventory.height * .9 or node.type != "IMAGE"
        or node.children or node.properties.get("psdKind") != "pixel"
        or node.properties.get("hasEffects") or node.properties.get("hasPixelMask")
        or node.properties.get("hasVectorMask") or node.properties.get("clipping")
        or node.properties.get("blendMode") != "normal"):
        return False
    x, y, width, height = _selection_box(manifest, node, inventory)
    return (abs(x - old.x) <= inventory.width * .05
            and abs(y - old.y) <= inventory.height * .05
            and abs(width - old.width) <= inventory.width * .05
            and abs(height - old.height) <= inventory.height * .05)


def _graph_shape_overlap(old: FguiObjectRef, node: SelectionNode,
                         inventory: FguiComponentInventory,
                         manifest: SelectionManifest) -> float:
    if (old.object_type not in {"graph", "image", "loader"} or old.structural_only or node.children
        or node.type.upper() not in {"VECTOR", "RECTANGLE", "IMAGE"}
        or node.properties.get("psdKind") not in {"shape", "pixel"}
        or node.properties.get("hasEffects") or node.properties.get("hasPixelMask")
        or (node.properties.get("hasVectorMask") and node.properties.get("psdKind") != "shape")
        or node.properties.get("clipping")
        or node.properties.get("blendMode") != "normal"):
        return 0.0
    x, y, width, height = _selection_box(manifest, node, inventory)
    if min(old.width, old.height, width, height) <= 0:
        return 0.0
    intersection = max(0.0, min(old.x + old.width, x + width) - max(old.x, x)) * max(
        0.0, min(old.y + old.height, y + height) - max(old.y, y))
    union = old.width * old.height + width * height - intersection
    return intersection / union if union else 0.0


def _shared_region_owner(
    manifest: SelectionManifest,
    node: SelectionNode,
    inventory: FguiComponentInventory,
) -> FguiObjectRef | None:
    """Return the smallest visible old object containing the node, when out of scope.

    A HIFI leaf whose smallest containing runtime object belongs to a
    cross-package component renders that shared component's pixels. It has no
    in-scope owner this round, and overlaying it as a new visual would fake the
    replacement, so the scope decision resolves it instead.
    """
    box = _selection_box(manifest, node, inventory)
    if box[2] <= 0 or box[3] <= 0:
        return None
    tolerance = min(inventory.width, inventory.height) * 0.005
    best: FguiObjectRef | None = None
    for old in inventory.objects:
        contained = (
            old.default_visible and old.width > 0 and old.height > 0
            and old.x - tolerance <= box[0] and old.y - tolerance <= box[1]
            and old.x + old.width + tolerance >= box[0] + box[2]
            and old.y + old.height + tolerance >= box[1] + box[3]
        )
        if contained and (best is None or old.width * old.height < best.width * best.height):
            best = old
    return best if best is not None and best.out_of_scope else None


def build_mapping(
    inventory: FguiComponentInventory,
    manifest: SelectionManifest,
    *,
    owned_visual_validator: Callable[[str, frozenset[str], frozenset[str]], bool] | None = None,
    proven_source_owners: dict[str, str] | None = None,
    full_bleed_visual_validator: Callable[[FguiObjectRef, SelectionNode], float] | None = None,
    graph_raster_validator: Callable[[SelectionNode], bool] | None = None,
) -> HifiMappingDraft:
    nodes = _nodes(manifest)
    is_psd = manifest.top_level_nodes[0].id.startswith("psd-root:")
    real_nodes = tuple(node for node in nodes if not is_psd or "generatedStateOwner" not in node.properties)
    generated_by_owner = {
        node.properties["generatedStateOwner"]: node
        for node in nodes if is_psd and isinstance(node.properties.get("generatedStateOwner"), str)
    }
    proven_source_owners = proven_source_owners or {}
    source_owner = {source: owner for owner, source in proven_source_owners.items()}
    background_scores: dict[str, list[tuple[float, str]]] = {}
    if is_psd and full_bleed_visual_validator is not None:
        for old in inventory.objects:
            if old.out_of_scope:
                continue
            scores = []
            for node in real_nodes:
                if _full_bleed_background(old, node, inventory, manifest):
                    similarity = full_bleed_visual_validator(old, node)
                    if similarity >= .98:
                        scores.append((similarity, node.id))
            background_scores[old.object_id] = sorted(scores, reverse=True)
    background_owners: dict[str, list[str]] = {}
    for old_id, scores in background_scores.items():
        for _, source_id in scores:
            background_owners.setdefault(source_id, []).append(old_id)
    proven_backdrops = {
        old_id: scores[0] for old_id, scores in background_scores.items()
        if scores and len(background_owners[scores[0][1]]) == 1
        and (len(scores) == 1 or scores[0][0] - scores[1][0] >= .1)
        and scores[0][1] not in source_owner
    }
    source_owner.update({source_id: old_id for old_id, (_, source_id) in proven_backdrops.items()})
    graph_proofs: dict[str, str] = {}
    if is_psd and graph_raster_validator is not None:
        graph_candidates: dict[str, list[tuple[float, str]]] = {}
        for old in inventory.objects:
            if old.object_type != "graph" or old.raster_conversion_allowed or old.out_of_scope:
                continue
            graph_candidates[old.object_id] = sorted((
                (overlap, node.id) for node in real_nodes
                if (overlap := _graph_shape_overlap(old, node, inventory, manifest)) >= .25
            ), reverse=True)
        for old_id, candidates in graph_candidates.items():
            if not candidates or candidates[0][0] < .60:
                continue
            best_overlap, best_id = candidates[0]
            if len(candidates) > 1 and best_overlap - candidates[1][0] < .25:
                continue
            if any(other != old_id and scores and scores[0][1] == best_id
                   and scores[0][0] >= .25 for other, scores in graph_candidates.items()):
                continue
            if best_id in source_owner:
                continue
            node = next(node for node in real_nodes if node.id == best_id)
            # A shape may also sit over an image/loader. Geometry alone does
            # not prove which existing visual object owns those pixels.
            if any(other.object_id != old_id and not other.structural_only
                   and other.object_type in {"graph", "image", "loader"}
                   and _graph_shape_overlap(other, node, inventory, manifest) >= best_overlap - .05
                   for other in inventory.objects):
                continue
            if graph_raster_validator(node):
                graph_proofs[old_id] = best_id
                source_owner[best_id] = old_id
    text_proofs: dict[str, str] = {}
    if is_psd:
        for old in inventory.objects:
            if old.out_of_scope:
                continue
            if (old.object_type not in {"text", "richtext"} or not old.default_visible
                or not old.effective_text or old.effective_text.startswith("@")):
                continue
            content = _normalized_text(old.effective_text)
            if len(content) < 3 or sum(
                other.object_type in {"text", "richtext"}
                and _normalized_text(other.effective_text or "") == content
                for other in inventory.objects
            ) != 1:
                continue
            choices = [node for node in real_nodes if node.type.upper() == "TEXT"
                       and node.visible and node.text is not None
                       and _normalized_text(node.text) == content]
            if len(choices) != 1 or choices[0].id in source_owner:
                continue
            node = choices[0]
            x, y, width, height = _selection_box(manifest, node, inventory)
            if math.dist((old.x + old.width / 2, old.y + old.height / 2),
                         (x + width / 2, y + height / 2)) > max(old.width, old.height) * 1.5:
                continue
            text_proofs[old.object_id] = node.id
            source_owner[node.id] = old.object_id
    figma_parents = _figma_parents(manifest)
    old_names = {item.object_id: _normalized_name(item.name) for item in inventory.objects}
    figma_names = {item.id: _normalized_name(item.name) for item in nodes}
    ranked: dict[str, list[tuple[float, SelectionNode, HifiMappingEvidence]]] = {}
    for old in inventory.objects:
        candidates: list[tuple[float, SelectionNode, HifiMappingEvidence]] = []
        if old.object_id in generated_by_owner:
            ranked[old.object_id] = []
            continue
        if is_psd and (old.structural_only or old.out_of_scope):
            ranked[old.object_id] = []
            continue
        for node in real_nodes:
            if (old.object_id in proven_source_owners and node.id != proven_source_owners[old.object_id]
                or node.id in source_owner and source_owner[node.id] != old.object_id):
                continue
            if is_psd and not psd_types_compatible(old.object_type, node, conversion_allowed=(
                old.raster_conversion_allowed or graph_proofs.get(old.object_id) == node.id)):
                continue
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
                len(real_nodes),
                parent_score,
                _selection_box(manifest, node, inventory),
            )
            candidates.append((score, node, evidence))
        ranked[old.object_id] = sorted(candidates, key=lambda item: (-item[0], item[1].id))

    claimed: set[str] = set()
    items: list[HifiMappingItem] = []
    for old in inventory.objects:
        generated = generated_by_owner.get(old.object_id)
        if generated is not None:
            claimed.add(generated.id)
            items.append(HifiMappingItem(
                version=1, item_id=f"old:{old.object_id}", old_object_id=old.object_id,
                old_name=old.name, old_object_type=old.object_type,
                old_resource_id=old.resource_id, figma_node_id=generated.id,
                figma_name=generated.name, status="matched", score=1.0,
                action="accept", generated_state=True, out_of_scope=old.out_of_scope,
                evidence=HifiMappingEvidence(version=1, name_score=1, position_score=1,
                    size_score=1, type_score=1, parent_score=1, order_score=1),
                candidates=(generated.id,), old_bounds=_old_bounds(old, inventory),
                figma_bounds=_figma_bounds(manifest, generated, inventory),
            ))
            continue
        backdrop = proven_backdrops.get(old.object_id)
        if backdrop is not None and backdrop[1] not in claimed:
            similarity, backdrop_id = backdrop
            proof = next((candidate for candidate in ranked[old.object_id]
                          if candidate[1].id == backdrop_id), None)
            if proof is not None:
                claimed.add(backdrop_id)
                items.append(HifiMappingItem(
                    version=1, item_id=f"old:{old.object_id}", old_object_id=old.object_id,
                    old_name=old.name, old_object_type=old.object_type,
                    old_resource_id=old.resource_id, figma_node_id=backdrop_id,
                    figma_name=proof[1].name, status="matched", score=similarity,
                    evidence=proof[2], action="accept", candidates=(backdrop_id,),
                    old_bounds=_old_bounds(old, inventory),
                    figma_bounds=_figma_bounds(manifest, proof[1], inventory),
                ))
                continue
        proven_graph = graph_proofs.get(old.object_id)
        if proven_graph is not None and proven_graph not in claimed:
            proof = next((candidate for candidate in ranked[old.object_id]
                          if candidate[1].id == proven_graph), None)
            if proof is not None:
                claimed.add(proven_graph)
                items.append(HifiMappingItem(
                    version=1, item_id=f"old:{old.object_id}", old_object_id=old.object_id,
                    old_name=old.name, old_object_type=old.object_type,
                    old_resource_id=old.resource_id, figma_node_id=proven_graph,
                    figma_name=proof[1].name, status="matched", score=proof[0],
                    evidence=proof[2], action="accept", candidates=(proven_graph,),
                    graph_conversion_proven=True,
                    old_bounds=_old_bounds(old, inventory),
                    figma_bounds=_figma_bounds(manifest, proof[1], inventory),
                ))
                continue
        proven_text = text_proofs.get(old.object_id)
        if proven_text is not None and proven_text not in claimed:
            proof = next((candidate for candidate in ranked[old.object_id]
                          if candidate[1].id == proven_text), None)
            if proof is not None:
                claimed.add(proven_text)
                items.append(HifiMappingItem(
                    version=1, item_id=f"old:{old.object_id}", old_object_id=old.object_id,
                    old_name=old.name, old_object_type=old.object_type,
                    old_resource_id=old.resource_id, figma_node_id=proven_text,
                    figma_name=proof[1].name,
                    status="matched",
                    score=proof[0], evidence=proof[2],
                    action="accept",
                    candidates=(proven_text,),
                    preserve_runtime_text=old.runtime_text_override,
                    old_bounds=_old_bounds(old, inventory),
                    figma_bounds=_figma_bounds(manifest, proof[1], inventory),
                ))
                continue
        if is_psd and old.out_of_scope:
            items.append(HifiMappingItem(
                version=1, item_id=f"old:{old.object_id}",
                old_object_id=old.object_id, old_name=old.name,
                old_object_type=old.object_type, old_resource_id=old.resource_id,
                status="out_of_scope", action="preserve_structure", out_of_scope=True,
                score=0,
                evidence=HifiMappingEvidence(version=1, name_score=0, position_score=0,
                    size_score=0, type_score=0, parent_score=0, order_score=0),
                old_bounds=_old_bounds(old, inventory),
            ))
            continue
        if is_psd and old.structural_only:
            items.append(HifiMappingItem(version=1,item_id=f"old:{old.object_id}",
                old_object_id=old.object_id,old_name=old.name,old_object_type=old.object_type,
                status="structural",action="preserve_structure",score=0,
                evidence=HifiMappingEvidence(version=1,name_score=0,position_score=0,size_score=0,
                    type_score=0,parent_score=0,order_score=0),old_bounds=_old_bounds(old,inventory)))
            continue
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
                    old_object_type=old.object_type,
                    old_resource_id=old.resource_id,
                    status="fgui_only",
                    score=top[0] if top else 0.0,
                    evidence=evidence,
                    # A missing PSD correspondence is not evidence that a
                    # visible legacy object should retain its old appearance.
                    action=None if manifest.top_level_nodes[0].id.startswith("psd-root:") else "keep_old",
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
        # A tentative correspondence reserves its PSD node too. Otherwise the
        # same node appears again as a supposed HIFI addition before review.
        claimed.add(top[1].id)
        items.append(
            HifiMappingItem(
                version=1,
                item_id=f"old:{old.object_id}",
                old_object_id=old.object_id,
                old_name=old.name,
                old_object_type=old.object_type,
                old_resource_id=old.resource_id,
                figma_node_id=top[1].id,
                figma_name=top[1].name,
                status=status,
                score=top[0],
                evidence=top[2],
                action="accept" if status == "matched" and not (is_psd and top[1].children) else None,
                candidates=tuple(item[1].id for item in candidates[:3]),
                old_bounds=_old_bounds(old, inventory),
                figma_bounds=_figma_bounds(manifest, top[1], inventory),
            )
        )
    if is_psd and owned_visual_validator is not None:
        by_node = {node.id: node for node in nodes}
        assigned = {item.figma_node_id: item for item in items if item.old_object_id and item.figma_node_id}
        old_by_id = {old.object_id: old for old in inventory.objects}
        promoted_anchors: set[str] = set()
        for index, item in enumerate(items):
            old = old_by_id.get(item.old_object_id)
            # A position-less score is renormalised over 0.76 of the evidence
            # weight, so the promotion gate scales by the same factor.
            gate = 0.55 if item.evidence.position_authoritative else 0.55 * 0.76
            if (old is None or old.object_type != "graph" or not old.raster_conversion_allowed
                or item.score < gate):
                continue
            # A sub-threshold item carries no tentative node, but its best
            # candidate is still the anchor of the owned partition.
            anchor = item.figma_node_id or (item.candidates[0] if item.candidates else None)
            if anchor is None or anchor in promoted_anchors:
                continue
            group_id = figma_parents.get(anchor)
            group = by_node.get(group_id)
            if group is None or group.type.upper() != "GROUP":
                continue
            descendants = []
            pending = list(group.children)
            while pending:
                child = pending.pop()
                if child.children:
                    pending.extend(child.children)
                else:
                    descendants.append(child)
            visual = [node for node in descendants if node.properties.get("psdKind", "").casefold()
                      in {"shape", "pixel", "smartobject"}]
            retained = [node for node in descendants if node.type.upper() == "TEXT"]
            if (len(visual) < 2 or not retained or anchor not in {node.id for node in visual}
                or len(visual) + len(retained) != len(descendants)
                or any(node.id in assigned and node.id != anchor for node in visual)):
                continue
            retained_items: dict[str, HifiMappingItem] = {}
            unpaired: list[SelectionNode] = []
            paired_ids: set[str] = set()
            blocked_pairing = False
            for node in retained:
                item_text = assigned.get(node.id)
                owner = old_by_id.get(item_text.old_object_id) if item_text is not None else None
                if (item_text is not None and owner is not None
                        and owner.object_type in {"text", "richtext"}
                        and owner.parent_id == old.parent_id):
                    retained_items[node.id] = item_text
                    paired_ids.add(item_text.old_object_id or "")
                elif node.id in claimed:
                    # The text is tentatively held by an unrelated object; the
                    # partition cannot take it without stealing.
                    blocked_pairing = True
                    break
                else:
                    unpaired.append(node)
            if blocked_pairing:
                continue
            if unpaired:
                # A retained text without a tentative match may still pair with
                # the sole unresolved text object under the same parent; the
                # button definition has exactly one title child.
                free_texts = [
                    text_item for text_item in items
                    if text_item.old_object_id
                    and text_item.old_object_id not in paired_ids
                    and text_item.figma_node_id is None
                    and text_item.status in {"fgui_only", "suggested", "uncertain"}
                    and (owner := old_by_id.get(text_item.old_object_id)) is not None
                    and owner.object_type in {"text", "richtext"}
                    and owner.parent_id == old.parent_id
                ]
                if len(free_texts) != len(unpaired):
                    continue
                ordered = sorted(
                    free_texts,
                    key=lambda text_item: old_by_id[text_item.old_object_id].child_index,
                )
                for node, text_item in zip(unpaired, ordered):
                    retained_items[node.id] = text_item
                    paired_ids.add(text_item.old_object_id or "")
            owned = frozenset(node.id for node in visual)
            text_ids = frozenset(node.id for node in retained)
            if not owned_visual_validator(group.id, owned, text_ids):
                continue
            promoted_anchors.add(anchor)
            items[index] = item.model_copy(update={
                "owned_source_ids": tuple(sorted(owned)),
                "owned_group_id": group.id,
                "retained_source_ids": tuple(sorted(text_ids)),
                "figma_node_id": anchor,
                "figma_name": by_node[anchor].name,
                "status": "matched",
                "action": "accept",
            })
            for node in retained:
                text_item = retained_items[node.id]
                text_index = items.index(text_item)
                updates: dict[str, object] = {"status": "matched", "action": "accept"}
                if text_item.figma_node_id is None:
                    updates["figma_node_id"] = node.id
                    updates["figma_name"] = by_node[node.id].name
                items[text_index] = text_item.model_copy(update=updates)
            claimed.update(owned)
            claimed.update(node.id for node in retained)
    if is_psd:
        item_index_by_old = {item.old_object_id: index
                             for index, item in enumerate(items) if item.old_object_id}
        for group in inventory.objects:
            # The layout group itself is a non-rendering container; only its
            # members receive visuals, so structural_only does not disqualify
            # it from anchoring the sequence proof.
            if (group.auto_layout is None or group.out_of_scope
                    or not group.default_visible):
                continue
            members = sorted(
                (old for old in inventory.objects if old.parent_id == group.object_id),
                key=lambda old: old.child_index,
            )
            if len(members) < 2 or any(
                member.structural_only or member.out_of_scope or not member.default_visible
                for member in members
            ):
                continue
            if any(
                (index := item_index_by_old.get(member.object_id)) is None
                or items[index].figma_node_id is not None
                or items[index].action is not None
                for member in members
            ):
                continue
            horizontal = group.auto_layout == "hz"
            axis = 0 if horizontal else 1
            cross_center = (
                (group.y + group.height / 2) if horizontal else (group.x + group.width / 2)
            )
            cross_tolerance = (group.height if horizontal else group.width)
            main_low, main_high = (
                (group.x, group.x + group.width) if horizontal
                else (group.y, group.y + group.height)
            )
            # An auto-layout group renders its members along the axis in
            # display order. A PSD group holding exactly the strip's
            # unclaimed visible leaves, with an agreeing type sequence and
            # region, proves the rank-to-rank correspondence.
            matches: list[tuple[SelectionNode, list[SelectionNode]]] = []
            for node in real_nodes:
                if node.type.upper() != "GROUP" or not node.children:
                    continue
                if any(child.children for child in node.children):
                    continue
                leaves = [
                    child for child in node.children
                    if child.id not in claimed and child.id not in source_owner
                    and not is_empty_psd_group(child)
                ]
                if len(leaves) != len(members):
                    continue
                boxes = [_selection_box(manifest, child, inventory) for child in leaves]
                if any(box[2] <= 0 or box[3] <= 0 for box in boxes):
                    continue
                ordered = sorted(zip(leaves, boxes), key=lambda pair: pair[1][axis])
                if any(
                    not psd_types_compatible(
                        member.object_type, leaf,
                        conversion_allowed=(member.raster_conversion_allowed
                                            or graph_proofs.get(member.object_id) == leaf.id),
                    )
                    or box[axis] + box[axis + 2] <= main_low
                    or box[axis] >= main_high
                    or abs(((box[1] + box[3] / 2) if horizontal else (box[0] + box[2] / 2))
                           - cross_center) > 2 * cross_tolerance + box[3 - axis]
                    for member, (leaf, box) in zip(members, ordered)
                ):
                    continue
                matches.append((node, [leaf for leaf, _ in ordered]))
            if len(matches) != 1:
                continue
            _, ordered_leaves = matches[0]
            for member, leaf in zip(members, ordered_leaves):
                index = item_index_by_old[member.object_id]
                parent_score = (
                    1.0 if old_names.get(member.parent_id) == figma_names.get(
                        figma_parents.get(leaf.id))
                    else 0.5
                )
                score, evidence = _score(
                    member, leaf, inventory, len(inventory.objects),
                    len(real_nodes), parent_score,
                    _selection_box(manifest, leaf, inventory),
                )
                # The rank agreement is the order evidence for the pairing.
                order_gain = (1.0 - evidence.order_score) * 0.06
                evidence = evidence.model_copy(update={"order_score": 1.0})
                items[index] = items[index].model_copy(update={
                    "figma_node_id": leaf.id,
                    "figma_name": leaf.name,
                    "status": "matched",
                    "action": "accept",
                    "score": min(1.0, round(score + order_gain, 6)),
                    "evidence": evidence,
                })
                claimed.add(leaf.id)
    descendants_with_matches = set(claimed)
    for node in reversed(nodes):
        if any(child.id in descendants_with_matches for child in node.children):
            descendants_with_matches.add(node.id)
    new_roots: list[SelectionNode] = []

    def collect_unmatched(node: SelectionNode) -> None:
        if is_psd and node.children:
            for child in node.children:
                collect_unmatched(child)
            return
        if node.id in claimed:
            return
        if node.id in descendants_with_matches:
            for child in node.children:
                collect_unmatched(child)
            return
        new_roots.append(node)

    for root in manifest.top_level_nodes:
        if root.type.upper() in {"FRAME", "COMPONENT", "GROUP"} and len(manifest.top_level_nodes) == 1:
            for child in root.children:
                collect_unmatched(child)
        else:
            collect_unmatched(root)

    for node in new_roots:
        if is_psd and _shared_region_owner(manifest, node, inventory) is not None:
            items.append(HifiMappingItem(
                version=1, item_id=f"new:{re.sub(r'[^A-Za-z0-9_.:-]', '_', node.id)}",
                figma_node_id=node.id, figma_name=node.name,
                status="out_of_scope", action="preserve_structure", out_of_scope=True,
                score=0,
                evidence=HifiMappingEvidence(version=1, name_score=0, position_score=0,
                    size_score=0, type_score=0, parent_score=0, order_score=0),
                figma_bounds=_figma_bounds(manifest, node, inventory),
            ))
            continue
        node_type = node.type.upper()
        addable = (
            (not node.children or node.properties.get("psdCompositeGroup") is True)
            and node.bounds.width > 0
            and node.bounds.height > 0
            and node_type in {
                "TEXT",
                "RECTANGLE",
                "ELLIPSE",
                "VECTOR",
                "IMAGE",
                "LINE",
                "POLYGON",
                "STAR",
                "GROUP",
            }
        )
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
                status="structural" if is_psd and is_empty_psd_group(node) else "hifi_added" if addable else "blocked",
                score=1.0,
                evidence=evidence,
                action="preserve_structure" if is_psd and is_empty_psd_group(node) else None,
                figma_bounds=_figma_bounds(manifest, node, inventory),
            )
        )
    visibility = {old.object_id: old.default_visible for old in inventory.objects}
    items = [item.model_copy(update={"default_visible": visibility[item.old_object_id]})
             if item.old_object_id in visibility else item for item in items]
    unresolved = sum(item.action is None for item in items)
    return HifiMappingDraft(
        version=1,
        policy_revision=19,
        mapping_revision=1,
        old_canvas_size=(inventory.width, inventory.height),
        source_canvas_size=(manifest.top_level_nodes[0].bounds.width, manifest.top_level_nodes[0].bounds.height),
        items=tuple(items),
        unresolved_count=unresolved,
    )


def apply_mapping_decision(
    draft: HifiMappingDraft,
    decision: HifiMappingDecision,
    manifest: SelectionManifest,
    *, conversion_object_ids: frozenset[str] = frozenset(),
) -> HifiMappingDraft:
    if decision.action == "preserve_structure":
        raise HifiMappingError("mapping_action_not_allowed")
    if decision.mapping_revision != draft.mapping_revision:
        raise HifiMappingError("stale_mapping")
    by_id = {item.item_id: item for item in draft.items}
    if decision.item_id not in by_id:
        raise HifiMappingError("mapping_item_not_found")
    selected_item = by_id[decision.item_id]
    if selected_item.out_of_scope:
        # The scope policy already decided this item; no user action can
        # overwrite it in this round.
        raise HifiMappingError("mapping_action_not_allowed")
    if selected_item.owned_source_ids and decision.action != "accept":
        raise HifiMappingError("hifi_owned_visual_requires_regeneration")
    if selected_item.status == "blocked" and decision.action != "exception":
        raise HifiMappingError("mapping_action_not_allowed")
    if selected_item.status == "hifi_added" and decision.action not in {
        "add_visual",
        "exception",
    }:
        raise HifiMappingError("mapping_action_not_allowed")
    if decision.action == "add_visual" and selected_item.status != "hifi_added":
        raise HifiMappingError("mapping_action_not_allowed")
    if decision.action == "keep_old" and selected_item.old_object_id is None:
        raise HifiMappingError("mapping_action_not_allowed")
    if (decision.action in {"keep_old", "exception"} and selected_item.old_object_id
        and manifest.top_level_nodes[0].id.startswith("psd-root:")):
        raise HifiMappingError("hifi_old_visual_retention_not_allowed")
    if decision.action == "accept" and (
        selected_item.old_object_id is None or selected_item.figma_node_id is None
    ):
        raise HifiMappingError("mapping_action_not_allowed")
    if decision.action == "retarget" and selected_item.old_object_id is None:
        raise HifiMappingError("mapping_action_not_allowed")
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
    if (
        manifest.top_level_nodes[0].id.startswith("psd-root:")
        and decision.action in {"accept", "retarget"}
        and selected_node is not None
        and not psd_types_compatible(selected_item.old_object_type or "", selected_node,
                                     conversion_allowed=(selected_item.old_object_id in conversion_object_ids
                                                         or selected_item.graph_conversion_proven
                                                         and selected_item.figma_node_id == selected_figma_id))
    ):
        raise HifiMappingError("hifi_incompatible_mapping")
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
                        "graph_conversion_proven": item.graph_conversion_proven
                        and item.figma_node_id == selected_figma_id,
                    }
                )
            )
        elif (
            decision.action in {"accept", "retarget"}
            and item.status in {"hifi_added", "blocked"}
            and item.figma_node_id == selected_figma_id
        ):
            updated_items.append(item.model_copy(update={"action": "exception"}))
        else:
            updated_items.append(item)
    items = tuple(updated_items)
    return draft.model_copy(update={
        "mapping_revision": draft.mapping_revision + 1,
        "items": items,
        "unresolved_count": sum(item.action is None for item in items),
    })
