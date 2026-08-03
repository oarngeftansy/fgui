from collections.abc import Iterable

from figma_to_fgui.models import (
    ClassificationDecision,
    DecisionSource,
    Diagnostic,
    NormalizedNode,
    Severity,
)
from figma_to_fgui.semantic_models import SemanticResponse, SemanticType

_OUTPUT_TYPES = {
    SemanticType.PANEL: "PANEL",
    SemanticType.COMPONENT: "COMPONENT",
    SemanticType.IMAGE: "IMAGE",
    SemanticType.TEXT: "TEXT",
    SemanticType.BUTTON: "BUTTON",
    SemanticType.LABEL: "LABEL",
    SemanticType.LIST: "LIST",
    SemanticType.SLIDER: "SLIDER",
}


def _index_tree(
    roots: Iterable[NormalizedNode],
) -> tuple[dict[str, NormalizedNode], dict[str, str | None]]:
    nodes: dict[str, NormalizedNode] = {}
    parents: dict[str, str | None] = {}

    def visit(node: NormalizedNode, parent_id: str | None) -> None:
        nodes[node.id] = node
        parents[node.id] = parent_id
        for child in node.children:
            visit(child, node.id)

    for root in roots:
        visit(root, None)
    return nodes, parents


def _is_descendant(node_id: str, ancestor_id: str, parents: dict[str, str | None]) -> bool:
    current_id = parents.get(node_id)
    while current_id is not None:
        if current_id == ancestor_id:
            return True
        current_id = parents.get(current_id)
    return False


def _contains(parent: NormalizedNode, child: NormalizedNode) -> bool:
    parent_right = parent.bounds.x + parent.bounds.width
    parent_bottom = parent.bounds.y + parent.bounds.height
    child_right = child.bounds.x + child.bounds.width
    child_bottom = child.bounds.y + child.bounds.height
    return (
        parent.bounds.x <= child.bounds.x
        and parent.bounds.y <= child.bounds.y
        and child_right <= parent_right
        and child_bottom <= parent_bottom
    )


def _warning(code: str, node_id: str, message: str) -> Diagnostic:
    return Diagnostic(code=code, severity=Severity.WARNING, message=message, node_id=node_id)


def validate_semantic_response(
    roots: tuple[NormalizedNode, ...], response: SemanticResponse
) -> tuple[tuple[ClassificationDecision, ...], tuple[Diagnostic, ...]]:
    """Convert only safe, tree-scoped semantic decisions into classification overrides."""
    nodes, parents = _index_tree(roots)
    decisions: list[ClassificationDecision] = []
    diagnostics: list[Diagnostic] = []
    for item in response.decisions:
        node = nodes.get(item.node_id)
        if node is None:
            diagnostics.append(
                _warning(
                    "semantic.unknown_node",
                    item.node_id,
                    "Semantic decision references a node outside the normalized tree.",
                )
            )
            continue
        child_ids = {child.id for child in node.children}
        if any(child_id not in child_ids for child_id in item.children_roles):
            diagnostics.append(
                _warning(
                    "semantic.invalid_child_role",
                    item.node_id,
                    "Semantic child roles must reference direct children of the decision node.",
                )
            )
            continue
        if item.reparent is not None:
            new_parent = nodes.get(item.reparent.new_parent)
            if item.reparent.new_parent == item.node_id or _is_descendant(
                item.reparent.new_parent, item.node_id, parents
            ):
                diagnostics.append(
                    _warning(
                        "semantic.reparent_cycle",
                        item.node_id,
                        "Suggested parent would create a tree cycle.",
                    )
                )
                continue
            if new_parent is None or not _contains(new_parent, node):
                diagnostics.append(
                    _warning(
                        "semantic.reparent_outside",
                        item.node_id,
                        "Suggested parent is missing or does not fully contain the node.",
                    )
                )
                continue
        decisions.append(
            ClassificationDecision(
                node_id=item.node_id,
                output_type=_OUTPUT_TYPES[item.semantic_type],
                rule_id="ai.semantic.v1",
                rule_version=1,
                evidence=("validated structured AI decision",),
                confidence=item.confidence,
                source=DecisionSource.AI,
                semantic_name=item.fgui_name,
            )
        )
    return tuple(decisions), tuple(diagnostics)
