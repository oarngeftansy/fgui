import re
from collections import Counter

from figma_to_fgui.models import (
    ClassificationDecision,
    Diagnostic,
    NormalizedNode,
    Severity,
)
from figma_to_fgui.tree import walk_nodes

SEMANTIC_NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{0,63}$"
_SEMANTIC_NAME = re.compile(SEMANTIC_NAME_PATTERN)


def is_valid_semantic_name(value: str) -> bool:
    return _SEMANTIC_NAME.fullmatch(value) is not None


def _warning(code: str, node_id: str, message: str) -> Diagnostic:
    return Diagnostic(code=code, severity=Severity.WARNING, message=message, node_id=node_id)


def _index_nodes(roots: tuple[NormalizedNode, ...]) -> dict[str, NormalizedNode]:
    return {node.id: node for node in walk_nodes(roots)}


def validate_semantic_overrides(
    roots: tuple[NormalizedNode, ...],
    overrides: tuple[ClassificationDecision, ...],
) -> tuple[tuple[ClassificationDecision, ...], tuple[Diagnostic, ...]]:
    """Accept only tree-scoped overrides with globally unambiguous semantic names."""
    nodes = _index_nodes(roots)
    diagnostics: list[Diagnostic] = []
    counts = Counter(item.node_id for item in overrides)
    duplicate_nodes: set[str] = set()
    candidates: list[ClassificationDecision] = []
    for item in overrides:
        if counts[item.node_id] > 1:
            if item.node_id not in duplicate_nodes:
                diagnostics.append(
                    _warning(
                        "semantic.duplicate_decision",
                        item.node_id,
                        "Every node may have at most one semantic decision.",
                    )
                )
                duplicate_nodes.add(item.node_id)
            continue
        if item.node_id not in nodes:
            diagnostics.append(
                _warning(
                    "semantic.unknown_node",
                    item.node_id,
                    "Semantic decision references a node outside the normalized tree.",
                )
            )
            continue
        if item.semantic_name is not None and not is_valid_semantic_name(item.semantic_name):
            diagnostics.append(
                _warning(
                    "semantic.invalid_name",
                    item.node_id,
                    "Semantic names must use bounded canonical identifiers.",
                )
            )
            continue
        candidates.append(item)

    candidate_names = Counter(
        item.semantic_name.casefold()
        for item in candidates
        if item.semantic_name is not None
    )
    existing_names: dict[str, set[str]] = {}
    for node_id, node in nodes.items():
        existing_names.setdefault(node.name.casefold(), set()).add(node_id)

    accepted: list[ClassificationDecision] = []
    for item in candidates:
        if item.semantic_name is not None:
            normalized_name = item.semantic_name.casefold()
            existing_owners = existing_names.get(normalized_name, set())
            if candidate_names[normalized_name] > 1 or existing_owners - {item.node_id}:
                diagnostics.append(
                    _warning(
                        "semantic.name_conflict",
                        item.node_id,
                        "Semantic names must be unique across AI decisions and existing nodes.",
                    )
                )
                continue
        accepted.append(item)
    return tuple(accepted), tuple(diagnostics)
