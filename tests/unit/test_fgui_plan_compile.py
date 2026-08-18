from figma_to_fgui.fgui_plan_compile import compile_fgui_plan
from figma_to_fgui.fgui_plan_models import FGUIPlanDocument
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
