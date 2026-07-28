from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from figma_to_fgui.models import Bounds, FrozenModel


class SelectionError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SelectionLimits:
    max_top_level: int = 20
    max_nodes: int = 5000
    max_session_bytes: int = 200 * 1024 * 1024
    max_resource_bytes: int = 25 * 1024 * 1024
    max_json_depth: int = 32
    max_string_length: int = 64 * 1024
    max_properties: int = 128
    max_resources: int = 1000


class SelectionResource(FrozenModel):
    key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    mime_type: Literal["image/png", "image/webp", "image/svg+xml"]
    size: int = Field(ge=0)


class SelectionWarning(FrozenModel):
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)


class SelectionNode(FrozenModel):
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=500)
    type: str = Field(min_length=1, max_length=80)
    bounds: Bounds
    children: tuple[SelectionNode, ...] = ()
    rotation: float = 0
    visible: bool = True
    opacity: float = Field(default=1, ge=0, le=1)
    source_order: int = Field(default=0, ge=0)
    text: str | None = Field(default=None, max_length=64 * 1024)
    properties: dict[str, Any] = Field(default_factory=dict)
    style: dict[str, Any] = Field(default_factory=dict)
    resource_keys: tuple[str, ...] = ()


class SelectionManifest(FrozenModel):
    version: Literal[1] = 1
    display_name: str = Field(min_length=1, max_length=500)
    top_level_nodes: tuple[SelectionNode, ...]
    resources: tuple[SelectionResource, ...] = ()
    warnings: tuple[SelectionWarning, ...] = ()


class SelectionVersion(FrozenModel):
    selection_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    device_id: str
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: SelectionManifest
    created_at: datetime
    preview_count: int = Field(default=0, ge=0, le=8)


class SelectionTopLevelSummary(FrozenModel):
    name: str
    type: str


class SelectionView(FrozenModel):
    version: Literal[1] = 1
    selection_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    display_name: str
    top_level_summaries: tuple[SelectionTopLevelSummary, ...]
    preview_urls: tuple[str, ...] = ()
    warnings: tuple[SelectionWarning, ...] = ()


def _validate_value(value: Any, limits: SelectionLimits, depth: int = 0) -> None:
    if depth > limits.max_json_depth:
        raise SelectionError("unsupported_selection_content")
    if isinstance(value, str):
        if len(value) > limits.max_string_length:
            raise SelectionError("selection_too_large")
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, (bytes, bytearray)):
        raise SelectionError("unsupported_selection_content")
    if isinstance(value, dict):
        if len(value) > limits.max_properties:
            raise SelectionError("selection_too_large")
        for key, nested in value.items():
            if not isinstance(key, str) or len(key) > limits.max_string_length:
                raise SelectionError("unsupported_selection_content")
            lowered = key.lower()
            if "font" in lowered and any(token in lowered for token in ("byte", "data", "file", "base64")):
                raise SelectionError("unsupported_selection_content")
            if (
                any(token in lowered for token in ("url", "href", "src"))
                and isinstance(nested, str)
                and nested.strip().lower().startswith(("http:", "https:", "//", "data:"))
            ):
                raise SelectionError("unsupported_selection_content")
            _validate_value(nested, limits, depth + 1)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > limits.max_properties:
            raise SelectionError("selection_too_large")
        for nested in value:
            _validate_value(nested, limits, depth + 1)
        return
    raise SelectionError("unsupported_selection_content")


def validate_selection_manifest(
    manifest: SelectionManifest, limits: SelectionLimits | None = None
) -> SelectionManifest:
    limits = limits or SelectionLimits()
    if len(manifest.top_level_nodes) > limits.max_top_level:
        raise SelectionError("selection_too_large")
    if len(manifest.resources) > limits.max_resources:
        raise SelectionError("selection_too_large")
    keys = [resource.key for resource in manifest.resources]
    if len(keys) != len(set(keys)):
        raise SelectionError("selection_resource_duplicate")
    total_size = 0
    node_count = 0
    declared = set(keys)
    pending = list(manifest.top_level_nodes)
    while pending:
        node = pending.pop()
        node_count += 1
        if node_count > limits.max_nodes:
            raise SelectionError("selection_too_large")
        _validate_value(node.properties, limits)
        _validate_value(node.style, limits)
        if any(key not in declared for key in node.resource_keys):
            raise SelectionError("selection_resource_unknown")
        pending.extend(node.children)
    for resource in manifest.resources:
        if resource.size > limits.max_resource_bytes:
            raise SelectionError("selection_too_large")
        total_size += resource.size
        if total_size > limits.max_session_bytes:
            raise SelectionError("selection_too_large")
    return manifest
