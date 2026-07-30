import json
from pathlib import Path

from figma_to_fgui.classify import classify_tree
from figma_to_fgui.normalize import normalize_document
from figma_to_fgui.rules import load_rules


def test_classification_records_rule_evidence_and_confidence() -> None:
    raw = json.loads(Path("tests/fixtures/figma/simple-frame.json").read_text("utf-8"))
    roots, _ = normalize_document(raw)
    decisions = classify_tree(roots, load_rules(Path("rules/default/classification.yaml")))
    by_node = {decision.node_id: decision for decision in decisions}
    assert by_node["1:1"].output_type == "PANEL"
    assert by_node["1:1"].rule_id == "node.top-level-panel"
    assert by_node["1:2"].output_type == "TEXT"
    assert by_node["1:2"].confidence == 1.0
