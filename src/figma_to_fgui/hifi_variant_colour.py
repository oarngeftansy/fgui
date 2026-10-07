from __future__ import annotations

"""Policy 28 state variant derivation: colour transforms between the states
of one controller-scoped family.

Old projects ship state families as pure colour variants of one shape
(normal / num / gift / unlock pages of the same badge). When a reskin
matches one state of the family (the base), the remaining states inherit
the old family relationship applied to the new base image:

    new_state = colour_transform(old_base -> old_state) applied to new_base

Acceptance is conservative: the old pair must share its alpha mask (same
shape, IoU >= 0.8), the fitted transform must explain the old pair
(residual limit), and the applied result must keep structure (variance
floor) so degenerate collapses (e.g. a solid-white sheet) never destroy the
new artwork.
"""
import numpy as np
from PIL import Image

_VARIANT_MASK_IOU = 0.8
_FIT_RESIDUAL_LIMIT = 24.0
_MIN_OUTPUT_VARIANCE = 12.0


def _opaque_mask(array: np.ndarray) -> np.ndarray:
    return array[:, :, 3] >= 200


def learn_colour_transform(
    old_base: Image.Image, old_variant: Image.Image,
    explain: list[str] | None = None,
) -> tuple[np.ndarray, np.ndarray] | None:
    base = old_base.convert("RGBA")
    variant = old_variant.convert("RGBA")
    if base.size != variant.size:
        variant = variant.resize(base.size, Image.Resampling.LANCZOS)
    base_array = np.asarray(base, dtype=np.float32)
    variant_array = np.asarray(variant, dtype=np.float32)
    base_mask = _opaque_mask(base_array)
    variant_mask = _opaque_mask(variant_array)
    both = base_mask & variant_mask
    union = base_mask | variant_mask
    if union.sum() == 0 or both.sum() < 64:
        if explain is not None:
            explain.append("shared_pixels")
        return None
    if both.sum() / union.sum() < _VARIANT_MASK_IOU:
        if explain is not None:
            explain.append("mask_iou")
        return None
    xs = base_array[:, :, :3][both]
    ys = variant_array[:, :, :3][both]
    x_mean = xs.mean(axis=0)
    y_mean = ys.mean(axis=0)
    x_centered = xs - x_mean
    y_centered = ys - y_mean
    covariance = x_centered.T @ x_centered
    ridge = max(1.0, float(np.trace(covariance)) * 1e-4)
    matrix = np.linalg.solve(
        covariance + ridge * np.eye(3, dtype=np.float32),
        x_centered.T @ y_centered,
    ).T
    offset = (y_mean - matrix @ x_mean).astype(np.float32)
    fitted = xs @ matrix.T + offset
    residual = float(np.abs(fitted - ys).mean())
    if residual > _FIT_RESIDUAL_LIMIT:
        if explain is not None:
            explain.append("fit_residual")
        return None
    return matrix.astype(np.float32), offset


def apply_colour_transform(
    image: Image.Image, matrix: np.ndarray, offset: np.ndarray,
    explain: list[str] | None = None,
) -> Image.Image | None:
    source = image.convert("RGBA")
    array = np.asarray(source, dtype=np.float32)
    mask = _opaque_mask(array)
    if mask.sum() == 0:
        if explain is not None:
            explain.append("empty_mask")
        return None
    flat = array[:, :, :3][mask]
    mapped = flat @ matrix.T + offset
    variance = float(mapped.var(axis=0).sum())
    if variance < _MIN_OUTPUT_VARIANCE:
        if explain is not None:
            explain.append("variance_floor")
        return None
    result = array.copy()
    result[:, :, :3] = np.clip(array[:, :, :3] @ matrix.T + offset, 0.0, 255.0)
    return Image.fromarray(result.astype(np.uint8), "RGBA")
