from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from psd_tools import PSDImage


class PsdIntakeError(ValueError):
    """A PSD cannot be admitted into the HIFI replacement workflow."""


@dataclass(frozen=True)
class PsdInspection:
    source_name: str
    byte_size: int
    sha256: str
    width: int
    height: int
    depth: int
    color_mode: str
    layer_count: int
    kind_counts: dict[str, int]
    text_layer_count: int
    smart_object_count: int
    adjustment_layer_count: int
    effect_layer_count: int
    blocking_issues: tuple[str, ...]
    warnings: tuple[str, ...]


_ADJUSTMENT_KINDS = {
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


def _digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_psd(path: Path, *, source_name: str) -> PsdInspection:
    try:
        with path.open("rb") as source:
            if source.read(4) != b"8BPS":
                raise PsdIntakeError("invalid_psd")
        document = PSDImage.open(path)
    except PsdIntakeError:
        raise
    except Exception as error:
        raise PsdIntakeError("invalid_psd") from error

    layers = list(document.descendants())
    kinds = Counter(str(layer.kind) for layer in layers)
    adjustment_count = sum(count for kind, count in kinds.items() if kind in _ADJUSTMENT_KINDS)
    effect_count = sum(1 for layer in layers if layer.has_effects())

    blockers: list[str] = []
    if document.color_mode.name != "RGB":
        blockers.append("color_mode_not_rgb")
    if document.depth not in {8, 16}:
        blockers.append("unsupported_bit_depth")
    if kinds.get("smartobject", 0):
        blockers.append("smart_objects_require_equivalence_check")
    if adjustment_count:
        blockers.append("adjustment_layers_require_equivalence_check")
    if effect_count:
        blockers.append("layer_effects_require_equivalence_check")

    warnings: list[str] = []
    if document.depth == 16:
        warnings.append("16_bit_pixels_must_not_be_downconverted")

    return PsdInspection(
        source_name=source_name,
        byte_size=path.stat().st_size,
        sha256=_digest(path),
        width=document.width,
        height=document.height,
        depth=document.depth,
        color_mode=document.color_mode.name,
        layer_count=len(layers),
        kind_counts=dict(sorted(kinds.items())),
        text_layer_count=kinds.get("type", 0),
        smart_object_count=kinds.get("smartobject", 0),
        adjustment_layer_count=adjustment_count,
        effect_layer_count=effect_count,
        blocking_issues=tuple(blockers),
        warnings=tuple(warnings),
    )
