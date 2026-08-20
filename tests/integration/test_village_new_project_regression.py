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

    writer_sources = "\n".join(
        path.read_text("utf-8")
        for path in Path("src/figma_to_fgui").glob("fgui_new_project_*.py")
    )
    for forbidden in (
        "村庄升阶",
        "village-root",
        "selection_village_ascend",
        "primary-button",
    ):
        assert forbidden not in writer_sources


def test_new_project_writer_never_imports_project_binding() -> None:
    writer_sources = "\n".join(
        path.read_text("utf-8")
        for path in Path("src/figma_to_fgui").glob("fgui_new_project_*.py")
    )
    assert "project_binding" not in writer_sources.casefold()
    assert "index_project" not in writer_sources
