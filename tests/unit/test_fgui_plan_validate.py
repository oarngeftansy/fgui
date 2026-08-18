import hashlib

from figma_to_fgui.fgui_plan_models import (
    CapabilityDecision,
    CapabilityStatus,
    FGUIPlanDocument,
    MaskPlan,
    PlanNodeType,
    TextPlan,
)
from figma_to_fgui.fgui_plan_validate import (
    canonical_plan_bytes,
    plan_sha256,
    validate_fgui_plan,
)
from figma_to_fgui.models import Diagnostic, Severity


def valid_plan() -> FGUIPlanDocument:
    return FGUIPlanDocument.model_validate(
        {
            "documentId": "plan:test",
            "sourceUirSha256": "a" * 64,
            "profileVersion": "fgui-6.1.4-v1",
            "ruleVersion": 1,
            "bindable": True,
            "roots": ("plan:root",),
            "nodes": {
                "plan:root": {
                    "id": "plan:root",
                    "uirNodeRef": "uir:root",
                    "children": ("plan:image", "plan:text"),
                    "zIndex": 0,
                    "type": "container",
                    "transform": {
                        "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}
                    },
                    "decisionRef": "decision:root",
                },
                "plan:text": {
                    "id": "plan:text",
                    "uirNodeRef": "uir:text",
                    "parentId": "plan:root",
                    "zIndex": 0,
                    "type": "text",
                    "transform": {
                        "bounds": {"x": 0, "y": 0, "width": 50, "height": 20}
                    },
                    "text": {"content": "Hello"},
                    "decisionRef": "decision:text",
                },
                "plan:image": {
                    "id": "plan:image",
                    "uirNodeRef": "uir:image",
                    "parentId": "plan:root",
                    "zIndex": 1,
                    "type": "image",
                    "transform": {
                        "bounds": {"x": 0, "y": 20, "width": 50, "height": 50}
                    },
                    "resourceRef": "resource:image",
                    "decisionRef": "decision:image",
                },
            },
            "resources": {
                "resource:image": {
                    "id": "resource:image",
                    "sourceAssetRef": "asset:image",
                    "mimeType": "image/png",
                    "exportFormat": "png",
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
                },
                "uir:text": {
                    "id": "decision:text",
                    "nodeRef": "uir:text",
                    "status": "native",
                    "ruleId": "fgui.native.text",
                    "ruleVersion": 1,
                },
                "uir:image": {
                    "id": "decision:image",
                    "nodeRef": "uir:image",
                    "status": "native",
                    "ruleId": "fgui.native.image",
                    "ruleVersion": 1,
                },
            },
        }
    )


def plan_with_dangling_refs() -> FGUIPlanDocument:
    plan = valid_plan()
    root = plan.nodes["plan:root"].model_copy(
        update={
            "children": ("plan:missing",),
            "resource_ref": "resource:missing",
            "mask_ref": "mask:missing",
            "decision_ref": "decision:missing",
        }
    )
    return plan.model_copy(
        update={
            "bindable": False,
            "roots": ("plan:absent", root.id),
            "nodes": {root.id: root},
            "resources": {},
            "masks": {},
            "decisions": {},
        }
    )


def inconsistent_capability_plan() -> FGUIPlanDocument:
    plan = valid_plan()
    fallback = plan.nodes["plan:image"].model_copy(
        update={"type": PlanNodeType.RASTER_SUBTREE, "resource_ref": None}
    )
    unsupported = CapabilityDecision(
        id="decision:unsupported",
        nodeRef="uir:unsupported",
        status="unsupported",
        ruleId="fgui.unsupported.node_type",
        ruleVersion=1,
        blocking=False,
    )
    fallback_decision = plan.decisions["uir:image"].model_copy(
        update={
            "status": CapabilityStatus.RASTER_FALLBACK,
            "rule_id": "fgui.fallback.raster_subtree",
        }
    )
    return plan.model_copy(
        update={
            "nodes": {**plan.nodes, fallback.id: fallback},
            "resources": {},
            "decisions": {
                **plan.decisions,
                "uir:image": fallback_decision,
                "uir:unsupported": unsupported,
            },
        }
    )


def plan_with_style_fact(key: str, value: object) -> FGUIPlanDocument:
    plan = valid_plan()
    text = plan.nodes["plan:text"]
    assert text.text is not None
    leaky_text = text.text.model_copy(update={"style_facts": {key: value}})
    leaky_node = text.model_copy(update={"text": leaky_text})
    return plan.model_copy(update={"nodes": {**plan.nodes, leaky_node.id: leaky_node}})


def native_mask_plan() -> FGUIPlanDocument:
    plan = valid_plan()
    mask = MaskPlan(
        id="mask:root",
        mode="nativeMask",
        kind="image",
        maskNodeRef="uir:image",
        contentNodeRefs=("uir:text",),
    )
    root = plan.nodes["plan:root"].model_copy(update={"mask_ref": mask.id})
    return plan.model_copy(
        update={
            "nodes": {**plan.nodes, root.id: root},
            "masks": {mask.id: mask},
        }
    )


def test_valid_plan_has_no_validation_diagnostics() -> None:
    assert validate_fgui_plan(valid_plan()) == ()


def test_validation_reports_all_dangling_references() -> None:
    codes = {item.code for item in validate_fgui_plan(plan_with_dangling_refs())}
    assert codes == {
        "fgui.plan.root_missing",
        "fgui.plan.child_missing",
        "fgui.plan.resource_missing",
        "fgui.plan.mask_missing",
        "fgui.plan.decision_missing",
    }


def test_fallback_requires_resource_and_unsupported_requires_blocking_diagnostic() -> None:
    codes = {item.code for item in validate_fgui_plan(inconsistent_capability_plan())}
    assert "fgui.plan.fallback_resource_required" in codes
    assert "fgui.plan.unsupported_not_blocked" in codes


def test_binding_field_leak_is_rejected_recursively() -> None:
    assert any(
        item.code == "fgui.plan.binding_field_leak"
        for item in validate_fgui_plan(plan_with_style_fact("pkg", "bad"))
    )


def test_canonical_bytes_and_hash_are_stable() -> None:
    first = canonical_plan_bytes(valid_plan())
    second = canonical_plan_bytes(valid_plan())
    assert first == second and first.endswith(b"\n")
    assert plan_sha256(valid_plan()) == hashlib.sha256(first).hexdigest()


def test_dictionary_keys_and_tree_ownership_are_validated() -> None:
    plan = valid_plan()
    text = plan.nodes["plan:text"].model_copy(update={"parent_id": "plan:image"})
    image = plan.nodes["plan:image"].model_copy(
        update={"id": "plan:other", "children": ("plan:text",)}
    )
    broken = plan.model_copy(
        update={
            "nodes": {
                "plan:root": plan.nodes["plan:root"],
                "plan:text": text,
                "plan:image": image,
            }
        }
    )
    codes = {item.code for item in validate_fgui_plan(broken)}
    assert "fgui.plan.node_key_mismatch" in codes
    assert "fgui.plan.child_multiple_parents" in codes
    assert "fgui.plan.parent_mismatch" in codes


def test_every_emitted_node_must_be_a_root_or_owned_child() -> None:
    plan = valid_plan()
    root = plan.nodes["plan:root"].model_copy(update={"children": ("plan:image",)})
    text = plan.nodes["plan:text"].model_copy(update={"parent_id": None})
    broken = plan.model_copy(
        update={"nodes": {**plan.nodes, root.id: root, text.id: text}}
    )

    assert any(
        item.code == "fgui.plan.node_unowned"
        for item in validate_fgui_plan(broken)
    )


def test_roots_must_be_unique() -> None:
    plan = valid_plan().model_copy(update={"roots": ("plan:root", "plan:root")})

    assert any(
        item.code == "fgui.plan.root_duplicate"
        for item in validate_fgui_plan(plan)
    )


def test_self_cycles_are_rejected() -> None:
    plan = valid_plan()
    root = plan.nodes["plan:root"].model_copy(
        update={"children": (*plan.nodes["plan:root"].children, "plan:root")}
    )
    broken = plan.model_copy(update={"nodes": {**plan.nodes, root.id: root}})

    assert any(
        item.code == "fgui.plan.node_cycle"
        for item in validate_fgui_plan(broken)
    )


def test_disconnected_cycles_are_rejected_as_cycles_and_unreachable() -> None:
    plan = valid_plan()
    root = plan.nodes["plan:root"].model_copy(update={"children": ()})
    text = plan.nodes["plan:text"].model_copy(
        update={"parent_id": "plan:image", "children": ("plan:image",)}
    )
    image = plan.nodes["plan:image"].model_copy(
        update={"parent_id": "plan:text", "children": ("plan:text",)}
    )
    broken = plan.model_copy(
        update={"nodes": {root.id: root, text.id: text, image.id: image}}
    )

    codes = {item.code for item in validate_fgui_plan(broken)}
    assert "fgui.plan.node_cycle" in codes
    assert "fgui.plan.node_unreachable" in codes


def test_nodes_reachable_from_more_than_one_root_are_rejected() -> None:
    plan = valid_plan().model_copy(
        update={"roots": ("plan:root", "plan:text")}
    )

    assert any(
        item.code == "fgui.plan.node_multiple_roots"
        for item in validate_fgui_plan(plan)
    )


def test_resource_consumers_are_symmetric_and_existing() -> None:
    plan = valid_plan()
    resource = plan.resources["resource:image"].model_copy(
        update={"consumers": ("plan:text", "plan:missing")}
    )
    broken = plan.model_copy(update={"resources": {resource.id: resource}})
    codes = {item.code for item in validate_fgui_plan(broken)}
    assert "fgui.plan.resource_consumer_missing" in codes
    assert "fgui.plan.resource_consumer_mismatch" in codes


def test_masks_must_have_exactly_one_target() -> None:
    plan = native_mask_plan()
    mask = plan.masks["mask:root"]
    orphaned = plan.model_copy(
        update={
            "nodes": valid_plan().nodes,
            "masks": {mask.id: mask},
        }
    )
    assert any(
        item.code == "fgui.plan.mask_orphan"
        for item in validate_fgui_plan(orphaned)
    )

    second_target = plan.nodes["plan:text"].model_copy(update={"mask_ref": mask.id})
    shared = plan.model_copy(
        update={"nodes": {**plan.nodes, second_target.id: second_target}}
    )
    assert any(
        item.code == "fgui.plan.mask_multiple_targets"
        for item in validate_fgui_plan(shared)
    )


def test_masks_require_nonempty_source_and_content_references() -> None:
    plan = native_mask_plan()
    mask = plan.masks["mask:root"].model_copy(
        update={"mask_node_ref": "", "content_node_refs": ()}
    )
    broken = plan.model_copy(update={"masks": {mask.id: mask}})

    assert any(
        item.code == "fgui.plan.mask_hierarchy_incoherent"
        for item in validate_fgui_plan(broken)
    )


def test_native_mask_mode_requires_matching_source_role_and_hierarchy() -> None:
    plan = native_mask_plan()
    source = plan.nodes["plan:image"].model_copy(
        update={
            "type": PlanNodeType.TEXT,
            "resource_ref": None,
            "text": TextPlan(content="x"),
        }
    )
    decision = plan.decisions["uir:image"].model_copy(
        update={"rule_id": "fgui.native.text"}
    )
    broken = plan.model_copy(
        update={
            "nodes": {**plan.nodes, source.id: source},
            "decisions": {**plan.decisions, "uir:image": decision},
        }
    )
    codes = {item.code for item in validate_fgui_plan(broken)}
    assert "fgui.plan.mask_node_type_incoherent" in codes
    assert "fgui.plan.mask_decision_incoherent" in codes


def test_native_mask_content_requires_a_coherent_native_decision() -> None:
    plan = native_mask_plan()
    decision = plan.decisions["uir:text"].model_copy(
        update={
            "status": CapabilityStatus.RASTER_FALLBACK,
            "rule_id": "fgui.fallback.raster_subtree",
        }
    )
    broken = plan.model_copy(
        update={"decisions": {**plan.decisions, "uir:text": decision}}
    )

    assert any(
        item.code == "fgui.plan.mask_decision_incoherent"
        and item.node_id == "plan:text"
        for item in validate_fgui_plan(broken)
    )


def test_raster_nodes_cannot_retain_native_descendants_or_duplicate_resource_ownership() -> None:
    plan = valid_plan()
    root = plan.nodes["plan:root"].model_copy(
        update={
            "type": PlanNodeType.RASTER_SUBTREE,
            "resource_ref": "resource:image",
            "decision_ref": "decision:root",
        }
    )
    decision = plan.decisions["uir:root"].model_copy(
        update={
            "status": CapabilityStatus.RASTER_FALLBACK,
            "rule_id": "fgui.fallback.raster_subtree",
        }
    )
    resource = plan.resources["resource:image"].model_copy(
        update={"consumers": (root.id, "plan:image")}
    )
    broken = plan.model_copy(
        update={
            "nodes": {**plan.nodes, root.id: root},
            "resources": {resource.id: resource},
            "decisions": {**plan.decisions, "uir:root": decision},
        }
    )
    codes = {item.code for item in validate_fgui_plan(broken)}
    assert "fgui.plan.raster_descendant_duplicate" in codes
    assert "fgui.plan.raster_native_resource_duplicate" in codes


def test_raster_native_resource_duplication_does_not_depend_on_consumer_metadata() -> None:
    plan = valid_plan()
    root = plan.nodes["plan:root"].model_copy(
        update={
            "type": PlanNodeType.RASTER_SUBTREE,
            "resource_ref": "resource:image",
            "children": (),
        }
    )
    text = plan.nodes["plan:text"].model_copy(update={"parent_id": None})
    image = plan.nodes["plan:image"].model_copy(update={"parent_id": None})
    decision = plan.decisions["uir:root"].model_copy(
        update={
            "status": CapabilityStatus.RASTER_FALLBACK,
            "rule_id": "fgui.fallback.raster_subtree",
        }
    )
    resource = plan.resources["resource:image"].model_copy(update={"consumers": ()})
    broken = plan.model_copy(
        update={
            "bindable": False,
            "roots": (root.id, text.id, image.id),
            "nodes": {root.id: root, text.id: text, image.id: image},
            "resources": {resource.id: resource},
            "decisions": {**plan.decisions, "uir:root": decision},
        }
    )

    codes = {item.code for item in validate_fgui_plan(broken)}
    assert "fgui.plan.resource_consumer_mismatch" in codes
    assert "fgui.plan.raster_native_resource_duplicate" in codes


def test_node_payload_and_decision_semantics_must_match_node_type() -> None:
    plan = valid_plan()
    text = plan.nodes["plan:text"].model_copy(update={"text": None})
    decision = plan.decisions["uir:text"].model_copy(
        update={"rule_id": "fgui.native.container"}
    )
    broken = plan.model_copy(
        update={
            "nodes": {**plan.nodes, text.id: text},
            "decisions": {**plan.decisions, "uir:text": decision},
        }
    )
    codes = {item.code for item in validate_fgui_plan(broken)}
    assert "fgui.plan.node_payload_required" in codes
    assert "fgui.plan.decision_node_type_mismatch" in codes


def test_native_or_fallback_decisions_require_an_emitted_node() -> None:
    plan = valid_plan()
    orphan = CapabilityDecision(
        id="decision:orphan",
        nodeRef="uir:orphan",
        status=CapabilityStatus.NATIVE,
        ruleId="fgui.native.container",
        ruleVersion=1,
    )
    broken = plan.model_copy(
        update={"decisions": {**plan.decisions, orphan.node_ref: orphan}}
    )

    assert any(
        item.code == "fgui.plan.decision_orphan"
        for item in validate_fgui_plan(broken)
    )


def test_unsupported_decisions_each_require_their_own_node_diagnostic() -> None:
    plan = valid_plan()
    first = CapabilityDecision(
        id="decision:unsupported-first",
        nodeRef="uir:unsupported-first",
        status=CapabilityStatus.UNSUPPORTED,
        ruleId="fgui.unsupported.node_type",
        ruleVersion=1,
        blocking=True,
    )
    second = first.model_copy(
        update={"id": "decision:unsupported-second", "node_ref": "uir:unsupported-second"}
    )
    error = Diagnostic(
        code="fgui.unsupported.node_type",
        severity=Severity.ERROR,
        message="Only the first node is diagnosed.",
        node_id=first.node_ref,
    )
    broken = plan.model_copy(
        update={
            "bindable": False,
            "decisions": {
                **plan.decisions,
                first.node_ref: first,
                second.node_ref: second,
            },
            "diagnostics": (error,),
        }
    )

    unsupported_errors = [
        item
        for item in validate_fgui_plan(broken)
        if item.code == "fgui.plan.unsupported_not_blocked"
    ]
    assert [item.node_id for item in unsupported_errors] == [second.node_ref]


def test_native_clip_source_decision_requires_a_native_clip_mask_role() -> None:
    plan = valid_plan()
    decision = plan.decisions["uir:root"].model_copy(
        update={"rule_id": "fgui.native.clip_source"}
    )
    broken = plan.model_copy(
        update={"decisions": {**plan.decisions, "uir:root": decision}}
    )

    assert any(
        item.code == "fgui.plan.decision_mask_role_incoherent"
        for item in validate_fgui_plan(broken)
    )


def test_bindable_flag_matches_errors_and_blocking_decisions() -> None:
    plan = valid_plan()
    embedded_error = Diagnostic(
        code="fixture.error", severity=Severity.ERROR, message="blocked"
    )
    broken = plan.model_copy(update={"diagnostics": (embedded_error,)})
    assert any(
        item.code == "fgui.plan.bindable_inconsistent"
        for item in validate_fgui_plan(broken)
    )


def test_bindable_flag_accounts_for_validation_errors() -> None:
    plan = valid_plan().model_copy(update={"roots": ("plan:missing",)})

    assert any(
        item.code == "fgui.plan.bindable_inconsistent"
        for item in validate_fgui_plan(plan)
    )


def test_valid_native_mask_has_no_validation_diagnostics() -> None:
    assert validate_fgui_plan(native_mask_plan()) == ()
