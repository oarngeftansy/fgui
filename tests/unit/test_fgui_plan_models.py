import json

import pytest
from pydantic import ValidationError

from figma_to_fgui.fgui_plan_models import (
    CapabilityStatus,
    ComponentReferencePlan,
    FGUIPlanDocument,
    MaskMode,
    PlanNodeType,
    TextPlan,
)


def _minimal_plan() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "documentId": "plan:example",
        "sourceUirSha256": "a" * 64,
        "profileVersion": "fgui-6.1.4-v1",
        "ruleVersion": 1,
        "bindable": True,
        "roots": ("node:root",),
        "nodes": {
            "node:root": {
                "id": "plan-node:root",
                "uirNodeRef": "node:root",
                "parentId": None,
                "children": (),
                "zIndex": 0,
                "type": "container",
                "transform": {
                    "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}
                },
            }
        },
        "resources": {},
        "masks": {},
        "decisions": {},
        "diagnostics": (),
    }


@pytest.fixture
def minimal_plan() -> dict[str, object]:
    return _minimal_plan()


@pytest.fixture
def valid_plan() -> FGUIPlanDocument:
    return FGUIPlanDocument.model_validate(_minimal_plan())


def test_plan_enums_are_closed() -> None:
    assert set(CapabilityStatus) == {"native", "rasterFallback", "unsupported"}
    assert set(PlanNodeType) == {
        "container",
        "text",
        "richText",
        "image",
        "loader",
        "componentReference",
        "rasterSubtree",
    }
    assert set(MaskMode) == {"nativeClip", "nativeMask", "rasterSubtree"}


def test_plan_rejects_unknown_and_target_binding_fields(
    minimal_plan: dict[str, object],
) -> None:
    minimal_plan["packageId"] = "real-id"
    with pytest.raises(ValidationError):
        FGUIPlanDocument.model_validate(minimal_plan)


def test_serialized_plan_contains_no_project_binding_fields(
    valid_plan: FGUIPlanDocument,
) -> None:
    encoded = json.dumps(valid_plan.model_dump(mode="json", by_alias=True))
    for forbidden in ("packageId", "componentId", '"src"', '"pkg"'):
        assert forbidden not in encoded


def test_plan_accepts_python_names_and_is_immutable() -> None:
    plan = FGUIPlanDocument(
        schema_version=1,
        document_id="plan:example",
        source_uir_sha256="a" * 64,
        profile_version="fgui-6.1.4-v1",
        rule_version=1,
        bindable=True,
        roots=("node:root",),
        nodes={
            "node:root": {
                "id": "plan-node:root",
                "uir_node_ref": "node:root",
                "z_index": 0,
                "type": PlanNodeType.CONTAINER,
                "transform": {
                    "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}
                },
            }
        },
    )
    with pytest.raises(ValidationError):
        plan.bindable = False


@pytest.mark.parametrize("source_hash", ("a" * 63, "A" * 64, "g" * 64))
def test_plan_rejects_malformed_source_hash(source_hash: str) -> None:
    payload = _minimal_plan()
    payload["sourceUirSha256"] = source_hash
    with pytest.raises(ValidationError):
        FGUIPlanDocument.model_validate(payload)


def test_plan_mapping_fields_are_deeply_immutable_and_json_serializable() -> None:
    text = TextPlan(content="Title", styleFacts={"font": {"weight": 500}})
    component = ComponentReferencePlan(
        candidateKey="common_button", variantProperties={"state": "normal"}
    )
    payload = _minimal_plan()
    payload["nodes"] = {
        "node:root": {
            "id": "plan-node:root",
            "uirNodeRef": "node:root",
            "zIndex": 0,
            "type": "container",
            "transform": {"bounds": {"x": 0, "y": 0, "width": 100, "height": 100}},
            "text": text,
            "component": component,
        }
    }
    plan = FGUIPlanDocument.model_validate(payload)

    with pytest.raises(TypeError):
        text.style_facts["new"] = True
    with pytest.raises(TypeError):
        text.style_facts["font"]["weight"] = 700  # type: ignore[index]
    with pytest.raises(TypeError):
        component.variant_properties["state"] = "pressed"
    for mapping in (plan.nodes, plan.resources, plan.masks, plan.decisions):
        with pytest.raises(TypeError):
            mapping["node:other"] = mapping.get("node:root")  # type: ignore[index]

    encoded = plan.model_dump(mode="json", by_alias=True)
    assert isinstance(encoded["nodes"], dict)
    assert encoded["nodes"]["node:root"]["text"]["styleFacts"] == {
        "font": {"weight": 500}
    }


def test_plan_rejects_nested_project_binding_fields() -> None:
    payload = _minimal_plan()
    payload["nodes"] = {
        "node:root": {
            **payload["nodes"]["node:root"],  # type: ignore[index]
            "text": {"content": "Title", "styleFacts": {"src": "local.png"}},
        }
    }
    with pytest.raises(ValidationError):
        FGUIPlanDocument.model_validate(payload)


def test_plan_freezes_nested_sequence_mappings_and_blocks_late_binding_injection() -> None:
    nested_values = [{"label": "safe"}]
    text = TextPlan(content="Title", styleFacts={"items": nested_values})

    with pytest.raises(TypeError):
        text.style_facts["items"][0] = {"src": "late-leak"}  # type: ignore[index]
    with pytest.raises(TypeError):
        text.style_facts["items"][0]["label"] = "changed"  # type: ignore[index]

    nested_values.append({"src": "input-leak"})
    encoded = text.model_dump(mode="json", by_alias=True)
    assert encoded["styleFacts"] == {"items": [{"label": "safe"}]}
    assert '"src"' not in text.model_dump_json(by_alias=True)


def test_plan_freezes_sets_in_deterministic_order_for_json() -> None:
    text = TextPlan(content="Title", styleFacts={"tags": {"z", "a", "m"}})

    assert text.style_facts["tags"] == ("a", "m", "z")
    first = text.model_dump_json(by_alias=True)
    second = text.model_dump_json(by_alias=True)
    assert first == second
    assert text.model_dump(mode="json", by_alias=True)["styleFacts"]["tags"] == [
        "a",
        "m",
        "z",
    ]
