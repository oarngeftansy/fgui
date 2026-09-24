from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, UnidentifiedImageError
from psd_tools import PSDImage

from figma_to_fgui.psd_intake import (
    PsdAnalysis,
    PsdInspection,
    PsdLayer,
    PsdLayerEffect,
    PsdTextRun,
    PsdTextStyle,
    analyze_psd,
)


class PsdSourceStoreError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _erase_masked_pixels(image: Image.Image, mask: Image.Image) -> Image.Image:
    """Fill text-shaped holes from the nearest exact backdrop pixels."""
    source = image.convert("RGBA")
    expanded_mask = mask.convert("L").filter(ImageFilter.MaxFilter(15))
    width, height = source.size
    mask_bytes = expanded_mask.tobytes()
    source_pixels = source.load()
    output = source.copy()
    output_pixels = output.load()
    for offset, value in enumerate(mask_bytes):
        if value == 0:
            continue
        x = offset % width
        y = offset // width
        samples: list[tuple[int, int, int, int]] = []
        for distance in range(1, max(width, height) + 1):
            for sample_x, sample_y in (
                (x - distance, y),
                (x + distance, y),
                (x, y - distance),
                (x, y + distance),
            ):
                if (
                    0 <= sample_x < width
                    and 0 <= sample_y < height
                    and mask_bytes[sample_y * width + sample_x] == 0
                ):
                    samples.append(source_pixels[sample_x, sample_y])
            if len(samples) >= 2:
                break
        if samples:
            output_pixels[x, y] = tuple(
                round(sum(sample[channel] for sample in samples) / len(samples))
                for channel in range(4)
            )
    return output


@dataclass(frozen=True)
class PsdSource:
    version: int
    source_id: str
    inspection: PsdInspection
    layers: tuple[PsdLayer, ...]


@dataclass(frozen=True)
class PsdRasterResource:
    layer_id: str
    key: str
    mime_type: str
    size: int


class PsdSourceStore:
    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir / "hifi-sources" / "psd"
        self._root.mkdir(parents=True, exist_ok=True)

    def admit(self, upload_path: Path, *, source_name: str) -> PsdSource:
        analysis = analyze_psd(upload_path, source_name=source_name)
        source_id = analysis.inspection.sha256
        destination = self._root / source_id
        if destination.is_dir():
            upload_path.unlink(missing_ok=True)
            refreshed = destination / f".hifi-ir-{uuid.uuid4().hex[:8]}.json"
            refreshed.write_text(
                json.dumps(
                    self._payload(source_id, analysis),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            refreshed.replace(destination / "hifi-ir.json")
            return self.get(source_id)

        staging = self._root / f".admit-{source_id}-{uuid.uuid4().hex}"
        staging.mkdir()
        try:
            upload_path.replace(staging / "source.psd")
            payload = self._payload(source_id, analysis)
            (staging / "hifi-ir.json").write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            try:
                staging.rename(destination)
            except OSError:
                if not destination.is_dir():
                    raise
                shutil.rmtree(staging)
            return self.get(source_id)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def get(self, source_id: str) -> PsdSource:
        if len(source_id) != 64 or any(character not in "0123456789abcdef" for character in source_id):
            raise PsdSourceStoreError("psd_source_not_found")
        source_root = self._root / source_id
        source_path = source_root / "source.psd"
        manifest_path = source_root / "hifi-ir.json"
        if not source_path.is_file() or not manifest_path.is_file():
            raise PsdSourceStoreError("psd_source_not_found")
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            source = self._parse(payload, expected_source_id=source_id)
            if source_path.stat().st_size != source.inspection.byte_size:
                raise PsdSourceStoreError("psd_source_corrupt")
            digest = sha256()
            with source_path.open("rb") as stored_psd:
                while chunk := stored_psd.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != source_id:
                raise PsdSourceStoreError("psd_source_corrupt")
            return source
        except PsdSourceStoreError:
            raise
        except (OSError, TypeError, ValueError, KeyError) as error:
            raise PsdSourceStoreError("psd_source_corrupt") from error

    def artifact_path(self, source_id: str) -> Path:
        self.get(source_id)
        return self._root / source_id

    def raster_resource(self, source_id: str, layer_id: str) -> PsdRasterResource:
        return self.raster_resources(source_id, (layer_id,))[layer_id]

    def raster_resources(
        self, source_id: str, layer_ids: tuple[str, ...]
    ) -> dict[str, PsdRasterResource]:
        source = self.get(source_id)
        by_id = {layer.id: layer for layer in source.layers}
        children_by_parent: dict[str | None, list[PsdLayer]] = {}
        for source_layer in source.layers:
            if source_layer.effective_visible:
                children_by_parent.setdefault(source_layer.parent_id, []).append(source_layer)

        def descendant_text_layers(group_id: str) -> tuple[PsdLayer, ...]:
            result: list[PsdLayer] = []
            pending = list(children_by_parent.get(group_id, ()))
            while pending:
                child = pending.pop()
                if child.kind.casefold() == "type":
                    result.append(child)
                pending.extend(children_by_parent.get(child.id, ()))
            return tuple(result)

        source_root = self._root / source_id
        resources = source_root / "resources"
        resources.mkdir(exist_ok=True)
        result: dict[str, PsdRasterResource] = {}
        pending: list[tuple[PsdLayer, str, Path, int, int]] = []
        for layer_id in dict.fromkeys(layer_ids):
            layer = by_id.get(layer_id)
            if layer is None:
                raise PsdSourceStoreError("psd_layer_not_found")
            if layer.kind.casefold() not in {"pixel", "shape", "smartobject", "group"}:
                raise PsdSourceStoreError("psd_layer_raster_unsupported")
            width = layer.bounds[2] - layer.bounds[0]
            height = layer.bounds[3] - layer.bounds[1]
            if width <= 0 or height <= 0:
                raise PsdSourceStoreError("psd_layer_raster_unavailable")
            resource_identity = (
                "group-backdrop-v7\0" + layer.id
                if layer.kind.casefold() == "group"
                else layer.id
            )
            key = "psd-" + sha256(resource_identity.encode("utf-8")).hexdigest()[:32]
            destination = resources / key
            if destination.is_file():
                try:
                    with Image.open(destination) as image:
                        if (
                            image.format != "PNG"
                            or image.mode != "RGBA"
                            or image.size != (width, height)
                        ):
                            raise PsdSourceStoreError("psd_layer_raster_corrupt")
                        image.verify()
                    result[layer.id] = PsdRasterResource(
                        layer_id=layer.id,
                        key=key,
                        mime_type="image/png",
                        size=destination.stat().st_size,
                    )
                    continue
                except (OSError, UnidentifiedImageError) as error:
                    raise PsdSourceStoreError("psd_layer_raster_corrupt") from error
            pending.append((layer, key, destination, width, height))

        if pending:
            try:
                document = PSDImage.open(source_root / "source.psd")
                document_layers = list(document.descendants())
            except (OSError, TypeError, ValueError) as error:
                raise PsdSourceStoreError("psd_layer_raster_unavailable") from error
            exact_document: Image.Image | None = None
            text_mask_document: Image.Image | None = None
            for layer, key, destination, width, height in pending:
                temporary = resources / f".tmp-{uuid.uuid4().hex[:8]}"
                try:
                    if layer.document_index >= len(document_layers):
                        raise PsdSourceStoreError("psd_layer_raster_unavailable")
                    if layer.kind.casefold() == "group":
                        if exact_document is None or text_mask_document is None:
                            exact = document.topil(apply_icc=True)
                            expected_size = (
                                source.inspection.width,
                                source.inspection.height,
                            )
                            if (
                                exact is None
                                or exact.size != expected_size
                            ):
                                raise PsdSourceStoreError("psd_layer_raster_unavailable")
                            exact_document = exact.convert("RGBA")
                            text_mask_document = Image.new("L", expected_size)
                        if exact_document.size != (
                            source.inspection.width,
                            source.inspection.height,
                        ):
                            raise PsdSourceStoreError("psd_layer_raster_unavailable")
                        left, top, right, bottom = layer.bounds
                        padding = 32
                        crop_box = (
                            max(0, left - padding),
                            max(0, top - padding),
                            min(source.inspection.width, right + padding),
                            min(source.inspection.height, bottom + padding),
                        )
                        group_text_mask = text_mask_document.crop(crop_box)
                        mask_draw = ImageDraw.Draw(group_text_mask)
                        for text_layer in descendant_text_layers(layer.id):
                            text_left, text_top, text_right, text_bottom = (
                                text_layer.bounds
                            )
                            mask_draw.rectangle(
                                (
                                    text_left - crop_box[0],
                                    text_top - crop_box[1],
                                    text_right - crop_box[0],
                                    text_bottom - crop_box[1],
                                ),
                                fill=255,
                            )
                        padded = _erase_masked_pixels(
                            exact_document.crop(crop_box), group_text_mask
                        )
                        image = padded.crop(
                            (
                                left - crop_box[0],
                                top - crop_box[1],
                                right - crop_box[0],
                                bottom - crop_box[1],
                            )
                        )
                    else:
                        image = document_layers[layer.document_index].composite(
                            force=True,
                            apply_icc=True,
                        )
                    if image is None or image.size != (width, height):
                        raise PsdSourceStoreError("psd_layer_raster_unavailable")
                    image.convert("RGBA").save(temporary, format="PNG")
                    temporary.replace(destination)
                    result[layer.id] = PsdRasterResource(
                        layer_id=layer.id,
                        key=key,
                        mime_type="image/png",
                        size=destination.stat().st_size,
                    )
                except PsdSourceStoreError:
                    raise
                except (ImportError, OSError, UnidentifiedImageError, ValueError) as error:
                    raise PsdSourceStoreError("psd_layer_raster_unavailable") from error
                finally:
                    temporary.unlink(missing_ok=True)
        return result

    def composite_path(self, source_id: str) -> Path:
        source = self.get(source_id)
        source_root = self._root / source_id
        composite = source_root / "composite.png"
        if composite.is_file():
            try:
                with Image.open(composite) as image:
                    if image.format != "PNG" or image.size != (
                        source.inspection.width,
                        source.inspection.height,
                    ):
                        raise PsdSourceStoreError("psd_composite_corrupt")
                    image.verify()
                return composite
            except (OSError, UnidentifiedImageError) as error:
                raise PsdSourceStoreError("psd_composite_corrupt") from error

        temporary = source_root / f".composite-{uuid.uuid4().hex}.png"
        try:
            document = PSDImage.open(source_root / "source.psd")
            image = document.topil(apply_icc=True)
            if image is None:
                raise PsdSourceStoreError("psd_composite_unavailable")
            if image.size != (source.inspection.width, source.inspection.height):
                raise PsdSourceStoreError("psd_composite_corrupt")
            image.save(temporary, format="PNG")
            temporary.replace(composite)
            return composite
        except PsdSourceStoreError:
            raise
        except (OSError, UnidentifiedImageError, ValueError) as error:
            raise PsdSourceStoreError("psd_composite_unavailable") from error
        finally:
            temporary.unlink(missing_ok=True)

    def effective_viewport_bounds(
        self, source_id: str, width: int, height: int
    ) -> tuple[int, int, int, int]:
        source = self.get(source_id)
        if (
            width <= 0
            or height <= 0
            or width > source.inspection.width
            or height > source.inspection.height
        ):
            raise PsdSourceStoreError("psd_viewport_dimensions_invalid")
        centered_left = (source.inspection.width - width) // 2
        centered_top = (source.inspection.height - height) // 2
        dimension_tokens = {str(width), str(height)}

        candidates: list[tuple[tuple[int, int, int, int], PsdLayer]] = []
        for layer in source.layers:
            layer_width = layer.bounds[2] - layer.bounds[0]
            layer_height = layer.bounds[3] - layer.bounds[1]
            if layer_width != width or layer_height != height:
                continue
            name_tokens = set(re.findall(r"\d+", layer.name))
            dimension_name = dimension_tokens.issubset(name_tokens)
            distance = abs(layer.bounds[0] - centered_left) + abs(
                layer.bounds[1] - centered_top
            )
            candidates.append(
                (
                    (
                        0 if dimension_name else 1,
                        0 if layer.parent_id is None else 1,
                        distance,
                        layer.document_index,
                    ),
                    layer,
                )
            )

        if candidates:
            marker = min(candidates, key=lambda item: item[0])[1]
            left = max(0, min(marker.bounds[0], source.inspection.width - width))
            top = max(0, min(marker.bounds[1], source.inspection.height - height))
        else:
            left = centered_left
            top = centered_top
        return left, top, width, height

    def composite_viewport_path(self, source_id: str, width: int, height: int) -> Path:
        left, top, width, height = self.effective_viewport_bounds(
            source_id, width, height
        )
        source_root = self._root / source_id
        viewport = source_root / f"viewport-{left}-{top}-{width}x{height}.png"
        if viewport.is_file():
            try:
                with Image.open(viewport) as image:
                    if image.format != "PNG" or image.size != (width, height):
                        raise PsdSourceStoreError("psd_viewport_corrupt")
                    image.verify()
                return viewport
            except (OSError, UnidentifiedImageError) as error:
                raise PsdSourceStoreError("psd_viewport_corrupt") from error

        temporary = source_root / f".viewport-{uuid.uuid4().hex}.png"
        try:
            with Image.open(self.composite_path(source_id)) as composite:
                composite.crop((left, top, left + width, top + height)).save(
                    temporary, format="PNG"
                )
            temporary.replace(viewport)
            return viewport
        except PsdSourceStoreError:
            raise
        except (OSError, UnidentifiedImageError, ValueError) as error:
            raise PsdSourceStoreError("psd_viewport_unavailable") from error
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _payload(source_id: str, analysis: PsdAnalysis) -> dict[str, Any]:
        return {
            "version": 1,
            "source_id": source_id,
            "inspection": asdict(analysis.inspection),
            "layers": [asdict(layer) for layer in analysis.layers],
        }

    @staticmethod
    def payload(source: PsdSource) -> dict[str, Any]:
        return {
            "version": source.version,
            "source_id": source.source_id,
            "inspection": asdict(source.inspection),
            "layers": [asdict(layer) for layer in source.layers],
        }

    @staticmethod
    def _parse(payload: Any, *, expected_source_id: str) -> PsdSource:
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise PsdSourceStoreError("psd_source_corrupt")
        if payload.get("source_id") != expected_source_id:
            raise PsdSourceStoreError("psd_source_corrupt")
        inspection_data = payload.get("inspection")
        layers_data = payload.get("layers")
        if not isinstance(inspection_data, dict) or not isinstance(layers_data, list):
            raise PsdSourceStoreError("psd_source_corrupt")
        inspection = PsdInspection(
            **{
                **inspection_data,
                "blocking_issues": tuple(inspection_data["blocking_issues"]),
                "warnings": tuple(inspection_data["warnings"]),
            }
        )
        if inspection.sha256 != expected_source_id:
            raise PsdSourceStoreError("psd_source_corrupt")
        layers = tuple(
            PsdSourceStore._parse_layer(item)
            for item in layers_data
            if isinstance(item, dict)
        )
        if len(layers) != len(layers_data) or len(layers) != inspection.layer_count:
            raise PsdSourceStoreError("psd_source_corrupt")
        if len({layer.id for layer in layers}) != len(layers):
            raise PsdSourceStoreError("psd_source_corrupt")
        return PsdSource(version=1, source_id=expected_source_id, inspection=inspection, layers=layers)

    @staticmethod
    def _parse_layer(item: dict[str, Any]) -> PsdLayer:
        text_style_data = item.get("text_style")
        text_style: PsdTextStyle | None = None
        if isinstance(text_style_data, dict):
            run_items = text_style_data.get("runs")
            transform = text_style_data.get("transform")
            if not isinstance(run_items, list) or not isinstance(transform, list):
                raise PsdSourceStoreError("psd_source_corrupt")
            runs = tuple(
                PsdTextRun(
                    **{
                        **run,
                        "fill_rgba": (
                            tuple(run["fill_rgba"])
                            if run.get("fill_rgba") is not None
                            else None
                        ),
                    }
                )
                for run in run_items
                if isinstance(run, dict)
            )
            if len(runs) != len(run_items) or len(transform) != 6:
                raise PsdSourceStoreError("psd_source_corrupt")
            text_style = PsdTextStyle(
                runs=runs,
                transform=(
                    float(transform[0]),
                    float(transform[1]),
                    float(transform[2]),
                    float(transform[3]),
                    float(transform[4]),
                    float(transform[5]),
                ),
                paragraph_justification=text_style_data.get("paragraph_justification"),
                anti_alias=text_style_data.get("anti_alias"),
            )
        effect_items = item.get("effects", [])
        if not isinstance(effect_items, list) or not all(
            isinstance(effect, dict) for effect in effect_items
        ):
            raise PsdSourceStoreError("psd_source_corrupt")
        effects = tuple(
            PsdLayerEffect(
                **{
                    **effect,
                    "color_rgba": (
                        tuple(effect["color_rgba"])
                        if effect.get("color_rgba") is not None
                        else None
                    ),
                }
            )
            for effect in effect_items
        )
        return PsdLayer(
            **{
                **item,
                "path": tuple(item["path"]),
                "bounds": tuple(item["bounds"]),
                "text_style": text_style,
                "effects": effects,
            }
        )
