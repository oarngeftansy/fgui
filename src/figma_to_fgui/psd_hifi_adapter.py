from __future__ import annotations

from figma_to_fgui.figma_selection import (
    SelectionManifest,
    SelectionNode,
    SelectionWarning,
)
from figma_to_fgui.models import Bounds
from figma_to_fgui.psd_intake import PsdLayer
from figma_to_fgui.psd_source_store import PsdSource

_PSD_NODE_TYPES = {
    "group": "GROUP",
    "type": "TEXT",
    "shape": "VECTOR",
    "pixel": "IMAGE",
    "smartobject": "IMAGE",
}


def _node_type(layer: PsdLayer) -> str:
    return _PSD_NODE_TYPES.get(layer.kind.casefold(), layer.kind.upper())


def psd_source_manifest(source: PsdSource) -> SelectionManifest:
    by_parent: dict[str | None, list[PsdLayer]] = {}
    for layer in source.layers:
        if not layer.effective_visible:
            continue
        by_parent.setdefault(layer.parent_id, []).append(layer)
    for children in by_parent.values():
        children.sort(key=lambda layer: (layer.sibling_index, layer.document_index, layer.id))

    def convert(layer: PsdLayer) -> SelectionNode:
        left, top, right, bottom = layer.bounds
        return SelectionNode(
            id=layer.id,
            name=layer.name,
            type=_node_type(layer),
            bounds=Bounds(
                x=left,
                y=top,
                width=max(0, right - left),
                height=max(0, bottom - top),
            ),
            children=tuple(convert(child) for child in by_parent.get(layer.id, ())),
            visible=layer.effective_visible,
            opacity=layer.opacity / 255,
            source_order=layer.sibling_index,
            text=layer.text,
            properties={
                "psdKind": layer.kind,
                "blendMode": layer.blend_mode,
                "clipping": layer.clipping,
                "hasPixelMask": layer.has_pixel_mask,
                "hasVectorMask": layer.has_vector_mask,
                "hasEffects": layer.has_effects,
            },
        )

    root = SelectionNode(
        id=f"psd-root:{source.source_id}",
        name=source.inspection.source_name,
        type="FRAME",
        bounds=Bounds(
            x=0,
            y=0,
            width=source.inspection.width,
            height=source.inspection.height,
        ),
        children=tuple(convert(layer) for layer in by_parent.get(None, ())),
    )
    warnings = tuple(
        SelectionWarning(
            code=code,
            message=f"PSD lossless gate: {code}",
        )
        for code in (*source.inspection.blocking_issues, *source.inspection.warnings)
    )
    return SelectionManifest(
        version=1,
        display_name=source.inspection.source_name,
        top_level_nodes=(root,),
        warnings=warnings,
    )
