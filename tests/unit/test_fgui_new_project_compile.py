from __future__ import annotations

import hashlib
import json

import pytest

from figma_to_fgui.fgui_asset_payloads import NewProjectInputError, ValidatedAssetPayload
from figma_to_fgui.fgui_new_project_compile import compile_new_project_manifest
from figma_to_fgui.fgui_new_project_models import AssetPayload, NewProjectConfig
from figma_to_fgui.fgui_new_project_validate import (
    canonical_manifest_bytes,
    validate_new_project_manifest,
)
from figma_to_fgui.fgui_plan_models import (
    CapabilityDecision,
    CapabilityStatus,
    FGUIPlanDocument,
    MaskKind,
    MaskMode,
    MaskPlan,
    PlanNodeType,
    TextPlan,
)
from figma_to_fgui.models import Diagnostic, Severity

CONFIG = NewProjectConfig(
    projectName="Demo",
    packageName="Generated",
    fairyGuiVersion="6.1.4",
    publishTarget="unity",
)


EXPORT_PARAMETERS_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "exportFormat": "png",
            "height": 30,
            "mimeType": "image/png",
            "width": 20,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()


def plan_with_order(order: str) -> FGUIPlanDocument:
    node_items = [
        (
            "plan:root",
            {
                "id": "plan:root",
                "uirNodeRef": "uir:root",
                "children": ("plan:image",),
                "zIndex": 0,
                "type": "container",
                "transform": {"bounds": {"x": 0, "y": 0, "width": 100, "height": 80}},
                "decisionRef": "decision:root",
            },
        ),
        (
            "plan:image",
            {
                "id": "plan:image",
                "uirNodeRef": "uir:image",
                "parentId": "plan:root",
                "zIndex": 0,
                "type": "image",
                "transform": {
                    "bounds": {"x": 7, "y": 9, "width": 20, "height": 30},
                    "visible": False,
                },
                "resourceRef": "resource:image",
                "decisionRef": "decision:image",
            },
        ),
    ]
    if order == "reverse":
        node_items.reverse()
    return FGUIPlanDocument.model_validate(
        {
            "documentId": "plan:test",
            "sourceUirSha256": "a" * 64,
            "profileVersion": "fgui-6.1.4-v1",
            "ruleVersion": 1,
            "bindable": True,
            "roots": ("plan:root",),
            "nodes": dict(node_items),
            "resources": {
                "resource:image": {
                    "id": "resource:image",
                    "sourceAssetRef": "asset:image",
                    "logicalAssetId": "logical:image",
                    "contentSha256": "b" * 64,
                    "exportParametersSha256": EXPORT_PARAMETERS_SHA256,
                    "mimeType": "image/png",
                    "exportFormat": "png",
                    "width": 20,
                    "height": 30,
                    "consumers": ("plan:image",),
                }
            },
            "decisions": {
                "uir:root": {
                    "id": "decision:root",
                    "nodeRef": "uir:root",
                    "status": "native",
                    "ruleId": "fgui.native.container",
                    "ruleVersion": 1,
                    "evidence": ("fixture.root",),
                },
                "uir:image": {
                    "id": "decision:image",
                    "nodeRef": "uir:image",
                    "status": "native",
                    "ruleId": "fgui.native.image",
                    "ruleVersion": 1,
                    "evidence": ("fixture.image",),
                },
            },
        }
    )


def assets_for(plan: FGUIPlanDocument) -> tuple[ValidatedAssetPayload, ...]:
    resource = plan.resources["resource:image"]
    return (
        ValidatedAssetPayload(
            resource=resource,
            payload=AssetPayload(
                resourceId=resource.id,
                declaredMimeType=resource.mime_type,
                content=b"validated elsewhere",
            ),
        ),
    )


def test_manifest_is_canonical_across_mapping_order() -> None:
    forward = plan_with_order("forward")
    reverse = plan_with_order("reverse")

    first = compile_new_project_manifest(forward, CONFIG, assets_for(forward))
    second = compile_new_project_manifest(reverse, CONFIG, assets_for(reverse))

    assert canonical_manifest_bytes(first) == canonical_manifest_bytes(second)


def component_definition_plan() -> FGUIPlanDocument:
    return FGUIPlanDocument.model_validate(
        {
            "documentId": "plan:components",
            "sourceUirSha256": "d" * 64,
            "profileVersion": "fgui-6.1.4-v1",
            "ruleVersion": 1,
            "bindable": True,
            "roots": ("plan:root-instance",),
            "nodes": {
                "plan:root-instance": {
                    "id": "plan:root-instance",
                    "uirNodeRef": "uir:root-instance",
                    "zIndex": 0,
                    "type": "componentReference",
                    "transform": {
                        "bounds": {"x": 11, "y": 13, "width": 90, "height": 40},
                        "opacity": 0.5,
                        "visible": False,
                    },
                    "component": {
                        "candidateKey": "outer",
                        "definitionRef": "definition:outer",
                    },
                    "decisionRef": "decision:root-instance",
                }
            },
            "componentDefinitions": {
                "definition:outer": {
                    "id": "definition:outer",
                    "name": "Outer",
                    "rootNodeRef": "definition-node:outer",
                    "nodes": {
                        "definition-node:outer": {
                            "id": "definition-node:outer",
                            "uirNodeRef": "uir:definition-outer",
                            "zIndex": 0,
                            "type": "componentReference",
                            "transform": {"bounds": {"x": 3, "y": 5, "width": 70, "height": 30}},
                            "component": {
                                "candidateKey": "inner",
                                "definitionRef": "definition:inner",
                            },
                            "decisionRef": "decision:definition-outer",
                        }
                    },
                },
                "definition:inner": {
                    "id": "definition:inner",
                    "name": "Inner",
                    "rootNodeRef": "definition-node:inner",
                    "nodes": {
                        "definition-node:inner": {
                            "id": "definition-node:inner",
                            "uirNodeRef": "uir:definition-inner",
                            "children": ("definition-node:label",),
                            "zIndex": 0,
                            "type": "container",
                            "transform": {"bounds": {"x": 0, "y": 0, "width": 60, "height": 20}},
                            "decisionRef": "decision:definition-inner",
                        },
                        "definition-node:label": {
                            "id": "definition-node:label",
                            "uirNodeRef": "uir:definition-label",
                            "parentId": "definition-node:inner",
                            "zIndex": 0,
                            "type": "text",
                            "transform": {"bounds": {"x": 7, "y": 8, "width": 40, "height": 10}},
                            "text": {"content": "Definition-local"},
                            "decisionRef": "decision:definition-label",
                        },
                    },
                },
            },
            "decisions": {
                uir_ref: {
                    "id": decision_id,
                    "nodeRef": uir_ref,
                    "status": "native",
                    "ruleId": rule_id,
                    "ruleVersion": 1,
                    "evidence": ("fixture.component",),
                }
                for uir_ref, decision_id, rule_id in (
                    (
                        "uir:root-instance",
                        "decision:root-instance",
                        "fgui.native.component_reference",
                    ),
                    (
                        "uir:definition-outer",
                        "decision:definition-outer",
                        "fgui.native.component_reference",
                    ),
                    (
                        "uir:definition-inner",
                        "decision:definition-inner",
                        "fgui.native.container",
                    ),
                    (
                        "uir:definition-label",
                        "decision:definition-label",
                        "fgui.native.text",
                    ),
                )
            },
        }
    )


def aliased_identity_plan(*, same_component_source_ref: bool) -> FGUIPlanDocument:
    root_id = "a"
    child_id = "b:c"
    definition_id = root_id if same_component_source_ref else "a:b"
    return FGUIPlanDocument.model_validate(
        {
            "documentId": "plan:identity-alias",
            "sourceUirSha256": "e" * 64,
            "profileVersion": "fgui-6.1.4-v1",
            "ruleVersion": 1,
            "bindable": True,
            "roots": (root_id,),
            "nodes": {
                root_id: {
                    "id": root_id,
                    "uirNodeRef": "uir:root-a",
                    "children": (child_id,),
                    "zIndex": 0,
                    "type": "container",
                    "transform": {
                        "bounds": {"x": 0, "y": 0, "width": 20, "height": 20}
                    },
                    "decisionRef": "decision:root-a",
                },
                child_id: {
                    "id": child_id,
                    "uirNodeRef": "uir:instance-b-c",
                    "parentId": root_id,
                    "zIndex": 0,
                    "type": "componentReference",
                    "transform": {
                        "bounds": {"x": 1, "y": 2, "width": 10, "height": 10}
                    },
                    "component": {
                        "candidateKey": "alias_fixture",
                        "definitionRef": definition_id,
                    },
                    "decisionRef": "decision:instance-b-c",
                },
            },
            "componentDefinitions": {
                definition_id: {
                    "id": definition_id,
                    "name": "Alias Definition",
                    "rootNodeRef": "c",
                    "nodes": {
                        "c": {
                            "id": "c",
                            "uirNodeRef": "uir:definition-c",
                            "zIndex": 0,
                            "type": "container",
                            "transform": {
                                "bounds": {"x": 0, "y": 0, "width": 10, "height": 10}
                            },
                            "decisionRef": "decision:definition-c",
                        }
                    },
                }
            },
            "decisions": {
                uir_ref: {
                    "id": decision_id,
                    "nodeRef": uir_ref,
                    "status": "native",
                    "ruleId": rule_id,
                    "ruleVersion": 1,
                    "evidence": ("fixture.identity",),
                }
                for uir_ref, decision_id, rule_id in (
                    ("uir:root-a", "decision:root-a", "fgui.native.container"),
                    (
                        "uir:instance-b-c",
                        "decision:instance-b-c",
                        "fgui.native.component_reference",
                    ),
                    (
                        "uir:definition-c",
                        "decision:definition-c",
                        "fgui.native.container",
                    ),
                )
            },
        }
    )


def test_definitions_are_local_and_topological_before_roots() -> None:
    manifest = compile_new_project_manifest(component_definition_plan(), CONFIG, ())

    assert [item.source_component_ref for item in manifest.components] == [
        "definition:inner",
        "definition:outer",
        "plan:root-instance",
    ]
    inner, outer, root = manifest.components
    assert inner.objects[0].source_node_ref == "definition-node:inner"
    assert inner.objects[0].child_object_refs == (inner.objects[1].id,)
    assert inner.objects[1].parent_object_ref == inner.objects[0].id
    assert inner.objects[1].transform.bounds.x == 7
    assert outer.objects[0].component_ref == inner.id
    assert root.objects[0].component_ref == outer.id
    assert root.objects[0].transform.bounds.x == 11
    assert root.objects[0].transform.opacity == 0.5
    assert root.objects[0].transform.visible is False


def test_root_and_definition_with_same_source_ref_use_distinct_typed_domains() -> None:
    manifest = compile_new_project_manifest(
        aliased_identity_plan(same_component_source_ref=True), CONFIG, ()
    )

    assert [(item.source_component_kind, item.source_component_ref) for item in manifest.components] == [
        ("definition", "a"),
        ("root", "a"),
    ]
    assert manifest.components[0].id != manifest.components[1].id


def test_object_logical_keys_are_unambiguous_across_colon_aliases() -> None:
    manifest = compile_new_project_manifest(
        aliased_identity_plan(same_component_source_ref=False), CONFIG, ()
    )
    object_ids = {
        (component.source_component_kind, component.source_component_ref, object_.source_node_ref): object_.id
        for component in manifest.components
        for object_ in component.objects
    }

    assert object_ids[("root", "a", "b:c")] != object_ids[("definition", "a:b", "c")]
    assert all(object_.uir_node_ref.startswith("uir:") for component in manifest.components for object_ in component.objects)


def test_compile_revalidates_bindability_and_validated_asset_identity() -> None:
    plan = plan_with_order("forward")
    blocked = plan.model_copy(update={"bindable": False})

    with pytest.raises(NewProjectInputError) as blocked_error:
        compile_new_project_manifest(blocked, CONFIG, assets_for(blocked))
    assert "fgui.writer.input.plan_not_bindable" in {
        item.code for item in blocked_error.value.diagnostics
    }
    assert all(
        item.code.startswith("fgui.writer.input.") and item.suggested_action is not None
        for item in blocked_error.value.diagnostics
    )

    mismatched_asset = assets_for(plan)[0]
    mismatched_asset = ValidatedAssetPayload(
        resource=mismatched_asset.resource.model_copy(update={"width": 999}),
        payload=mismatched_asset.payload,
    )
    with pytest.raises(NewProjectInputError) as asset_error:
        compile_new_project_manifest(plan, CONFIG, (mismatched_asset,))
    assert [item.code for item in asset_error.value.diagnostics] == [
        "fgui.writer.input.asset_incoherent"
    ]


@pytest.mark.parametrize(
    ("update", "expected_code"),
    (
        ({"schema_version": 999}, "fgui.writer.input.unsupported_plan_schema"),
        ({"profile_version": "fgui-9.9.9-v99"}, "fgui.writer.input.unsupported_profile"),
        ({"rule_version": 999}, "fgui.writer.input.unsupported_rule_version"),
    ),
)
def test_compile_rejects_unsupported_plan_contract_versions(
    update: dict[str, object], expected_code: str
) -> None:
    plan = plan_with_order("forward").model_copy(update=update)

    with pytest.raises(NewProjectInputError) as captured:
        compile_new_project_manifest(plan, CONFIG, assets_for(plan_with_order("forward")))

    assert [item.code for item in captured.value.diagnostics] == [expected_code]


def test_compile_canonical_revalidation_contains_typed_corruption() -> None:
    marker = r"C:\private\secret-token.txt"
    plan = plan_with_order("forward")
    corrupted = plan.model_copy(
        update={"nodes": {"plan:root": {"id": marker, "unexpected": marker}}}
    )

    with pytest.raises(NewProjectInputError) as captured:
        compile_new_project_manifest(corrupted, CONFIG, assets_for(plan))

    assert [item.code for item in captured.value.diagnostics] == [
        "fgui.writer.input.plan_schema_invalid"
    ]
    assert marker not in str(captured.value)
    assert marker not in repr(captured.value.diagnostics)


def test_writer_input_diagnostic_order_is_independent_of_plan_tuple_order() -> None:
    plan = raster_mask_plan().model_copy(update={"bindable": False})
    reversed_plan = plan.model_copy(update={"diagnostics": tuple(reversed(plan.diagnostics))})

    captured: list[tuple[Diagnostic, ...]] = []
    for candidate in (plan, reversed_plan):
        with pytest.raises(NewProjectInputError) as error:
            compile_new_project_manifest(candidate, CONFIG, assets_for(candidate))
        captured.append(error.value.diagnostics)

    assert captured[0] == captured[1]
    assert all(item.evidence and item.suggested_action for item in captured[0])


def raster_mask_plan() -> FGUIPlanDocument:
    plan = plan_with_order("forward")
    root = plan.nodes["plan:root"].model_copy(
        update={
            "children": (),
            "type": PlanNodeType.RASTER_SUBTREE,
            "resource_ref": "resource:image",
            "mask_ref": "mask:raster",
            "decision_ref": "decision:raster",
        }
    )
    resource = plan.resources["resource:image"].model_copy(
        update={"consumers": (root.id,), "reason": "mask_raster_fallback"}
    )
    return plan.model_copy(
        update={
            "roots": (root.id,),
            "nodes": {root.id: root},
            "resources": {resource.id: resource},
            "masks": {
                "mask:raster": MaskPlan(
                    id="mask:raster",
                    mode="rasterSubtree",
                    kind="boolean",
                    maskNodeRef="uir:consumed-mask",
                    contentNodeRefs=("uir:consumed-content",),
                    resourceRef=resource.id,
                )
            },
            "decisions": {
                "uir:root": CapabilityDecision(
                    id="decision:raster",
                    nodeRef="uir:root",
                    status=CapabilityStatus.RASTER_FALLBACK,
                    ruleId="fgui.fallback.raster_subtree",
                    ruleVersion=1,
                    evidence=("fixture.raster",),
                )
            },
            "diagnostics": (
                Diagnostic(
                    code="fgui.mask.raster_fallback",
                    severity=Severity.WARNING,
                    message="Mask uses a reviewed raster fallback.",
                    node_id="uir:root",
                    rule_id="fgui.fallback.raster_subtree",
                    rule_version=1,
                    evidence=("fixture.raster",),
                    suggested_action="Review the generated raster result.",
                ),
            ),
        }
    )


def test_raster_mask_preserves_consumed_source_roles() -> None:
    plan = raster_mask_plan()
    manifest = compile_new_project_manifest(plan, CONFIG, assets_for(plan))
    object_ = manifest.components[-1].objects[0]

    assert object_.mask_mode == "rasterSubtree"
    assert object_.mask_kind == "boolean"
    assert object_.mask_object_ref is None
    assert object_.mask_content_object_refs == ()
    assert object_.raster_consumed_node_refs == (
        "uir:consumed-mask",
        "uir:consumed-content",
    )


def native_mask_plan() -> FGUIPlanDocument:
    plan = plan_with_order("forward")
    root = plan.nodes["plan:root"].model_copy(
        update={"children": ("plan:image", "plan:text"), "mask_ref": "mask:native"}
    )
    text = plan.nodes["plan:image"].model_copy(
        update={
            "id": "plan:text",
            "uir_node_ref": "uir:text",
            "z_index": 1,
            "type": PlanNodeType.TEXT,
            "resource_ref": None,
            "text": TextPlan(content="Masked"),
            "decision_ref": "decision:text",
        }
    )
    return FGUIPlanDocument.model_validate(
        plan.model_copy(
            update={
                "nodes": {root.id: root, "plan:image": plan.nodes["plan:image"], text.id: text},
                "masks": {
                    "mask:native": MaskPlan(
                        id="mask:native",
                        mode="nativeMask",
                        kind="image",
                        maskNodeRef="uir:image",
                        contentNodeRefs=("uir:text",),
                    )
                },
                "decisions": {
                    **plan.decisions,
                    "uir:text": CapabilityDecision(
                        id="decision:text",
                        nodeRef="uir:text",
                        status=CapabilityStatus.NATIVE,
                        ruleId="fgui.native.text",
                        ruleVersion=1,
                        evidence=("fixture.text",),
                    ),
                },
            }
        ).model_dump(mode="python", by_alias=True)
    )


def test_native_mask_references_definition_local_target_objects() -> None:
    plan = native_mask_plan()
    manifest = compile_new_project_manifest(plan, CONFIG, assets_for(plan))
    objects = {item.source_node_ref: item for item in manifest.components[-1].objects}
    target = objects["plan:root"]

    assert target.mask_mode == "nativeMask"
    assert target.mask_kind == "image"
    assert target.mask_object_ref == objects["plan:image"].id
    assert target.mask_content_object_refs == (objects["plan:text"].id,)


def test_native_rounded_clip_compiles_with_source_local_radii_contract() -> None:
    plan = native_mask_plan()
    mask = plan.masks["mask:native"].model_copy(
        update={
            "mode": MaskMode.NATIVE_CLIP,
            "kind": MaskKind.ROUNDED_RECTANGLE,
            "mask_node_ref": "uir:root",
            "content_node_refs": ("uir:image", "uir:text"),
            "corner_radii": (5.0, 5.0, 5.0, 5.0),
        }
    )
    root_decision = plan.decisions["uir:root"].model_copy(
        update={"rule_id": "fgui.native.clip_source"}
    )
    plan = plan.model_copy(
        update={
            "masks": {mask.id: mask},
            "decisions": {**plan.decisions, "uir:root": root_decision},
        }
    )

    manifest = compile_new_project_manifest(plan, CONFIG, assets_for(plan))

    assert manifest.components[-1].objects[0].mask_corner_radii == (5.0,) * 4


def test_validator_rechecks_target_keys_and_native_mask_order() -> None:
    manifest = compile_new_project_manifest(
        native_mask_plan(), CONFIG, assets_for(native_mask_plan())
    )
    component = manifest.components[-1]
    target = component.objects[0]
    reversed_target = target.model_copy(
        update={"child_object_refs": tuple(reversed(target.child_object_refs))}
    )
    malformed = manifest.model_copy(
        update={
            "components": (
                component.model_copy(
                    update={
                        "id": "deadbeef",
                        "objects": (reversed_target, *component.objects[1:]),
                    }
                ),
            )
        }
    )

    codes = {item.code for item in validate_new_project_manifest(malformed)}

    assert "fgui.writer.manifest.target_id_key_mismatch" in codes
    assert "fgui.writer.manifest.mask_order_incoherent" in codes


def test_validator_rejects_noncanonical_object_tuple_and_exact_path_mismatch() -> None:
    plan = native_mask_plan()
    manifest = compile_new_project_manifest(plan, CONFIG, assets_for(plan))
    component = manifest.components[-1]
    malformed = manifest.model_copy(
        update={
            "components": (
                component.model_copy(
                    update={
                        "name": "Renamed",
                        "objects": (component.objects[1], component.objects[0], *component.objects[2:]),
                    }
                ),
            )
        }
    )

    codes = {item.code for item in validate_new_project_manifest(malformed)}

    assert "fgui.writer.manifest.object_order_incoherent" in codes
    assert "fgui.writer.manifest.component_path_incoherent" in codes


def test_validator_uses_mandatory_uir_identity_for_raster_consumption() -> None:
    plan = raster_mask_plan()
    manifest = compile_new_project_manifest(plan, CONFIG, assets_for(plan))
    component = manifest.components[-1]
    raster = component.objects[0]
    harmless = raster.model_copy(update={"raster_consumed_node_refs": ("plan:other",)})
    other = raster.model_copy(
        update={
            "id": "deadbeef",
            "source_node_ref": "plan:other",
            "uir_node_ref": "uir:other",
            "raster_consumed_node_refs": (),
            "mask_mode": None,
            "mask_kind": None,
            "resource_ref": None,
            "type": PlanNodeType.CONTAINER,
        }
    )
    harmless_manifest = manifest.model_copy(
        update={"components": (component.model_copy(update={"objects": (harmless, other)}),)}
    )
    assert "fgui.writer.manifest.raster_descendant_duplicate" not in {
        item.code for item in validate_new_project_manifest(harmless_manifest)
    }

    duplicate = harmless.model_copy(update={"raster_consumed_node_refs": ("uir:other",)})
    duplicate_manifest = harmless_manifest.model_copy(
        update={"components": (component.model_copy(update={"objects": (duplicate, other)}),)}
    )
    assert "fgui.writer.manifest.raster_descendant_duplicate" in {
        item.code for item in validate_new_project_manifest(duplicate_manifest)
    }


def test_manifest_diagnostics_do_not_echo_malicious_ids_and_are_actionable() -> None:
    plan = plan_with_order("forward")
    manifest = compile_new_project_manifest(plan, CONFIG, assets_for(plan))
    marker = r"C:\\private\\accessToken=do-not-leak"
    malformed_object = manifest.components[-1].objects[0].model_copy(update={"id": marker})
    malformed = manifest.model_copy(
        update={
            "components": (
                manifest.components[-1].model_copy(update={"objects": (malformed_object,)}),
            )
        }
    )

    diagnostics = validate_new_project_manifest(malformed)

    assert marker not in repr(diagnostics)
    assert all(item.evidence and item.suggested_action for item in diagnostics)


@pytest.mark.parametrize(
    ("updates", "expected"),
    (
        ({"type": PlanNodeType.TEXT}, "fgui.writer.manifest.mask_target_incoherent"),
        ({"mask_content_object_refs": ()}, "fgui.writer.manifest.mask_target_incoherent"),
        ({"mask_kind": "rectangle"}, "fgui.writer.manifest.mask_role_incoherent"),
        ({"mask_corner_radii": (1.0, 1.0, 1.0, 1.0)}, "fgui.writer.manifest.mask_radii_incoherent"),
    ),
)
def test_validator_rejects_native_mask_role_combinations(
    updates: dict[str, object], expected: str
) -> None:
    plan = native_mask_plan()
    manifest = compile_new_project_manifest(plan, CONFIG, assets_for(plan))
    component = manifest.components[-1]
    target = component.objects[0].model_copy(update=updates)
    malformed = manifest.model_copy(
        update={"components": (component.model_copy(update={"objects": (target, *component.objects[1:])}),)}
    )

    assert expected in {item.code for item in validate_new_project_manifest(malformed)}


def test_validator_rejects_bad_export_hash_and_casefold_logical_key_collision() -> None:
    plan = plan_with_order("forward")
    manifest = compile_new_project_manifest(plan, CONFIG, assets_for(plan))
    component = manifest.components[-1]
    colliding = component.model_copy(
        update={
            "id": "deadbeef",
            "source_component_ref": component.source_component_ref.swapcase(),
            "relative_path": "components/Other-deadbeef.xml",
        }
    )
    bad_resource = manifest.resources[0].model_copy(
        update={"export_parameters_sha256": "A" * 64}
    )
    malformed = manifest.model_copy(
        update={"components": (component, colliding), "resources": (bad_resource,)}
    )

    codes = {item.code for item in validate_new_project_manifest(malformed)}

    assert "fgui.writer.manifest.target_identity_policy_invalid" in codes
    assert "fgui.writer.manifest.export_parameters_hash_invalid" in codes
