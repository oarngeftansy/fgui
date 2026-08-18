"""Classify UIR nodes by their generic FairyGUI conversion capability."""

from __future__ import annotations

import hashlib
import json

from figma_to_fgui.fgui_plan_models import CapabilityDecision, CapabilityStatus
from figma_to_fgui.uir_models import ConversionMode, UIRDocument, UIRNode


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


def decision_for_node(
    node: UIRNode, document: UIRDocument, rule_version: int = 1
) -> CapabilityDecision:
    """Return the first applicable generic capability rule for ``node``."""
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


def analyze_capabilities(
    document: UIRDocument, *, rule_version: int = 1
) -> dict[str, CapabilityDecision]:
    """Classify every UIR node in stable document-key order."""
    return {
        node_id: decision_for_node(document.nodes[node_id], document, rule_version)
        for node_id in sorted(document.nodes)
    }
