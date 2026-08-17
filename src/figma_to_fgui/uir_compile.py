import hashlib
import json
from collections.abc import Iterable
from typing import Any

from figma_to_fgui.models import Bounds, NormalizedNode
from figma_to_fgui.uir_models import (
    ConversionMode,
    SemanticStatus,
    UIRAsset,
    UIRComponentInstance,
    UIRConversion,
    UIRDocument,
    UIRGeometry,
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


def _conversion(node: NormalizedNode) -> UIRConversion:
    if node.properties.get("export_strategy") == "composite_png":
        return UIRConversion(
            mode=ConversionMode.RASTER_FALLBACK,
            reasons=tuple(node.properties.get("raster_reasons", ()))
            or ("composite_visual",),
        )
    return UIRConversion(mode=ConversionMode.NATIVE)


def _compile_node(
    node: NormalizedNode,
    *,
    parent: NormalizedNode | None,
    parent_id: str | None,
    path: tuple[int, ...],
    selection_id: str,
    nodes: dict[str, UIRNode],
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
    nodes[node_id] = UIRNode(
        id=node_id,
        source=UIRNodeSource(
            nodeId=node.id,
            type=node.type,
            name=node.name,
            fingerprint=_source_fingerprint(node),
        ),
        semantic=UIRSemantic(status=SemanticStatus.CANDIDATE),
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
        conversion=_conversion(node),
    )
    return node_id


def compile_uir(
    roots: tuple[NormalizedNode, ...],
    *,
    source_revision: str,
    selection_id: str,
    compiler_version: str = "uir-v1",
    assets: Iterable[UIRAsset] = (),
    mapping_catalog: object | None = None,
) -> UIRDocument:
    del mapping_catalog  # Mapping decisions are added at the next compiler boundary.
    nodes: dict[str, UIRNode] = {}
    root_ids = tuple(
        _compile_node(
            root,
            parent=None,
            parent_id=None,
            path=(index,),
            selection_id=selection_id,
            nodes=nodes,
        )
        for index, root in enumerate(roots)
    )
    asset_items = tuple(assets)
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
        assets={item.id: item for item in asset_items},
    )
