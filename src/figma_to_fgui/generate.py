import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree

from figma_to_fgui.assets import make_resource_id
from figma_to_fgui.models import (
    ClassificationDecision,
    Diagnostic,
    GeneratedFile,
    NormalizedNode,
    Severity,
)
from figma_to_fgui.normalize import SelectionAsset
from figma_to_fgui.paths import safe_relative_path
from figma_to_fgui.project_index import ProjectIndex

_ASSET_SUFFIX = {
    "image/png": ".png",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


@dataclass(frozen=True)
class _RegisteredAsset:
    asset: str
    resource_id: str
    reused: bool


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
                if (
                    isinstance(asset, str)
                    and asset.startswith("asset_")
                    and isinstance(mime_type, str)
                    and mime_type in _ASSET_SUFFIX
                ):
                    result.append(reference)
    for child in node.children:
        result.extend(_asset_references(child))
    return tuple(result)


def _sha256_matches(path: Path, selection_asset: SelectionAsset) -> bool:
    if not path.is_file() or path.stat().st_size != selection_asset.size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest() == selection_asset.sha256


def _matches_registered_asset(
    item: etree._Element,
    project_root: Path,
    package_name: str,
    name: str,
    selection_asset: SelectionAsset,
) -> bool:
    path = item.attrib.get("path")
    resource_id = item.attrib.get("id")
    if not isinstance(path, str) or not resource_id:
        return False
    try:
        expected = safe_relative_path(f"{package_name}/assets/{name}")
        actual = safe_relative_path(f"{package_name}/{path.strip('/')}/{name}")
    except ValueError:
        return False
    return actual == expected and _sha256_matches(project_root / actual, selection_asset)


def _resolved_asset_name(
    asset: str,
    selection_asset: SelectionAsset,
    existing: dict[str, etree._Element],
    project_root: Path,
    package_name: str,
) -> tuple[str, etree._Element | None]:
    suffix = _ASSET_SUFFIX[selection_asset.mime_type]
    attempt = 0
    while True:
        resolved = asset if attempt == 0 else f"{asset}_{hashlib.sha256(f'{asset}|{selection_asset.sha256}|{attempt}'.encode()).hexdigest()}"
        name = f"{resolved}{suffix}"
        previous = existing.get(name)
        if previous is None:
            return resolved, None
        if _matches_registered_asset(previous, project_root, package_name, name, selection_asset):
            return resolved, previous
        attempt += 1


def _write_package_resources(
    project_root: Path,
    package_name: str,
    staging_root: Path,
    assets: dict[str, SelectionAsset],
    panel_names: tuple[str, ...],
    index: ProjectIndex,
) -> tuple[dict[str, _RegisteredAsset], GeneratedFile]:
    source = project_root / package_name / "package.xml"
    tree = etree.parse(str(source), etree.XMLParser(resolve_entities=False, no_network=True))
    resources = tree.getroot().find("resources")
    if resources is None:
        raise ValueError("package resources are unavailable")
    occupied = set(index.ids_by_package.get(package_name, frozenset()))
    existing = {str(item.attrib.get("name", "")): item for item in resources.findall("image")}
    registered: dict[str, _RegisteredAsset] = {}
    for asset, selection_asset in sorted(assets.items()):
        mime_type = selection_asset.mime_type
        resolved, previous = _resolved_asset_name(
            asset, selection_asset, existing, project_root, package_name
        )
        name = f"{resolved}{_ASSET_SUFFIX[mime_type]}"
        if previous is not None:
            registered[asset] = _RegisteredAsset(
                asset=resolved,
                resource_id=str(previous.attrib["id"]),
                reused=True,
            )
            continue
        resource_id = make_resource_id(f"{resolved}|{name}", frozenset(occupied))
        occupied.add(resource_id)
        previous = etree.SubElement(
            resources,
            "image",
            id=resource_id,
            name=name,
            path="/assets/",
            exported="true",
        )
        existing[name] = previous
        registered[asset] = _RegisteredAsset(
            asset=resolved,
            resource_id=resource_id,
            reused=False,
        )
    existing_components = {str(item.attrib.get("name", "")) for item in resources.findall("component")}
    for panel_name in panel_names:
        file_name = f"{panel_name}.xml"
        if file_name in existing_components:
            continue
        resource_id = make_resource_id(f"{panel_name}|{file_name}", frozenset(occupied))
        occupied.add(resource_id)
        etree.SubElement(
            resources,
            "component",
            id=resource_id,
            name=file_name,
            path="/Panel/",
            exported="true",
        )
    relative = safe_relative_path(f"{package_name}/package.xml")
    payload = etree.tostring(tree, encoding="utf-8", xml_declaration=True, pretty_print=True)
    target = staging_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return registered, GeneratedFile(
        relative_path=relative,
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
    )


def generate_staging(
    roots: tuple[NormalizedNode, ...],
    decisions: tuple[ClassificationDecision, ...],
    package_name: str,
    staging_root: Path,
    project_root: Path | None = None,
    project_index: ProjectIndex | None = None,
    selection_assets: tuple[SelectionAsset, ...] = (),
) -> tuple[tuple[GeneratedFile, ...], tuple[Diagnostic, ...]]:
    if project_index is not None and package_name not in project_index.packages:
        raise ValueError("project package is unavailable")
    decision_by_id = {item.node_id: item for item in decisions}
    diagnostics: list[Diagnostic] = []
    files: list[GeneratedFile] = []
    asset_sources = {asset.asset: asset for asset in selection_assets}
    assets: dict[str, SelectionAsset] = {}
    panel_assets: dict[str, dict[str, SelectionAsset]] = {}
    for root in roots:
        if decision_by_id[root.id].output_type != "PANEL":
            continue
        root_assets: dict[str, SelectionAsset] = {}
        for reference in _asset_references(root):
            asset = str(reference["asset"])
            entry = asset_sources.get(asset)
            if entry is None or entry.mime_type != reference["mimeType"]:
                raise ValueError("selection asset reference is unavailable")
            if asset in assets and assets[asset] != entry:
                raise ValueError("selection asset reference conflict")
            assets[asset] = entry
            root_assets[asset] = entry
        panel_assets[root.id] = root_assets
    panel_names = tuple(
        f"Panel_{package_name}_{root.name}"
        for root in roots
        if decision_by_id[root.id].output_type == "PANEL"
    )
    if len(panel_names) != len(set(panel_names)):
        raise ValueError("selection contains duplicate panel names")
    registrations: dict[str, _RegisteredAsset] = {}
    package_file: GeneratedFile | None = None
    if assets or panel_names:
        if project_root is None or project_index is None:
            if assets:
                raise ValueError("project package resources are unavailable")
        else:
            registrations, package_file = _write_package_resources(
                project_root, package_name, staging_root, assets, panel_names, project_index
            )
    if assets:
        if package_file is None:
            raise ValueError("project package resources are unavailable")
        for asset, selection_asset in sorted(assets.items()):
            registration = registrations[asset]
            if registration.reused:
                continue
            mime_type = selection_asset.mime_type
            asset_relative = safe_relative_path(
                f"{package_name}/assets/{registration.asset}{_ASSET_SUFFIX[mime_type]}"
            )
            asset_target = staging_root / asset_relative
            asset_target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with selection_asset.source_path.open("rb") as source, asset_target.open("wb") as destination:
                while chunk := source.read(64 * 1024):
                    size += len(chunk)
                    digest.update(chunk)
                    destination.write(chunk)
            if size != selection_asset.size or digest.hexdigest() != selection_asset.sha256:
                raise ValueError("selection asset is unavailable")
            files.append(
                GeneratedFile(
                    relative_path=asset_relative,
                    sha256=digest.hexdigest(),
                    size=size,
                )
            )
    for root in roots:
        if decision_by_id[root.id].output_type != "PANEL":
            continue
        root_assets = panel_assets[root.id]
        relative = safe_relative_path(
            f"{package_name}/Panel/Panel_{package_name}_{root.name}.xml"
        )
        target = staging_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        component = etree.Element("component", name=f"Panel_{package_name}_{root.name}")
        display = etree.SubElement(component, "displayList")
        for asset, selection_asset in sorted(root_assets.items()):
            registration = registrations[asset]
            mime_type = selection_asset.mime_type
            etree.SubElement(
                display,
                "image",
                id=f"image_{registration.asset}",
                name=registration.asset,
                src=registration.resource_id,
                file=f"assets/{registration.asset}{_ASSET_SUFFIX[mime_type]}",
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
    if package_file is not None:
        files.append(package_file)
    return tuple(files), tuple(diagnostics)
