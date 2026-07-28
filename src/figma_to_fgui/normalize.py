from pathlib import Path
from typing import Any

from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.models import Bounds, Diagnostic, NormalizedNode


def _node(raw: dict[str, Any], source_order: int) -> NormalizedNode:
    box = raw["absoluteBoundingBox"]
    children = tuple(_node(child, index) for index, child in enumerate(raw.get("children", [])))
    properties = {
        name: str(value.get("value", ""))
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


def selection_document(manifest: SelectionManifest, resources_root: Path) -> dict[str, object]:
    resources = {resource.key: resource for resource in manifest.resources}

    def node(selection: SelectionNode) -> dict[str, object]:
        references = []
        for key in selection.resource_keys:
            resource = resources[key]
            if not (resources_root / key).is_file():
                raise ValueError("selection resource is unavailable")
            references.append({"path": f"resources/{key}", "mimeType": resource.mime_type})
        style = dict(selection.style)
        if references:
            style["resourceRefs"] = tuple(references)
        raw: dict[str, object] = {
            "id": selection.id,
            "name": selection.name,
            "type": selection.type,
            "absoluteBoundingBox": selection.bounds.model_dump(mode="json"),
            "children": [node(child) for child in selection.children],
            "rotation": selection.rotation,
            "sourceOrder": selection.source_order,
            "componentProperties": {
                name: {"value": value} for name, value in selection.properties.items()
            },
            "style": style,
        }
        if selection.text is not None:
            raw["characters"] = selection.text
        return raw

    return {"roots": [node(selection) for selection in manifest.top_level_nodes]}
