"""Bounded PSD rendering with explicit leaf ownership; never a merged-page crop.

RGBA8 output still requires Photoshop/Editor equivalence verification.
Unsupported effects fail instead of silently disappearing.
"""

from __future__ import annotations

import math
from typing import Any

from PIL import Image

from figma_to_fgui.psd_intake import PsdAnalysis, PsdLayer, PsdLayerEffect
from figma_to_fgui.psd_stroke_render import render_stroke_only, stroke_viewport


def composite_hard_shadow(body: Image.Image, effect: PsdLayerEffect) -> Image.Image:
    values = (effect.opacity, effect.angle, effect.distance, *(effect.color_rgba or ()))
    if (
        effect.opacity is None or effect.angle is None or effect.distance is None
    ):
        raise ValueError("psd_shadow_unsupported")
    if (
        effect.kind != "DropShadow"
        or effect.blend_mode != "normal"
        or effect.size != 0
        or effect.choke not in (None, 0)
        or effect.spread not in (None, 0)
        or effect.color_rgba is None
        or len(effect.color_rgba) != 4
        or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)
        or not 0 <= effect.opacity <= 100
        or not 0 <= effect.distance <= 256
        or not all(0 <= v <= 1 for v in effect.color_rgba)
    ):
        raise ValueError("psd_shadow_unsupported")
    angle = math.radians(effect.angle)
    dx, dy = -math.cos(angle) * effect.distance, math.sin(angle) * effect.distance
    alpha = body.getchannel("A").transform(
        body.size,
        Image.Transform.AFFINE,
        (1, 0, -dx, 0, 1, -dy),
        resample=Image.Resampling.BILINEAR,
        fillcolor=0,
    )
    alpha = alpha.point(
        [round(v * effect.opacity / 100 * effect.color_rgba[3]) for v in range(256)]
    )
    result = Image.new(
        "RGBA", body.size, tuple(round(v * 255) for v in effect.color_rgba[:3]) + (0,)
    )
    result.putalpha(alpha)
    result.alpha_composite(body)
    return result


def _effects(metadata: PsdLayer) -> tuple[PsdLayerEffect, ...]:
    return tuple(e for e in metadata.effects if e.enabled)


def layer_viewport(layer: Any, metadata: PsdLayer) -> tuple[int, int, int, int]:
    bounds = metadata.bounds
    if not getattr(getattr(layer, "stroke", None), "fill_enabled", True):
        try:
            bounds = stroke_viewport(layer)
        except (AttributeError, KeyError, IndexError, TypeError) as error:
            raise ValueError("psd_stroke_only_raster_unsupported") from error
    padding = 0
    for effect in _effects(metadata):
        values = (effect.size or 0, effect.distance or 0)
        if not all(math.isfinite(v) and 0 <= v <= 256 for v in values):
            raise ValueError("psd_effect_unsupported")
        padding = max(padding, math.ceil(sum(values)) + 2)
    return bounds[0] - padding, bounds[1] - padding, bounds[2] + padding, bounds[3] + padding


def _inherit_overlays(image: Image.Image, layer: Any) -> Image.Image:
    ancestor = getattr(layer, "parent", None)
    while ancestor is not None:
        if (
            getattr(ancestor, "opacity", 255) != 255
            or getattr(ancestor, "clipping", False)
            or getattr(ancestor, "has_mask", lambda: False)()
            or getattr(ancestor, "has_vector_mask", lambda: False)()
            or getattr(getattr(ancestor, "blend_mode", None), "value", b"norm")
            not in {b"norm", b"pass"}
        ):
            raise ValueError("psd_owned_context_unsupported")
        effects = getattr(ancestor, "effects", None)
        if effects is not None and effects.enabled:
            enabled = [e for e in effects if e.enabled]
            overlays = list(effects.find("ColorOverlay"))
            if len(enabled) != len(overlays) or len(overlays) > 1:
                raise ValueError("psd_owned_context_unsupported")
            for effect in overlays:
                if effect.opacity != 100 or effect.blend_mode not in {b"norm", b"normal", b"Nrml"}:
                    raise ValueError("psd_owned_context_unsupported")
                channels = tuple(float(effect.color[k]) for k in (b"Rd  ", b"Grn ", b"Bl  "))
                if not all(math.isfinite(v) and 0 <= v <= 255 for v in channels):
                    raise ValueError("psd_owned_context_unsupported")
                tinted = Image.new("RGBA", image.size, tuple(round(v) for v in channels) + (0,))
                tinted.putalpha(image.getchannel("A"))
                image = tinted
        ancestor = getattr(ancestor, "parent", None)
    return image


def render_leaf(
    layer: Any,
    metadata: PsdLayer,
    *,
    viewport: tuple[int, int, int, int] | None = None,
    apply_ancestors: bool = True,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    effects = _effects(metadata)
    if any(
        e.kind not in {"ColorOverlay", "GradientOverlay", "PatternOverlay", "Stroke", "DropShadow"}
        for e in effects
    ):
        raise ValueError("psd_effect_unsupported")
    shadows = [e for e in effects if e.kind == "DropShadow"]
    if shadows:
        # Only the exact zero-blur linear-contour variant has been implemented.
        if len(effects) != 1 or layer.opacity != 255 or layer.effects.scale != 100:
            raise ValueError("psd_shadow_unsupported")
        actual = next(layer.effects.find("DropShadow"))
        descriptor = actual.descriptor
        curve = descriptor[b"TrnS"][b"Crv "]
        if (
            float(descriptor[b"Nose"]) != 0
            or not bool(descriptor[b"layerConceals"])
            or bool(descriptor[b"AntA"])
            or len(curve) != 2
            or tuple((float(k[b"Hrzn"]), float(k[b"Vrtc"])) for k in curve)
            != ((0.0, 0.0), (255.0, 255.0))
        ):
            raise ValueError("psd_shadow_unsupported")
    viewport = viewport or layer_viewport(layer, metadata)
    width, height = viewport[2] - viewport[0], viewport[3] - viewport[1]
    if width <= 0 or height <= 0 or width * height > 16_000_000:
        raise ValueError("psd_raster_bounds_unsupported")
    if not getattr(getattr(layer, "stroke", None), "fill_enabled", True):
        image = render_stroke_only(layer, viewport=viewport)
    else:
        image = layer.composite(viewport=viewport, force=True, alpha=0.0)
    if image is None:
        raise ValueError("psd_layer_raster_unavailable")
    image = image.convert("RGBA")
    if shadows:
        image = composite_hard_shadow(image, shadows[0])
    if apply_ancestors:
        image = _inherit_overlays(image, layer)
    return image, viewport


def validate_owned_partition(
    leaves: list[PsdLayer], owned: frozenset[str], retained: frozenset[str]
) -> None:
    # A group with no visible descendants has no pixel source. A mask on that
    # empty group can only remove pixels, so it cannot contribute artwork.
    # Effects and non-normal compositing remain blocked until rendered proof.
    visible = {l.id: l for l in leaves if l.effective_visible and not (
        l.kind == "group" and not l.has_effects and not l.clipping
        and l.opacity == 255 and l.blend_mode in {"normal", "pass_through"}
    )}
    if (
        not owned
        or owned & retained
        or owned | retained != set(visible)
        or any(visible[key].kind not in {"shape", "pixel", "smartobject"} for key in owned)
        or any(visible[key].kind != "type" for key in retained)
    ):
        raise ValueError("psd_visual_ownership_incomplete")


def render_owned_visual(
    document: Any,
    source: PsdAnalysis,
    group_id: str,
    owned: frozenset[str],
    retained: frozenset[str],
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Render declared visual leaves; retained text is never baked into the bitmap.

    This verifies PSD ownership only. It cannot approve an FGUI correspondence.
    """
    metadata = {l.id: l for l in source.layers}
    children: dict[str, list[PsdLayer]] = {}
    for item in source.layers:
        if item.effective_visible:
            children.setdefault(item.parent_id or "", []).append(item)
    group = metadata[group_id]
    if group.kind != "group":
        raise ValueError("psd_visual_ownership_incomplete")
    descendants: list[PsdLayer] = []

    def collect(item: PsdLayer) -> None:
        descendants.append(item)
        for child in children.get(item.id or "", ()):
            collect(child)

    collect(group)
    leaves = [l for l in descendants if not children.get(l.id or "")]
    validate_owned_partition(leaves, owned, retained)
    ancestor = metadata.get(group.parent_id or "")
    while ancestor is not None:
        if (
            ancestor.has_effects
            or ancestor.has_pixel_mask
            or ancestor.has_vector_mask
            or ancestor.opacity != 255
            or ancestor.clipping
            or ancestor.blend_mode not in {"normal", "pass_through"}
        ):
            raise ValueError("psd_owned_context_unsupported")
        ancestor = metadata.get(ancestor.parent_id or "")
    actual = list(document.descendants())
    boxes = [layer_viewport(actual[l.document_index], l) for l in leaves if l.id in owned]
    viewport = (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )
    size = viewport[2] - viewport[0], viewport[3] - viewport[1]
    if size[0] * size[1] > 16_000_000:
        raise ValueError("psd_raster_bounds_unsupported")

    def draw(item: PsdLayer) -> Image.Image:
        if item.id in retained:
            return Image.new("RGBA", size)
        if item.blend_mode not in {"normal", "pass_through"} or item.clipping:
            raise ValueError("psd_owned_context_unsupported")
        if item.kind != "group":
            return render_leaf(
                actual[item.document_index], item, viewport=viewport, apply_ancestors=False
            )[0]
        if not children.get(item.id) and not item.has_effects:
            return Image.new("RGBA", size)
        if item.has_pixel_mask or item.has_vector_mask or item.opacity != 255:
            raise ValueError("psd_owned_context_unsupported")
        effects = _effects(item)
        if (
            any(
                e.kind != "ColorOverlay"
                or e.blend_mode != "normal"
                or e.opacity != 100
                or e.color_rgba is None
                for e in effects
            )
            or len(effects) > 1
        ):
            raise ValueError("psd_owned_context_unsupported")
        if effects:
            branch = []

            def ids(node: PsdLayer) -> None:
                branch.append(node.id)
                for child in children.get(node.id, ()):
                    ids(child)

            ids(item)
            if retained.intersection(branch):
                raise ValueError("psd_owned_context_unsupported")
        image = Image.new("RGBA", size)
        for child in sorted(children.get(item.id, ()), key=lambda l: l.sibling_index):
            image.alpha_composite(draw(child))
        if effects:
            color = effects[0].color_rgba or (0.0, 0.0, 0.0, 1.0)
            tinted = Image.new("RGBA", size, tuple(round(v * 255) for v in color[:3]) + (0,))
            tinted.putalpha(image.getchannel("A"))
            image = tinted
        return image

    return draw(group), viewport
