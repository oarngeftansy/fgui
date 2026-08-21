"""Backend-authored conversion dispositions for committed Figma selections."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Literal

from figma_to_fgui.fgui_plan_models import CapabilityStatus, FGUIPlanDocument
from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.models import Diagnostic
from figma_to_fgui.service_contracts import (
    NewProjectAdjustmentStrategy,
    NewProjectConversionDisposition,
    NewProjectDispositionLevel,
    NewProjectDispositionReason,
)

_REASON_ALIASES = {"composite_visual": NewProjectDispositionReason.VISUAL_STYLE}
_EDITABLE_RISKS = frozenset(
    {
        NewProjectDispositionReason.RICH_TEXT_RUNS,
        NewProjectDispositionReason.INSTANCE_COMPOSITE,
    }
)


def _source_nodes(manifest: SelectionManifest) -> dict[str, SelectionNode]:
    result: dict[str, SelectionNode] = {}
    pending = list(manifest.top_level_nodes)
    while pending:
        node = pending.pop()
        if node.id in result:
            raise ValueError("duplicate source node identity")
        result[node.id] = node
        pending.extend(node.children)
    return result


def _reason(value: str) -> NewProjectDispositionReason:
    alias = _REASON_ALIASES.get(value)
    if alias is not None:
        return alias
    return NewProjectDispositionReason(value)


def _disposition_id(source_node_id: str, reason: NewProjectDispositionReason) -> str:
    encoded = (
        len(source_node_id.encode("utf-8")).to_bytes(4, "big")
        + source_node_id.encode("utf-8")
        + len(reason.value.encode("utf-8")).to_bytes(4, "big")
        + reason.value.encode("utf-8")
    )
    return f"disposition:{hashlib.sha256(encoded).hexdigest()[:16]}"


def build_conversion_dispositions(
    manifest: SelectionManifest,
    plan: FGUIPlanDocument,
    source_node_ids: Mapping[str, str],
) -> tuple[NewProjectConversionDisposition, ...]:
    """Project raster decisions into stable public review dispositions."""
    source_nodes = _source_nodes(manifest)
    projected: list[NewProjectConversionDisposition] = []
    seen: set[tuple[str, NewProjectDispositionReason]] = set()
    for decision in sorted(plan.decisions.values(), key=lambda item: item.node_ref):
        if decision.status is not CapabilityStatus.RASTER_FALLBACK:
            continue
        source_node_id = source_node_ids.get(decision.node_ref)
        source = None if source_node_id is None else source_nodes.get(source_node_id)
        if source_node_id is None or source is None:
            raise ValueError("raster decision is missing source provenance")
        for raw_reason in decision.reasons or ("composite_visual",):
            reason = _reason(raw_reason)
            identity = (source_node_id, reason)
            if identity in seen:
                continue
            seen.add(identity)
            editable_risk = reason in _EDITABLE_RISKS
            allowed = (
                (
                    NewProjectAdjustmentStrategy.RASTERIZE_SUBTREE,
                    NewProjectAdjustmentStrategy.PRESERVE_EDITABLE,
                )
                if editable_risk
                else (NewProjectAdjustmentStrategy.RASTERIZE_SUBTREE,)
            )
            projected.append(
                NewProjectConversionDisposition(
                    id=_disposition_id(source_node_id, reason),
                    sourceNodeId=source_node_id,
                    sourceName=source.name,
                    sourceType=source.type.upper(),
                    level=(
                        NewProjectDispositionLevel.EDITABLE_RISK
                        if editable_risk
                        else NewProjectDispositionLevel.RASTER_PRESERVED
                    ),
                    reason=reason,
                    defaultStrategy=NewProjectAdjustmentStrategy.RASTERIZE_SUBTREE,
                    allowedStrategies=allowed,
                    visualImpact="visual_preserved",
                    editabilityImpact=(
                        "text_not_editable"
                        if reason is NewProjectDispositionReason.RICH_TEXT_RUNS
                        else "subtree_not_editable"
                    ),
                    componentImpact=(
                        "instance_not_reusable"
                        if reason is NewProjectDispositionReason.INSTANCE_COMPOSITE
                        else "unchanged"
                    ),
                    blocksApproval=False,
                )
            )
    return tuple(
        sorted(projected, key=lambda item: (item.level.value, item.source_node_id, item.reason.value))
    )


def build_blocked_dispositions(
    manifest: SelectionManifest, diagnostics: tuple[Diagnostic, ...]
) -> tuple[NewProjectConversionDisposition, ...]:
    """Return source-addressable red review items for known pre-build blockers."""
    codes = {item.code for item in diagnostics}
    projected: list[NewProjectConversionDisposition] = []
    for source in sorted(_source_nodes(manifest).values(), key=lambda item: item.id):
        reason: NewProjectDispositionReason | None = None
        component_impact: Literal["unchanged", "instance_not_reusable"] = "unchanged"
        if (
            "fgui.component.definition_missing" in codes
            and source.type.upper() == "INSTANCE"
            and source.properties.get("export_strategy") != "composite_png"
        ):
            reason = NewProjectDispositionReason.COMPONENT_DEFINITION_MISSING
            component_impact = "instance_not_reusable"
        elif (
            "fgui.writer.workflow.validation_failed" in codes
            and bool(source.properties.get("interactions"))
        ):
            reason = NewProjectDispositionReason.INTERACTION_UNSUPPORTED
        if reason is None:
            continue
        projected.append(
            NewProjectConversionDisposition(
                id=_disposition_id(source.id, reason),
                sourceNodeId=source.id,
                sourceName=source.name,
                sourceType=source.type.upper(),
                level=NewProjectDispositionLevel.BLOCKED,
                reason=reason,
                defaultStrategy=None,
                allowedStrategies=(),
                visualImpact="may_differ",
                editabilityImpact="unchanged",
                componentImpact=component_impact,
                blocksApproval=True,
            )
        )
    return tuple(projected)
