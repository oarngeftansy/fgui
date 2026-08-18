import json

import pytest
from pydantic import ValidationError

from figma_to_fgui.fgui_plan_models import (
    CapabilityStatus,
    FGUIPlanDocument,
    MaskMode,
    PlanNodeType,
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
