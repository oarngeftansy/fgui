"""Compile project-neutral UIR facts into deterministic FairyGUI primitive plans."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from figma_to_fgui.fgui_capabilities import (
    NATIVE_CLIP_SOURCE_RULE_ID,
    analyze_capabilities,
    analyze_mask_capabilities,
)
from figma_to_fgui.fgui_plan_models import (
    CapabilityDecision,
    CapabilityStatus,
    ComponentReferencePlan,
    FGUIPlanDocument,
    FGUIPlanNode,
    MaskMode,
    MaskPlan,
    PlanNodeType,
    ResourcePlan,
    TextPlan,
    TransformPlan,
)
from figma_to_fgui.models import Diagnostic, Severity
from figma_to_fgui.uir_models import MappingStatus, UIRAsset, UIRDocument, UIRNode
from figma_to_fgui.uir_validate import uir_sha256

RULE_TO_NODE_TYPE = {
    "fgui.native.container": PlanNodeType.CONTAINER,
    "fgui.native.text": PlanNodeType.TEXT,
    "fgui.native.image": PlanNodeType.IMAGE,
    "fgui.native.component_reference": PlanNodeType.COMPONENT_REFERENCE,
    NATIVE_CLIP_SOURCE_RULE_ID: PlanNodeType.CONTAINER,
    "fgui.fallback.raster_subtree": PlanNodeType.RASTER_SUBTREE,
}
NATIVE_RULE_TO_NODE_TYPE = {
    rule_id: node_type
    for rule_id, node_type in RULE_TO_NODE_TYPE.items()
    if node_type != PlanNodeType.RASTER_SUBTREE
}
RASTER_RULE_ID = "fgui.fallback.raster_subtree"


def valid_nine_slice(asset: UIRAsset) -> bool:
    """Return whether explicitly supplied asset grid facts fit the asset dimensions."""
    grid = asset.nine_slice
    return grid is None or (
        asset.width is not None
        and asset.height is not None
        and grid.x + grid.width <= asset.width
        and grid.y + grid.height <= asset.height
    )


def _stable_plan_node_id(
    source_uir_sha256: str,
    uir_node_id: str,
    profile_version: str,
    rule_version: int,
) -> str:
    payload = json.dumps(
        {
            "profileVersion": profile_version,
            "ruleVersion": rule_version,
            "sourceUirSha256": source_uir_sha256,
            "uirNodeId": uir_node_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"plan-node:{hashlib.sha256(payload).hexdigest()[:24]}"


def _stable_mask_id(
    source_uir_sha256: str,
    container_ref: str,
    profile_version: str,
    rule_version: int,
) -> str:
    payload = json.dumps(
        {
            "containerRef": container_ref,
            "profileVersion": profile_version,
            "ruleVersion": rule_version,
            "sourceUirSha256": source_uir_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"mask:{hashlib.sha256(payload).hexdigest()[:24]}"


def _text_plan(node: UIRNode) -> TextPlan:
    source = node.text or {}
    style_value = source.get("style", {})
    style = style_value if isinstance(style_value, Mapping) else {}
    candidates_value = source.get("fontCandidates", style.get("fontCandidates", ()))
    candidates = (
        tuple(item for item in candidates_value if isinstance(item, str))
        if isinstance(candidates_value, (list, tuple))
        else ()
    )
    font_size_value = source.get("fontSize", style.get("fontSize"))
    font_size = (
        float(font_size_value)
        if isinstance(font_size_value, (int, float))
        and not isinstance(font_size_value, bool)
        and font_size_value > 0
        else None
    )
    color_value = source.get("color", style.get("color"))
    horizontal_align_value = source.get(
        "horizontalAlign", style.get("textAlignHorizontal", style.get("horizontalAlign"))
    )
    vertical_align_value = source.get(
        "verticalAlign", style.get("textAlignVertical", style.get("verticalAlign"))
    )
    content_value = source.get("content", "")
    return TextPlan(
        content=content_value if isinstance(content_value, str) else "",
        fontCandidates=candidates,
        fontSize=font_size,
        color=color_value if isinstance(color_value, str) else None,
        horizontalAlign=(
            horizontal_align_value if isinstance(horizontal_align_value, str) else None
        ),
        verticalAlign=vertical_align_value if isinstance(vertical_align_value, str) else None,
        styleFacts=dict(style),
    )


def _component_plan(document: UIRDocument, node: UIRNode) -> ComponentReferencePlan | None:
    decision_ref = node.semantic.decision_ref
    mapping = (
        None if decision_ref is None else document.mapping_decisions.get(decision_ref)
    )
    if mapping is None or mapping.status != MappingStatus.VERIFIED:
        return None
    variant_properties = {} if node.component is None else node.component.variant_properties
    return ComponentReferencePlan(
        candidateKey=mapping.candidate_key,
        variantProperties=variant_properties,
    )


def _diagnostic(
    code: str,
    message: str,
    *,
    node_id: str | None = None,
) -> Diagnostic:
    return Diagnostic(code=code, severity=Severity.ERROR, message=message, node_id=node_id)


def _node_type_for_decision(
    document: UIRDocument,
    node: UIRNode,
    decision: CapabilityDecision,
) -> PlanNodeType | None:
    if decision.status == CapabilityStatus.NATIVE:
        return NATIVE_RULE_TO_NODE_TYPE.get(decision.rule_id)
    if (
        decision.status == CapabilityStatus.RASTER_FALLBACK
        and decision.rule_id == RASTER_RULE_ID
        and node.conversion.asset_ref in document.assets
    ):
        return PlanNodeType.RASTER_SUBTREE
    return None


def _decision_diagnostic(node: UIRNode, decision: CapabilityDecision) -> Diagnostic:
    if decision.status == CapabilityStatus.UNSUPPORTED:
        if decision.rule_id.startswith("fgui.mask.") or decision.rule_id == (
            "fgui.visual.effect_unsupported"
        ):
            return _diagnostic(
                decision.rule_id,
                "UIR mask facts cannot be compiled safely.",
                node_id=node.id,
            )
        if decision.rule_id in RULE_TO_NODE_TYPE:
            return _diagnostic(
                "fgui.decision.status_rule_incoherent",
                "Unsupported capability decisions cannot select a plan-node rule.",
                node_id=node.id,
            )
        return _diagnostic(
            "fgui.node.unsupported",
            "UIR node has an unsupported FairyGUI capability decision.",
            node_id=node.id,
        )
    if decision.status == CapabilityStatus.RASTER_FALLBACK:
        if decision.rule_id != RASTER_RULE_ID:
            return _diagnostic(
                "fgui.decision.status_rule_incoherent",
                "Raster fallback decisions must select the raster-subtree rule.",
                node_id=node.id,
            )
        return _diagnostic(
            "fgui.decision.raster_resource_missing",
            "Raster fallback decisions require an existing source asset.",
            node_id=node.id,
        )
    return _diagnostic(
        "fgui.decision.status_rule_incoherent",
        "Native capability decisions must select a native plan-node rule.",
        node_id=node.id,
    )


def compile_fgui_plan(
    document: UIRDocument,
    *,
    profile_version: str = "fgui-6.1.4-v1",
    rule_version: int = 1,
    decisions: Mapping[str, CapabilityDecision] | None = None,
) -> FGUIPlanDocument:
    """Compile native UIR primitives without assigning target-project binding IDs.

    When supplied, ``decisions`` are reviewed capability decisions and are used
    directly instead of deriving a new decision set.
    """
    source_hash = uir_sha256(document)
    resolved_decisions = (
        analyze_capabilities(document, rule_version=rule_version)
        if decisions is None
        else decisions
    )
    mask_capabilities = analyze_mask_capabilities(document)
    node_ids = {
        node_id: _stable_plan_node_id(
            source_hash, node_id, profile_version, rule_version
        )
        for node_id in document.nodes
    }
    diagnostics = list(document.diagnostics)
    resource_consumers: dict[str, set[str]] = {
        asset_id: set() for asset_id in document.assets
    }
    resource_reasons: dict[str, str] = {}
    nodes: dict[str, FGUIPlanNode] = {}
    active_node_ids: set[str] = set()
    compiled_node_ids: set[str] = set()
    consumed_uir_nodes: set[str] = set()
    incompatible_mask_roots: set[str] = set()
    mask_refs_by_node: dict[str, str] = {}
    masks: dict[str, MaskPlan] = {}

    def add_diagnostic_once(code: str, message: str, node_id: str) -> None:
        if not any(item.code == code and item.node_id == node_id for item in diagnostics):
            diagnostics.append(_diagnostic(code, message, node_id=node_id))

    if decisions is not None:
        for analysis in mask_capabilities.values():
            if analysis.mode != MaskMode.RASTER_SUBTREE or analysis.facts is None:
                continue
            safe_root_id = analysis.facts.safe_raster_root_ref
            reviewed = None if safe_root_id is None else resolved_decisions.get(safe_root_id)
            if (
                safe_root_id is not None
                and (
                    reviewed is None
                    or reviewed.status != CapabilityStatus.RASTER_FALLBACK
                    or reviewed.rule_id != RASTER_RULE_ID
                )
            ):
                incompatible_mask_roots.add(safe_root_id)
                add_diagnostic_once(
                    "fgui.decision.mask_requirement_incoherent",
                    "Reviewed capability decision conflicts with required mask fallback.",
                    safe_root_id,
                )

    for analysis in mask_capabilities.values():
        facts = analysis.facts
        if facts is None or analysis.mode is None:
            continue
        if analysis.mode == MaskMode.RASTER_SUBTREE:
            safe_root_id = facts.safe_raster_root_ref
            if safe_root_id is None:
                continue
            consumed_uir_nodes.update(analysis.consumed_node_refs)
            consumed_uir_nodes.discard(safe_root_id)
            if analysis.resource_ref is not None:
                resource_reasons[analysis.resource_ref] = "mask_raster_fallback"

    for container_id in sorted(mask_capabilities):
        analysis = mask_capabilities[container_id]
        if (
            container_id in consumed_uir_nodes
            and analysis.mode != MaskMode.RASTER_SUBTREE
        ):
            continue
        if analysis.diagnostic_code is not None:
            add_diagnostic_once(
                analysis.diagnostic_code,
                "UIR mask facts cannot be compiled safely.",
                container_id,
            )
            continue
        facts = analysis.facts
        mode = analysis.mode
        if facts is None or mode is None:
            continue
        mask_id = _stable_mask_id(source_hash, container_id, profile_version, rule_version)
        masks[mask_id] = MaskPlan(
            id=mask_id,
            mode=mode,
            kind=facts.kind,
            maskNodeRef=facts.mask_node_ref,
            contentNodeRefs=facts.content_node_refs,
            resourceRef=analysis.resource_ref,
        )
        target_node_id = container_id
        if mode == MaskMode.RASTER_SUBTREE:
            safe_root_id = facts.safe_raster_root_ref
            if safe_root_id is None:
                continue
            target_node_id = safe_root_id
        mask_refs_by_node[target_node_id] = mask_id

    def is_compilable(uir_node_id: str) -> bool:
        if uir_node_id in consumed_uir_nodes or uir_node_id in incompatible_mask_roots:
            return False
        node = document.nodes.get(uir_node_id)
        decision = resolved_decisions.get(uir_node_id)
        return (
            node is not None
            and decision is not None
            and _node_type_for_decision(document, node, decision) is not None
        )

    def compile_node(uir_node_id: str, parent_plan_id: str | None) -> str | None:
        if uir_node_id in consumed_uir_nodes or uir_node_id in incompatible_mask_roots:
            return None
        if uir_node_id in active_node_ids:
            diagnostics.append(
                _diagnostic(
                    "fgui.node.cycle",
                    "UIR child references form a cycle and cannot be compiled.",
                    node_id=uir_node_id,
                )
            )
            return None
        node = document.nodes.get(uir_node_id)
        decision = resolved_decisions.get(uir_node_id)
        if node is None or decision is None:
            diagnostics.append(
                _diagnostic(
                    "fgui.node.missing",
                    "UIR node could not be compiled because it is missing.",
                    node_id=uir_node_id,
                )
            )
            return None
        node_type = _node_type_for_decision(document, node, decision)
        if node_type is None:
            item = _decision_diagnostic(node, decision)
            add_diagnostic_once(item.code, item.message, node.id)
            return None
        plan_node_id = node_ids[node.id]
        if plan_node_id in compiled_node_ids:
            return plan_node_id
        active_node_ids.add(node.id)
        child_ids = tuple(
            node_ids[child_id]
            for child_id in node.children
            if child_id not in active_node_ids and is_compilable(child_id)
        )
        component = (
            _component_plan(document, node)
            if node_type == PlanNodeType.COMPONENT_REFERENCE
            else None
        )
        if node_type == PlanNodeType.COMPONENT_REFERENCE and component is None:
            diagnostics.append(
                _diagnostic(
                    "fgui.component.mapping_unverified",
                    "Component references require a verified UIR mapping decision.",
                    node_id=node.id,
                )
            )
        resource_ref = (
            None
            if decision.rule_id == NATIVE_CLIP_SOURCE_RULE_ID
            else node.conversion.asset_ref
        )
        if resource_ref is not None and resource_ref in resource_consumers:
            resource_consumers[resource_ref].add(plan_node_id)
        nodes[plan_node_id] = FGUIPlanNode(
            id=plan_node_id,
            uirNodeRef=node.id,
            parentId=parent_plan_id,
            children=child_ids,
            zIndex=node.z_index,
            type=node_type,
            transform=TransformPlan(
                bounds=node.geometry.resolved_bounds,
                rotation=node.geometry.rotation,
                opacity=node.geometry.opacity,
            ),
            text=_text_plan(node) if node_type == PlanNodeType.TEXT else None,
            resourceRef=resource_ref,
            component=component,
            maskRef=mask_refs_by_node.get(node.id),
            decisionRef=decision.id,
        )
        compiled_node_ids.add(plan_node_id)
        if node.id not in mask_refs_by_node or node_type != PlanNodeType.RASTER_SUBTREE:
            for child_id in node.children:
                compile_node(child_id, plan_node_id)
        active_node_ids.remove(node.id)
        return plan_node_id

    roots = tuple(
        compiled_id
        for root_id in document.roots
        if (compiled_id := compile_node(root_id, None)) is not None
    )
    resources: dict[str, ResourcePlan] = {}
    for asset_id in sorted(document.assets):
        asset = document.assets[asset_id]
        grid = asset.nine_slice
        if not valid_nine_slice(asset):
            diagnostics.append(
                _diagnostic(
                    "fgui.resource.nine_slice_invalid",
                    "Nine-slice grid must fit within explicit asset dimensions.",
                    node_id=asset.source_node_id,
                )
            )
            grid = None
        resources[asset_id] = ResourcePlan(
            id=asset.id,
            sourceAssetRef=asset.id,
            mimeType=asset.mime_type,
            exportFormat=asset.export_format,
            width=asset.width,
            height=asset.height,
            nineSlice=None if grid is None else (grid.x, grid.y, grid.width, grid.height),
            consumers=tuple(sorted(resource_consumers[asset_id])),
            reason=resource_reasons.get(asset_id),
        )
    plan_decisions = {
        node_id: resolved_decisions[node_id]
        for node_id in sorted(resolved_decisions)
        if node_id not in consumed_uir_nodes
    }
    bindable = not any(
        item.severity == Severity.ERROR for item in diagnostics
    ) and not any(item.blocking for item in plan_decisions.values())
    return FGUIPlanDocument(
        documentId=document.document_id,
        sourceUirSha256=source_hash,
        profileVersion=profile_version,
        ruleVersion=rule_version,
        bindable=bindable,
        roots=roots,
        nodes=nodes,
        resources=resources,
        masks=masks,
        decisions=plan_decisions,
        diagnostics=tuple(diagnostics),
    )
