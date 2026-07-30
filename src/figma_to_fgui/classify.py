from collections.abc import Iterable

from figma_to_fgui.models import ClassificationDecision, NormalizedNode
from figma_to_fgui.rules import Rule


def _walk(nodes: Iterable[NormalizedNode]) -> Iterable[NormalizedNode]:
    for node in nodes:
        yield node
        yield from _walk(node.children)


def _matches(node: NormalizedNode, rule: Rule) -> tuple[bool, tuple[str, ...]]:
    evidence: list[str] = []
    expected_type = rule.when.get("type")
    if expected_type is not None and node.type != expected_type:
        return False, ()
    if expected_type is not None:
        evidence.append(f"type={node.type}")
    min_width = rule.when.get("minWidth")
    if min_width is not None and node.bounds.width < float(min_width):
        return False, ()
    if min_width is not None:
        evidence.append(f"width>={min_width}")
    min_children = rule.when.get("minChildren")
    if min_children is not None and len(node.children) < int(min_children):
        return False, ()
    if min_children is not None:
        evidence.append(f"children>={min_children}")
    return True, tuple(evidence or ("fallback",))


def classify_tree(
    roots: tuple[NormalizedNode, ...], rules: tuple[Rule, ...]
) -> tuple[ClassificationDecision, ...]:
    decisions: list[ClassificationDecision] = []
    for node in _walk(roots):
        for rule in rules:
            matched, evidence = _matches(node, rule)
            if matched:
                decisions.append(
                    ClassificationDecision(
                        node_id=node.id,
                        output_type=rule.action["outputType"],
                        rule_id=rule.id,
                        rule_version=rule.version,
                        evidence=evidence,
                        confidence=rule.confidence,
                    )
                )
                break
    return tuple(decisions)
