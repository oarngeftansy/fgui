"""Conservative native shapes; complex paths/effects remain explicit blockers."""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from psd_tools import PSDImage
from psd_tools.constants import Tag


def native_graph_for_layer(layer) -> dict | None:
    if getattr(layer, "kind", None) != "shape":
        return None
    current = layer
    while current is not None:
        blend = getattr(getattr(current, "blend_mode", None), "value", b"norm")
        if (
            getattr(current, "clipping", False)
            or getattr(current, "has_effects", lambda: False)()
            or getattr(current, "has_mask", lambda: False)()
            or blend not in {b"norm", b"pass"}
            or current is not layer
            and getattr(current, "opacity", 255) != 255
        ):
            return None
        current = getattr(current, "parent", None)
    try:
        origins = layer.origination
        if len(origins) != 1 or origins[0].invalidated or origins[0].origin_type not in {1, 2, 5}:
            return None
        origin = origins[0]
        mask = layer.vector_mask
        if mask is None or mask.inverted or len(mask.paths) != 1:
            return None
        document = getattr(layer, "_psd", None)
        actual_bounds = (
            tuple(
                v * d
                for v, d in zip(
                    mask.bbox, (document.width, document.height, document.width, document.height)
                )
            )
            if document
            else layer.bbox
        )
        if any(abs(float(a) - float(b)) > 0.01 for a, b in zip(origin.bbox, actual_bounds)):
            return None
        if layer.stroke is not None and getattr(layer.stroke, "enabled", True):
            return None
        fill_opacity = layer.tagged_blocks.get_data(Tag.BLEND_FILL_OPACITY, 255)
        if int(fill_opacity) != 255:
            return None
        fill = layer.tagged_blocks.get_data(Tag.SOLID_COLOR_SHEET_SETTING)
        color = fill[b"Clr "]
        channels = [float(color[k]) for k in (b"Rd  ", b"Grn ", b"Bl  ")]
        if not all(math.isfinite(v) and 0 <= v <= 255 for v in channels):
            return None
        result = {
            "shape": "ellipse" if origin.origin_type == 5 else "rect",
            "fillColor": "#ff" + "".join(f"{round(v):02x}" for v in channels),
            "lineSize": 0,
        }
        if origin.origin_type == 2:
            # Both GraphPlan and the 6.1.4 serializer use TL, TR, BR, BL.
            radii = tuple(
                float(origin.radii[k])
                for k in (b"topLeft", b"topRight", b"bottomRight", b"bottomLeft")
            )
            if not all(math.isfinite(v) and v >= 0 for v in radii):
                return None
            result["cornerRadii"] = radii
        return result
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


@lru_cache(maxsize=4)
def read_native_graphs(path: Path, source_id: str) -> dict[str, dict]:
    document = PSDImage.open(path)
    result = {}
    for index, layer in enumerate(document.descendants()):
        if not layer.is_visible():
            continue
        graph = native_graph_for_layer(layer)
        if graph is not None:
            native_id = layer.layer_id
            identity = str(native_id) if native_id is not None else f"index-{index}"
            key = f"psd-layer:{source_id}:{identity}"
            result[key] = {"graph": graph, "bounds": tuple(layer.origination[0].bbox)}
    return result
