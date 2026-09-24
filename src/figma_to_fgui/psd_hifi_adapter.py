from __future__ import annotations

from dataclasses import asdict

from figma_to_fgui.figma_selection import (
    SelectionManifest,
    SelectionNode,
    SelectionResource,
    SelectionWarning,
)
from figma_to_fgui.models import Bounds
from figma_to_fgui.psd_intake import PsdLayer
from figma_to_fgui.psd_source_store import PsdRasterResource, PsdSource

_PSD_NODE_TYPES = {
    "group": "GROUP",
    "type": "TEXT",
    "shape": "VECTOR",
    "pixel": "IMAGE",
    "smartobject": "IMAGE",
}

_PSD_ADJUSTMENT_KINDS = {
    "brightnesscontrast",
    "channelmixer",
    "colorbalance",
    "curves",
    "exposure",
    "gradientmap",
    "huesaturation",
    "levels",
    "photofilter",
    "posterize",
    "selectivecolor",
    "threshold",
    "vibrance",
}


def _node_type(layer: PsdLayer) -> str:
    return _PSD_NODE_TYPES.get(layer.kind.casefold(), layer.kind.upper())


def psd_composite_group_ids(source: PsdSource) -> frozenset[str]:
    """Return natural PSD visual sections that must keep group compositing semantics."""
    by_parent: dict[str | None, list[PsdLayer]] = {}
    by_id = {layer.id: layer for layer in source.layers}
    for layer in source.layers:
        if layer.effective_visible:
            by_parent.setdefault(layer.parent_id, []).append(layer)

    def has_tall_group_ancestor(layer: PsdLayer) -> bool:
        parent_id = layer.parent_id
        while parent_id is not None:
            parent = by_id[parent_id]
            if (
                parent.kind.casefold() == "group"
                and parent.bounds[3] - parent.bounds[1]
                > source.inspection.height * 0.25
            ):
                return True
            parent_id = parent.parent_id
        return False

    candidates: set[str] = set()
    for layer in source.layers:
        if not layer.effective_visible:
            continue
        left, top, right, bottom = layer.bounds
        descendants = _visible_descendants(layer.id, by_parent)
        descendant_kinds = {child.kind.casefold() for child in descendants}
        simple_editable_banner = (
            len(descendants) <= 8
            and "type" in descendant_kinds
            and descendant_kinds <= {"group", "type", "shape"}
            and not (descendant_kinds & _PSD_ADJUSTMENT_KINDS)
        )
        dense_text_strip = (
            bottom - top < 48
            and "type" in descendant_kinds
        )
        has_unrenderable_effect_group = any(
            child.kind.casefold() == "group"
            and child.has_effects
            and (
                child.bounds[2] <= child.bounds[0]
                or child.bounds[3] <= child.bounds[1]
            )
            for child in descendants
        )
        if (
            layer.kind.casefold() == "group"
            and right > left
            and bottom > top
            and bottom - top <= source.inspection.height * 0.25
            and not has_tall_group_ancestor(layer)
            and not has_unrenderable_effect_group
            and not simple_editable_banner
            and not dense_text_strip
            and "type" in descendant_kinds
            and any(
                child.kind.casefold() != "type"
                for child in descendants
            )
        ):
            candidates.add(layer.id)
    return frozenset(
        layer_id
        for layer_id in candidates
        if not any(
            descendant.id in candidates
            for descendant in _visible_descendants(layer_id, by_parent)
        )
    )


def _visible_descendants(
    layer_id: str, by_parent: dict[str | None, list[PsdLayer]]
) -> tuple[PsdLayer, ...]:
    result: list[PsdLayer] = []
    pending = list(reversed(by_parent.get(layer_id, ())))
    while pending:
        layer = pending.pop()
        result.append(layer)
        pending.extend(reversed(by_parent.get(layer.id, ())))
    return tuple(result)


def psd_source_manifest(
    source: PsdSource,
    *,
    raster_resources: dict[str, PsdRasterResource] | None = None,
) -> SelectionManifest:
    raster_resources = raster_resources or {}
    by_parent: dict[str | None, list[PsdLayer]] = {}
    for layer in source.layers:
        if not layer.effective_visible:
            continue
        by_parent.setdefault(layer.parent_id, []).append(layer)
    for children in by_parent.values():
        children.sort(key=lambda layer: (layer.sibling_index, layer.document_index, layer.id))
    composite_groups = psd_composite_group_ids(source)

    def convert(layer: PsdLayer, *, composite_text: bool = False) -> SelectionNode:
        left, top, right, bottom = layer.bounds
        raster = raster_resources.get(layer.id)
        if layer.id in composite_groups:
            child_layers = tuple(
                child
                for child in _visible_descendants(layer.id, by_parent)
                if child.kind.casefold() == "type"
            )
        else:
            child_layers = tuple(by_parent.get(layer.id, ()))
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
            children=tuple(
                convert(
                    child,
                    composite_text=layer.id in composite_groups
                    and child.kind.casefold() == "type",
                )
                for child in child_layers
            ),
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
                "psdDocumentIndex": layer.document_index,
                "psdEffects": tuple(asdict(effect) for effect in layer.effects),
                "psdCompositeGroup": layer.id in composite_groups,
                "psdCompositeText": composite_text,
            },
            style=(
                {"psdTextStyle": asdict(layer.text_style)}
                if layer.text_style is not None
                else {}
            ),
            resource_keys=(raster.key,) if raster is not None else (),
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
        resources=tuple(
            SelectionResource(
                key=resource.key,
                mime_type="image/png",
                size=resource.size,
            )
            for resource in sorted(raster_resources.values(), key=lambda item: item.key)
        ),
        warnings=warnings,
    )
