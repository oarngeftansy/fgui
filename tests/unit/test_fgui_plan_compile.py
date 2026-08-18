import pytest

import figma_to_fgui.fgui_plan_compile as plan_compile
from figma_to_fgui.fgui_plan_compile import compile_fgui_plan
from figma_to_fgui.fgui_plan_models import (
    CapabilityDecision,
    CapabilityStatus,
    FGUIPlanDocument,
)
from figma_to_fgui.models import Bounds
from figma_to_fgui.uir_models import (
    ConversionMode,
    MappingStatus,
    UIRAsset,
    UIRComponentInstance,
    UIRConversion,
    UIRDocument,
    UIRGeometry,
    UIRMappingDecision,
    UIRNineSlice,
    UIRNode,
    UIRNodeSource,
    UIRSemantic,
    UIRSource,
)


def _node(
    node_id: str,
    source_type: str,
    *,
    parent_id: str | None = None,
    children: tuple[str, ...] = (),
    z_index: int = 0,
    bounds: Bounds | None = None,
    text: dict[str, object] | None = None,
    component: UIRComponentInstance | None = None,
    decision_ref: str | None = None,
    asset_ref: str | None = None,
    visual: dict[str, object] | None = None,
) -> UIRNode:
    return UIRNode(
        id=node_id,
        source=UIRNodeSource(
            nodeId=node_id.removeprefix("node:"),
            type=source_type,
            name=node_id,
            fingerprint="b" * 64,
        ),
        semantic=UIRSemantic(decisionRef=decision_ref),
        parentId=parent_id,
        children=children,
        zIndex=z_index,
        geometry=UIRGeometry(
            resolvedBounds=bounds or Bounds(x=0, y=0, width=100, height=100)
        ),
        visual=visual or {},
        text=text,
        component=component,
        conversion=UIRConversion(mode=ConversionMode.NATIVE, assetRef=asset_ref),
    )


def _document(
    roots: tuple[str, ...],
    nodes: dict[str, UIRNode],
    *,
    assets: dict[str, UIRAsset] | None = None,
    mapping_decisions: dict[str, UIRMappingDecision] | None = None,
) -> UIRDocument:
    return UIRDocument(
        documentId="uir:compile-fixture",
        compilerVersion="uir-v1",
        source=UIRSource(revision="a" * 64, selectionId="selection"),
        roots=roots,
        nodes=nodes,
        assets=assets or {},
        mappingDecisions=mapping_decisions or {},
    )


def generic_primitives_document() -> UIRDocument:
    root = _node(
        "node:root",
        "FRAME",
        children=("node:text", "node:image"),
        bounds=Bounds(x=0, y=0, width=400, height=300),
    )
    text = _node(
        "node:text",
        "TEXT",
        parent_id=root.id,
        z_index=0,
        bounds=Bounds(x=12, y=20, width=240, height=44),
        text={
            "content": "Generic title",
            "style": {"fontSize": 32, "textAlignHorizontal": "CENTER"},
        },
    )
    image = _node(
        "node:image",
        "RECTANGLE",
        parent_id=root.id,
        z_index=1,
        asset_ref="asset:image",
    )
    asset = UIRAsset(id="asset:image", logicalId="image", mimeType="image/png")
    return _document((root.id,), {root.id: root, text.id: text, image.id: image}, assets={asset.id: asset})


def component_document(status: MappingStatus) -> UIRDocument:
    mapping = UIRMappingDecision(
        id="decision:component",
        candidateKey="common_primary_button",
        status=status,
        confidence=1.0 if status == MappingStatus.VERIFIED else 0.0,
        ruleSource="fixture",
    )
    node = _node(
        "node:instance",
        "INSTANCE",
        decision_ref=mapping.id,
        component=UIRComponentInstance(variantProperties={"state": "normal"}),
    ).model_copy(
        update={"conversion": UIRConversion(mode=ConversionMode.COMPONENT_REFERENCE)}
    )
    return _document((node.id,), {node.id: node}, mapping_decisions={mapping.id: mapping})


def image_document(
    *, size: tuple[int, int], nine_slice: tuple[int, int, int, int] | None
) -> UIRDocument:
    asset = UIRAsset(
        id="asset:image",
        logicalId="image",
        mimeType="image/png",
        width=size[0],
        height=size[1],
        nineSlice=(
            None
            if nine_slice is None
            else UIRNineSlice(
                x=nine_slice[0],
                y=nine_slice[1],
                width=nine_slice[2],
                height=nine_slice[3],
            )
        ),
    )
    node = _node("node:image", "RECTANGLE", asset_ref=asset.id)
    return _document((node.id,), {node.id: node}, assets={asset.id: asset})


def only_node(plan: FGUIPlanDocument):
    return plan.nodes[plan.roots[0]]


def only_resource(plan: FGUIPlanDocument):
    return next(iter(plan.resources.values()))


def only_mask(plan: FGUIPlanDocument):
    return next(iter(plan.masks.values()))


def mask_document(
    *,
    kind: str,
    safe_raster: bool = False,
    source_missing: bool = False,
    cross_parent: bool = False,
) -> UIRDocument:
    mask_ref = "node:missing" if source_missing else "node:mask"
    mask_facts = {
        "kind": kind,
        "maskNodeRef": mask_ref,
        "contentNodeRefs": ["node:content", "node:group"],
        "safeRasterRootRef": "node:root" if safe_raster else None,
        "effects": [kind] if kind in {"boolean", "gradient", "blur", "blend"} else [],
    }
    raster_asset_ref = "asset:mask-raster" if safe_raster else None
    root = _node(
        "node:root",
        "FRAME",
        children=("node:mask", "node:content", "node:group"),
        asset_ref=raster_asset_ref,
        visual={"mask": mask_facts},
    )
    mask = _node(
        "node:mask",
        "RECTANGLE",
        parent_id="node:elsewhere" if cross_parent else root.id,
        asset_ref="asset:mask-source",
    )
    content = _node("node:content", "TEXT", parent_id=root.id, text={"content": "masked"})
    group = _node(
        "node:group",
        "GROUP",
        parent_id=root.id,
        children=("node:grandchild",),
    )
    grandchild = _node(
        "node:grandchild",
        "TEXT",
        parent_id=group.id,
        text={"content": "nested"},
    )
    nodes = {node.id: node for node in (root, mask, content, group, grandchild)}
    assets = {
        "asset:mask-source": UIRAsset(
            id="asset:mask-source",
            logicalId="mask-source",
            mimeType="image/png",
            sourceNodeId=mask.id,
        )
    }
    if safe_raster:
        assets["asset:mask-raster"] = UIRAsset(
            id="asset:mask-raster",
            logicalId="mask-raster",
            mimeType="image/png",
            sourceNodeId=root.id,
        )
    return _document((root.id,), nodes, assets=assets)


def test_compile_preserves_tree_transform_and_text_facts() -> None:
    plan = compile_fgui_plan(generic_primitives_document())

    root = plan.nodes[plan.roots[0]]
    text = next(plan.nodes[item] for item in root.children if plan.nodes[item].type == "text")

    assert text.transform.bounds == Bounds(x=12, y=20, width=240, height=44)
    assert text.text is not None
    assert text.text.content == "Generic title"
    assert text.text.font_size == 32
    assert text.text.horizontal_align == "CENTER"


def test_verified_component_uses_candidate_key_without_target_ids() -> None:
    plan = compile_fgui_plan(component_document(MappingStatus.VERIFIED))

    node = only_node(plan)
    assert node.type == "componentReference"
    assert node.component is not None
    assert node.component.candidate_key == "common_primary_button"
    assert node.component.variant_properties == {"state": "normal"}
    encoded = plan.model_dump_json(by_alias=True).encode("utf-8")
    assert b"packageId" not in encoded and b"componentId" not in encoded


def test_valid_nine_slice_is_preserved_and_invalid_grid_blocks() -> None:
    valid = compile_fgui_plan(
        image_document(size=(100, 80), nine_slice=(10, 10, 70, 50))
    )
    invalid = compile_fgui_plan(
        image_document(size=(100, 80), nine_slice=(10, 10, 100, 50))
    )

    assert only_resource(valid).nine_slice == (10, 10, 70, 50)
    assert invalid.bindable is False
    assert only_resource(invalid).nine_slice is None
    assert any(
        item.code == "fgui.resource.nine_slice_invalid" for item in invalid.diagnostics
    )


def test_ordinary_images_never_gain_inferred_nine_slice() -> None:
    plan = compile_fgui_plan(image_document(size=(100, 80), nine_slice=None))

    assert only_resource(plan).nine_slice is None


def test_plan_ids_and_resource_consumers_are_deterministic() -> None:
    first = compile_fgui_plan(generic_primitives_document())
    second = compile_fgui_plan(generic_primitives_document())

    assert first.model_dump(mode="json", by_alias=True) == second.model_dump(
        mode="json", by_alias=True
    )
    assert only_resource(first).consumers == tuple(sorted(only_resource(first).consumers))


def test_supplied_reviewed_decisions_are_used_without_reanalysis(monkeypatch) -> None:
    node = _node("node:text", "TEXT", text={"content": "Reviewed"})
    document = _document((node.id,), {node.id: node})
    reviewed = {
        node.id: CapabilityDecision(
            id="decision:reviewed",
            nodeRef=node.id,
            status=CapabilityStatus.NATIVE,
            ruleId="fgui.native.container",
            ruleVersion=7,
        )
    }

    def analysis_must_not_run(*args, **kwargs):
        raise AssertionError("reviewed decisions must bypass capability analysis")

    monkeypatch.setattr(plan_compile, "analyze_capabilities", analysis_must_not_run)

    plan = compile_fgui_plan(document, rule_version=7, decisions=reviewed)

    compiled = only_node(plan)
    assert compiled.type == "container"
    assert compiled.decision_ref == "decision:reviewed"
    assert plan.decisions == reviewed


def test_cyclic_uir_graph_is_blocked_without_recursion_error() -> None:
    first = _node("node:first", "FRAME", parent_id="node:second", children=("node:second",))
    second = _node("node:second", "FRAME", parent_id=first.id, children=(first.id,))
    document = _document((first.id,), {first.id: first, second.id: second})

    plan = compile_fgui_plan(document)

    assert plan.bindable is False
    assert any(item.code == "fgui.node.cycle" for item in plan.diagnostics)


def test_unsupported_reviewed_decision_never_emits_a_native_node() -> None:
    node = _node("node:text", "TEXT", text={"content": "Do not compile"})
    document = _document((node.id,), {node.id: node})
    decisions = {
        node.id: CapabilityDecision(
            id="decision:unsupported",
            nodeRef=node.id,
            status=CapabilityStatus.UNSUPPORTED,
            ruleId="fgui.native.text",
            ruleVersion=1,
        )
    }

    plan = compile_fgui_plan(document, decisions=decisions)

    assert plan.bindable is False
    assert plan.nodes == {}
    assert any(
        item.code == "fgui.decision.status_rule_incoherent"
        for item in plan.diagnostics
    )


def test_raster_fallback_decisions_require_raster_rule_and_resource() -> None:
    node = _node("node:frame", "FRAME")
    document = _document((node.id,), {node.id: node})
    native_rule = {
        node.id: CapabilityDecision(
            id="decision:raster-native-rule",
            nodeRef=node.id,
            status=CapabilityStatus.RASTER_FALLBACK,
            ruleId="fgui.native.container",
            ruleVersion=1,
        )
    }
    missing_resource = {
        node.id: CapabilityDecision(
            id="decision:raster-missing-resource",
            nodeRef=node.id,
            status=CapabilityStatus.RASTER_FALLBACK,
            ruleId="fgui.fallback.raster_subtree",
            ruleVersion=1,
        )
    }

    incoherent = compile_fgui_plan(document, decisions=native_rule)
    missing = compile_fgui_plan(document, decisions=missing_resource)

    assert incoherent.bindable is False
    assert incoherent.nodes == {}
    assert any(
        item.code == "fgui.decision.status_rule_incoherent"
        for item in incoherent.diagnostics
    )
    assert missing.bindable is False
    assert missing.nodes == {}
    assert any(
        item.code == "fgui.decision.raster_resource_missing"
        for item in missing.diagnostics
    )


def test_plan_decisions_are_sorted_independently_of_caller_mapping_order() -> None:
    document = generic_primitives_document()
    analyzed = plan_compile.analyze_capabilities(document)
    ascending = {node_id: analyzed[node_id] for node_id in sorted(analyzed)}
    descending = {node_id: analyzed[node_id] for node_id in sorted(analyzed, reverse=True)}

    first = compile_fgui_plan(document, decisions=ascending)
    second = compile_fgui_plan(document, decisions=descending)

    assert list(first.decisions) == sorted(ascending)
    assert first.model_dump(mode="json", by_alias=True) == second.model_dump(
        mode="json", by_alias=True
    )


def opaque_facts_document(
    style: dict[str, object], variants: dict[str, str]
) -> UIRDocument:
    mapping = UIRMappingDecision(
        id="decision:component",
        candidateKey="common_primary_button",
        status=MappingStatus.VERIFIED,
        confidence=1.0,
        ruleSource="fixture",
    )
    root = _node("node:root", "FRAME", children=("node:text", "node:instance"))
    text = _node(
        "node:text",
        "TEXT",
        parent_id=root.id,
        text={"content": "Stable facts", "style": style},
    )
    instance = _node(
        "node:instance",
        "INSTANCE",
        parent_id=root.id,
        decision_ref=mapping.id,
        component=UIRComponentInstance(variantProperties=variants),
    ).model_copy(
        update={"conversion": UIRConversion(mode=ConversionMode.COMPONENT_REFERENCE)}
    )
    return _document(
        (root.id,),
        {root.id: root, text.id: text, instance.id: instance},
        mapping_decisions={mapping.id: mapping},
    )


def test_opaque_plan_facts_are_canonicalized_independently_of_insertion_order() -> None:
    first = opaque_facts_document(
        {"zeta": {"second": 2, "first": 1}, "alpha": "start"},
        {"state": "normal", "size": "large"},
    )
    second = opaque_facts_document(
        {"alpha": "start", "zeta": {"first": 1, "second": 2}},
        {"size": "large", "state": "normal"},
    )

    first_plan = compile_fgui_plan(first)
    second_plan = compile_fgui_plan(second)

    text = next(node.text for node in first_plan.nodes.values() if node.type == "text")
    component = next(
        node.component
        for node in first_plan.nodes.values()
        if node.type == "componentReference"
    )
    assert text is not None
    assert component is not None
    assert list(text.style_facts) == ["alpha", "zeta"]
    assert list(text.style_facts["zeta"]) == ["first", "second"]
    assert list(component.variant_properties) == ["size", "state"]
    assert first_plan.model_dump_json(by_alias=True) == second_plan.model_dump_json(
        by_alias=True
    )


@pytest.mark.parametrize("kind", ["rectangle", "roundedRectangle"])
def test_rectangle_masks_compile_as_native_clip(kind: str) -> None:
    plan = compile_fgui_plan(mask_document(kind=kind))

    mask = only_mask(plan)
    assert mask.mode == "nativeClip"
    assert mask.kind == kind
    assert mask.mask_node_ref == "node:mask"
    assert mask.content_node_refs == ("node:content", "node:group")
    assert only_node(plan).mask_ref == mask.id
    assert plan.bindable is True


def test_simple_image_mask_compiles_as_native_mask() -> None:
    plan = compile_fgui_plan(mask_document(kind="image"))

    assert only_mask(plan).mode == "nativeMask"
    assert only_mask(plan).kind == "image"
    assert plan.bindable is True


@pytest.mark.parametrize("kind", ["boolean", "gradient", "blur", "blend"])
def test_complex_mask_rasterizes_only_safe_subtree(kind: str) -> None:
    document = mask_document(kind=kind, safe_raster=True)

    plan = compile_fgui_plan(document)

    raster = next(node for node in plan.nodes.values() if node.type == "rasterSubtree")
    emitted_source_ids = {node.uir_node_ref for node in plan.nodes.values()}
    source_descendant_ids = set(document.nodes["node:root"].children) | {
        "node:grandchild"
    }
    assert raster.uir_node_ref == "node:root"
    assert raster.resource_ref in plan.resources
    assert only_mask(plan).mode == "rasterSubtree"
    assert source_descendant_ids.isdisjoint(emitted_source_ids)
    assert plan.bindable is True


def test_missing_or_cross_parent_mask_is_blocking() -> None:
    for document in (
        mask_document(kind="rectangle", source_missing=True),
        mask_document(kind="rectangle", cross_parent=True),
    ):
        plan = compile_fgui_plan(document)
        assert plan.bindable is False
        assert any(
            item.code
            in {"fgui.mask.source_missing", "fgui.mask.invalid_hierarchy"}
            for item in plan.diagnostics
        )


def test_complex_mask_without_a_valid_raster_asset_is_blocking() -> None:
    plan = compile_fgui_plan(mask_document(kind="blur", safe_raster=False))

    assert plan.bindable is False
    assert any(
        item.code == "fgui.visual.effect_unsupported" for item in plan.diagnostics
    )


def test_raster_consumed_unsupported_descendants_do_not_block_or_emit() -> None:
    document = mask_document(kind="boolean", safe_raster=True)
    unsupported_mask = document.nodes["node:mask"].model_copy(
        update={
            "conversion": UIRConversion(
                mode=ConversionMode.UNSUPPORTED,
                reasons=("complex_mask_source",),
            )
        }
    )
    document = document.model_copy(
        update={"nodes": {**document.nodes, unsupported_mask.id: unsupported_mask}}
    )

    plan = compile_fgui_plan(document)

    assert plan.bindable is True
    assert "node:mask" not in {node.uir_node_ref for node in plan.nodes.values()}
    assert "node:mask" not in plan.decisions


def test_native_rectangle_clip_preserves_geometry_without_an_image_asset() -> None:
    document = mask_document(kind="rectangle")
    mask_source = document.nodes["node:mask"].model_copy(
        update={"conversion": UIRConversion(mode=ConversionMode.NATIVE)}
    )
    document = document.model_copy(
        update={
            "nodes": {**document.nodes, mask_source.id: mask_source},
            "assets": {},
        }
    )

    plan = compile_fgui_plan(document)

    assert plan.bindable is True
    assert only_mask(plan).mode == "nativeClip"
    planned_mask_source = next(
        node for node in plan.nodes.values() if node.uir_node_ref == "node:mask"
    )
    assert planned_mask_source.type == "container"
    assert planned_mask_source.resource_ref is None
    assert planned_mask_source.transform.bounds == document.nodes["node:mask"].geometry.resolved_bounds


def test_native_kind_with_complex_effects_uses_safe_raster_fallback() -> None:
    document = mask_document(kind="rectangle", safe_raster=True)
    root = document.nodes["node:root"]
    mask_facts = dict(root.visual["mask"])
    mask_facts["effects"] = ["blur"]
    root = root.model_copy(update={"visual": {"mask": mask_facts}})
    document = document.model_copy(
        update={"nodes": {**document.nodes, root.id: root}}
    )

    plan = compile_fgui_plan(document)

    assert plan.bindable is True
    assert only_mask(plan).mode == "rasterSubtree"


def test_invalid_nested_mask_is_consumed_by_valid_outer_raster() -> None:
    document = mask_document(kind="boolean", safe_raster=True)
    group = document.nodes["node:group"].model_copy(
        update={"visual": {"mask": {"unexpected": True}}}
    )
    document = document.model_copy(
        update={"nodes": {**document.nodes, group.id: group}}
    )

    plan = compile_fgui_plan(document)

    assert plan.bindable is True
    assert len(plan.masks) == 1
    assert not any(item.node_id == group.id for item in plan.diagnostics)


def test_raster_mask_resource_records_fallback_reason() -> None:
    plan = compile_fgui_plan(mask_document(kind="blend", safe_raster=True))

    mask = only_mask(plan)
    assert mask.resource_ref is not None
    assert plan.resources[mask.resource_ref].reason == "mask_raster_fallback"
