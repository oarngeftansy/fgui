"""Semantic validation and canonical serialization for FairyGUI generation plans."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from figma_to_fgui.fgui_plan_models import (
    CapabilityDecision,
    CapabilityStatus,
    FGUIPlanDocument,
    FGUIPlanNode,
    MaskKind,
    MaskMode,
    MaskPlan,
    PlanNodeType,
)
from figma_to_fgui.models import Diagnostic, Severity

_FORBIDDEN_BINDING_FIELDS = frozenset({"packageId", "componentId", "src", "pkg"})
_NATIVE_RULE_NODE_TYPES = {
    "fgui.native.container": PlanNodeType.CONTAINER,
    "fgui.native.text": PlanNodeType.TEXT,
    "fgui.native.rich_text": PlanNodeType.RICH_TEXT,
    "fgui.native.image": PlanNodeType.IMAGE,
    "fgui.native.loader": PlanNodeType.LOADER,
    "fgui.native.component_reference": PlanNodeType.COMPONENT_REFERENCE,
    "fgui.native.clip_source": PlanNodeType.CONTAINER,
}
_RESOURCE_NODE_TYPES = frozenset(
    {PlanNodeType.IMAGE, PlanNodeType.LOADER, PlanNodeType.RASTER_SUBTREE}
)
_TEXT_NODE_TYPES = frozenset({PlanNodeType.TEXT, PlanNodeType.RICH_TEXT})


def _error(
    code: str,
    message: str,
    *,
    node_id: str | None = None,
    path: str | None = None,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=Severity.ERROR,
        message=message,
        node_id=node_id,
        path=path,
    )


def _append_once(
    diagnostics: list[Diagnostic],
    seen: set[tuple[str, str | None, str | None]],
    code: str,
    message: str,
    *,
    node_id: str | None = None,
    path: str | None = None,
) -> None:
    key = (code, node_id, path)
    if key not in seen:
        seen.add(key)
        diagnostics.append(
            _error(code, message, node_id=node_id, path=path)
        )


def _binding_leak_paths(value: Any, path: str = "$") -> tuple[str, ...]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            nested_path = f"{path}.{key}"
            if key in _FORBIDDEN_BINDING_FIELDS:
                paths.append(nested_path)
            paths.extend(_binding_leak_paths(value[key], nested_path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            paths.extend(_binding_leak_paths(nested, f"{path}[{index}]"))
    return tuple(paths)


def _decision_for_node(
    node: FGUIPlanNode,
    decisions_by_id: Mapping[str, CapabilityDecision],
) -> CapabilityDecision | None:
    if node.decision_ref is None:
        return None
    return decisions_by_id.get(node.decision_ref)


def _validate_tree(
    plan: FGUIPlanDocument,
    diagnostics: list[Diagnostic],
    seen: set[tuple[str, str | None, str | None]],
) -> None:
    owners: dict[str, str] = {}

    for root_id in plan.roots:
        root = plan.nodes.get(root_id)
        if root is None:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.root_missing",
                "FairyGUI plan root does not exist.",
                node_id=root_id,
            )
        elif root.parent_id is not None:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.root_parent_incoherent",
                "FairyGUI plan roots cannot have a parent.",
                node_id=root.id,
            )

    for key in sorted(plan.nodes):
        node = plan.nodes[key]
        if key != node.id:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.node_key_mismatch",
                "FairyGUI plan node key differs from its ID.",
                node_id=node.id,
            )
        if node.parent_id is not None and node.parent_id not in plan.nodes:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.parent_missing",
                "FairyGUI plan parent node does not exist.",
                node_id=node.id,
            )

        local_children: set[str] = set()
        for child_id in node.children:
            child = plan.nodes.get(child_id)
            if child is None:
                _append_once(
                    diagnostics,
                    seen,
                    "fgui.plan.child_missing",
                    "FairyGUI plan child node does not exist.",
                    node_id=node.id,
                )
                continue
            previous_owner = owners.get(child_id)
            if child_id in local_children or (
                previous_owner is not None and previous_owner != node.id
            ):
                _append_once(
                    diagnostics,
                    seen,
                    "fgui.plan.child_multiple_parents",
                    "FairyGUI plan child is owned more than once.",
                    node_id=child_id,
                )
            else:
                owners[child_id] = node.id
                local_children.add(child_id)
            if child.parent_id != node.id:
                _append_once(
                    diagnostics,
                    seen,
                    "fgui.plan.parent_mismatch",
                    "FairyGUI plan child and parent references are not symmetric.",
                    node_id=child_id,
                )

    for node in plan.nodes.values():
        if node.parent_id is None or node.parent_id not in plan.nodes:
            if node.id not in plan.roots:
                _append_once(
                    diagnostics,
                    seen,
                    "fgui.plan.node_unowned",
                    "Every emitted plan node must be a root or an owned child.",
                    node_id=node.id,
                )
        elif node.id not in plan.nodes[node.parent_id].children:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.parent_mismatch",
                "FairyGUI plan child and parent references are not symmetric.",
                node_id=node.id,
            )


def _validate_resources(
    plan: FGUIPlanDocument,
    diagnostics: list[Diagnostic],
    seen: set[tuple[str, str | None, str | None]],
) -> None:
    for key in sorted(plan.resources):
        resource = plan.resources[key]
        if key != resource.id:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.resource_key_mismatch",
                "FairyGUI resource key differs from its ID.",
                path=f"$.resources.{key}",
            )
        for consumer_id in resource.consumers:
            consumer = plan.nodes.get(consumer_id)
            if consumer is None:
                _append_once(
                    diagnostics,
                    seen,
                    "fgui.plan.resource_consumer_missing",
                    "FairyGUI resource consumer does not exist.",
                    node_id=consumer_id,
                )
            elif consumer.resource_ref != resource.id:
                _append_once(
                    diagnostics,
                    seen,
                    "fgui.plan.resource_consumer_mismatch",
                    "FairyGUI resource ownership is not symmetric.",
                    node_id=consumer.id,
                )

    for node in plan.nodes.values():
        if node.resource_ref is None:
            continue
        referenced_resource = plan.resources.get(node.resource_ref)
        if referenced_resource is None:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.resource_missing",
                "FairyGUI plan resource does not exist.",
                node_id=node.id,
            )
        elif node.id not in referenced_resource.consumers:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.resource_consumer_mismatch",
                "FairyGUI resource ownership is not symmetric.",
                node_id=node.id,
            )

    for resource in plan.resources.values():
        consumers = [
            plan.nodes[consumer_id]
            for consumer_id in resource.consumers
            if consumer_id in plan.nodes
        ]
        has_raster = any(node.type == PlanNodeType.RASTER_SUBTREE for node in consumers)
        has_native = any(node.type != PlanNodeType.RASTER_SUBTREE for node in consumers)
        if has_raster and has_native:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.raster_native_resource_duplicate",
                "A resource cannot be owned by both raster and native plan nodes.",
                path=f"$.resources.{resource.id}",
            )


def _validate_decisions(
    plan: FGUIPlanDocument,
    diagnostics: list[Diagnostic],
    seen: set[tuple[str, str | None, str | None]],
) -> dict[str, CapabilityDecision]:
    decisions_by_id: dict[str, CapabilityDecision] = {}
    for key in sorted(plan.decisions):
        decision = plan.decisions[key]
        if key != decision.node_ref:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.decision_key_mismatch",
                "Capability decision key differs from its node reference.",
                node_id=decision.node_ref,
            )
        if decision.id in decisions_by_id:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.decision_id_duplicate",
                "Capability decision ID is not unique.",
                node_id=decision.node_ref,
            )
        else:
            decisions_by_id[decision.id] = decision
        if decision.rule_version != plan.rule_version:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.decision_rule_version_mismatch",
                "Capability decision rule version differs from the plan.",
                node_id=decision.node_ref,
            )
        if decision.status == CapabilityStatus.UNSUPPORTED:
            has_blocking_diagnostic = any(
                item.severity == Severity.ERROR
                and (
                    item.node_id == decision.node_ref
                    or item.rule_id == decision.rule_id
                    or item.code == decision.rule_id
                )
                for item in plan.diagnostics
            )
            if not decision.blocking or not has_blocking_diagnostic:
                _append_once(
                    diagnostics,
                    seen,
                    "fgui.plan.unsupported_not_blocked",
                    "Unsupported capability requires a blocking decision and diagnostic.",
                    node_id=decision.node_ref,
                )
        elif decision.blocking:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.decision_blocking_incoherent",
                "Only unsupported capability decisions may be blocking.",
                node_id=decision.node_ref,
            )
    return decisions_by_id


def _validate_node_payload_and_decision(
    plan: FGUIPlanDocument,
    decisions_by_id: Mapping[str, CapabilityDecision],
    diagnostics: list[Diagnostic],
    seen: set[tuple[str, str | None, str | None]],
) -> None:
    decision_owners: dict[str, str] = {}
    for node in plan.nodes.values():
        if node.type in _TEXT_NODE_TYPES and node.text is None:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.node_payload_required",
                "Text plan nodes require a text payload.",
                node_id=node.id,
            )
        elif node.type not in _TEXT_NODE_TYPES and node.text is not None:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.node_payload_forbidden",
                "Only text plan nodes may contain a text payload.",
                node_id=node.id,
            )

        if node.type == PlanNodeType.COMPONENT_REFERENCE and node.component is None:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.node_payload_required",
                "Component-reference nodes require a component payload.",
                node_id=node.id,
            )
        elif node.type != PlanNodeType.COMPONENT_REFERENCE and node.component is not None:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.node_payload_forbidden",
                "Only component-reference nodes may contain a component payload.",
                node_id=node.id,
            )

        if node.type in _RESOURCE_NODE_TYPES and node.resource_ref is None:
            code = (
                "fgui.plan.fallback_resource_required"
                if node.type == PlanNodeType.RASTER_SUBTREE
                else "fgui.plan.node_payload_required"
            )
            _append_once(
                diagnostics,
                seen,
                code,
                "Resource-bearing plan node requires a resource.",
                node_id=node.id,
            )
        elif (
            node.type not in _RESOURCE_NODE_TYPES
            and node.resource_ref is not None
            and node.resource_ref in plan.resources
        ):
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.node_payload_forbidden",
                "This plan-node type cannot own a raster resource.",
                node_id=node.id,
            )

        if node.type == PlanNodeType.RASTER_SUBTREE and node.children:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.raster_descendant_duplicate",
                "Raster-subtree nodes cannot retain native descendants.",
                node_id=node.id,
            )

        if node.decision_ref is None:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.decision_missing",
                "FairyGUI plan node requires a capability decision.",
                node_id=node.id,
            )
            continue
        decision = decisions_by_id.get(node.decision_ref)
        if decision is None:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.decision_missing",
                "FairyGUI plan capability decision does not exist.",
                node_id=node.id,
            )
            continue
        previous_owner = decision_owners.get(decision.id)
        if previous_owner is not None and previous_owner != node.id:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.decision_multiple_nodes",
                "Capability decision is owned by more than one plan node.",
                node_id=node.id,
            )
        else:
            decision_owners[decision.id] = node.id
        if decision.node_ref != node.uir_node_ref:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.decision_node_mismatch",
                "Capability decision and plan node refer to different UIR nodes.",
                node_id=node.id,
            )

        if decision.status == CapabilityStatus.NATIVE:
            expected_type = _NATIVE_RULE_NODE_TYPES.get(decision.rule_id)
            if expected_type is None:
                _append_once(
                    diagnostics,
                    seen,
                    "fgui.plan.decision_status_rule_incoherent",
                    "Native capability decision uses an unknown native rule.",
                    node_id=node.id,
                )
            elif node.type != expected_type:
                _append_once(
                    diagnostics,
                    seen,
                    "fgui.plan.decision_node_type_mismatch",
                    "Native capability rule does not match the plan-node type.",
                    node_id=node.id,
                )
        elif decision.status == CapabilityStatus.RASTER_FALLBACK:
            if decision.rule_id != "fgui.fallback.raster_subtree":
                _append_once(
                    diagnostics,
                    seen,
                    "fgui.plan.decision_status_rule_incoherent",
                    "Raster fallback must use the raster-subtree rule.",
                    node_id=node.id,
                )
            if node.type != PlanNodeType.RASTER_SUBTREE:
                _append_once(
                    diagnostics,
                    seen,
                    "fgui.plan.decision_node_type_mismatch",
                    "Raster fallback decision requires a raster-subtree node.",
                    node_id=node.id,
                )
            if node.resource_ref is None:
                _append_once(
                    diagnostics,
                    seen,
                    "fgui.plan.fallback_resource_required",
                    "Raster fallback decision requires a resource.",
                    node_id=node.id,
                )
        else:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.unsupported_node_emitted",
                "Unsupported capability decisions cannot own emitted plan nodes.",
                node_id=node.id,
            )

    for decision in plan.decisions.values():
        if (
            decision.status != CapabilityStatus.UNSUPPORTED
            and decision.id not in decision_owners
        ):
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.decision_orphan",
                "Native and raster-fallback decisions require an emitted plan node.",
                node_id=decision.node_ref,
            )


def _native_mask_nodes(
    mask: MaskPlan,
    nodes_by_uir_ref: Mapping[str, list[FGUIPlanNode]],
) -> tuple[FGUIPlanNode | None, tuple[FGUIPlanNode, ...]]:
    source_matches = nodes_by_uir_ref.get(mask.mask_node_ref, [])
    source = source_matches[0] if len(source_matches) == 1 else None
    contents = tuple(
        matches[0]
        for ref in mask.content_node_refs
        if len(matches := nodes_by_uir_ref.get(ref, [])) == 1
    )
    return source, contents


def _validate_masks(
    plan: FGUIPlanDocument,
    decisions_by_id: Mapping[str, CapabilityDecision],
    diagnostics: list[Diagnostic],
    seen: set[tuple[str, str | None, str | None]],
) -> None:
    mask_targets: dict[str, list[FGUIPlanNode]] = defaultdict(list)
    nodes_by_uir_ref: dict[str, list[FGUIPlanNode]] = defaultdict(list)
    for node in plan.nodes.values():
        nodes_by_uir_ref[node.uir_node_ref].append(node)
        if node.mask_ref is None:
            continue
        if node.mask_ref not in plan.masks:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.mask_missing",
                "FairyGUI plan mask does not exist.",
                node_id=node.id,
            )
        else:
            mask_targets[node.mask_ref].append(node)

    for uir_ref, nodes in nodes_by_uir_ref.items():
        if len(nodes) > 1:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.uir_node_duplicate",
                "More than one plan node owns the same UIR node.",
                node_id=uir_ref,
            )

    for key in sorted(plan.masks):
        mask = plan.masks[key]
        if key != mask.id:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.mask_key_mismatch",
                "FairyGUI mask key differs from its ID.",
                path=f"$.masks.{key}",
            )
        targets = mask_targets.get(mask.id, [])
        if not targets:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.mask_orphan",
                "FairyGUI mask is not owned by a plan node.",
                path=f"$.masks.{key}",
            )
        elif len(targets) > 1:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.mask_multiple_targets",
                "FairyGUI mask is assigned to more than one target node.",
                path=f"$.masks.{key}",
            )

        if mask.resource_ref is not None and mask.resource_ref not in plan.resources:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.resource_missing",
                "FairyGUI mask resource does not exist.",
                path=f"$.masks.{key}.resourceRef",
            )
        if (
            not mask.mask_node_ref
            or not mask.content_node_refs
            or mask.mask_node_ref in mask.content_node_refs
            or len(set(mask.content_node_refs)) != len(mask.content_node_refs)
            or any(not content_ref for content_ref in mask.content_node_refs)
        ):
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.mask_hierarchy_incoherent",
                "Mask source and content references must be distinct.",
                path=f"$.masks.{key}",
            )

        if mask.mode == MaskMode.RASTER_SUBTREE:
            _validate_raster_mask(
                plan, mask, targets, nodes_by_uir_ref, decisions_by_id, diagnostics, seen
            )
        else:
            _validate_native_mask(
                mask, targets, nodes_by_uir_ref, decisions_by_id, diagnostics, seen
            )

    native_clip_sources = {
        mask.mask_node_ref
        for mask in plan.masks.values()
        if mask.mode == MaskMode.NATIVE_CLIP
        and len(mask_targets.get(mask.id, [])) == 1
    }
    for node in plan.nodes.values():
        decision = _decision_for_node(node, decisions_by_id)
        if (
            decision is not None
            and decision.rule_id == "fgui.native.clip_source"
            and node.uir_node_ref not in native_clip_sources
        ):
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.decision_mask_role_incoherent",
                "Native clip-source decisions require a native clip mask role.",
                node_id=node.id,
            )


def _validate_raster_mask(
    plan: FGUIPlanDocument,
    mask: MaskPlan,
    targets: list[FGUIPlanNode],
    nodes_by_uir_ref: Mapping[str, list[FGUIPlanNode]],
    decisions_by_id: Mapping[str, CapabilityDecision],
    diagnostics: list[Diagnostic],
    seen: set[tuple[str, str | None, str | None]],
) -> None:
    if mask.resource_ref is None:
        _append_once(
            diagnostics,
            seen,
            "fgui.plan.mask_resource_incoherent",
            "Raster-subtree masks require a resource.",
            path=f"$.masks.{mask.id}",
        )
    for target in targets:
        decision = _decision_for_node(target, decisions_by_id)
        if target.type != PlanNodeType.RASTER_SUBTREE:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.mask_node_type_incoherent",
                "Raster-subtree mask target must be a raster-subtree node.",
                node_id=target.id,
            )
        if target.resource_ref != mask.resource_ref:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.mask_resource_incoherent",
                "Raster mask and target must own the same resource.",
                node_id=target.id,
            )
        if (
            decision is None
            or decision.status != CapabilityStatus.RASTER_FALLBACK
            or decision.rule_id != "fgui.fallback.raster_subtree"
        ):
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.mask_decision_incoherent",
                "Raster mask target requires a raster-fallback decision.",
                node_id=target.id,
            )

    emitted_refs = {mask.mask_node_ref, *mask.content_node_refs}.intersection(
        nodes_by_uir_ref
    )
    if emitted_refs:
        _append_once(
            diagnostics,
            seen,
            "fgui.plan.raster_descendant_duplicate",
            "Raster mask source/content nodes cannot also be emitted natively.",
            path=f"$.masks.{mask.id}",
        )


def _validate_native_mask(
    mask: MaskPlan,
    targets: list[FGUIPlanNode],
    nodes_by_uir_ref: Mapping[str, list[FGUIPlanNode]],
    decisions_by_id: Mapping[str, CapabilityDecision],
    diagnostics: list[Diagnostic],
    seen: set[tuple[str, str | None, str | None]],
) -> None:
    source, contents = _native_mask_nodes(mask, nodes_by_uir_ref)
    if source is None:
        _append_once(
            diagnostics,
            seen,
            "fgui.plan.mask_source_missing",
            "Native mask source node does not exist exactly once.",
            path=f"$.masks.{mask.id}.maskNodeRef",
        )
    for content_ref in mask.content_node_refs:
        if len(nodes_by_uir_ref.get(content_ref, [])) != 1:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.mask_content_missing",
                "Native mask content node does not exist exactly once.",
                node_id=content_ref,
            )
    if mask.resource_ref is not None:
        _append_once(
            diagnostics,
            seen,
            "fgui.plan.mask_resource_incoherent",
            "Native masks cannot own a raster-subtree resource.",
            path=f"$.masks.{mask.id}.resourceRef",
        )

    for target in targets:
        if target.type != PlanNodeType.CONTAINER:
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.mask_node_type_incoherent",
                "Native mask target must be a container node.",
                node_id=target.id,
            )
        participants = (() if source is None else (source,)) + contents
        if any(node.parent_id != target.id for node in participants):
            _append_once(
                diagnostics,
                seen,
                "fgui.plan.mask_hierarchy_incoherent",
                "Native mask participants must be children of the target.",
                node_id=target.id,
            )
        if source is not None and len(contents) == len(mask.content_node_refs):
            expected = (source.id, *(node.id for node in contents))
            try:
                start = target.children.index(source.id)
            except ValueError:
                start = -1
            if start < 0 or target.children[start : start + len(expected)] != expected:
                _append_once(
                    diagnostics,
                    seen,
                    "fgui.plan.mask_hierarchy_incoherent",
                    "Native mask content must immediately follow its source.",
                    node_id=target.id,
                )

    if source is None:
        return
    decision = _decision_for_node(source, decisions_by_id)
    if mask.mode == MaskMode.NATIVE_CLIP:
        role_valid = (
            mask.kind in {MaskKind.RECTANGLE, MaskKind.ROUNDED_RECTANGLE}
            and source.type == PlanNodeType.CONTAINER
            and source.resource_ref is None
        )
        decision_valid = (
            decision is not None
            and decision.status == CapabilityStatus.NATIVE
            and decision.rule_id == "fgui.native.clip_source"
        )
    else:
        role_valid = (
            mask.mode == MaskMode.NATIVE_MASK
            and mask.kind == MaskKind.IMAGE
            and source.type == PlanNodeType.IMAGE
            and source.resource_ref is not None
        )
        decision_valid = (
            decision is not None
            and decision.status == CapabilityStatus.NATIVE
            and decision.rule_id == "fgui.native.image"
        )
    if not role_valid:
        _append_once(
            diagnostics,
            seen,
            "fgui.plan.mask_node_type_incoherent",
            "Native mask mode and source node role are inconsistent.",
            node_id=source.id,
        )
    if not decision_valid:
        _append_once(
            diagnostics,
            seen,
            "fgui.plan.mask_decision_incoherent",
            "Native mask mode and source decision are inconsistent.",
            node_id=source.id,
        )


def validate_fgui_plan(plan: FGUIPlanDocument) -> tuple[Diagnostic, ...]:
    """Return every independently detectable semantic error in stable order."""
    diagnostics: list[Diagnostic] = []
    seen: set[tuple[str, str | None, str | None]] = set()

    for path in _binding_leak_paths(plan.model_dump(mode="json", by_alias=True)):
        _append_once(
            diagnostics,
            seen,
            "fgui.plan.binding_field_leak",
            "Generation plans cannot contain target-project binding fields.",
            path=path,
        )

    _validate_tree(plan, diagnostics, seen)
    _validate_resources(plan, diagnostics, seen)
    decisions_by_id = _validate_decisions(plan, diagnostics, seen)
    _validate_node_payload_and_decision(plan, decisions_by_id, diagnostics, seen)
    _validate_masks(plan, decisions_by_id, diagnostics, seen)

    is_blocked = bool(diagnostics) or any(
        item.severity == Severity.ERROR for item in plan.diagnostics
    ) or any(decision.blocking for decision in plan.decisions.values())
    if plan.bindable == is_blocked:
        _append_once(
            diagnostics,
            seen,
            "fgui.plan.bindable_inconsistent",
            "Plan bindability disagrees with embedded errors or blocking decisions.",
        )
    return tuple(diagnostics)


def canonical_plan_bytes(plan: FGUIPlanDocument) -> bytes:
    """Serialize a plan with stable object ordering and no insignificant whitespace."""
    payload = plan.model_dump(mode="json", by_alias=True)
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def plan_sha256(plan: FGUIPlanDocument) -> str:
    """Return the SHA-256 digest of the canonical plan representation."""
    return hashlib.sha256(canonical_plan_bytes(plan)).hexdigest()
