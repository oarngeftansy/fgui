import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.models import Bounds, Diagnostic, NormalizedNode


@dataclass(frozen=True)
class SelectionAsset:
    asset: str
    mime_type: str
    source_path: Path
    size: int
    sha256: str
    artifact_fingerprint: str


class SelectionDocument(dict[str, object]):
    """A mapping-shaped document with private conversion-only asset context."""

    def __init__(self, raw: dict[str, object], selection_assets: tuple[SelectionAsset, ...]) -> None:
        super().__init__(raw)
        self._selection_assets = selection_assets

    @property
    def _conversion_assets(self) -> tuple[SelectionAsset, ...]:
        return self._selection_assets

    def copy(self) -> Self:
        return type(self)(dict(self), self._selection_assets)


@dataclass(frozen=True)
class SelectionConversionDocument:
    raw: SelectionDocument
    assets: tuple[SelectionAsset, ...]


def _node(raw: dict[str, Any], source_order: int) -> NormalizedNode:
    box = raw["absoluteBoundingBox"]
    children = tuple(_node(child, index) for index, child in enumerate(raw.get("children", [])))
    properties = {
        name: value.get("value", "")
        for name, value in raw.get("componentProperties", {}).items()
    }
    return NormalizedNode(
        id=str(raw["id"]),
        name=str(raw.get("name", "")),
        type=str(raw["type"]),
        bounds=Bounds(x=box["x"], y=box["y"], width=box["width"], height=box["height"]),
        children=children,
        text=raw.get("characters"),
        rotation=float(raw.get("rotation", 0)),
        opacity=float(raw.get("opacity", 1)),
        visible=bool(raw.get("visible", True)),
        source_order=int(raw.get("sourceOrder", source_order)),
        properties=properties,
        raw_style=dict(raw.get("style", {})),
    )


def normalize_document(
    raw: dict[str, object],
) -> tuple[tuple[NormalizedNode, ...], tuple[Diagnostic, ...]]:
    roots = raw.get("roots")
    if isinstance(roots, list) and all(isinstance(root, dict) for root in roots):
        return tuple(_node(root, index) for index, root in enumerate(roots)), ()
    return (_node(raw, 0),), ()


def selection_conversion_document(
    manifest: SelectionManifest, resources_root: Path, artifact_fingerprint: str = ""
) -> SelectionConversionDocument:
    resources = {resource.key: resource for resource in manifest.resources}
    references: dict[str, dict[str, object]] = {}
    assets: list[SelectionAsset] = []
    try:
        root = resources_root.resolve(strict=True)
    except OSError as error:
        raise ValueError("selection resources are unavailable") from error

    for index, (key, resource) in enumerate(resources.items()):
        try:
            source = (root / key).resolve(strict=True)
        except OSError as error:
            raise ValueError("selection resource is unavailable") from error
        if not source.is_file() or root not in source.parents or source.stat().st_size != resource.size:
            raise ValueError("selection resource is unavailable")
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            while chunk := handle.read(64 * 1024):
                digest.update(chunk)
        asset = "asset_" + hashlib.sha256(
            f"{artifact_fingerprint}|{index}|{resource.mime_type}|{resource.size}|{digest.hexdigest()}".encode()
        ).hexdigest()[:24]
        references[key] = {
            "asset": asset,
            "mimeType": resource.mime_type,
        }
        assets.append(
            SelectionAsset(
                asset=asset,
                mime_type=resource.mime_type,
                source_path=source,
                size=resource.size,
                sha256=digest.hexdigest(),
                artifact_fingerprint=artifact_fingerprint,
            )
        )

    def node_id(selection: SelectionNode, position: tuple[int, ...]) -> str:
        payload = {
            "position": position,
            "name": selection.name,
            "type": selection.type,
            "bounds": selection.bounds.model_dump(mode="json"),
            "rotation": selection.rotation,
            "text": selection.text,
            "properties": selection.properties,
            "style": selection.style,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"node_{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:20]}"

    def node(selection: SelectionNode, position: tuple[int, ...]) -> dict[str, object]:
        node_references = []
        for key in selection.resource_keys:
            node_references.append(references[key])
        style = dict(selection.style)
        if node_references:
            style["resourceRefs"] = tuple(node_references)
        raw: dict[str, object] = {
            "id": node_id(selection, position),
            "name": selection.name,
            "type": selection.type,
            "absoluteBoundingBox": selection.bounds.model_dump(mode="json"),
            "children": [node(child, position + (index,)) for index, child in enumerate(selection.children)],
            "rotation": selection.rotation,
            "opacity": selection.opacity,
            "visible": selection.visible,
            "sourceOrder": selection.source_order,
            "componentProperties": {
                name: {"value": value} for name, value in selection.properties.items()
            },
            "style": style,
        }
        if selection.text is not None:
            raw["characters"] = selection.text
        return raw

    return SelectionConversionDocument(
        raw=SelectionDocument(
            {"roots": [node(selection, (index,)) for index, selection in enumerate(manifest.top_level_nodes)]},
            tuple(assets),
        ),
        assets=tuple(assets),
    )


def selection_document(manifest: SelectionManifest, resources_root: Path) -> dict[str, object]:
    return selection_conversion_document(manifest, resources_root).raw
