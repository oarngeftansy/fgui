from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from lxml import etree

from figma_to_fgui.hifi_replacement_models import (
    FguiComponentInventory,
    FguiObjectRef,
    HifiComponentOption,
    HifiDirectoryOption,
    HifiPackageOption,
    HifiProjectTreeView,
    HifiTargetRef,
)
from figma_to_fgui.paths import safe_relative_path
from figma_to_fgui.uploaded_project import UploadedProjectVersion

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False)
_KNOWN_OBJECT_TAGS = {"component", "graph", "group", "image", "loader", "list", "movieclip", "text"}
_KNOWN_ATTRIBUTES = {
    "id", "name", "xy", "size", "src", "fileName", "type", "text", "color", "font",
    "fontSize", "align", "vAlign", "visible", "touchable", "alpha", "rotation", "pivot",
    "group",
}
_VISUAL_ATTRIBUTES = {
    "xy", "size", "src", "fileName", "text", "color", "font", "fontSize", "align",
    "vAlign", "visible", "alpha", "rotation", "pivot",
}


def _package_manifests(root: Path) -> tuple[Path, ...]:
    return tuple(sorted({*root.glob("*/package.xml"), *root.glob("assets/*/package.xml")}))


def _supports_fairygui_614(root: Path) -> bool:
    markers = tuple(root.glob("*.fairy"))
    if len(markers) != 1:
        return False
    try:
        marker = etree.parse(str(markers[0]), _PARSER).getroot()
    except (OSError, etree.XMLSyntaxError):
        return False
    return (
        str(marker.tag) == "projectDescription"
        and str(marker.attrib.get("type", "")) == "Unity"
        and str(marker.attrib.get("version", "")) == "5.0"
    )


def _resource_relative(package_root: str, virtual_path: str, name: str) -> str:
    return safe_relative_path(f"{package_root}/{virtual_path.strip('/')}/{name}")


def inspect_hifi_targets(
    root: Path,
    project: UploadedProjectVersion,
) -> HifiProjectTreeView:
    supported = _supports_fairygui_614(root)
    package_views: list[HifiPackageOption] = []
    for manifest_path in _package_manifests(root):
        package_root = manifest_path.parent.relative_to(root).as_posix()
        package = etree.parse(str(manifest_path), _PARSER).getroot()
        package_id = str(package.attrib["id"])
        directory_items: dict[str, list[HifiComponentOption]] = {}
        for resource in package.xpath("./resources/component"):
            name = str(resource.attrib.get("name", ""))
            virtual_path = str(resource.attrib.get("path", "/"))
            relative_path = _resource_relative(package_root, virtual_path, name)
            source = root / relative_path
            selectable = False
            reason: str | None = None
            try:
                document = etree.parse(str(source), _PARSER)
                selectable = supported and document.getroot().tag == "component"
                if not selectable:
                    reason = (
                        "unsupported_fairygui_version"
                        if not supported
                        else "invalid_component_root"
                    )
            except (OSError, etree.XMLSyntaxError):
                reason = "component_unavailable"
            directory = virtual_path.strip("/") or "/"
            directory_items.setdefault(directory, []).append(
                HifiComponentOption(
                    version=1,
                    resource_id=str(resource.attrib["id"]),
                    name=Path(name).stem,
                    relative_path=relative_path,
                    selectable=selectable,
                    reason=reason,
                )
            )
        directories = tuple(
            HifiDirectoryOption(
                version=1,
                path=path,
                components=tuple(sorted(items, key=lambda item: item.name.casefold())),
                selectable=any(item.selectable for item in items),
                reason=None if any(item.selectable for item in items) else "no_selectable_components",
            )
            for path, items in sorted(directory_items.items())
        )
        package_views.append(
            HifiPackageOption(
                version=1,
                package_id=package_id,
                name=manifest_path.parent.name,
                directories=directories,
            )
        )
    return HifiProjectTreeView(
        version=1,
        project_id=project.project_id,
        project_fingerprint=project.fingerprint,
        packages=tuple(package_views),
    )


def target_from_option(
    project: UploadedProjectVersion,
    package: HifiPackageOption,
    directory: HifiDirectoryOption,
    component: HifiComponentOption,
) -> HifiTargetRef:
    if not component.selectable or component not in directory.components:
        raise ValueError("component is not selectable in directory")
    return HifiTargetRef(
        version=1,
        project_id=project.project_id,
        project_fingerprint=project.fingerprint,
        package_id=package.package_id,
        package_name=package.name,
        directory=directory.path,
        component_id=component.resource_id,
        component_name=component.name,
        component_relative_path=component.relative_path,
    )


def _pair(value: str | None) -> tuple[float, float]:
    if value is None:
        return 0.0, 0.0
    parts = value.split(",")
    if len(parts) != 2:
        return 0.0, 0.0
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return 0.0, 0.0


def _protected_sha256(element: etree._Element) -> str:
    protected = copy.deepcopy(element)
    for node in protected.iter():
        for attribute in tuple(node.attrib):
            if attribute in _VISUAL_ATTRIBUTES:
                del node.attrib[attribute]
    payload = etree.tostring(protected, method="c14n", with_comments=True)
    return hashlib.sha256(payload).hexdigest()


def inspect_component(root: Path, target: HifiTargetRef) -> FguiComponentInventory:
    relative_path = safe_relative_path(target.component_relative_path)
    source = root / relative_path
    try:
        source.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ValueError("component path escapes project") from error
    component = etree.parse(str(source), _PARSER).getroot()
    if component.tag != "component":
        raise ValueError("invalid component root")
    width, height = _pair(component.attrib.get("size"))
    if width <= 0 or height <= 0:
        raise ValueError("invalid component size")

    transitions: dict[str, list[str]] = {}
    for transition in component.xpath("./transition"):
        transition_name = str(transition.attrib.get("name", ""))
        for item in transition.xpath(".//*[@target]"):
            transitions.setdefault(str(item.attrib["target"]), []).append(transition_name)

    objects: list[FguiObjectRef] = []
    unknown_tags: set[str] = set()
    display_list = component.find("displayList")
    if display_list is not None:
        for index, element in enumerate(display_list):
            object_id = str(element.attrib.get("id", ""))
            if not object_id:
                continue
            x, y = _pair(element.attrib.get("xy"))
            object_width, object_height = _pair(element.attrib.get("size"))
            controller_refs = tuple(
                dict.fromkeys(
                    str(node.attrib["controller"])
                    for node in element.xpath(".//*[@controller]")
                    if node.attrib.get("controller")
                )
            )
            relation_refs = tuple(
                dict.fromkeys(
                    str(node.attrib.get("target", ""))
                    for node in element.xpath(".//relation")
                    if node.attrib.get("target")
                )
            )
            if str(element.tag) not in _KNOWN_OBJECT_TAGS:
                unknown_tags.add(str(element.tag))
            unknown_attributes = tuple(
                sorted(attribute for attribute in element.attrib if attribute not in _KNOWN_ATTRIBUTES)
            )
            objects.append(
                FguiObjectRef(
                    version=1,
                    object_id=object_id,
                    name=str(element.attrib.get("name", object_id)),
                    object_type=str(element.tag),
                    parent_id=element.attrib.get("group"),
                    child_index=index,
                    x=x,
                    y=y,
                    width=object_width,
                    height=object_height,
                    resource_id=element.attrib.get("src"),
                    shared_resource=element.tag == "component" and element.attrib.get("src") is not None,
                    protected_sha256=_protected_sha256(element),
                    controller_refs=controller_refs,
                    transition_refs=tuple(dict.fromkeys(transitions.get(object_id, []))),
                    relation_refs=relation_refs,
                    unknown_attributes=unknown_attributes,
                )
            )
    return FguiComponentInventory(
        version=1,
        target=target,
        width=width,
        height=height,
        objects=tuple(objects),
        unknown_tags=tuple(sorted(unknown_tags)),
        parse_complete=not unknown_tags and not any(item.unknown_attributes for item in objects),
    )
