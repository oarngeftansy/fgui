"""Classify UIR nodes by their generic FairyGUI conversion capability."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from figma_to_fgui.fgui_plan_models import (
    CapabilityDecision,
    CapabilityStatus,
    MaskKind,
    MaskMode,
)
from figma_to_fgui.uir_models import ConversionMode, UIRDocument, UIRNode

NATIVE_CLIP_KINDS = frozenset({"rectangle", "roundedRectangle"})
NATIVE_MASK_KINDS = frozenset({"image"})
RASTER_MASK_KINDS = frozenset({"boolean", "gradient", "blur", "blend"})
NATIVE_CLIP_SOURCE_RULE_ID = "fgui.native.clip_source"
class MaskFacts(BaseModel):
    """Strictly parsed mask facts stored in a UIR node's opaque visual map."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    kind: MaskKind
    mask_node_ref: str = Field(alias="maskNodeRef", min_length=1)
    content_node_refs: tuple[str, ...] = Field(alias="contentNodeRefs", min_length=1)
    safe_raster_root_ref: str | None = Field(default=None, alias="safeRasterRootRef")
    effects: tuple[str, ...] = ()


@dataclass(frozen=True)
class MaskCapability:
    """Validated, project-neutral result used by the plan compiler."""

    container_ref: str
    facts: MaskFacts | None
    mode: MaskMode | None
    resource_ref: str | None = None
    consumed_node_refs: tuple[str, ...] = ()
    diagnostic_code: str | None = None


def _decision_id(node_id: str, rule_id: str, rule_version: int) -> str:
    payload = json.dumps(
        {
            "nodeId": node_id,
            "ruleId": rule_id,
            "ruleVersion": rule_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"decision:{hashlib.sha256(payload).hexdigest()[:24]}"


def _decision(
    node: UIRNode,
    status: CapabilityStatus,
    rule_id: str,
    rule_version: int,
    reasons: tuple[str, ...] = (),
    blocking: bool = False,
) -> CapabilityDecision:
    return CapabilityDecision(
        id=_decision_id(node.id, rule_id, rule_version),
        nodeRef=node.id,
        status=status,
        ruleId=rule_id,
        ruleVersion=rule_version,
        reasons=reasons,
        blocking=blocking,
    )


def _base_decision_for_node(
    node: UIRNode, document: UIRDocument, rule_version: int = 1
) -> CapabilityDecision:
    if node.conversion.mode == ConversionMode.UNSUPPORTED:
        return _decision(
            node,
            CapabilityStatus.UNSUPPORTED,
            "fgui.unsupported.source",
            rule_version,
            node.conversion.reasons,
            True,
        )
    if node.conversion.mode == ConversionMode.RASTER_FALLBACK:
        if node.conversion.asset_ref not in document.assets:
            return _decision(
                node,
                CapabilityStatus.UNSUPPORTED,
                "fgui.unsupported.raster_asset",
                rule_version,
                ("raster_asset_missing",),
                True,
            )
        return _decision(
            node,
            CapabilityStatus.RASTER_FALLBACK,
            "fgui.fallback.raster_subtree",
            rule_version,
            node.conversion.reasons,
        )
    if node.conversion.mode == ConversionMode.COMPONENT_REFERENCE:
        return _decision(
            node,
            CapabilityStatus.NATIVE,
            "fgui.native.component_reference",
            rule_version,
        )
    if node.source.type in {"FRAME", "GROUP", "COMPONENT", "SECTION"}:
        return _decision(
            node,
            CapabilityStatus.NATIVE,
            "fgui.native.container",
            rule_version,
        )
    if node.source.type == "TEXT":
        return _decision(
            node,
            CapabilityStatus.NATIVE,
            "fgui.native.text",
            rule_version,
        )
    if (
        node.source.type in {"RECTANGLE", "ELLIPSE", "VECTOR", "IMAGE"}
        and node.conversion.asset_ref in document.assets
    ):
        return _decision(
            node,
            CapabilityStatus.NATIVE,
            "fgui.native.image",
            rule_version,
        )
    return _decision(
        node,
        CapabilityStatus.UNSUPPORTED,
        "fgui.unsupported.node_type",
        rule_version,
        ("node_type_unsupported",),
        True,
    )


def _is_ancestor(document: UIRDocument, ancestor_id: str, node_id: str) -> bool:
    visited: set[str] = set()
    current_id: str | None = node_id
    while current_id is not None and current_id not in visited:
        if current_id == ancestor_id:
            return True
        visited.add(current_id)
        current = document.nodes.get(current_id)
        current_id = None if current is None else current.parent_id
    return False


def _subtree_ids(document: UIRDocument, root_id: str) -> tuple[str, ...]:
    result: list[str] = []
    pending = [root_id]
    visited: set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        result.append(node_id)
        node = document.nodes.get(node_id)
        if node is not None:
            pending.extend(reversed(node.children))
    return tuple(result)


def _invalid_mask(container_ref: str, code: str) -> MaskCapability:
    return MaskCapability(
        container_ref=container_ref,
        facts=None,
        mode=None,
        diagnostic_code=code,
    )


def analyze_mask_capabilities(document: UIRDocument) -> dict[str, MaskCapability]:
    """Parse and validate all declared mask facts in stable container order."""
    results: dict[str, MaskCapability] = {}
    for container_id in sorted(document.nodes):
        container = document.nodes[container_id]
        if "mask" not in container.visual:
            continue
        try:
            facts = MaskFacts.model_validate(container.visual["mask"])
        except ValidationError:
            results[container_id] = _invalid_mask(
                container_id, "fgui.mask.facts_invalid"
            )
            continue

        referenced_ids = (facts.mask_node_ref, *facts.content_node_refs)
        required_ids = referenced_ids + (
            () if facts.safe_raster_root_ref is None else (facts.safe_raster_root_ref,)
        )
        if any(node_id not in document.nodes for node_id in required_ids):
            results[container_id] = _invalid_mask(
                container_id, "fgui.mask.source_missing"
            )
            continue

        child_positions = {node_id: index for index, node_id in enumerate(container.children)}
        owned_nodes = (document.nodes[node_id] for node_id in referenced_ids)
        content_positions = [child_positions.get(node_id) for node_id in facts.content_node_refs]
        mask_position = child_positions.get(facts.mask_node_ref)
        hierarchy_invalid = (
            len(set(referenced_ids)) != len(referenced_ids)
            or any(node.parent_id != container_id for node in owned_nodes)
            or any(node_id not in child_positions for node_id in referenced_ids)
            or any(position is None for position in content_positions)
            or mask_position is None
        )
        if not hierarchy_invalid:
            assert mask_position is not None
            numeric_positions = [position for position in content_positions if position is not None]
            hierarchy_invalid = numeric_positions != list(
                range(mask_position + 1, mask_position + 1 + len(numeric_positions))
            )
        if hierarchy_invalid:
            results[container_id] = _invalid_mask(
                container_id, "fgui.mask.invalid_hierarchy"
            )
            continue

        if facts.kind in NATIVE_CLIP_KINDS and not facts.effects:
            results[container_id] = MaskCapability(
                container_ref=container_id,
                facts=facts,
                mode=MaskMode.NATIVE_CLIP,
            )
            continue
        if facts.kind in NATIVE_MASK_KINDS and not facts.effects:
            results[container_id] = MaskCapability(
                container_ref=container_id,
                facts=facts,
                mode=MaskMode.NATIVE_MASK,
            )
            continue

        if facts.kind not in RASTER_MASK_KINDS and not facts.effects:
            results[container_id] = _invalid_mask(
                container_id, "fgui.mask.facts_invalid"
            )
            continue

        safe_root_id = facts.safe_raster_root_ref
        if safe_root_id is None:
            results[container_id] = _invalid_mask(
                container_id, "fgui.visual.effect_unsupported"
            )
            continue
        if any(
            not _is_ancestor(document, safe_root_id, node_id)
            for node_id in referenced_ids
        ):
            results[container_id] = _invalid_mask(
                container_id, "fgui.mask.invalid_hierarchy"
            )
            continue
        safe_root = document.nodes[safe_root_id]
        asset_ref = safe_root.conversion.asset_ref
        if asset_ref is None or asset_ref not in document.assets:
            results[container_id] = _invalid_mask(
                container_id, "fgui.visual.effect_unsupported"
            )
            continue
        consumed_node_refs = _subtree_ids(document, safe_root_id)
        if any(
            not _is_ancestor(document, safe_root_id, node_id)
            for node_id in consumed_node_refs
        ):
            results[container_id] = _invalid_mask(
                container_id, "fgui.mask.invalid_hierarchy"
            )
            continue
        results[container_id] = MaskCapability(
            container_ref=container_id,
            facts=facts,
            mode=MaskMode.RASTER_SUBTREE,
            resource_ref=asset_ref,
            consumed_node_refs=consumed_node_refs,
        )

    raster_items = [
        (container_id, analysis)
        for container_id, analysis in results.items()
        if analysis.mode == MaskMode.RASTER_SUBTREE
    ]
    overlapping_containers: set[str] = set()
    for index, (container_id, analysis) in enumerate(raster_items):
        claimed_nodes = set(analysis.consumed_node_refs)
        for other_container_id, other_analysis in raster_items[index + 1 :]:
            if claimed_nodes.intersection(other_analysis.consumed_node_refs):
                overlapping_containers.update((container_id, other_container_id))
    for container_id in overlapping_containers:
        results[container_id] = _invalid_mask(
            container_id, "fgui.mask.invalid_hierarchy"
        )
    return results


def _mask_decision(
    node: UIRNode,
    analysis: MaskCapability,
    rule_version: int,
) -> CapabilityDecision:
    if analysis.diagnostic_code is not None:
        return _decision(
            node,
            CapabilityStatus.UNSUPPORTED,
            analysis.diagnostic_code,
            rule_version,
            ("mask_invalid",),
            True,
        )
    return _decision(
        node,
        CapabilityStatus.RASTER_FALLBACK,
        "fgui.fallback.raster_subtree",
        rule_version,
        ("mask_raster_fallback",),
    )


def decision_for_node(
    node: UIRNode, document: UIRDocument, rule_version: int = 1
) -> CapabilityDecision:
    """Return the first applicable generic capability or mask rule for ``node``."""
    decisions = analyze_capabilities(document, rule_version=rule_version)
    return decisions.get(node.id, _base_decision_for_node(node, document, rule_version))


def analyze_capabilities(
    document: UIRDocument, *, rule_version: int = 1
) -> dict[str, CapabilityDecision]:
    """Classify every UIR node in stable document-key order."""
    decisions = {
        node_id: _base_decision_for_node(document.nodes[node_id], document, rule_version)
        for node_id in sorted(document.nodes)
    }
    for analysis in analyze_mask_capabilities(document).values():
        if analysis.diagnostic_code is not None:
            node = document.nodes[analysis.container_ref]
            decisions[node.id] = _mask_decision(node, analysis, rule_version)
        elif analysis.mode == MaskMode.RASTER_SUBTREE and analysis.facts is not None:
            safe_root_id = analysis.facts.safe_raster_root_ref
            if safe_root_id is not None:
                node = document.nodes[safe_root_id]
                decisions[node.id] = _mask_decision(node, analysis, rule_version)
        elif analysis.mode == MaskMode.NATIVE_CLIP and analysis.facts is not None:
            node = document.nodes[analysis.facts.mask_node_ref]
            if node.conversion.mode != ConversionMode.UNSUPPORTED:
                decisions[node.id] = _decision(
                    node,
                    CapabilityStatus.NATIVE,
                    NATIVE_CLIP_SOURCE_RULE_ID,
                    rule_version,
                )
    return decisions
