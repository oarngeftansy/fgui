import hashlib

from figma_to_fgui.models import Bounds
from figma_to_fgui.uir_models import (
    ConversionMode,
    MappingStatus,
    UIRConversion,
    UIRDocument,
    UIRGeometry,
    UIRMappingDecision,
    UIRNode,
    UIRNodeSource,
    UIRSemantic,
    UIRSource,
)
from figma_to_fgui.uir_validate import canonical_uir_bytes, uir_sha256, validate_uir


def valid_document() -> UIRDocument:
    node = UIRNode(
        id="node:root",
        source=UIRNodeSource(
            nodeId="root", type="FRAME", name="Root", fingerprint="b" * 64
        ),
        semantic=UIRSemantic(),
        zIndex=0,
        geometry=UIRGeometry(
            resolvedBounds=Bounds(x=0, y=0, width=100, height=100)
        ),
        conversion=UIRConversion(mode=ConversionMode.NATIVE),
    )
    return UIRDocument(
        documentId="uir:test",
        compilerVersion="uir-v1",
        source=UIRSource(revision="a" * 64, selectionId="selection"),
        roots=(node.id,),
        nodes={node.id: node},
    )


def test_validation_rejects_dangling_root_child_and_decision_refs() -> None:
    document = valid_document()
    root = document.nodes["node:root"].model_copy(
        update={
            "children": ("node:missing",),
            "semantic": UIRSemantic(decisionRef="decision:missing"),
        }
    )
    document = document.model_copy(
        update={"roots": ("node:absent",), "nodes": {root.id: root}}
    )
    assert {item.code for item in validate_uir(document)} == {
        "uir.root_missing",
        "uir.child_missing",
        "uir.decision_missing",
    }


def test_validation_blocks_unresolved_mapping_conflicts() -> None:
    document = valid_document()
    decision = UIRMappingDecision(
        id="decision:conflict",
        candidateKey="button",
        status=MappingStatus.CONFLICT,
        confidence=0,
        ruleSource="fixture",
    )
    root = document.nodes["node:root"].model_copy(
        update={
            "semantic": UIRSemantic(decisionRef=decision.id),
            "conversion": UIRConversion(mode=ConversionMode.UNSUPPORTED),
        }
    )
    document = document.model_copy(
        update={
            "nodes": {root.id: root},
            "mapping_decisions": {decision.id: decision},
        }
    )
    diagnostics = validate_uir(document)
    assert any(
        item.code == "uir.mapping_conflict" and item.severity == "ERROR"
        for item in diagnostics
    )


def test_canonical_bytes_and_digest_are_stable() -> None:
    document = valid_document()
    first = canonical_uir_bytes(document)
    second = canonical_uir_bytes(document)
    assert first == second
    assert first.endswith(b"\n")
    assert uir_sha256(document) == hashlib.sha256(first).hexdigest()


def test_validation_rejects_duplicate_ownership_and_parent_asymmetry() -> None:
    document = valid_document()
    child = document.nodes["node:root"].model_copy(
        update={"id": "node:child", "parent_id": "node:wrong", "children": ()}
    )
    first = document.nodes["node:root"].model_copy(
        update={"children": (child.id,)}
    )
    second = first.model_copy(update={"id": "node:other", "children": (child.id,)})
    document = document.model_copy(
        update={
            "roots": (first.id, second.id),
            "nodes": {first.id: first, second.id: second, child.id: child},
        }
    )
    codes = {item.code for item in validate_uir(document)}
    assert "uir.child_multiple_parents" in codes
    assert "uir.parent_mismatch" in codes
