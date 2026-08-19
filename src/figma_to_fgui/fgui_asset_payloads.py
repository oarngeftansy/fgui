"""Fail-closed validation for raw asset payloads used by the XML writer."""

from __future__ import annotations

import hashlib
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from io import BytesIO
from threading import Lock
from typing import Final

from PIL import Image, ImageFile, UnidentifiedImageError

from figma_to_fgui.fgui_new_project_models import AssetPayload, AssetPayloadSet
from figma_to_fgui.fgui_plan_models import ResourcePlan
from figma_to_fgui.models import Diagnostic, Severity

HASH_CHUNK_SIZE: Final = 64 * 1024
MAX_IMAGE_PIXELS: Final = 89_478_485
_PILLOW_LOCK = Lock()
_FORMAT_DETAILS: Final = {
    "PNG": ("png", "image/png"),
    "JPEG": ("jpg", "image/jpeg"),
    "WEBP": ("webp", "image/webp"),
}


@dataclass(frozen=True)
class ValidatedAssetPayload:
    """One resource whose retained byte payload matches its public plan facts."""

    resource: ResourcePlan
    payload: AssetPayload = field(repr=False)

    @property
    def content(self) -> bytes:
        """Return bytes only to the serializer after this input gate succeeds."""
        return self.payload.content


class NewProjectInputError(Exception):
    """Input-gate failure containing only deterministic, public diagnostics."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("New FairyGUI project input validation failed.")


def diagnostic_sort_key(diagnostic: Diagnostic) -> tuple[str, str, str, str, int, str, str, bool]:
    """Provide one public, stable order for error reporting."""
    return (
        diagnostic.code,
        diagnostic.node_id or "",
        diagnostic.path or "",
        diagnostic.rule_id or "",
        diagnostic.rule_version or 0,
        diagnostic.message,
        diagnostic.suggested_action or "",
        diagnostic.blocks_binding,
    )


def _diagnostic(code: str, resource_id: str, message: str) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=Severity.ERROR,
        message=message,
        node_id=resource_id,
        blocks_binding=True,
    )


def _streamed_sha256(content: bytes) -> str:
    digest = hashlib.sha256()
    view = memoryview(content)
    for offset in range(0, len(view), HASH_CHUNK_SIZE):
        digest.update(view[offset : offset + HASH_CHUNK_SIZE])
    return digest.hexdigest()


def _read_raster_details(content: bytes) -> tuple[str, int, int] | None:
    """Verify and load a Pillow-supported raster without accepting unsafe input."""
    with _PILLOW_LOCK:
        previous_limit = Image.MAX_IMAGE_PIXELS
        previous_truncated_setting = ImageFile.LOAD_TRUNCATED_IMAGES
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        ImageFile.LOAD_TRUNCATED_IMAGES = False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as image:
                    detected_format = image.format
                    width, height = image.size
                    image.verify()
                with Image.open(BytesIO(content)) as image:
                    image.load()
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            OSError,
            SyntaxError,
            UnidentifiedImageError,
            ValueError,
        ):
            return None
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit
            ImageFile.LOAD_TRUNCATED_IMAGES = previous_truncated_setting

    if detected_format is None:
        return None
    return detected_format, width, height


def _nine_slice_is_in_bounds(resource: ResourcePlan, width: int, height: int) -> bool:
    nine_slice = resource.nine_slice
    return nine_slice is None or (
        nine_slice.x + nine_slice.width <= width and nine_slice.y + nine_slice.height <= height
    )


def validate_asset_payloads(
    resources: Mapping[str, ResourcePlan], payloads: AssetPayloadSet
) -> tuple[ValidatedAssetPayload, ...]:
    """Validate every supplied payload before any resource bytes reach the writer.

    This deliberately accumulates only public metadata failures.  Raw bytes and
    parser details are never placed in diagnostics or exception text.
    """
    diagnostics: list[Diagnostic] = []
    resource_keys = set(resources)
    payload_keys = set(payloads.by_resource_id)

    for resource_id in sorted(resource_keys - payload_keys):
        diagnostics.append(
            _diagnostic(
                "fgui.writer.asset.missing",
                resource_id,
                "The resource has no supplied asset payload.",
            )
        )
    for resource_id in sorted(payload_keys - resource_keys):
        diagnostics.append(
            _diagnostic(
                "fgui.writer.asset.unexpected",
                resource_id,
                "The supplied asset payload is not declared by the resource plan.",
            )
        )

    validated: dict[str, ValidatedAssetPayload] = {}
    for resource_id in sorted(resource_keys & payload_keys):
        resource = resources[resource_id]
        payload = payloads.payload_for(resource_id)
        if resource.id != resource_id:
            diagnostics.append(
                _diagnostic(
                    "fgui.writer.asset.resource_key_mismatch",
                    resource_id,
                    "The resource mapping key does not match the resource identity.",
                )
            )
            continue
        if resource.export_format == "svg":
            diagnostics.append(
                _diagnostic(
                    "fgui.writer.asset.svg_unsupported",
                    resource_id,
                    "SVG payloads are not supported by the Writer v1 input gate.",
                )
            )
            continue

        if (
            resource.content_sha256 is None
            or _streamed_sha256(payload.content) != resource.content_sha256
        ):
            diagnostics.append(
                _diagnostic(
                    "fgui.writer.asset.hash_mismatch",
                    resource_id,
                    "The asset payload does not match the declared content hash.",
                )
            )
            continue

        raster_details = _read_raster_details(payload.content)
        if raster_details is None:
            diagnostics.append(
                _diagnostic(
                    "fgui.writer.asset.invalid_image",
                    resource_id,
                    "The asset payload is not a complete supported raster image.",
                )
            )
            continue
        detected_format, width, height = raster_details
        format_details = _FORMAT_DETAILS.get(detected_format)
        if format_details is None:
            diagnostics.append(
                _diagnostic(
                    "fgui.writer.asset.format_mismatch",
                    resource_id,
                    "The detected image format is not supported by the Writer v1 input gate.",
                )
            )
            continue
        detected_export_format, detected_mime_type = format_details
        if resource.export_format != detected_export_format:
            diagnostics.append(
                _diagnostic(
                    "fgui.writer.asset.format_mismatch",
                    resource_id,
                    "The detected image format does not match the resource export format.",
                )
            )
            continue
        if (
            resource.mime_type != detected_mime_type
            or payload.declared_mime_type != detected_mime_type
        ):
            diagnostics.append(
                _diagnostic(
                    "fgui.writer.asset.mime_mismatch",
                    resource_id,
                    "The declared MIME type does not match the detected image format.",
                )
            )
            continue
        if resource.width != width or resource.height != height:
            diagnostics.append(
                _diagnostic(
                    "fgui.writer.asset.dimension_mismatch",
                    resource_id,
                    "The declared resource dimensions do not match the detected image dimensions.",
                )
            )
            continue
        if not _nine_slice_is_in_bounds(resource, width, height):
            diagnostics.append(
                _diagnostic(
                    "fgui.writer.asset.nine_slice_out_of_bounds",
                    resource_id,
                    "The declared nine-slice bounds exceed the detected image dimensions.",
                )
            )
            continue
        validated[resource_id] = ValidatedAssetPayload(resource=resource, payload=payload)

    if diagnostics:
        raise NewProjectInputError(tuple(sorted(diagnostics, key=diagnostic_sort_key)))
    return tuple(validated[resource_id] for resource_id in sorted(validated))
