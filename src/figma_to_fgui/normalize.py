from typing import Any

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
        source_order=source_order,
        properties=properties,
        raw_style=dict(raw.get("style", {})),
    )


def normalize_document(
    raw: dict[str, object],
) -> tuple[tuple[NormalizedNode, ...], tuple[Diagnostic, ...]]:
    return (_node(raw, 0),), ()
