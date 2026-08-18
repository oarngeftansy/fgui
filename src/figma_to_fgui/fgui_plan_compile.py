"""Compile project-neutral UIR facts into deterministic FairyGUI primitive plans."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from figma_to_fgui.fgui_capabilities import analyze_capabilities
from figma_to_fgui.fgui_plan_models import (
    ComponentReferencePlan,
    FGUIPlanDocument,
    FGUIPlanNode,
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
    "fgui.fallback.raster_subtree": PlanNodeType.RASTER_SUBTREE,
}


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


def compile_fgui_plan(
    document: UIRDocument,
    *,
    profile_version: str = "fgui-6.1.4-v1",
    rule_version: int = 1,
) -> FGUIPlanDocument:
    """Compile native UIR primitives without assigning target-project binding IDs."""
    source_hash = uir_sha256(document)
    decisions = analyze_capabilities(document, rule_version=rule_version)
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
    nodes: dict[str, FGUIPlanNode] = {}

    def is_compilable(uir_node_id: str) -> bool:
        decision = decisions.get(uir_node_id)
        return decision is not None and decision.rule_id in RULE_TO_NODE_TYPE

    def compile_node(uir_node_id: str, parent_plan_id: str | None) -> str | None:
        node = document.nodes.get(uir_node_id)
        decision = decisions.get(uir_node_id)
        if node is None or decision is None:
            diagnostics.append(
                _diagnostic(
                    "fgui.node.missing",
                    "UIR node could not be compiled because it is missing.",
                    node_id=uir_node_id,
                )
            )
            return None
        node_type = RULE_TO_NODE_TYPE.get(decision.rule_id)
        if node_type is None:
            diagnostics.append(
                _diagnostic(
                    "fgui.node.unsupported",
                    "UIR node has no supported FairyGUI primitive rule.",
                    node_id=node.id,
                )
            )
            return None
        plan_node_id = node_ids[node.id]
        child_ids = tuple(
            node_ids[child_id]
            for child_id in node.children
            if is_compilable(child_id)
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
        resource_ref = node.conversion.asset_ref
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
            decisionRef=decision.id,
        )
        for child_id in node.children:
            compile_node(child_id, plan_node_id)
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
        )
    bindable = not any(
        item.severity == Severity.ERROR for item in diagnostics
    ) and not any(item.blocking for item in decisions.values())
    return FGUIPlanDocument(
        documentId=document.document_id,
        sourceUirSha256=source_hash,
        profileVersion=profile_version,
        ruleVersion=rule_version,
        bindable=bindable,
        roots=roots,
        nodes=nodes,
        resources=resources,
        decisions=decisions,
        diagnostics=tuple(diagnostics),
    )
