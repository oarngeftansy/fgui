import json

import pytest
from pydantic import ValidationError

from figma_to_fgui.uir_models import (
    ConversionMode,
    MappingStatus,
    SemanticStatus,
    UIRDocument,
)


def minimal_document() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "documentId": "uir_test",
        "compilerVersion": "uir-v1",
        "source": {
            "kind": "figma",
            "revision": "a" * 64,
            "selectionId": "selection_test",
        },
        "roots": ["node:root"],
        "nodes": {
            "node:root": {
                "id": "node:root",
                "source": {
                    "nodeId": "root",
                    "type": "FRAME",
                    "name": "村庄升阶",
                    "fingerprint": "b" * 64,
                },
                "semantic": {
                    "name": "villageAscend",
                    "role": "panel",
                    "status": "confirmed",
                },
                "children": [],
                "zIndex": 0,
                "geometry": {
                    "resolvedBounds": {
                        "x": 0,
                        "y": 0,
                        "width": 1080,
                        "height": 1923,
                    },
                    "rotation": 0,
                    "opacity": 1,
                },
                "layout": {},
                "visual": {},
                "interactions": [],
                "conversion": {"mode": "native", "reasons": []},
            }
        },
        "componentDefinitions": {},
        "assets": {},
        "mappingDecisions": {},
        "diagnostics": [],
    }


def test_uir_v1_rejects_unknown_fields() -> None:
    payload = minimal_document()
    payload["packageId"] = "forbidden"
    with pytest.raises(ValidationError):
        UIRDocument.model_validate(payload)


def test_uir_schema_has_only_declared_status_values() -> None:
    assert set(SemanticStatus) == {"candidate", "confirmed", "rejected", "fallback"}
    assert set(ConversionMode) == {
        "native",
        "componentReference",
        "existingResource",
        "rasterFallback",
        "unsupported",
    }
    assert set(MappingStatus) == {"verified", "missing", "conflict"}


def test_serialized_core_contains_no_fairygui_target_fields() -> None:
    encoded = json.dumps(
        UIRDocument.model_validate(minimal_document()).model_dump(mode="json")
    )
    for forbidden in (
        "packageId",
        "componentId",
        "gearDisplay",
        "gearFrame",
        "controller",
    ):
        assert forbidden not in encoded
