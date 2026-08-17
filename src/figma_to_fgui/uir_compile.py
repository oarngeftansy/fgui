import hashlib
import json
from collections.abc import Iterable
from typing import Any

from figma_to_fgui.component_mapping import ComponentMapping, ComponentMappingCatalog
from figma_to_fgui.models import Bounds, NormalizedNode
from figma_to_fgui.uir_models import (
    ConversionMode,
    MappingStatus,
    SemanticStatus,
    UIRAsset,
    UIRComponentInstance,
    UIRConversion,
    UIRDocument,
    UIRGeometry,
    UIRMappingDecision,
    UIRNode,
    UIRNodeSource,
    UIRSemantic,
    UIRSource,
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _stable_id(prefix: str, value: object) -> str:
    return f"{prefix}:{_digest(value)[:24]}"


def _local_bounds(node: NormalizedNode, parent: NormalizedNode | None) -> Bounds:
    if parent is None:
        return Bounds(x=0, y=0, width=node.bounds.width, height=node.bounds.height)
    return Bounds(
        x=node.bounds.x - parent.bounds.x,
        y=node.bounds.y - parent.bounds.y,
        width=node.bounds.width,
        height=node.bounds.height,
    )


def _source_fingerprint(node: NormalizedNode) -> str:
    return _digest(
        {
            "id": node.id,
            "name": node.name,
            "type": node.type,
            "bounds": node.bounds.model_dump(mode="json"),
            "text": node.text,
            "rotation": node.rotation,
            "opacity": node.opacity,
            "visible": node.visible,
            "sourceOrder": node.source_order,
            "properties": node.properties,
            "rawStyle": node.raw_style,
            "children": [child.id for child in node.children],
        }
    )


def _derived_asset(node: NormalizedNode) -> UIRAsset | None:
    references = node.properties.get("resourceRefs")
    if not isinstance(references, dict):
        return None
    for key in sorted(references):
        reference = references[key]
        if not isinstance(reference, dict):
            continue
        logical_id = reference.get("asset")
        mime_type = reference.get("mimeType")
        if not isinstance(logical_id, str) or not logical_id:
            continue
        if not isinstance(mime_type, str) or not mime_type:
            continue
        asset_id = _stable_id(
            "asset",
            {"logicalId": logical_id, "mimeType": mime_type, "sourceNodeId": node.id},
        )
        return UIRAsset(
            id=asset_id,
            logicalId=logical_id,
            mimeType=mime_type,
            sourceNodeId=node.id,
        )
    return None


def _conversion(node: NormalizedNode, asset_ref: str | None = None) -> UIRConversion:
    if node.properties.get("export_strategy") == "composite_png":
        return UIRConversion(
            mode=ConversionMode.RASTER_FALLBACK,
            reasons=tuple(node.properties.get("raster_reasons", ()))
            or ("composite_visual",),
            assetRef=asset_ref,
        )
    return UIRConversion(mode=ConversionMode.NATIVE)


def _mapping_for(
    node: NormalizedNode, catalog: ComponentMappingCatalog
) -> ComponentMapping | None:
    matches = [
        item
        for item in catalog.components
        if node.id in item.figma.node_ids or node.name in item.figma.names
    ]
    return matches[0] if len(matches) == 1 else None


def _mapping_decision(
    node: NormalizedNode,
    mapping: ComponentMapping,
    selection_id: str,
) -> tuple[UIRMappingDecision, UIRSemantic, UIRConversion]:
    if mapping.status == "candidate":
        raise ValueError("component mapping catalog must be validated")
    decision_id = _stable_id(
        "decision",
        {
            "candidateKey": mapping.key,
            "selectionId": selection_id,
            "sourceNodeId": node.id,
        },
    )
    evidence = (
        "exact_node_id" if node.id in mapping.figma.node_ids else "exact_name",
        *((mapping.reason,) if mapping.reason else ()),
    )
    confidence = 1.0 if mapping.status == "verified" else 0.0
    decision = UIRMappingDecision(
        id=decision_id,
        candidateKey=mapping.key,
        status=MappingStatus(mapping.status),
        evidence=evidence,
        confidence=confidence,
        ruleSource="component-mapping:" + ",".join(mapping.source),
    )
    if mapping.status == "verified":
        return (
            decision,
            UIRSemantic(
                name=mapping.key,
                role="component",
                status=SemanticStatus.CONFIRMED,
                decisionRef=decision_id,
            ),
            UIRConversion(mode=ConversionMode.COMPONENT_REFERENCE),
        )
    if mapping.status == "missing":
        return (
            decision,
            UIRSemantic(
                name=mapping.key,
                role="component",
                status=SemanticStatus.FALLBACK,
                decisionRef=decision_id,
            ),
            UIRConversion(
                mode=ConversionMode.RASTER_FALLBACK,
                reasons=("component_mapping_missing",),
            ),
        )
    return (
        decision,
        UIRSemantic(
            name=mapping.key,
            role="component",
            status=SemanticStatus.CANDIDATE,
            decisionRef=decision_id,
        ),
        UIRConversion(
            mode=ConversionMode.UNSUPPORTED,
            reasons=("component_mapping_conflict",),
        ),
    )


def _compile_node(
    node: NormalizedNode,
    *,
    parent: NormalizedNode | None,
    parent_id: str | None,
    path: tuple[int, ...],
    selection_id: str,
    nodes: dict[str, UIRNode],
    decisions: dict[str, UIRMappingDecision],
    assets: dict[str, UIRAsset],
    mapping_catalog: ComponentMappingCatalog | None,
) -> str:
    node_id = _stable_id(
        "node", {"selectionId": selection_id, "sourceNodeId": node.id, "path": path}
    )
    child_ids = tuple(
        _compile_node(
            child,
            parent=node,
            parent_id=node_id,
            path=(*path, index),
            selection_id=selection_id,
            nodes=nodes,
            decisions=decisions,
            assets=assets,
            mapping_catalog=mapping_catalog,
        )
        for index, child in enumerate(node.children)
    )
    text: dict[str, Any] | None = None
    if node.type == "TEXT":
        text = {"content": node.text or "", "style": dict(node.raw_style)}
    component = None
    if node.type == "INSTANCE":
        raw_variants = node.properties.get("componentProperties", {})
        variants = (
            {str(key): str(value) for key, value in raw_variants.items()}
            if isinstance(raw_variants, dict)
            else {}
        )
        component = UIRComponentInstance(variantProperties=variants)
    semantic = UIRSemantic(status=SemanticStatus.CANDIDATE)
    derived_asset = _derived_asset(node)
    if derived_asset is not None:
        assets[derived_asset.id] = derived_asset
    conversion = _conversion(
        node, None if derived_asset is None else derived_asset.id
    )
    if node.type == "INSTANCE" and mapping_catalog is not None:
        mapping = _mapping_for(node, mapping_catalog)
        if mapping is not None:
            decision, semantic, conversion = _mapping_decision(
                node, mapping, selection_id
            )
            decisions[decision.id] = decision
    nodes[node_id] = UIRNode(
        id=node_id,
        source=UIRNodeSource(
            nodeId=node.id,
            type=node.type,
            name=node.name,
            fingerprint=_source_fingerprint(node),
        ),
        semantic=semantic,
        parentId=parent_id,
        children=child_ids,
        zIndex=path[-1] if path else 0,
        geometry=UIRGeometry(
            resolvedBounds=_local_bounds(node, parent),
            rotation=node.rotation,
            opacity=node.opacity,
        ),
        layout={"sourceOrder": node.source_order, "visible": node.visible},
        visual={} if node.type == "TEXT" else dict(node.raw_style),
        text=text,
        component=component,
        conversion=conversion,
    )
    return node_id


def compile_uir(
    roots: tuple[NormalizedNode, ...],
    *,
    source_revision: str,
    selection_id: str,
    compiler_version: str = "uir-v1",
    assets: Iterable[UIRAsset] = (),
    mapping_catalog: ComponentMappingCatalog | None = None,
) -> UIRDocument:
    if mapping_catalog is not None and any(
        item.status == "candidate" for item in mapping_catalog.components
    ):
        raise ValueError("component mapping catalog must be validated")
    nodes: dict[str, UIRNode] = {}
    decisions: dict[str, UIRMappingDecision] = {}
    asset_items = tuple(assets)
    compiled_assets = {item.id: item for item in asset_items}
    root_ids = tuple(
        _compile_node(
            root,
            parent=None,
            parent_id=None,
            path=(index,),
            selection_id=selection_id,
            nodes=nodes,
            decisions=decisions,
            assets=compiled_assets,
            mapping_catalog=mapping_catalog,
        )
        for index, root in enumerate(roots)
    )
    document_id = _stable_id(
        "uir",
        {
            "compilerVersion": compiler_version,
            "selectionId": selection_id,
            "sourceRevision": source_revision,
        },
    )
    return UIRDocument(
        documentId=document_id,
        compilerVersion=compiler_version,
        source=UIRSource(revision=source_revision, selectionId=selection_id),
        roots=root_ids,
        nodes=nodes,
        assets=compiled_assets,
        mappingDecisions=decisions,
    )
