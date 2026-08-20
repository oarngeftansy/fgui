from __future__ import annotations

import json
from pathlib import Path

from figma_to_fgui.component_mapping import (
    load_mapping_catalog,
    validate_mapping_catalog,
)
from figma_to_fgui.fgui_plan_compile import compile_fgui_plan
from figma_to_fgui.fgui_plan_validate import validate_fgui_plan
from figma_to_fgui.normalize import normalize_document
from figma_to_fgui.project_index import index_project
from figma_to_fgui.uir_compile import compile_uir

PRODUCTION_ROOTS = (Path("src/figma_to_fgui"), Path("rules/default"))
PRODUCTION_SUFFIXES = frozenset({".json", ".py", ".toml", ".yaml", ".yml"})
SAMPLE_ONLY_MARKERS = (
    "村庄升阶",
    "village-root",
    "selection_village_ascend",
    "village_background",
    "primary-button",
    "rank-before",
)
# Plain `title` and `background` are intentionally not forbidden: they are generic
# presentation names, unlike the fixture-unique IDs above.
GENERIC_MAPPING_TERMS = ("common_primary_button", "通用一级按钮", "23:55")
GENERIC_MAPPING_ALLOWLIST = frozenset(
    {Path("rules/default/component-mapping-candidates.json")}
)


def _production_special_case_violations(
    overrides: dict[Path, str] | None = None,
) -> tuple[tuple[Path, str], ...]:
    replacements = overrides or {}
    files = sorted(
        path
        for root in PRODUCTION_ROOTS
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in PRODUCTION_SUFFIXES
    )
    violations: list[tuple[Path, str]] = []
    for path in files:
        content = replacements.get(path, path.read_text("utf-8"))
        violations.extend(
            (path, marker) for marker in SAMPLE_ONLY_MARKERS if marker in content
        )
        for term in GENERIC_MAPPING_TERMS:
            occurrences = content.count(term)
            allowed_once = path in GENERIC_MAPPING_ALLOWLIST and occurrences == 1
            if occurrences and not allowed_once:
                violations.append((path, term))
    return tuple(violations)


def test_village_is_a_generic_mapping_regression_not_a_writer_special_case() -> None:
    raw = json.loads(
        Path("tests/fixtures/uir/village-ascend-normalized.json").read_text("utf-8")
    )
    roots, diagnostics = normalize_document(raw)
    assert diagnostics == ()
    catalog = validate_mapping_catalog(
        load_mapping_catalog(Path("rules/default/component-mapping-candidates.json")),
        index_project(Path("tests/fixtures/uir/common-project")),
    )
    uir = compile_uir(
        roots,
        source_revision="7" * 64,
        selection_id="selection_village_ascend",
        mapping_catalog=catalog,
    )

    plan = compile_fgui_plan(uir)
    plan_diagnostics = validate_fgui_plan(plan)

    # The demand-side mapping remains generic input. UIR v1 does not yet carry a
    # generatable component tree, so Writer v1 must stop at the upstream boundary.
    assert not plan.bindable
    assert "fgui.component.definition_missing" in {
        item.code for item in (*plan.diagnostics, *plan_diagnostics)
    }
    assert len(plan.nodes) == len(uir.nodes) - 1
    assert len(plan.resources) == 1

    assert _production_special_case_violations() == ()


def test_special_case_scan_includes_cli_and_rejects_injected_village_marker() -> None:
    cli = Path("src/figma_to_fgui/cli.py")
    injected = cli.read_text("utf-8") + '\nSAMPLE_BRANCH = "village-root"\n'

    assert (cli, "village-root") in _production_special_case_violations(
        {cli: injected}
    )


def test_special_case_scan_rejects_injected_unique_fixture_node_id() -> None:
    cli = Path("src/figma_to_fgui/cli.py")
    injected = cli.read_text("utf-8") + '\nSAMPLE_NODE = "rank-before"\n'

    assert (cli, "rank-before") in _production_special_case_violations(
        {cli: injected}
    )


def test_new_project_writer_never_imports_project_binding() -> None:
    writer_sources = "\n".join(
        path.read_text("utf-8")
        for path in Path("src/figma_to_fgui").glob("fgui_new_project_*.py")
    )
    assert "project_binding" not in writer_sources.casefold()
    assert "index_project" not in writer_sources
