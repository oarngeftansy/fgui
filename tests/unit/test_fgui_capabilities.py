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
    node_id: str = "node:fixture",
    name: str = "Node",
    width: float = 100,
    conversion: UIRConversion | None = None,
    decision_ref: str | None = None,
    parent_id: str | None = None,
    children: tuple[str, ...] = (),
    visual: dict[str, object] | None = None,
) -> UIRNode:
    return UIRNode(
        id=node_id,
        source=UIRNodeSource(
            nodeId=node_id.removeprefix("node:"),
            type=source_type,
            name=name,
            fingerprint="b" * 64,
        ),
        semantic=UIRSemantic(decisionRef=decision_ref),
        parentId=parent_id,
        children=children,
        zIndex=0,
        geometry=UIRGeometry(
            resolvedBounds=Bounds(x=0, y=0, width=width, height=100)
        ),
        visual=visual or {},
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


def _mask_capability_document(
    *,
    kind: str = "rectangle",
    facts_update: dict[str, object] | None = None,
    raster_asset: bool = True,
) -> UIRDocument:
    mask_facts: dict[str, object] = {
        "kind": kind,
        "maskNodeRef": "node:mask",
        "contentNodeRefs": ["node:first", "node:second"],
        "safeRasterRootRef": "node:container" if kind == "boolean" else None,
        "effects": [],
    }
    mask_facts.update(facts_update or {})
    asset_ref = "asset:mask-raster" if kind == "boolean" else None
    container = _node(
        "FRAME",
        node_id="node:container",
        children=("node:mask", "node:first", "node:second"),
        visual={"mask": mask_facts},
        conversion=UIRConversion(mode=ConversionMode.NATIVE, assetRef=asset_ref),
    )
    mask = _node("RECTANGLE", node_id="node:mask", parent_id=container.id)
    first = _node("TEXT", node_id="node:first", parent_id=container.id)
    second = _node("TEXT", node_id="node:second", parent_id=container.id)
    assets = (
        {
            "asset:mask-raster": UIRAsset(
                id="asset:mask-raster",
                logicalId="mask-raster",
                mimeType="image/png",
            )
        }
        if asset_ref is not None and raster_asset
        else {}
    )
    return UIRDocument(
        documentId="uir:mask-capability",
        compilerVersion="uir-v1",
        source=UIRSource(revision="a" * 64, selectionId="selection"),
        roots=(container.id,),
        nodes={node.id: node for node in (container, mask, first, second)},
        assets=assets,
    )


def test_unknown_mask_fact_keys_are_blocking() -> None:
    document = _mask_capability_document(facts_update={"unexpected": True})

    decision = analyze_capabilities(document)["node:container"]

    assert decision.status == "unsupported"
    assert decision.rule_id == "fgui.mask.facts_invalid"
    assert decision.blocking is True


def test_invalid_mask_ownership_and_order_are_blocking() -> None:
    cross_parent = _mask_capability_document().model_copy(
        update={
            "nodes": {
                **_mask_capability_document().nodes,
                "node:mask": _mask_capability_document().nodes["node:mask"].model_copy(
                    update={"parent_id": "node:other"}
                ),
            }
        }
    )
    reversed_content = _mask_capability_document(
        facts_update={"contentNodeRefs": ["node:second", "node:first"]}
    )

    for document in (cross_parent, reversed_content):
        decision = analyze_capabilities(document)["node:container"]
        assert decision.status == "unsupported"
        assert decision.rule_id == "fgui.mask.invalid_hierarchy"


def test_complex_mask_requires_a_safe_raster_asset() -> None:
    valid = analyze_capabilities(_mask_capability_document(kind="boolean"))
    missing = analyze_capabilities(
        _mask_capability_document(kind="boolean", raster_asset=False)
    )

    assert valid["node:container"].status == "rasterFallback"
    assert valid["node:container"].rule_id == "fgui.fallback.raster_subtree"
    assert missing["node:container"].status == "unsupported"
    assert missing["node:container"].rule_id == "fgui.visual.effect_unsupported"


def test_safe_raster_root_must_own_every_consumed_descendant() -> None:
    document = _mask_capability_document(kind="boolean")
    container = document.nodes["node:container"].model_copy(
        update={"children": (*document.nodes["node:container"].children, "node:orphan")}
    )
    orphan = _node("TEXT", node_id="node:orphan", parent_id="node:elsewhere")
    document = document.model_copy(
        update={"nodes": {**document.nodes, container.id: container, orphan.id: orphan}}
    )

    decision = analyze_capabilities(document)["node:container"]

    assert decision.status == "unsupported"
    assert decision.rule_id == "fgui.mask.invalid_hierarchy"


def test_overlapping_safe_raster_subtrees_are_blocking() -> None:
    document = _mask_capability_document(kind="boolean")
    outer = document.nodes["node:container"].model_copy(
        update={
            "children": (*document.nodes["node:container"].children, "node:inner")
        }
    )
    inner = _node(
        "FRAME",
        node_id="node:inner",
        parent_id=outer.id,
        children=("node:inner-mask", "node:inner-content"),
        visual={
            "mask": {
                "kind": "blur",
                "maskNodeRef": "node:inner-mask",
                "contentNodeRefs": ["node:inner-content"],
                "safeRasterRootRef": "node:inner",
                "effects": ["blur"],
            }
        },
        conversion=UIRConversion(
            mode=ConversionMode.NATIVE, assetRef="asset:inner-raster"
        ),
    )
    inner_mask = _node("RECTANGLE", node_id="node:inner-mask", parent_id=inner.id)
    inner_content = _node("TEXT", node_id="node:inner-content", parent_id=inner.id)
    inner_asset = UIRAsset(
        id="asset:inner-raster",
        logicalId="inner-raster",
        mimeType="image/png",
    )
    document = document.model_copy(
        update={
            "nodes": {
                **document.nodes,
                outer.id: outer,
                inner.id: inner,
                inner_mask.id: inner_mask,
                inner_content.id: inner_content,
            },
            "assets": {**document.assets, inner_asset.id: inner_asset},
        }
    )

    decisions = analyze_capabilities(document)

    assert decisions[outer.id].rule_id == "fgui.mask.invalid_hierarchy"
    assert decisions[inner.id].rule_id == "fgui.mask.invalid_hierarchy"
