import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
from lxml import etree

from figma_to_fgui.classify import classify_tree
from figma_to_fgui.generate import generate_staging
from figma_to_fgui.models import ClassificationDecision, DecisionSource
from figma_to_fgui.normalize import normalize_document
from figma_to_fgui.project_index import index_project
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


def test_registers_no_asset_panel_in_package_xml(tmp_path: Path) -> None:
    raw = json.loads(Path("tests/fixtures/figma/simple-frame.json").read_text("utf-8"))
    roots, _ = normalize_document(raw)
    decisions = classify_tree(roots, load_rules(Path("rules/default/classification.yaml")))
    project_root = tmp_path / "project"
    shutil.copytree(Path("tests/fixtures/fgui"), project_root)
    staging_root = tmp_path / "staging"

    files, _ = generate_staging(
        roots,
        decisions,
        "Sample",
        staging_root,
        project_root,
        index_project(project_root),
    )

    assert "Sample/Panel/Panel_Sample_Main.xml" in {item.relative_path for item in files}
    assert "Sample/package.xml" in {item.relative_path for item in files}
    package = etree.parse(str(staging_root / "Sample" / "package.xml"))
    registered = package.xpath(
        "./resources/component[@name='Panel_Sample_Main.xml' and @path='/Panel/']"
    )
    assert len(registered) == 1


def test_rejects_duplicate_top_level_panel_names(tmp_path: Path) -> None:
    first = json.loads(Path("tests/fixtures/figma/simple-frame.json").read_text("utf-8"))
    second = deepcopy(first)
    second["id"] = "2:1"
    second["name"] = "main"
    second["children"][0]["id"] = "2:2"
    roots, _ = normalize_document({"roots": [first, second]})
    decisions = classify_tree(roots, load_rules(Path("rules/default/classification.yaml")))

    with pytest.raises(ValueError, match="duplicate panel names"):
        generate_staging(roots, decisions, "Sample", tmp_path)


def test_uses_validated_semantic_name_for_panel_output(tmp_path: Path) -> None:
    raw = json.loads(Path("tests/fixtures/figma/simple-frame.json").read_text("utf-8"))
    roots, _ = normalize_document(raw)
    decisions = list(classify_tree(roots, load_rules(Path("rules/default/classification.yaml"))))
    decisions[0] = ClassificationDecision(
        node_id="1:1",
        output_type="PANEL",
        rule_id="ai.semantic.v1",
        rule_version=1,
        evidence=("validated structured AI decision",),
        confidence=0.9,
        source=DecisionSource.AI,
        semantic_name="Checkout",
    )

    generate_staging(roots, tuple(decisions), "Sample", tmp_path)

    assert (tmp_path / "Sample/Panel/Panel_Sample_Checkout.xml").is_file()


def test_rejects_unvalidated_semantic_name_before_writing_paths(tmp_path: Path) -> None:
    raw = json.loads(Path("tests/fixtures/figma/simple-frame.json").read_text("utf-8"))
    roots, _ = normalize_document(raw)
    decisions = list(classify_tree(roots, load_rules(Path("rules/default/classification.yaml"))))
    decisions[0] = ClassificationDecision(
        node_id="1:1",
        output_type="PANEL",
        rule_id="ai.semantic.v1",
        rule_version=1,
        evidence=("unvalidated external override",),
        confidence=0.9,
        source=DecisionSource.AI,
        semantic_name="../escape",
    )

    with pytest.raises(ValueError, match="semantic name"):
        generate_staging(roots, tuple(decisions), "Sample", tmp_path)

    assert not (tmp_path / "Sample").exists()


def test_rejects_case_insensitive_generated_object_name_collisions(tmp_path: Path) -> None:
    raw = json.loads(Path("tests/fixtures/figma/simple-frame.json").read_text("utf-8"))
    duplicate = deepcopy(raw["children"][0])
    duplicate["id"] = "1:3"
    duplicate["name"] = "title"
    raw["children"].append(duplicate)
    roots, _ = normalize_document(raw)
    decisions = classify_tree(roots, load_rules(Path("rules/default/classification.yaml")))

    with pytest.raises(ValueError, match="duplicate generated object names"):
        generate_staging(roots, decisions, "Sample", tmp_path)

    assert not (tmp_path / "Sample").exists()


def test_rejects_case_only_existing_package_component_before_writing(tmp_path: Path) -> None:
    raw = json.loads(Path("tests/fixtures/figma/simple-frame.json").read_text("utf-8"))
    roots, _ = normalize_document(raw)
    decisions = list(classify_tree(roots, load_rules(Path("rules/default/classification.yaml"))))
    decisions[0] = ClassificationDecision(
        node_id="1:1",
        output_type="PANEL",
        rule_id="ai.semantic.v1",
        rule_version=1,
        evidence=("validated structured AI decision",),
        confidence=0.9,
        source=DecisionSource.AI,
        semantic_name="main",
    )
    project = tmp_path / "project"
    shutil.copytree(Path("tests/fixtures/fgui"), project)
    package_path = project / "Sample/package.xml"
    package = etree.parse(str(package_path))
    etree.SubElement(
        package.getroot().find("resources"),
        "component",
        id="cmp-case",
        name="Panel_Sample_Main.xml",
        path="/Panel/",
        exported="true",
    )
    package.write(str(package_path), encoding="utf-8", xml_declaration=True)
    staging = tmp_path / "staging"

    with pytest.raises(ValueError, match="case-insensitive panel collision"):
        generate_staging(
            roots,
            tuple(decisions),
            "Sample",
            staging,
            project,
            index_project(project),
        )

    assert not staging.exists()


def test_rejects_case_only_existing_panel_file_before_writing(tmp_path: Path) -> None:
    raw = json.loads(Path("tests/fixtures/figma/simple-frame.json").read_text("utf-8"))
    roots, _ = normalize_document(raw)
    decisions = list(classify_tree(roots, load_rules(Path("rules/default/classification.yaml"))))
    decisions[0] = ClassificationDecision(
        node_id="1:1",
        output_type="PANEL",
        rule_id="ai.semantic.v1",
        rule_version=1,
        evidence=("validated structured AI decision",),
        confidence=0.9,
        source=DecisionSource.AI,
        semantic_name="main",
    )
    project = tmp_path / "project"
    shutil.copytree(Path("tests/fixtures/fgui"), project)
    existing = project / "Sample/Panel/Panel_Sample_Main.xml"
    existing.parent.mkdir()
    existing.write_text("<component name='Panel_Sample_Main'/>", "utf-8")
    staging = tmp_path / "staging"

    with pytest.raises(ValueError, match="case-insensitive panel collision"):
        generate_staging(
            roots,
            tuple(decisions),
            "Sample",
            staging,
            project,
            index_project(project),
        )

    assert not staging.exists()


def test_allows_exact_existing_panel_name_as_an_update(tmp_path: Path) -> None:
    raw = json.loads(Path("tests/fixtures/figma/simple-frame.json").read_text("utf-8"))
    roots, _ = normalize_document(raw)
    decisions = classify_tree(roots, load_rules(Path("rules/default/classification.yaml")))
    project = tmp_path / "project"
    shutil.copytree(Path("tests/fixtures/fgui"), project)
    package_path = project / "Sample/package.xml"
    package = etree.parse(str(package_path))
    etree.SubElement(
        package.getroot().find("resources"),
        "component",
        id="cmp-main",
        name="Panel_Sample_Main.xml",
        path="/Panel/",
        exported="true",
    )
    package.write(str(package_path), encoding="utf-8", xml_declaration=True)
    existing = project / "Sample/Panel/Panel_Sample_Main.xml"
    existing.parent.mkdir()
    existing.write_text("<component name='Panel_Sample_Main'/>", "utf-8")
    staging = tmp_path / "staging"

    generate_staging(
        roots,
        decisions,
        "Sample",
        staging,
        project,
        index_project(project),
    )

    assert (staging / "Sample/Panel/Panel_Sample_Main.xml").is_file()
    staged_package = etree.parse(str(staging / "Sample/package.xml"))
    assert len(staged_package.xpath("./resources/component[@name='Panel_Sample_Main.xml']")) == 1
