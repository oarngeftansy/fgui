import json
from pathlib import Path

from lxml import etree

from figma_to_fgui.classify import classify_tree
from figma_to_fgui.generate import generate_staging
from figma_to_fgui.normalize import normalize_document
from figma_to_fgui.rules import load_rules


def test_generates_parseable_xml_and_reports_rounding(tmp_path: Path) -> None:
    raw = json.loads(Path("tests/fixtures/figma/simple-frame.json").read_text("utf-8"))
    roots, _ = normalize_document(raw)
    decisions = classify_tree(roots, load_rules(Path("rules/default/classification.yaml")))
    files, diagnostics = generate_staging(roots, decisions, "Sample", tmp_path)
    output = tmp_path / "Sample/Panel/Panel_Sample_Main.xml"
    etree.parse(str(output))
    text = output.read_text("utf-8")
    assert 'xy="100,51"' in text
    assert any(item.code == "geometry.rounded" for item in diagnostics)
    assert files[0].relative_path == "Sample/Panel/Panel_Sample_Main.xml"
