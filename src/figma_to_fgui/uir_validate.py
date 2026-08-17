import hashlib
import json

from figma_to_fgui.models import Diagnostic, Severity
from figma_to_fgui.uir_models import ConversionMode, MappingStatus, UIRDocument


def _error(code: str, message: str, node_id: str | None = None) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=Severity.ERROR,
        message=message,
        node_id=node_id,
    )


def validate_uir(document: UIRDocument) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    ownership: dict[str, str] = {}

    for root_id in document.roots:
        if root_id not in document.nodes:
            diagnostics.append(
                _error("uir.root_missing", "UIR root does not exist.", root_id)
            )

    for key, node in document.nodes.items():
        if key != node.id:
            diagnostics.append(
                _error("uir.node_key_mismatch", "UIR node key differs from its ID.", node.id)
            )
        if node.parent_id is not None and node.parent_id not in document.nodes:
            diagnostics.append(
                _error(
                    "uir.parent_missing", "UIR parent node does not exist.", node.id
                )
            )
        for child_id in node.children:
            child = document.nodes.get(child_id)
            if child is None:
                diagnostics.append(
                    _error("uir.child_missing", "UIR child node does not exist.", node.id)
                )
                continue
            previous_owner = ownership.get(child_id)
            if previous_owner is not None and previous_owner != node.id:
                diagnostics.append(
                    _error(
                        "uir.child_multiple_parents",
                        "UIR child is owned by more than one parent.",
                        child_id,
                    )
                )
            else:
                ownership[child_id] = node.id
            if child.parent_id != node.id:
                diagnostics.append(
                    _error(
                        "uir.parent_mismatch",
                        "UIR child and parent references are not symmetric.",
                        child_id,
                    )
                )

        decision_ref = node.semantic.decision_ref
        if decision_ref is not None and decision_ref not in document.mapping_decisions:
            diagnostics.append(
                _error(
                    "uir.decision_missing",
                    "UIR semantic mapping decision does not exist.",
                    node.id,
                )
            )
        asset_ref = node.conversion.asset_ref
        if asset_ref is not None and asset_ref not in document.assets:
            diagnostics.append(
                _error("uir.asset_missing", "UIR conversion asset does not exist.", node.id)
            )
        if (
            node.component is not None
            and node.component.definition_ref is not None
            and node.component.definition_ref not in document.component_definitions
        ):
            diagnostics.append(
                _error(
                    "uir.component_definition_missing",
                    "UIR component definition does not exist.",
                    node.id,
                )
            )
        if (
            node.conversion.mode == ConversionMode.COMPONENT_REFERENCE
            and decision_ref is None
        ):
            diagnostics.append(
                _error(
                    "uir.component_decision_required",
                    "Component reference conversion requires a mapping decision.",
                    node.id,
                )
            )

    for decision in document.mapping_decisions.values():
        if decision.status == MappingStatus.CONFLICT:
            diagnostics.append(
                _error(
                    "uir.mapping_conflict",
                    "UIR contains an unresolved component mapping conflict.",
                )
            )

    return tuple(diagnostics)


def canonical_uir_bytes(document: UIRDocument) -> bytes:
    payload = document.model_dump(mode="json", by_alias=True)
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def uir_sha256(document: UIRDocument) -> str:
    return hashlib.sha256(canonical_uir_bytes(document)).hexdigest()
