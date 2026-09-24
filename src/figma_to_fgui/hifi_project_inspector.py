from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from lxml import etree

from figma_to_fgui.hifi_replacement_models import (
    FguiBehaviorSummary,
    FguiComponentInventory,
    FguiControllerContract,
    FguiControllerPage,
    FguiInstanceContract,
    FguiObjectRef,
    FguiTransitionContract,
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

_GEAR_PROPERTIES = {
    "gearAnimation": ("frame", "playing"),
    "gearColor": ("color", "strokeColor"),
    "gearDisplay": ("visible",),
    "gearDisplay2": ("visible",),
    "gearFontSize": ("fontSize",),
    "gearIcon": ("icon",),
    "gearLook": ("alpha", "rotation", "grayed", "touchable"),
    "gearSize": ("size", "scale"),
    "gearText": ("text",),
    "gearXY": ("xy",),
}
_RUNTIME_OBJECT_TAGS = {"component", "list", "loader", "movieclip"}
_INSTANCE_PARAMETER_TAGS = {
    "Button", "Label", "ProgressBar", "ScrollPane", "property", "customProperty"
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


def _controller_contract(element: etree._Element) -> FguiControllerContract:
    raw_pages = str(element.attrib.get("pages", ""))
    values = raw_pages.split(",") if raw_pages else []
    pages = tuple(
        FguiControllerPage(version=1, page_id=values[index], name=values[index + 1], index=index // 2)
        for index in range(0, len(values) - 1, 2)
    )
    return FguiControllerContract(
        version=1,
        name=str(element.attrib.get("name", "")),
        raw_pages=raw_pages,
        pages=pages,
        action_count=len(element.xpath("./action")),
    )


def _transition_contract(element: etree._Element) -> FguiTransitionContract:
    items = tuple(element.xpath("./item"))
    return FguiTransitionContract(
        version=1,
        name=str(element.attrib.get("name", "")),
        autoplay=str(element.attrib.get("autoPlay", "false")).casefold() == "true",
        repeat=element.attrib.get("repeat"),
        item_count=len(items),
        target_ids=tuple(dict.fromkeys(str(item.attrib["target"]) for item in items if item.attrib.get("target"))),
        item_types=tuple(dict.fromkeys(str(item.attrib.get("type", "")) for item in items)),
    )


def _package_resource_index(root: Path) -> tuple[dict[tuple[str, str], Path], dict[Path, str]]:
    resources: dict[tuple[str, str], Path] = {}
    package_ids: dict[Path, str] = {}
    for manifest_path in _package_manifests(root):
        try:
            package = etree.parse(str(manifest_path), _PARSER).getroot()
        except (OSError, etree.XMLSyntaxError):
            continue
        package_id = str(package.attrib.get("id", ""))
        package_ids[manifest_path.parent.resolve()] = package_id
        for resource in package.xpath("./resources/component[@id][@name]"):
            relative = Path(str(resource.attrib.get("path", "/")).strip("/")) / str(resource.attrib["name"])
            resources[(package_id, str(resource.attrib["id"]))] = manifest_path.parent / relative
    return resources, package_ids


def _owner_id(element: etree._Element, display_list: etree._Element | None) -> str | None:
    current: etree._Element | None = element
    while current is not None and current.getparent() is not display_list:
        current = current.getparent()
    return str(current.attrib.get("id", "")) if current is not None else None


def _instance_parameters(element: etree._Element) -> tuple[str, ...]:
    values: list[str] = []
    for child in element:
        if str(child.tag) not in _INSTANCE_PARAMETER_TAGS and child.attrib.get("controller") is None:
            continue
        attributes = ",".join(f"{key}={value}" for key, value in sorted(child.attrib.items()))
        values.append(f"{child.tag}:{attributes}")
    return tuple(values)


def _referenced_behavior(
    path: Path | None,
    root: Path,
    resources: dict[tuple[str, str], Path],
    package_ids: dict[Path, str],
    seen: set[Path],
) -> tuple[str | None, tuple[str, ...], tuple[int, int, int, int]]:
    if path is None:
        return None, (), (0, 0, 0, 0)
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return None, (), (0, 0, 0, 0)
    if resolved in seen or not resolved.is_file():
        return None, (), (0, 0, 0, 0)
    seen.add(resolved)
    try:
        component = etree.parse(str(resolved), _PARSER).getroot()
    except (OSError, etree.XMLSyntaxError):
        return None, (), (0, 0, 0, 0)
    closure = [resolved.relative_to(root.resolve()).as_posix()]
    counts = [
        len(component.xpath("./controller")),
        len(component.xpath("./transition")),
        len(component.xpath(".//action")),
        len(component.xpath(".//*[starts-with(local-name(), 'gear')]")),
    ]
    package_root = next((parent for parent in package_ids if resolved.is_relative_to(parent)), None)
    local_package = package_ids.get(package_root, "") if package_root is not None else ""
    for instance in component.xpath("./displayList/component[@src]"):
        package_id = str(instance.attrib.get("pkg", local_package))
        nested = resources.get((package_id, str(instance.attrib["src"])))
        _, nested_paths, nested_counts = _referenced_behavior(
            nested, root, resources, package_ids, seen
        )
        closure.extend(nested_paths)
        counts = [value + nested_counts[index] for index, value in enumerate(counts)]
    return (
        _protected_sha256(component),
        tuple(dict.fromkeys(closure)),
        (counts[0], counts[1], counts[2], counts[3]),
    )


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

    controller_contracts = tuple(_controller_contract(item) for item in component.xpath("./controller"))
    transition_contracts = tuple(_transition_contract(item) for item in component.xpath("./transition"))
    transitions: dict[str, list[str]] = {}
    for transition in component.xpath("./transition"):
        transition_name = str(transition.attrib.get("name", ""))
        for item in transition.xpath(".//*[@target]"):
            transitions.setdefault(str(item.attrib["target"]), []).append(transition_name)

    action_targets = {
        str(action.attrib["target"])
        for action in component.xpath(".//action[@target]")
        if action.attrib.get("target")
    }
    resources, package_ids = _package_resource_index(root)
    source_parent = source.parent.resolve()
    package_root = next(
        (parent for parent in sorted(package_ids, key=lambda item: len(item.parts), reverse=True) if source_parent.is_relative_to(parent)),
        None,
    )
    local_package_id = package_ids.get(package_root, "") if package_root is not None else ""

    objects: list[FguiObjectRef] = []
    instances: list[FguiInstanceContract] = []
    unknown_tags: set[str] = set()
    dynamic_object_ids: set[str] = set()
    runtime_bound_object_ids: set[str] = set()
    unresolved_instance_ids: set[str] = set()
    referenced_paths: list[str] = []
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
            gear_nodes = tuple(element.xpath(".//*[starts-with(local-name(), 'gear')]"))
            dynamic_properties = tuple(
                dict.fromkeys(
                    property_name
                    for gear in gear_nodes
                    for property_name in _GEAR_PROPERTIES.get(str(gear.tag), (str(gear.tag),))
                )
            )
            roles: list[str] = []
            if gear_nodes:
                roles.append("controller_driven")
            if object_id in transitions:
                roles.append("transition_target")
            if object_id in action_targets:
                roles.append("controller_action_target")
            if relation_refs:
                roles.append("relation_bound")
            if str(element.tag) in _RUNTIME_OBJECT_TAGS:
                roles.append("runtime_object")
            text_value = str(element.attrib.get("text", ""))
            if (
                element.attrib.get("autoClearText") == "true"
                or text_value.startswith("@")
                or ("{" in text_value and "}" in text_value)
            ):
                roles.append("runtime_data")
                runtime_bound_object_ids.add(object_id)
            instance_parameters = _instance_parameters(element)
            if element.tag == "component" and element.attrib.get("src"):
                roles.append("component_instance")
                if instance_parameters:
                    roles.append("instance_parameterized")
                package_id = str(element.attrib.get("pkg", local_package_id))
                referenced = resources.get((package_id, str(element.attrib["src"])))
                behavior_sha, closure, referenced_counts = _referenced_behavior(
                    referenced, root, resources, package_ids, set()
                )
                referenced_paths.extend(closure)
                controller_assignments = tuple(
                    dict.fromkeys(
                        str(node.attrib["controller"])
                        for node in element.xpath(".//*[@controller]")
                        if node.attrib.get("controller")
                    )
                )
                property_assignments = tuple(
                    value for value in instance_parameters if value.startswith(("property:", "customProperty:"))
                )
                instances.append(
                    FguiInstanceContract(
                        version=1,
                        object_id=object_id,
                        resource_id=str(element.attrib["src"]),
                        package_id=package_id or None,
                        controller_assignments=controller_assignments,
                        property_assignments=property_assignments,
                        parameter_tags=instance_parameters,
                        referenced_component_path=(
                            referenced.resolve().relative_to(root.resolve()).as_posix()
                            if referenced is not None and referenced.is_file()
                            else None
                        ),
                        referenced_behavior_sha256=behavior_sha,
                        referenced_controller_count=referenced_counts[0],
                        referenced_transition_count=referenced_counts[1],
                        referenced_action_count=referenced_counts[2],
                        referenced_gear_count=referenced_counts[3],
                    )
                )
                if behavior_sha is not None:
                    roles.append("nested_behavior")
                else:
                    roles.append("unresolved_component_reference")
                    unresolved_instance_ids.add(object_id)
            if roles:
                dynamic_object_ids.add(object_id)
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
                    behavior_roles=tuple(dict.fromkeys(roles)),
                    dynamic_properties=dynamic_properties,
                    instance_parameters=instance_parameters,
                    behavior_protected=bool(roles),
                )
            )
    dynamic_groups = {
        item.parent_id
        for item in objects
        if item.parent_id is not None and item.behavior_protected
    }
    if dynamic_groups or any(item.parent_id is not None for item in objects):
        updated: list[FguiObjectRef] = []
        for item in objects:
            roles = list(item.behavior_roles)
            if item.parent_id is not None:
                roles.append("group_member")
            if item.object_id in dynamic_groups:
                roles.append("behavior_group")
                dynamic_object_ids.add(item.object_id)
            updated.append(
                item.model_copy(
                    update={
                        "behavior_roles": tuple(dict.fromkeys(roles)),
                        "behavior_protected": bool(roles),
                    }
                )
            )
        objects = updated
    behavior = FguiBehaviorSummary(
        version=1,
        protected_sha256=_protected_sha256(component),
        controllers=controller_contracts,
        transitions=transition_contracts,
        instances=tuple(instances),
        gear_count=len(component.xpath(".//*[starts-with(local-name(), 'gear')]")),
        relation_count=len(component.xpath(".//relation")),
        action_count=len(component.xpath(".//action")),
        dynamic_object_ids=tuple(item.object_id for item in objects if item.object_id in dynamic_object_ids),
        runtime_bound_object_ids=tuple(item.object_id for item in objects if item.object_id in runtime_bound_object_ids),
        referenced_component_paths=tuple(dict.fromkeys(referenced_paths)),
        unresolved_instance_ids=tuple(
            item.object_id for item in objects if item.object_id in unresolved_instance_ids
        ),
    )
    return FguiComponentInventory(
        version=1,
        target=target,
        width=width,
        height=height,
        objects=tuple(objects),
        behavior=behavior,
        unknown_tags=tuple(sorted(unknown_tags)),
        parse_complete=(
            not unknown_tags
            and not unresolved_instance_ids
            and not any(item.unknown_attributes for item in objects)
        ),
    )
