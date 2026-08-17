from figma_to_fgui.component_mapping import (
    ComponentMapping,
    ComponentMappingCatalog,
    FguiMappingTarget,
    FigmaMappingTarget,
    LegacyMappingHint,
    ResolvedMappingTarget,
)
from figma_to_fgui.models import Bounds, NormalizedNode
from figma_to_fgui.uir_compile import compile_uir


def sample_roots() -> tuple[NormalizedNode, ...]:
    return (
        NormalizedNode(
            id="frame",
            name="村庄升阶",
            type="FRAME",
            bounds=Bounds(x=100, y=200, width=1080, height=1923),
            children=(
                NormalizedNode(
                    id="title",
                    name="标题",
                    type="TEXT",
                    bounds=Bounds(x=130, y=233, width=239, height=40),
                    text="Village Ascend",
                    source_order=0,
                    raw_style={"fontSize": 36, "textAlignHorizontal": "LEFT"},
                ),
            ),
        ),
    )


def test_compile_preserves_order_source_facts_and_resolved_geometry() -> None:
    document = compile_uir(
        sample_roots(), source_revision="a" * 64, selection_id="selection_village"
    )
    root = document.nodes[document.roots[0]]
    child = document.nodes[root.children[0]]
    assert root.source.name == "村庄升阶"
    assert child.source.name == "标题"
    assert child.geometry.resolved_bounds == Bounds(
        x=30, y=33, width=239, height=40
    )
    assert child.text == {
        "content": "Village Ascend",
        "style": {"fontSize": 36, "textAlignHorizontal": "LEFT"},
    }


def test_compile_is_deterministic_for_the_same_inputs() -> None:
    first = compile_uir(
        sample_roots(), source_revision="a" * 64, selection_id="same"
    )
    second = compile_uir(
        sample_roots(), source_revision="a" * 64, selection_id="same"
    )
    assert first == second
    assert first.document_id == second.document_id


def test_compile_preserves_child_order_not_source_order_sorting() -> None:
    root = sample_roots()[0]
    later = root.children[0].model_copy(update={"id": "later", "source_order": 99})
    earlier = root.children[0].model_copy(update={"id": "earlier", "source_order": 0})
    document = compile_uir(
        (root.model_copy(update={"children": (later, earlier)}),),
        source_revision="a" * 64,
        selection_id="ordered",
    )
    compiled_root = document.nodes[document.roots[0]]
    assert [document.nodes[item].source.node_id for item in compiled_root.children] == [
        "later",
        "earlier",
    ]


def mapping_catalog(status: str) -> ComponentMappingCatalog:
    resolved = (
        ResolvedMappingTarget(
            package_id="qil5i1mk",
            component_id="v27f1nupomj",
            relative_path="assets/Common/Core/Button/Common_Btn_Primary.xml",
        )
        if status == "verified"
        else None
    )
    component = ComponentMapping(
        key="common_primary_button",
        figma=FigmaMappingTarget(names=("通用一级按钮",)),
        fgui=FguiMappingTarget(
            package="Common",
            component="Common_Btn_Primary",
            path="Core/Button/Common_Btn_Primary.xml",
        ),
        legacyHint=LegacyMappingHint(
            packageId="qil5i1mk", componentId="v27f1nupomj"
        ),
        source=("figma-to-fgui", "auto-panel"),
        status=cast(Literal["candidate", "verified", "missing", "conflict"], status),
        resolved=resolved,
        reason=None if status == "verified" else f"fixture_{status}",
    )
    return ComponentMappingCatalog(
        schemaVersion=1, sources=("figma-to-fgui", "auto-panel"), components=(component,)
    )


def instance_roots() -> tuple[NormalizedNode, ...]:
    return (
        NormalizedNode(
            id="button",
            name="通用一级按钮",
            type="INSTANCE",
            bounds=Bounds(x=0, y=0, width=300, height=80),
        ),
    )


def compile_with_status(status: str):
    return compile_uir(
        instance_roots(),
        source_revision="a" * 64,
        selection_id=f"selection_{status}",
        mapping_catalog=mapping_catalog(status),
    )


def test_verified_candidate_creates_engine_neutral_component_decision() -> None:
    document = compile_with_status("verified")
    node = next(item for item in document.nodes.values() if item.source.type == "INSTANCE")
    assert node.semantic.decision_ref is not None
    decision = document.mapping_decisions[node.semantic.decision_ref]
    assert decision.status == "verified"
    assert decision.candidate_key == "common_primary_button"
    assert node.conversion.mode == "componentReference"
    encoded = document.model_dump_json(by_alias=True)
    assert "qil5i1mk" not in encoded
    assert "v27f1nupomj" not in encoded


def test_missing_candidate_explicitly_falls_back_but_conflict_stays_blocking() -> None:
    missing = compile_with_status("missing")
    conflict = compile_with_status("conflict")
    missing_node = next(iter(missing.nodes.values()))
    conflict_node = next(iter(conflict.nodes.values()))
    assert missing_node.conversion.mode == "rasterFallback"
    assert conflict_node.conversion.mode == "unsupported"
    assert conflict_node.semantic.decision_ref is not None
    assert (
        conflict.mapping_decisions[conflict_node.semantic.decision_ref].status
        == "conflict"
    )


def test_unvalidated_candidate_catalog_is_rejected() -> None:
    with pytest.raises(ValueError, match="validated"):
        compile_with_status("candidate")
from typing import Literal, cast

import pytest
