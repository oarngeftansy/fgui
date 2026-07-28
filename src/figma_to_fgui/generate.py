import hashlib
from pathlib import Path
from typing import Any

from lxml import etree

from figma_to_fgui.models import (
    ClassificationDecision,
    Diagnostic,
    GeneratedFile,
    NormalizedNode,
    Severity,
)
from figma_to_fgui.paths import safe_relative_path

_ASSET_SUFFIX = {
    "image/png": ".png",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


def _integer(value: float, node_id: str, field: str) -> tuple[int, Diagnostic | None]:
    result = round(value)
    if result == value:
        return result, None
    return result, Diagnostic(
        code="geometry.rounded",
        severity=Severity.INFO,
        message=f"Rounded {field} from {value} to {result}",
        node_id=node_id,
        rule_id="geometry.integer-output",
        rule_version=1,
    )


def _asset_references(node: NormalizedNode) -> tuple[dict[str, Any], ...]:
    references = node.raw_style.get("resourceRefs", ())
    result: list[dict[str, Any]] = []
    if isinstance(references, (list, tuple)):
        for reference in references:
            if isinstance(reference, dict):
                asset = reference.get("asset")
                mime_type = reference.get("mimeType")
                content = reference.get("content")
                if (
                    isinstance(asset, str)
                    and asset.startswith("asset_")
                    and isinstance(mime_type, str)
                    and mime_type in _ASSET_SUFFIX
                    and isinstance(content, bytes)
                ):
                    result.append(reference)
    for child in node.children:
        result.extend(_asset_references(child))
    return tuple(result)


def generate_staging(
    roots: tuple[NormalizedNode, ...],
    decisions: tuple[ClassificationDecision, ...],
    package_name: str,
    staging_root: Path,
) -> tuple[tuple[GeneratedFile, ...], tuple[Diagnostic, ...]]:
    decision_by_id = {item.node_id: item for item in decisions}
    diagnostics: list[Diagnostic] = []
    files: list[GeneratedFile] = []
    for root in roots:
        if decision_by_id[root.id].output_type != "PANEL":
            continue
        assets: dict[str, tuple[str, bytes]] = {}
        for reference in _asset_references(root):
            asset = str(reference["asset"])
            entry = (str(reference["mimeType"]), bytes(reference["content"]))
            if asset in assets and assets[asset] != entry:
                raise ValueError("selection asset reference conflict")
            assets[asset] = entry
        relative = safe_relative_path(
            f"{package_name}/Panel/Panel_{package_name}_{root.name}.xml"
        )
        target = staging_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        component = etree.Element("component", name=f"Panel_{package_name}_{root.name}")
        display = etree.SubElement(component, "displayList")
        for asset, (mime_type, _) in sorted(assets.items()):
            etree.SubElement(
                display,
                "image",
                id=f"image_{asset}",
                name=asset,
                file=f"assets/{asset}{_ASSET_SUFFIX[mime_type]}",
            )
        for child in sorted(root.children, key=lambda item: item.source_order):
            x, dx = _integer(child.bounds.x - root.bounds.x, child.id, "x")
            y, dy = _integer(child.bounds.y - root.bounds.y, child.id, "y")
            width, dw = _integer(child.bounds.width, child.id, "width")
            height, dh = _integer(child.bounds.height, child.id, "height")
            diagnostics.extend(item for item in (dx, dy, dw, dh) if item is not None)
            if decision_by_id[child.id].output_type == "TEXT":
                etree.SubElement(
                    display,
                    "text",
                    id=child.id.replace(":", "_"),
                    name=child.name,
                    xy=f"{x},{y}",
                    size=f"{width},{height}",
                    autoSize="none",
                    text=child.text or "",
                )
        payload = etree.tostring(
            component, encoding="utf-8", xml_declaration=True, pretty_print=True
        )
        target.write_bytes(payload)
        files.append(
            GeneratedFile(
                relative_path=relative,
                sha256=hashlib.sha256(payload).hexdigest(),
                size=len(payload),
            )
        )
        for asset, (mime_type, content) in sorted(assets.items()):
            asset_relative = safe_relative_path(
                f"{package_name}/assets/{asset}{_ASSET_SUFFIX[mime_type]}"
            )
            asset_target = staging_root / asset_relative
            asset_target.parent.mkdir(parents=True, exist_ok=True)
            asset_target.write_bytes(content)
            files.append(
                GeneratedFile(
                    relative_path=asset_relative,
                    sha256=hashlib.sha256(content).hexdigest(),
                    size=len(content),
                )
            )
    return tuple(files), tuple(diagnostics)
