import pytest

from figma_to_fgui.fgui_capabilities import analyze_capabilities, decision_for_node
from figma_to_fgui.models import Bounds
from figma_to_fgui.uir_models import (
    ConversionMode,
    MappingStatus,
    UIRAsset,
    UIRConversion,
    UIRDocument,
    UIRGeometry,
    UIRMappingDecision,
    UIRNode,
    UIRNodeSource,
    UIRSemantic,
    UIRSource,
)


def _node(
    source_type: str,
    *,
    name: str = "Node",
    width: float = 100,
    conversion: UIRConversion | None = None,
    decision_ref: str | None = None,
) -> UIRNode:
    return UIRNode(
        id="node:fixture",
        source=UIRNodeSource(
            nodeId="figma:fixture",
            type=source_type,
            name=name,
            fingerprint="b" * 64,
        ),
        semantic=UIRSemantic(decisionRef=decision_ref),
        zIndex=0,
        geometry=UIRGeometry(
            resolvedBounds=Bounds(x=0, y=0, width=width, height=100)
        ),
        conversion=conversion or UIRConversion(mode=ConversionMode.NATIVE),
    )


def _document(
    node: UIRNode,
    *,
    assets: dict[str, UIRAsset] | None = None,
    mapping_decisions: dict[str, UIRMappingDecision] | None = None,
) -> UIRDocument:
    return UIRDocument(
        documentId="uir:fixture",
        compilerVersion="uir-v1",
        source=UIRSource(revision="a" * 64, selectionId="selection"),
        roots=(node.id,),
        nodes={node.id: node},
        assets=assets or {},
        mappingDecisions=mapping_decisions or {},
    )


def document_with_node(source_type: str) -> tuple[UIRNode, UIRDocument]:
    asset_ref = "asset:fixture" if source_type == "RECTANGLE" else None
    node = _node(
        source_type,
        conversion=UIRConversion(mode=ConversionMode.NATIVE, assetRef=asset_ref),
    )
    assets = (
        {asset_ref: UIRAsset(id=asset_ref, logicalId="fixture", mimeType="image/png")}
        if asset_ref is not None
        else {}
    )
    return node, _document(node, assets=assets)


@pytest.mark.parametrize(
    ("source_type", "expected_rule"),
    [
        ("FRAME", "fgui.native.container"),
        ("GROUP", "fgui.native.container"),
        ("TEXT", "fgui.native.text"),
        ("RECTANGLE", "fgui.native.image"),
    ],
)
def test_generic_node_types_use_native_rules(
    source_type: str, expected_rule: str
) -> None:
    node, document = document_with_node(source_type)

    decision = decision_for_node(node, document, 1)

    assert decision.status == "native"
    assert decision.rule_id == expected_rule


def _instance_decision(status: MappingStatus) -> object:
    mapping = UIRMappingDecision(
        id="decision:mapping",
        candidateKey="button",
        status=status,
        confidence=1 if status == MappingStatus.VERIFIED else 0,
        ruleSource="fixture",
    )
    conversion = (
        UIRConversion(mode=ConversionMode.COMPONENT_REFERENCE)
        if status == MappingStatus.VERIFIED
        else UIRConversion(
            mode=ConversionMode.UNSUPPORTED,
            reasons=("component_mapping_conflict",),
        )
    )
    node = _node("INSTANCE", conversion=conversion, decision_ref=mapping.id)
    return decision_for_node(node, _document(node, mapping_decisions={mapping.id: mapping}), 1)


def test_verified_component_is_native_but_conflict_is_blocking() -> None:
    verified = _instance_decision(MappingStatus.VERIFIED)
    conflict = _instance_decision(MappingStatus.CONFLICT)

    assert verified.rule_id == "fgui.native.component_reference"
    assert conflict.status == "unsupported"
    assert conflict.blocking is True


def _raster_decision(asset: bool) -> object:
    asset_ref = "asset:raster"
    node = _node(
        "FRAME",
        conversion=UIRConversion(
            mode=ConversionMode.RASTER_FALLBACK,
            reasons=("composite_visual",),
            assetRef=asset_ref,
        ),
    )
    assets = (
        {asset_ref: UIRAsset(id=asset_ref, logicalId="raster", mimeType="image/png")}
        if asset
        else {}
    )
    return decision_for_node(node, _document(node, assets=assets), 1)


def test_explicit_raster_conversion_requires_an_asset() -> None:
    assert _raster_decision(asset=True).status == "rasterFallback"
    missing = _raster_decision(asset=False)

    assert missing.status == "unsupported"
    assert "raster_asset_missing" in missing.reasons


def test_rule_result_is_independent_of_name_and_dimensions() -> None:
    first = _node("FRAME", name="Village", width=1080)
    second = _node("FRAME", name="Inventory", width=750)

    first_decision = decision_for_node(first, _document(first), 1)
    second_decision = decision_for_node(second, _document(second), 1)

    assert (first_decision.status, first_decision.rule_id) == (
        second_decision.status,
        second_decision.rule_id,
    )


def test_analysis_uses_node_keys_in_sorted_order() -> None:
    first = _node("FRAME").model_copy(update={"id": "node:z"})
    second = _node("TEXT").model_copy(update={"id": "node:a"})
    document = _document(first).model_copy(update={"nodes": {first.id: first, second.id: second}})

    decisions = analyze_capabilities(document)

    assert list(decisions) == ["node:a", "node:z"]
