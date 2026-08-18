"""Compile project-neutral UIR facts into deterministic FairyGUI primitive plans."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace

from figma_to_fgui.fgui_capabilities import (
    NATIVE_CLIP_SOURCE_RULE_ID,
    MaskCapability,
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
from figma_to_fgui.uir_models import (
    ConversionMode,
    MappingStatus,
    UIRAsset,
    UIRDocument,
    UIRNode,
)
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


@dataclass(frozen=True)
class _MaskReconciliation:
    container_ref: str
    capability: MaskCapability
    target_node_ref: str | None
    emit: bool
    diagnostic_code: str | None = None
    diagnostic_message: str | None = None
    diagnostic_node_ref: str | None = None
    excluded_node_refs: tuple[str, ...] = ()
    suppressed_resource_refs: tuple[str, ...] = ()


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


def _expected_native_mask_rule(
    document: UIRDocument,
    node: UIRNode,
    *,
    mode: MaskMode,
    is_mask_source: bool,
) -> str | None:
    if node.conversion.mode == ConversionMode.UNSUPPORTED:
        return None
    if is_mask_source and mode == MaskMode.NATIVE_CLIP:
        return NATIVE_CLIP_SOURCE_RULE_ID
    if is_mask_source and mode == MaskMode.NATIVE_MASK:
        return (
            "fgui.native.image"
            if node.conversion.mode == ConversionMode.NATIVE
            and node.source.type in {"RECTANGLE", "ELLIPSE", "VECTOR", "IMAGE"}
            and node.conversion.asset_ref in document.assets
            else None
        )
    if node.conversion.mode == ConversionMode.RASTER_FALLBACK:
        return None
    if node.conversion.mode == ConversionMode.COMPONENT_REFERENCE:
        return "fgui.native.component_reference"
    if node.source.type in {"FRAME", "GROUP", "COMPONENT", "SECTION"}:
        return "fgui.native.container"
    if node.source.type == "TEXT":
        return "fgui.native.text"
    if (
        node.source.type in {"RECTANGLE", "ELLIPSE", "VECTOR", "IMAGE"}
        and node.conversion.asset_ref in document.assets
    ):
        return "fgui.native.image"
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
    mask_refs_by_node: dict[str, str] = {}
    masks: dict[str, MaskPlan] = {}

    def add_diagnostic_once(code: str, message: str, node_id: str) -> None:
        if not any(item.code == code and item.node_id == node_id for item in diagnostics):
            diagnostics.append(_diagnostic(code, message, node_id=node_id))

    reconciliations: dict[str, _MaskReconciliation] = {}
    for container_id, analysis in mask_capabilities.items():
        facts = analysis.facts
        mode = analysis.mode
        target_node_ref: str | None = container_id
        if mode == MaskMode.RASTER_SUBTREE and facts is not None:
            target_node_ref = facts.safe_raster_root_ref
        reconciliations[container_id] = _MaskReconciliation(
            container_ref=container_id,
            capability=analysis,
            target_node_ref=target_node_ref,
            emit=facts is not None and mode is not None and analysis.diagnostic_code is None,
            diagnostic_code=analysis.diagnostic_code,
            diagnostic_message=(
                None
                if analysis.diagnostic_code is None
                else "UIR mask facts cannot be compiled safely."
            ),
            diagnostic_node_ref=(
                None if analysis.diagnostic_code is None else container_id
            ),
        )

    def required_native_refs(state: _MaskReconciliation) -> tuple[str, ...]:
        facts = state.capability.facts
        if facts is None:
            return ()
        return (
            state.container_ref,
            facts.mask_node_ref,
            *facts.content_node_refs,
        )

    def resource_refs_for(state: _MaskReconciliation) -> tuple[str, ...]:
        refs: set[str] = set()
        if state.capability.resource_ref is not None:
            refs.add(state.capability.resource_ref)
        for node_id in required_native_refs(state):
            asset_ref = document.nodes[node_id].conversion.asset_ref
            if asset_ref is not None:
                refs.add(asset_ref)
        return tuple(sorted(refs))

    if decisions is not None:
        for container_id, state in tuple(reconciliations.items()):
            analysis = state.capability
            facts = analysis.facts
            if not state.emit or facts is None or analysis.mode is None:
                continue
            if analysis.mode == MaskMode.RASTER_SUBTREE:
                safe_root_id = facts.safe_raster_root_ref
                reviewed = (
                    None if safe_root_id is None else resolved_decisions.get(safe_root_id)
                )
                if safe_root_id is None or (
                    reviewed is None
                    or reviewed.status != CapabilityStatus.RASTER_FALLBACK
                    or reviewed.rule_id != RASTER_RULE_ID
                ):
                    diagnostic_node = safe_root_id or container_id
                    reconciliations[container_id] = replace(
                        state,
                        emit=False,
                        diagnostic_code="fgui.decision.mask_requirement_incoherent",
                        diagnostic_message=(
                            "Reviewed capability decision conflicts with required mask fallback."
                        ),
                        diagnostic_node_ref=diagnostic_node,
                        excluded_node_refs=(diagnostic_node,),
                        suppressed_resource_refs=resource_refs_for(state),
                    )
                continue

            for node_id in required_native_refs(state):
                reviewed = resolved_decisions.get(node_id)
                expected_rule = _expected_native_mask_rule(
                    document,
                    document.nodes[node_id],
                    mode=analysis.mode,
                    is_mask_source=node_id == facts.mask_node_ref,
                )
                if (
                    reviewed is None
                    or expected_rule is None
                    or reviewed.status != CapabilityStatus.NATIVE
                    or reviewed.rule_id != expected_rule
                ):
                    message = (
                        "Reviewed capability decision promotes an unsupported mask node."
                        if document.nodes[node_id].conversion.mode
                        == ConversionMode.UNSUPPORTED
                        else "Reviewed capability decision assigns an incoherent mask role."
                    )
                    reconciliations[container_id] = replace(
                        state,
                        emit=False,
                        diagnostic_code="fgui.decision.mask_requirement_incoherent",
                        diagnostic_message=message,
                        diagnostic_node_ref=node_id,
                        excluded_node_refs=(node_id,),
                        suppressed_resource_refs=resource_refs_for(state),
                    )
                    break

    targets: dict[str, list[str]] = {}
    for container_id, state in reconciliations.items():
        if state.emit and state.target_node_ref is not None:
            targets.setdefault(state.target_node_ref, []).append(container_id)
    for target_node_id, container_ids in targets.items():
        if len(container_ids) < 2:
            continue
        for container_id in container_ids:
            state = reconciliations[container_id]
            reconciliations[container_id] = replace(
                state,
                emit=False,
                diagnostic_code="fgui.mask.target_collision",
                diagnostic_message="Multiple masks target the same plan node.",
                diagnostic_node_ref=target_node_id,
                excluded_node_refs=(target_node_id,),
                suppressed_resource_refs=resource_refs_for(state),
            )

    for state in reconciliations.values():
        if not state.emit:
            continue
        analysis = state.capability
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

    for container_id, state in tuple(reconciliations.items()):
        analysis = state.capability
        if not state.emit or analysis.mode == MaskMode.RASTER_SUBTREE:
            continue
        native_refs = required_native_refs(state)
        if native_refs and all(
            node_id in consumed_uir_nodes for node_id in native_refs
        ):
            reconciliations[container_id] = replace(
                state,
                emit=False,
                diagnostic_code=None,
                diagnostic_message=None,
                diagnostic_node_ref=None,
                suppressed_resource_refs=resource_refs_for(state),
            )
            continue
        bad_node_id = next(
            (
                node_id
                for node_id in native_refs
                if node_id in consumed_uir_nodes
                or (decision := resolved_decisions.get(node_id)) is None
                or _node_type_for_decision(document, document.nodes[node_id], decision)
                is None
            ),
            None,
        )
        if bad_node_id is not None:
            reconciliations[container_id] = replace(
                state,
                emit=False,
                diagnostic_code="fgui.decision.mask_requirement_incoherent",
                diagnostic_message="A required native mask node cannot be compiled.",
                diagnostic_node_ref=bad_node_id,
                excluded_node_refs=(bad_node_id,),
                suppressed_resource_refs=resource_refs_for(state),
            )

    incompatible_mask_nodes = {
        node_id
        for state in reconciliations.values()
        for node_id in state.excluded_node_refs
    }
    suppressed_mask_resources = {
        resource_ref
        for state in reconciliations.values()
        for resource_ref in state.suppressed_resource_refs
    }

    for container_id in sorted(reconciliations):
        state = reconciliations[container_id]
        if not state.emit:
            absorbed_invalid_mask = (
                container_id in consumed_uir_nodes
                and state.capability.diagnostic_code is not None
            )
            if (
                not absorbed_invalid_mask
                and state.diagnostic_code is not None
                and state.diagnostic_message is not None
                and state.diagnostic_node_ref is not None
            ):
                add_diagnostic_once(
                    state.diagnostic_code,
                    state.diagnostic_message,
                    state.diagnostic_node_ref,
                )
            continue
        analysis = state.capability
        facts = analysis.facts
        mode = analysis.mode
        emission_target_id = state.target_node_ref
        if facts is None or mode is None or emission_target_id is None:
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
        mask_refs_by_node[emission_target_id] = mask_id

    def is_excluded(uir_node_id: str) -> bool:
        return (
            uir_node_id in consumed_uir_nodes
            or uir_node_id in incompatible_mask_nodes
        )

    def is_compilable(uir_node_id: str) -> bool:
        if is_excluded(uir_node_id):
            return False
        node = document.nodes.get(uir_node_id)
        decision = resolved_decisions.get(uir_node_id)
        return (
            node is not None
            and decision is not None
            and _node_type_for_decision(document, node, decision) is not None
        )

    def compile_node(uir_node_id: str, parent_plan_id: str | None) -> str | None:
        if is_excluded(uir_node_id):
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
        if (
            asset_id in suppressed_mask_resources
            and not resource_consumers[asset_id]
        ):
            continue
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
