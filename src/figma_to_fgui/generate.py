import hashlib
from pathlib import Path

from lxml import etree

from figma_to_fgui.models import (
    ClassificationDecision,
    Diagnostic,
    GeneratedFile,
    NormalizedNode,
    Severity,
)
from figma_to_fgui.paths import safe_relative_path


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
        relative = safe_relative_path(
            f"{package_name}/Panel/Panel_{package_name}_{root.name}.xml"
        )
        target = staging_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        component = etree.Element("component", name=f"Panel_{package_name}_{root.name}")
        display = etree.SubElement(component, "displayList")
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
    return tuple(files), tuple(diagnostics)
