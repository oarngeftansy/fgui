"""Instance-qualified inventory. Definition identity never replaces instance identity."""

from __future__ import annotations

import re

import base64
import copy
import hashlib
import os
import shutil
import tempfile
from itertools import pairwise
from pathlib import Path

from lxml import etree
from PIL import Image, UnidentifiedImageError

from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.hifi_project_inspector import (
    _package_resource_index,
    _pair,
    inspect_component,
    resolve_runtime_bound_geometry,
)
from figma_to_fgui.hifi_replacement_models import (
    FguiComponentInventory,
    FguiObjectRef,
    HifiMappingDraft,
    HifiMappingItem,
    HifiObjectDiff,
    HifiReplacementReview,
    HifiTargetRef,
)
from figma_to_fgui.service_contracts import ChangeBundle

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


def _component_content_node(node: SelectionNode) -> SelectionNode:
    """Return a PSD group with bounds derived from its rendered leaves."""
    from figma_to_fgui.models import Bounds

    if not node.children:
        return node
    leaves: list[SelectionNode] = []
    pending = list(node.children)
    while pending:
        child = pending.pop()
        if child.children:
            pending.extend(child.children)
        elif child.visible and child.bounds.width > 0 and child.bounds.height > 0:
            leaves.append(child)
    if not leaves:
        return node
    left = min(child.bounds.x for child in leaves)
    top = min(child.bounds.y for child in leaves)
    right = max(child.bounds.x + child.bounds.width for child in leaves)
    bottom = max(child.bounds.y + child.bounds.height for child in leaves)
    return node.model_copy(update={
        "bounds": Bounds(x=left, y=top, width=right - left, height=bottom - top)
    })


def _visible_on_selected_pages(element: etree._Element, controllers: dict[str, str]) -> bool:
    if element.get("visible") == "false":
        return False
    for gear in element.findall("gearDisplay"):
        selected = controllers.get(gear.get("controller", ""))
        if selected is None:
            continue
        pages = {page for page in gear.get("pages", "").split(",") if page}
        if pages and selected not in pages:
            return False
    return True


def _instance_controller_overrides(element: etree._Element) -> dict[str, str]:
    raw = [value for value in element.get("controller", "").split(",") if value]
    return {raw[index]: raw[index + 1] for index in range(0, len(raw) - 1, 2)}


def _runtime_controller_pages(
    document: etree._ElementTree,
    overrides: dict[str, str],
) -> dict[str, str]:
    """Resolve the page used when a component instance is constructed.

    FairyGUI resets a referenced component's controllers to their first page
    when constructing an instance.  The definition's ``selected`` attribute
    is editor state, not the runtime initial page.  A parent instance may then
    override an exported controller by index through its ``controller``
    attribute.
    """
    result: dict[str, str] = {}
    for controller in document.xpath("./controller[@name]"):
        raw_pages = controller.get("pages", "").split(",")
        page_ids = raw_pages[0::2]
        if not page_ids:
            continue
        selected = page_ids[0]
        override = overrides.get(str(controller.get("name")))
        if override is not None:
            try:
                index = int(override)
            except ValueError:
                if override in page_ids:
                    selected = override
            else:
                if 0 <= index < len(page_ids):
                    selected = page_ids[index]
        result[str(controller.get("name"))] = selected
    return result


def component_target(root: Path, target: HifiTargetRef, path: str) -> HifiTargetRef:
    resources, _ = _package_resource_index(root)
    resolved = (root / path).resolve()
    for (package_id, resource_id), resource in resources.items():
        if resource.resolve() == resolved:
            package_root = next(p for p in resolved.parents if (p / "package.xml").is_file())
            relative = resolved.relative_to(package_root)
            return target.model_copy(
                update={
                    "package_id": package_id,
                    "package_name": package_root.name,
                    "component_id": resource_id,
                    "component_name": resolved.stem,
                    "directory": relative.parent.as_posix(),
                    "component_relative_path": path,
                }
            )
    raise ValueError("hifi_component_reference_missing")


_LIST_TEMPLATE_SUFFIX = "@item"


def _resolve_component_reference(root: Path, reference: str) -> str | None:
    """Resolve a ui://package+resource reference to a component path."""
    payload = reference[5:] if reference.startswith("ui://") else reference
    if not payload:
        return None
    for manifest_path in sorted(root.glob("assets/*/package.xml")):
        try:
            package = etree.parse(str(manifest_path), _PARSER).getroot()
        except (OSError, etree.XMLSyntaxError):
            continue
        package_id = str(package.get("id", ""))
        if not package_id or not payload.startswith(package_id):
            continue
        resource_id = payload[len(package_id):]
        for resource in package.xpath("./resources/component[@id][@name][@path]"):
            if str(resource.get("id")) != resource_id:
                continue
            relative = Path(str(resource.get("path", "/")).strip("/")) / str(
                resource.get("name")
            )
            return (manifest_path.parent / relative).relative_to(root).as_posix()
    return None


def _shared_list_templates(root: Path) -> set[str]:
    """defaultItem references used by more than one list in the project."""
    counts: dict[str, int] = {}
    for manifest_path in sorted(root.glob("assets/*/package.xml")):
        for component_path in sorted(manifest_path.parent.rglob("*.xml")):
            if component_path == manifest_path:
                continue
            try:
                document = etree.parse(str(component_path), _PARSER)
            except (OSError, etree.XMLSyntaxError):
                continue
            for lst in document.xpath("./displayList/list[@defaultItem]"):
                reference = str(lst.get("defaultItem"))
                counts[reference] = counts.get(reference, 0) + 1
    return {reference for reference, count in counts.items() if count > 1}


def _qualified(prefix: tuple[str, ...], local_id: str) -> str:
    value = (prefix[-1] + ":" if prefix else "") + local_id
    return value if len(value) <= 110 else "nested:" + hashlib.sha256(value.encode()).hexdigest()


def inspect_component_tree(root: Path, target: HifiTargetRef) -> FguiComponentInventory:
    initial = inspect_component(root, target)
    result: list[FguiObjectRef] = []
    issues: list[str] = []
    complete = initial.parse_complete
    shared_templates = _shared_list_templates(root)

    def visit(
        local: FguiComponentInventory,
        prefix: tuple[str, ...],
        origin: tuple[float, float],
        scale: tuple[float, float],
        ancestors: frozenset[str],
        inherited: tuple[str, ...],
        parent_visible: bool,
        instance_title: str | None,
        controller_overrides: dict[str, str],
    ) -> None:
        nonlocal complete
        path = local.target.component_relative_path
        if path in ancestors:
            issues.append("cycle:" + ":".join(prefix))
            complete = False
            return
        complete = complete and local.parse_complete
        document = etree.parse(str(root / path), _PARSER)
        elements = {e.get("id"): e for e in document.xpath("./displayList/*[@id]")}
        controllers = _runtime_controller_pages(document, controller_overrides)
        instances = {i.object_id: i for i in local.behavior.instances}
        for item in local.objects:
            element = elements[item.object_id]
            default_visible = parent_visible and _visible_on_selected_pages(element, controllers)
            runtime_text_override = item.object_type in {"text", "richtext"} and item.name == "title" and instance_title is not None
            blockers = inherited
            if element.get("rotation", "0") != "0" or element.get("skew"):
                blockers += ("transformed_object_requires_editor_geometry",)
            x, y = item.x, item.y
            if element.get("anchor") == "true":
                px, py = _pair(element.get("pivot"))
                x -= px * item.width
                y -= py * item.height
            instance = instances.get(item.object_id)
            object_id = _qualified(prefix, item.object_id)
            global_item = item.model_copy(
                update={
                    "object_id": object_id,
                    "out_of_scope": False,
                    "parent_id": _qualified(prefix, item.parent_id)
                    if item.parent_id
                    else (prefix[-1] if prefix else None),
                    "component_relative_path": path,
                    "local_object_id": item.object_id,
                    "instance_path": prefix,
                    "owner_origin": origin,
                    "owner_scale": scale,
                    "x": origin[0] + x * scale[0],
                    "y": origin[1] + y * scale[1],
                    "width": item.width * scale[0],
                    "height": item.height * scale[1],
                    "behavior_protected": item.behavior_protected or bool(prefix),
                    "behavior_roles": (*item.behavior_roles, "nested_instance")
                    if prefix
                    else item.behavior_roles,
                    "write_blockers": tuple(dict.fromkeys(blockers)),
                    "raster_conversion_allowed": False,
                    "default_visible": default_visible,
                    "effective_text": instance_title if runtime_text_override else element.get("text"),
                    "runtime_text_override": runtime_text_override,
                }
            )
            if item.object_type == "graph":
                from figma_to_fgui.hifi_type_permissions import can_convert

                global_item = global_item.model_copy(
                    update={"raster_conversion_allowed": can_convert(root, local, item.object_id)}
                )
            result.append(global_item)
            # Policy 28 §13: a GList defaultItem template is a semantic root of
            # its own; its children enter the inventory at the list origin so
            # PSD row groups can pair with the row template.
            default_item = element.get("defaultItem") if element.tag == "list" else None
            if default_item:
                template_relative = _resolve_component_reference(root, str(default_item))
                if template_relative is not None:
                    template_blockers = blockers
                    if str(default_item) in shared_templates:
                        template_blockers += (
                            "shared_list_template_requires_user_decision",
                        )
                    try:
                        template_target = component_target(
                            root, target, template_relative
                        )
                        template = inspect_component(root, template_target)
                    except (OSError, ValueError, etree.XMLSyntaxError):
                        complete = False
                        issues.append("unreadable:" + object_id + _LIST_TEMPLATE_SUFFIX)
                        template = None
                    if template is not None and template.objects:
                        result[-1] = global_item.model_copy(
                            update={"structural_only": True}
                        )
                        mark_from = len(result)
                        visit(
                            template,
                            (*prefix, object_id),
                            (global_item.x, global_item.y),
                            scale,
                            ancestors | {path},
                            tuple(dict.fromkeys(template_blockers)),
                            default_visible,
                            None,
                            {},
                        )
                        result[mark_from:] = [
                            obj.model_copy(
                                update={
                                    "behavior_roles": (
                                        *obj.behavior_roles,
                                        "list_item_template",
                                    )
                                }
                            )
                            for obj in result[mark_from:]
                        ]
            if instance is None or instance.referenced_component_path is None:
                continue
            try:
                child_target = component_target(root, target, instance.referenced_component_path)
                child = inspect_component(root, child_target)
            except (OSError, ValueError, etree.XMLSyntaxError):
                complete = False
                issues.append("unreadable:" + object_id)
                continue
            if child.objects:
                result[-1] = global_item.model_copy(update={"structural_only": True})
            if (item.width, item.height) != (child.width, child.height):
                blockers += ("resized_instance_layout_requires_editor_geometry",)
            if element.get("scale") not in {None, "1,1"}:
                blockers += ("scaled_instance_requires_editor_geometry",)
            if element.get("controller") or any(
                e.tag in {"Button", "Label", "property"} for e in element
            ):
                blockers += ("instance_parameters_require_preservation",)
            visit(
                child,
                (*prefix, object_id),
                (global_item.x, global_item.y),
                scale,
                ancestors | {path},
                tuple(dict.fromkeys(blockers)),
                default_visible,
                next((parameters.get("title") for tag in ("Button", "Label")
                      if (parameters := element.find(tag)) is not None
                      and parameters.get("title")), None),
                _instance_controller_overrides(element),
            )

    visit(initial, (), (0.0, 0.0), (1.0, 1.0), frozenset(), (), True, None, {})
    # Scope follows real references: only instance chains that leave the
    # selected tree through an externally shared definition, and are too deep
    # for variant isolation, keep their old visuals.
    shared = _external_shared_definitions(root, tuple(result))
    by_id = {o.object_id: o for o in result}
    scoped: list[FguiObjectRef] = []
    for obj in result:
        chain = obj.instance_path
        chain_objs = _chain_objects(by_id, chain)
        chain_shared = any(
            definition in shared
            for definition in (
                *(o.component_relative_path for o in chain_objs[1:] if o is not None),
                obj.component_relative_path,
            )
            if definition
        )
        scoped.append(
            obj
            if not (chain_shared and len(chain) > _VARIANT_CHAIN_CAP)
            else obj.model_copy(update={"out_of_scope": True})
        )
    result = scoped
    return initial.model_copy(
        update={
            "objects": resolve_runtime_bound_geometry(result),
            "expanded_instances": True,
            "parse_complete": complete,
            "scope_issues": tuple(issues),
        }
    )


def _assert_shared_scope(
    root: Path, inventory: FguiComponentInventory, changed_paths: set[str]
) -> None:
    from figma_to_fgui.hifi_patch import HifiPatchError

    resources, packages = _package_resource_index(root)
    selected_files = {path for path in (o.component_relative_path for o in inventory.objects)
                      if path is not None}
    edges = []
    for package_root, package_id in packages.items():
        for path in package_root.rglob("*.xml"):
            if path.name == "package.xml" or path.name.startswith("_"):
                continue
            relative = path.relative_to(root.resolve()).as_posix()
            try:
                document = etree.parse(str(path), _PARSER)
            except etree.XMLSyntaxError:
                raise HifiPatchError("hifi_shared_scope_unverifiable")
            for element in document.xpath("./displayList/component[@src]"):
                referenced = resources.get((element.get("pkg", package_id), element.get("src")))
                if referenced:
                    edges.append((relative, referenced.relative_to(root).as_posix()))
    affected = set(changed_paths)
    while True:
        expanded = set(affected)
        for owner_file, referenced_file in edges:
            if (referenced_file not in affected
                    or referenced_file == inventory.target.component_relative_path):
                continue
            if owner_file not in selected_files:
                raise HifiPatchError("hifi_shared_scope_violation")
            expanded.add(owner_file)
        if expanded == affected:
            break
        affected = expanded


def _externally_shared_paths(
    root: Path, inventory: FguiComponentInventory, changed_paths: set[str]
) -> set[str]:
    """Definitions whose existing users extend beyond the selected tree."""
    resources, packages = _package_resource_index(root)
    selected = {o.component_relative_path for o in inventory.objects}
    external = set()
    for package_root, package_id in packages.items():
        for path in package_root.rglob("*.xml"):
            if path.name == "package.xml" or path.name.startswith("_"):
                continue
            owner = path.relative_to(root).as_posix()
            if owner in selected:
                continue
            document = etree.parse(str(path), _PARSER)
            for element in document.xpath("./displayList/component[@src]"):
                referenced = resources.get((element.get("pkg", package_id), element.get("src")))
                if referenced is not None:
                    relative = referenced.relative_to(root).as_posix()
                    if relative in changed_paths:
                        external.add(relative)
    return external


_VARIANT_CHAIN_CAP = 5


def _chain_objects(
    objects_by_id: dict[str, FguiObjectRef], chain: tuple[str, ...]
) -> list[FguiObjectRef | None]:
    """Instance object of each level of an object chain.

    Chain elements are the qualified object ids of the per-level instances
    themselves, so each level is a direct lookup. An object's
    component_relative_path is the definition that CONTAINS it; the
    definition it REFERENCES is where its children live, which is the next
    level's containing definition. The XML instance id to patch at each
    level is that level's local_object_id, not the chain element.
    """
    return [objects_by_id.get(element) for element in chain]


def _external_shared_definitions(
    root: Path, objects: tuple[FguiObjectRef, ...]
) -> set[str]:
    """Tree definitions with real users outside the selected tree.

    Documentation components (file names starting with an underscore) are
    readers of record, not runtime screens, so they do not make a definition
    shared.
    """
    resources, packages = _package_resource_index(root)
    tree = {o.component_relative_path for o in objects if o.component_relative_path}
    external: set[str] = set()
    for package_root, package_id in packages.items():
        for path in package_root.rglob("*.xml"):
            if path.name == "package.xml" or path.name.startswith("_"):
                continue
            owner = path.relative_to(root).as_posix()
            if owner in tree:
                continue
            document = etree.parse(str(path), _PARSER)
            for element in document.xpath("./displayList/component[@src]"):
                referenced = resources.get(
                    (element.get("pkg", package_id), element.get("src"))
                )
                if referenced is not None:
                    relative = referenced.relative_to(root).as_posix()
                    if relative in tree:
                        external.add(relative)
    # Sharing is transitive: a shared definition stays in the project for its
    # outside users, and it keeps referencing its child definitions. Writing
    # those children would still reach the outside users through the shared
    # original, so they are shared as well.
    while True:
        expanded = set(external)
        for definition in external:
            resolved = (root / definition).resolve()
            package_id = next(
                (pid for package_root, pid in packages.items()
                 if resolved.is_relative_to(package_root)),
                "",
            )
            document = etree.parse(str(root / definition), _PARSER)
            for element in document.xpath("./displayList/component[@src]"):
                referenced = resources.get(
                    (element.get("pkg", package_id), element.get("src"))
                )
                if referenced is not None:
                    expanded.add(referenced.relative_to(root).as_posix())
        if expanded == external:
            break
        external = expanded
    return external


def _local_plans(
    root: Path,
    inventory: FguiComponentInventory,
    selection: SelectionManifest,
    mapping: HifiMappingDraft,
    *,
    conflicts: set[str] | None = None,
) -> list[tuple[FguiComponentInventory, SelectionManifest, HifiMappingDraft]]:
    from figma_to_fgui.hifi_patch import HifiPatchError, _flatten, _project_font_uris, _set_visual
    from figma_to_fgui.models import Bounds

    objects = {o.object_id: o for o in inventory.objects}
    decisions = {i.old_object_id: i for i in mapping.items if i.old_object_id}
    nodes = _flatten(selection)
    mapped_ids = {
        i.old_object_id
        for i in mapping.items
        if i.action in {"accept", "retarget"} and i.old_object_id
    }
    container_ids: set[str] = set()
    for oid in mapped_ids:
        holder = objects.get(oid)
        if holder is None or holder.object_type != "component":
            continue
        if any(
            other != oid
            and (other_obj := objects.get(other)) is not None
            and oid in other_obj.instance_path
            for other in mapped_ids
        ):
            # A mapped component that owns mapped descendants is a layout
            # container: its definition frame stays where the runtime knows
            # it, and the PSD visuals are written inside that old frame.
            # Moving the instance instead would drift every retained child
            # by the origin delta.
            container_ids.add(oid)
    viewport = selection.top_level_nodes[0].properties.get("psdViewportBounds")
    viewport_offset = (viewport[0], viewport[1]) if viewport else (0, 0)
    fonts = _project_font_uris(root)
    files: dict[str, tuple[FguiComponentInventory, dict[str | None, etree._Element]]] = {}
    seen_nodes: set[str | None] = set()
    previews: dict[tuple[str, str | None], tuple[bytes, tuple[str, ...]]] = {}
    grouped: dict[str, dict[str | None, tuple[HifiMappingItem, SelectionNode | None]]] = {}
    for obj in inventory.objects:
        path = obj.component_relative_path
        if path is None:
            raise HifiPatchError("hifi_nested_inventory_invalid")
        if path not in files:
            local = inspect_component(root, component_target(root, inventory.target, path))
            doc = etree.parse(str(root / path), _PARSER)
            files[path] = local, {e.get("id"): e for e in doc.xpath("./displayList/*[@id]")}
        local, elements = files[path]
        original = elements[obj.local_object_id]
        preview = copy.deepcopy(original)
        decision = decisions.get(obj.object_id)
        new_node: SelectionNode | None = None
        hidden = False
        removed = False
        if decision and decision.action in {"accept", "retarget"}:
            if decision.figma_node_id in seen_nodes:
                raise HifiPatchError("duplicate_figma_mapping")
            seen_nodes.add(decision.figma_node_id)
            node = nodes.get(decision.figma_node_id or "")
            if node is None:
                raise HifiPatchError("mapping_target_missing")
            if node.properties.get("hifiViewportEmpty") is True:
                key = (path, obj.local_object_id)
                signature = (etree.tostring(preview, method="c14n"), ())
                if key in previews and previews[key] != signature:
                    if conflicts is None:
                        raise HifiPatchError("hifi_shared_instance_conflict")
                    conflicts.add(path)
                previews[key] = signature
                continue
            if obj.object_type == "component":
                node = _component_content_node(node)
            if decision.preserve_runtime_text:
                if (not obj.runtime_text_override or node.type.upper() != "TEXT"
                    or original.get("text") is None):
                    raise HifiPatchError("hifi_instance_override_conflict")
                node = node.model_copy(update={
                    "text": original.get("text"),
                    "properties": {
                        **node.properties,
                        "hifiMappedText": node.text,
                    },
                })
            # A resized instance keeps deterministic walk geometry: children
            # hold their local coordinates at the instance origin, and the
            # matches were computed with exactly that model. Explicit scale
            # and rotation stay blocked because the walk does not model them;
            # the mandatory editor render comparison verifies the rest.
            blockers = set(obj.write_blockers) - {
                "instance_parameters_require_preservation",
                "resized_instance_layout_requires_editor_geometry",
            }
            if blockers:
                raise HifiPatchError("hifi_nested_geometry_unverified")
            if (
                "instance_parameters_require_preservation" in obj.write_blockers
                and obj.name in {"title", "icon"}
                and (
                    node.resource_keys
                    or node.text is not None
                    and node.text != original.get("text")
                )
            ):
                parameter_update = (
                    obj.name == "title" and obj.runtime_text_override
                    and node.type.upper() == "TEXT" and node.text is not None
                    and node.text != obj.effective_text
                )
                if not parameter_update:
                    isolated = "__hifi_" in Path(path).stem
                    if conflicts is not None and obj.instance_path:
                        conflicts.add(path)
                    elif not isolated:
                        raise HifiPatchError("hifi_instance_override_conflict")
                # The PSD renamed the label. The new text flows through the
                # instance's own Button parameter in the containing panel;
                # the shared definition keeps its placeholder untouched, so
                # every other instance is unaffected.
                if parameter_update:
                    continue
            origin = (
                obj.owner_origin[0] + viewport_offset[0],
                obj.owner_origin[1] + viewport_offset[1],
            )
            owner_width: float | None = None
            if obj.instance_path:
                owner = objects[obj.instance_path[-1]]
                owner_decision = decisions.get(owner.object_id)
                if owner_decision and owner_decision.action in {"accept", "retarget"}:
                    owner_node = nodes.get(owner_decision.figma_node_id or "")
                    if owner_node is None:
                        raise HifiPatchError("hifi_nested_geometry_unverified")
                    if owner.object_type == "component":
                        owner_node = _component_content_node(owner_node)
                    if owner.object_id in container_ids:
                        origin = (
                            owner.x + viewport_offset[0],
                            owner.y + viewport_offset[1],
                        )
                        owner_width = owner.width
                    else:
                        origin = (owner_node.bounds.x, owner_node.bounds.y)
                        owner_width = owner_node.bounds.width
            bounds = node.bounds
            local_properties = {
                **node.properties,
                **({"hifiOwnerWidth": owner_width} if owner_width is not None else {}),
            }
            text_style = node.style.get("psdTextStyle")
            if isinstance(text_style, dict):
                transform = text_style.get("transform")
                if isinstance(transform, (tuple, list)) and len(transform) == 6:
                    try:
                        local_properties["hifiPsdTextOrigin"] = (
                            float(transform[4]) - origin[0],
                            float(transform[5]) - origin[1],
                        )
                    except (TypeError, ValueError):
                        pass
            if obj.object_type == "component" and decision.logical_bounds_policy == "resize":
                local_properties["hifiResizeLogicalBounds"] = True
            new_node = node.model_copy(
                update={
                    "bounds": Bounds(
                        x=bounds.x - origin[0],
                        y=bounds.y - origin[1],
                        width=bounds.width,
                        height=bounds.height,
                    ),
                    "children": () if obj.object_type == "component" else node.children,
                    "properties": local_properties,
                }
            )
            if obj.object_type == "component" and obj.object_id in container_ids:
                keep_x, keep_y = _pair(original.get("xy"))
                new_node = new_node.model_copy(update={
                    "bounds": Bounds(
                        x=keep_x,
                        y=keep_y,
                        width=obj.width,
                        height=obj.height,
                    )
                })
            if obj.object_type == "component" and not any(
                i.old_object_id
                and i.old_object_id.startswith(obj.object_id + ":")
                and i.action in {"accept", "retarget"}
                for i in mapping.items
            ):
                raise HifiPatchError("hifi_nested_visual_mapping_required")
            frame = selection.top_level_nodes[0].model_copy(
                update={"bounds": Bounds(x=0, y=0, width=local.width, height=local.height)}
            )
            if preview.tag == "graph" and new_node.resource_keys:
                from figma_to_fgui.hifi_type_permissions import can_convert_mapping, convert_graph

                local_decision = decision.model_copy(update={"old_object_id": obj.local_object_id})
                if not can_convert_mapping(root, local, local_decision, new_node):
                    raise HifiPatchError("hifi_type_conversion_not_authorized")
                convert_graph(preview)
            _set_visual(preview, new_node, frame, local, fonts)
            # Include material identity in consensus: two different raster sources
            # must not become one shared definition merely because their boxes match.
            material: tuple[str, ...] = new_node.resource_keys
        elif (
            decision is not None
            and decision.action == "keep_old"
            and decision.visual_disposition == "retire"
            and obj.default_visible
        ):
            # PSD target state no longer contains this static legacy visual.
            # Keep the object identity and all runtime mechanics, but remove its
            # default pixel contribution.
            preview.set("visible", "false")
            hidden = True
            material = ()
        elif (decision is not None and decision.action == "exception"
              and decision.status == "fgui_only" and obj.default_visible):
            # Legacy non-PSD flow: retain the established exception behavior.
            preview.set("visible", "false")
            hidden = True
            material = ()
        elif decision is not None and decision.action == "remove_old":
            # §9: user-confirmed Legacy Removal. The per-file build path
            # drops the element and closes references; here the object is only
            # marked for the plan with a distinct consensus signature so a
            # shared definition removed in one place cannot silently merge
            # with a differently-decided instance.
            removed = True
            material = ("\x00removed",)
        else:
            material = ()
        key = (path, obj.local_object_id)
        signature = (etree.tostring(preview, method="c14n"), material)
        if key in previews and previews[key] != signature:
            if conflicts is None:
                raise HifiPatchError("hifi_shared_instance_conflict")
            conflicts.add(path)
        previews[key] = signature
        if new_node is not None or hidden or removed:
            assert decision is not None
            grouped.setdefault(path, {})[obj.local_object_id] = (decision, new_node)
    if selection.top_level_nodes[0].id.startswith("psd-root:"):
        # §12: route proven novelty additions into the root component's plan.
        # They paint on the target canvas, so they carry no legacy object and
        # enter the plan with a synthetic local key.
        root_path = inventory.target.component_relative_path
        for item in mapping.items:
            if (item.action != "add_visual" or item.old_object_id is not None
                    or item.figma_node_id is None):
                continue
            node = nodes.get(item.figma_node_id)
            if node is None:
                raise HifiPatchError("mapping_target_missing")
            if root_path not in files:
                local = inspect_component(
                    root, component_target(root, inventory.target, root_path)
                )
                doc = etree.parse(str(root / root_path), _PARSER)
                files[root_path] = local, {
                    e.get("id"): e for e in doc.xpath("./displayList/*[@id]")
                }
            grouped.setdefault(root_path, {})["__hifi_add__" + item.figma_node_id] = (
                item,
                node.model_copy(update={"bounds": Bounds(
                    x=node.bounds.x - viewport_offset[0],
                    y=node.bounds.y - viewport_offset[1],
                    width=node.bounds.width,
                    height=node.bounds.height,
                )}),
            )
    if conflicts is None:
        _assert_shared_scope(root, inventory, set(grouped) - {inventory.target.component_relative_path})
    plans: list[tuple[FguiComponentInventory, SelectionManifest, HifiMappingDraft]] = []
    for path, entries in sorted(grouped.items()):
        local, _ = files[path]
        local_items = tuple(
            (
                d
                if local_id.startswith("__hifi_add__")
                else d.model_copy(update={"old_object_id": local_id})
            )
            for local_id, (d, n) in entries.items()
        )
        frame = selection.top_level_nodes[0].model_copy(
            update={
                "bounds": Bounds(x=0, y=0, width=local.width, height=local.height),
                "children": tuple(n for d, n in entries.values() if n is not None),
            }
        )
        plans.append(
            (
                local,
                selection.model_copy(update={"top_level_nodes": (frame,)}),
                mapping.model_copy(update={"items": local_items, "unresolved_count": 0}),
            )
        )
    return plans


def _instance_title_updates(
    inventory: FguiComponentInventory,
    mapping: HifiMappingDraft,
    nodes: dict[str, SelectionNode],
) -> dict[str, str]:
    """Instance Button titles whose label the PSD changed, keyed by instance id."""
    from figma_to_fgui.hifi_patch import HifiPatchError

    decisions = {i.old_object_id: i for i in mapping.items if i.old_object_id}
    by_id = {o.object_id: o for o in inventory.objects}
    updates: dict[str, str] = {}
    for obj in inventory.objects:
        decision = decisions.get(obj.object_id)
        if (not decision or decision.action not in {"accept", "retarget"}
                or obj.name != "title" or not obj.runtime_text_override
                or not obj.instance_path):
            continue
        node = nodes.get(decision.figma_node_id or "")
        if node is None or node.type.upper() != "TEXT" or node.text is None:
            continue
        if node.text == obj.effective_text:
            continue
        # A title can pass through several nested Label/Button components.
        # The value visible on this screen is owned by the outermost instance
        # in the selected component, not by the innermost shared definition.
        # Update that page-local parameter so runtime APIs and shared component
        # definitions stay intact while the default visible value matches PSD.
        page_instances = [
            instance_id for instance_id in obj.instance_path
            if (instance_obj := by_id.get(instance_id)) is not None
            and instance_obj.component_relative_path
            == inventory.target.component_relative_path
        ]
        if not page_instances:
            # The parameter lives inside a shared container; altering it would
            # change other screens, so the conflict stays a conflict.
            raise HifiPatchError("hifi_instance_override_conflict")
        instance_id = page_instances[0]
        updates[instance_id] = str(node.text)
    return updates


def _resize_mapped_component_definitions(
    staged: Path,
    inventory: FguiComponentInventory,
    selection: SelectionManifest,
    mapping: HifiMappingDraft,
) -> None:
    """Keep an instance and its private definition on the same PSD canvas.

    FairyGUI scales a referenced component when the instance size differs
    from the definition size. PSD child coordinates are already written in
    the target group's coordinate system, so leaving the legacy definition
    size would scale and clip the correctly mapped children a second time.
    """
    from figma_to_fgui.hifi_patch import HifiPatchError, _editor_int32, _flatten

    nodes = _flatten(selection)
    decisions = {item.old_object_id: item for item in mapping.items if item.old_object_id}
    for obj in inventory.objects:
        decision = decisions.get(obj.object_id)
        if (
            obj.object_type != "component"
            or decision is None
            or decision.action not in {"accept", "retarget"}
            or decision.logical_bounds_policy != "resize"
        ):
            continue
        node = nodes.get(decision.figma_node_id or "")
        if node is None:
            raise HifiPatchError("mapping_target_missing")
        node = _component_content_node(node)
        instance_chain = (*obj.instance_path, obj.object_id)
        referenced_paths = {
            child.component_relative_path
            for child in inventory.objects
            if child.instance_path == instance_chain
            and child.component_relative_path is not None
        }
        if len(referenced_paths) != 1:
            raise HifiPatchError("hifi_variant_inventory_incomplete")
        path = referenced_paths.pop()
        document = etree.parse(str(staged / path), _PARSER)
        root = document.getroot()
        desired = (
            f"{_editor_int32(node.bounds.width)},"
            f"{_editor_int32(node.bounds.height)}"
        )
        changed = root.get("size") != desired
        if changed:
            root.set("size", desired)
        restriction = root.get("restrictSize")
        if restriction:
            try:
                min_width, max_width, min_height, max_height = (
                    float(value) for value in restriction.split(",", 3)
                )
            except ValueError:
                pass
            else:
                width, height = node.bounds.width, node.bounds.height
                adjusted = (
                    min(min_width, width),
                    max_width if max_width == 0 or width <= max_width else width,
                    min(min_height, height),
                    max_height if max_height == 0 or height <= max_height else height,
                )
                serialized = ",".join(_editor_int32(value) for value in adjusted)
                if serialized != restriction:
                    root.set("restrictSize", serialized)
                    changed = True
        if changed:
            document.write(str(staged / path), encoding="utf-8", xml_declaration=True)


def _sync_changed_group_bounds(
    staged: Path,
    inventory: FguiComponentInventory,
    mapping: HifiMappingDraft,
    selection: SelectionManifest | None = None,
) -> None:
    """Recompute existing FGUI group bounds after mapped members move.

    Advanced groups apply relations and layout from their stored bounds. If a
    member moves but the group keeps its legacy rectangle, FairyGUI shifts the
    member again when loading the component. The group object and membership
    stay unchanged; only its derived rectangle follows the member union.
    """
    from figma_to_fgui.hifi_patch import _editor_int32

    objects = {obj.object_id: obj for obj in inventory.objects}
    decisions = {item.old_object_id: item for item in mapping.items if item.old_object_id}
    changed_by_path: dict[str, set[str]] = {}
    for item in mapping.items:
        if item.action not in {"accept", "retarget"} or not item.old_object_id:
            continue
        obj = objects.get(item.old_object_id)
        if obj is not None and obj.component_relative_path and obj.local_object_id:
            changed_by_path.setdefault(obj.component_relative_path, set()).add(
                obj.local_object_id
            )

    desired_bounds: dict[tuple[str, str], tuple[float, float, float, float]] = {}
    if selection is not None:
        from figma_to_fgui.hifi_patch import _flatten

        nodes = _flatten(selection)
        viewport = selection.top_level_nodes[0].properties.get("psdViewportBounds")
        viewport_offset = (viewport[0], viewport[1]) if viewport else (0, 0)
        for object_id, decision in decisions.items():
            if decision.action not in {"accept", "retarget"} or not decision.figma_node_id:
                continue
            obj = objects.get(object_id or "")
            node = nodes.get(decision.figma_node_id)
            if (
                obj is None
                or node is None
                or obj.component_relative_path is None
                or obj.local_object_id is None
            ):
                continue
            if obj.object_type == "component":
                node = _component_content_node(node)
            origin = (
                obj.owner_origin[0] + viewport_offset[0],
                obj.owner_origin[1] + viewport_offset[1],
            )
            if obj.instance_path:
                owner = objects.get(obj.instance_path[-1])
                owner_decision = decisions.get(owner.object_id) if owner is not None else None
                owner_node = (
                    nodes.get(owner_decision.figma_node_id or "")
                    if owner_decision is not None
                    and owner_decision.action in {"accept", "retarget"}
                    else None
                )
                if owner_node is not None:
                    if owner is not None and owner.object_type == "component":
                        owner_node = _component_content_node(owner_node)
                    origin = (owner_node.bounds.x, owner_node.bounds.y)
            desired_bounds[(obj.component_relative_path, obj.local_object_id)] = (
                node.bounds.x - origin[0],
                node.bounds.y - origin[1],
                node.bounds.width,
                node.bounds.height,
            )

    def bounds(element: etree._Element) -> tuple[float, float, float, float] | None:
        try:
            x, y = (float(value) for value in element.get("xy", "0,0").split(",", 1))
            width, height = (
                float(value) for value in element.get("size", "0,0").split(",", 1)
            )
        except ValueError:
            return None
        if width <= 0 or height <= 0:
            return None
        if element.get("anchor") == "true":
            try:
                pivot_x, pivot_y = (
                    float(value) for value in element.get("pivot", "0,0").split(",", 1)
                )
            except ValueError:
                pivot_x, pivot_y = 0.0, 0.0
            x -= pivot_x * width
            y -= pivot_y * height
        return x, y, width, height

    for path, changed_ids in changed_by_path.items():
        document = etree.parse(str(staged / path), _PARSER)
        display = document.find("./displayList")
        if display is None:
            continue
        groups = list(display.xpath("./group[@id]"))
        dirty = False
        # Nested groups are represented by the same `group` attribute as
        # ordinary members. Repeating propagates a child-group update to its
        # parent without changing display-list order.
        for _ in range(max(1, len(groups))):
            progressed = False
            for group in groups:
                group_id = group.get("id")
                members = list(display.xpath("./*[@group=$group]", group=group_id))
                if not members or not any(member.get("id") in changed_ids for member in members):
                    continue
                member_geometry = [
                    (member, value) for member in members if (value := bounds(member))
                ]
                if not member_geometry:
                    continue
                member_bounds = [value for _, value in member_geometry]
                layout = group.get("layout")
                gap_bounds = [
                    desired_bounds.get((path, str(member.get("id"))), value)
                    for member, value in member_geometry
                ]
                if (
                    layout == "hz"
                    and len(member_geometry) == 2
                    and {member.tag for member, _ in member_geometry}
                    in ({"loader", "text"}, {"image", "text"})
                ):
                    # PSD image bounds omit effect padding and PSD text bounds
                    # omit the corrected live-font bearing. Use the final two
                    # old-object boxes for a compact icon+label row so the hz
                    # layout does not add that offset back at Editor load.
                    gap_bounds = [value for _, value in member_geometry]
                resolved_gap: float | None = None
                if layout in {"hz", "vt"} and len(gap_bounds) >= 2:
                    gaps = [
                        (
                            next_bounds[0] - (current[0] + current[2])
                            if layout == "hz"
                            else next_bounds[1] - (current[1] + current[3])
                        )
                        for current, next_bounds in pairwise(gap_bounds)
                    ]
                    # One FGUI group exposes one shared gap. Only update it
                    # when the mapped PSD member geometry proves a consistent
                    # value; otherwise retain the old layout contract.
                    if max(gaps) - min(gaps) <= 1:
                        attribute = "colGap" if layout == "hz" else "lineGap"
                        gap = _editor_int32(sum(gaps) / len(gaps))
                        resolved_gap = float(gap)
                        if group.get(attribute) != gap:
                            group.set(attribute, gap)
                            dirty = progressed = True
                left = min(value[0] for value in member_bounds)
                top = min(value[1] for value in member_bounds)
                right = max(value[0] + value[2] for value in member_bounds)
                bottom = max(value[1] + value[3] for value in member_bounds)
                if layout == "hz" and resolved_gap is not None:
                    right = left + sum(value[2] for value in member_bounds) + resolved_gap * (
                        len(member_bounds) - 1
                    )
                elif layout == "vt" and resolved_gap is not None:
                    bottom = top + sum(value[3] for value in member_bounds) + resolved_gap * (
                        len(member_bounds) - 1
                    )
                xy = f"{_editor_int32(left)},{_editor_int32(top)}"
                size = f"{_editor_int32(right - left)},{_editor_int32(bottom - top)}"
                if group.get("xy") != xy or group.get("size") != size:
                    group.set("xy", xy)
                    group.set("size", size)
                    dirty = progressed = True
                if group_id not in changed_ids:
                    changed_ids.add(group_id)
                    progressed = True
            if not progressed:
                break
        if dirty:
            document.write(str(staged / path), encoding="utf-8", xml_declaration=True)


def _apply_instance_title_updates(
    staged: Path,
    inventory: FguiComponentInventory,
    selection: SelectionManifest,
    mapping: HifiMappingDraft,
) -> None:
    from figma_to_fgui.hifi_patch import HifiPatchError, _flatten

    updates = _instance_title_updates(inventory, mapping, _flatten(selection))
    for instance_id, new_text in updates.items():
        path = next(
            (o.component_relative_path for o in inventory.objects
             if o.object_id == instance_id and o.component_relative_path is not None),
            None,
        )
        if path is None:
            raise HifiPatchError("hifi_instance_override_conflict")
        document = etree.parse(str(staged / path), _PARSER)
        element = next(
            (e for e in document.xpath("./displayList/component[@id]")
             if e.get("id") == instance_id), None,
        )
        parameter = element.find("Button") if element is not None else None
        if parameter is None and element is not None:
            parameter = element.find("Label")
        if parameter is None or parameter.get("title") is None:
            raise HifiPatchError("hifi_instance_override_conflict")
        parameter.set("title", new_text)
        document.write(str(staged / path), encoding="utf-8", xml_declaration=True)


def _update_runtime_gear_icon(
    component_root: etree._Element,
    gear: etree._Element,
    icon_uri: str,
    controller_overrides: dict[str, str],
) -> bool:
    """Replace only the gear value FairyGUI renders for this instance.

    ``controller.selected`` is editor state. Referenced components start on
    the first page unless their parent instance supplies an exported-controller
    override, so updating the selected page can leave the old visual on screen.
    """
    controller_name = gear.get("controller")
    if not controller_name:
        return False
    controllers = _runtime_controller_pages(
        etree.ElementTree(component_root),
        controller_overrides,
    )
    runtime_page = controllers.get(controller_name)
    pages = [page for page in gear.get("pages", "").split(",") if page]
    if runtime_page in pages:
        values = gear.get("values", "").split("|")
        values.extend("" for _ in range(len(pages) - len(values)))
        values[pages.index(runtime_page)] = icon_uri
        serialized = "|".join(values[:len(pages)])
        if gear.get("values") != serialized:
            gear.set("values", serialized)
            return True
        return False
    if gear.get("default") != icon_uri:
        gear.set("default", icon_uri)
        return True
    return False


def _apply_instance_icon_updates(
    staged: Path,
    inventory: FguiComponentInventory,
    mapping: HifiMappingDraft,
) -> None:
    """Route a replaced nested icon through its existing instance API."""
    accepted = {
        item.old_object_id for item in mapping.items
        if item.action in {"accept", "retarget"}
    }
    objects = {obj.object_id: obj for obj in inventory.objects}
    documents: dict[str, etree._ElementTree] = {}
    dirty: set[str] = set()

    def document(path: str) -> etree._ElementTree:
        if path not in documents:
            documents[path] = etree.parse(str(staged / path), _PARSER)
        return documents[path]

    for obj in inventory.objects:
        if (
            obj.object_id not in accepted
            or obj.name not in {"icon", "icon_bg"}
            or not obj.instance_path
            or obj.component_relative_path is None
            or obj.local_object_id is None
        ):
            continue
        visual_doc = document(obj.component_relative_path)
        visuals = visual_doc.xpath("./displayList/*[@id=$id]", id=obj.local_object_id)
        if len(visuals) != 1:
            continue
        visual = visuals[0]
        icon_uri = visual.get("url")
        if icon_uri is None and visual.get("src"):
            package_id = visual.get("pkg") or component_target(
                staged, inventory.target, obj.component_relative_path
            ).package_id
            icon_uri = f"ui://{package_id}{visual.get('src')}"
        if icon_uri is None:
            continue
        instance = objects.get(obj.instance_path[-1])
        if (
            instance is None
            or instance.component_relative_path is None
            or instance.local_object_id is None
        ):
            continue
        parent_doc = document(instance.component_relative_path)
        matches = parent_doc.xpath(
            "./displayList/component[@id=$id]", id=instance.local_object_id
        )
        if len(matches) != 1:
            continue
        controller_overrides = _instance_controller_overrides(matches[0])
        visual_gear_changed = False
        for gear in visual.findall("gearIcon"):
            visual_gear_changed = (
                _update_runtime_gear_icon(
                    visual_doc.getroot(), gear, icon_uri, controller_overrides
                )
                or visual_gear_changed
            )
        if visual_gear_changed:
            dirty.add(obj.component_relative_path)
        parameter = matches[0].find("Button")
        if parameter is None:
            parameter = matches[0].find("Label")
        if parameter is None:
            continue
        if parameter.get("icon") != icon_uri:
            parameter.set("icon", icon_uri)
            dirty.add(instance.component_relative_path)
        for gear in matches[0].findall("gearIcon"):
            if _update_runtime_gear_icon(parent_doc.getroot(), gear, icon_uri, {}):
                dirty.add(instance.component_relative_path)
    for path in dirty:
        documents[path].write(str(staged / path), encoding="utf-8", xml_declaration=True)


def _activate_mapped_display_states(
    staged: Path,
    inventory: FguiComponentInventory,
    mapping: HifiMappingDraft,
) -> None:
    """Select an existing controller page that exposes a mapped component."""
    decisions = {
        item.old_object_id: item for item in mapping.items
        if item.old_object_id and item.action in {"accept", "retarget"}
        and not item.generated_state and (item.figma_node_id or "").startswith("psd-layer:")
    }
    objects = {obj.object_id: obj for obj in inventory.objects}
    documents: dict[str, etree._ElementTree] = {}
    dirty: set[str] = set()

    def document(path: str) -> etree._ElementTree:
        if path not in documents:
            documents[path] = etree.parse(str(staged / path), _PARSER)
        return documents[path]

    def set_controller_override(
        instance: etree._Element,
        controller_name: str,
        selected_page_index: str,
    ) -> bool:
        """Set one exported-controller default without dropping its siblings."""
        raw = [part for part in instance.get("controller", "").split(",") if part]
        pairs = [raw[index:index + 2] for index in range(0, len(raw) - 1, 2)]
        for pair in pairs:
            if pair[0] != controller_name:
                continue
            if pair[1] == selected_page_index:
                return False
            pair[1] = selected_page_index
            instance.set("controller", ",".join(part for pair in pairs for part in pair))
            return True
        pairs.append([controller_name, selected_page_index])
        instance.set("controller", ",".join(part for pair in pairs for part in pair))
        return True

    for object_id in decisions:
        obj = objects.get(object_id)
        if (
            obj is None
            or obj.object_type != "component"
            or not obj.instance_path
            or obj.component_relative_path is None
            or obj.local_object_id is None
        ):
            continue
        own_doc = document(obj.component_relative_path)
        own_matches = own_doc.xpath(
            "./displayList/component[@id=$id]", id=obj.local_object_id
        )
        if len(own_matches) != 1:
            continue
        desired_gears = [
            gear for gear in own_matches[0].findall("gearDisplay")
            if gear.get("controller") and gear.get("pages")
        ]
        if not desired_gears:
            continue
        owner = objects.get(obj.instance_path[-1])
        if (
            owner is None
            or owner.component_relative_path is None
            or owner.local_object_id is None
        ):
            continue
        parent_doc = document(owner.component_relative_path)
        for gear in desired_gears:
            desired_pages = {page for page in gear.get("pages", "").split(",") if page}
            for controller in parent_doc.findall("controller"):
                matching_actions = [
                    action for action in controller.findall("action")
                    if action.get("objectId") == owner.local_object_id
                    and action.get("controller") == gear.get("controller")
                    and action.get("targetPage") in desired_pages
                ]
                if not matching_actions:
                    continue
                outer_page = matching_actions[0].get("toPage")
                raw_pages = controller.get("pages", "").split(",")
                page_ids = raw_pages[::2]
                if outer_page in page_ids:
                    selected = str(page_ids.index(outer_page))
                    if controller.get("selected", "0") != selected:
                        controller.set("selected", selected)
                        dirty.add(owner.component_relative_path)
                    # A nested component does not reliably execute a parent
                    # definition's default-page action when that parent is
                    # itself instantiated. Carry the same exported-controller
                    # selection onto that concrete ancestor instance. This
                    # changes only its initial visual state; controller names,
                    # pages and actions remain byte-for-byte intact.
                    if len(obj.instance_path) < 2:
                        continue
                    ancestor = objects.get(obj.instance_path[-2])
                    if (
                        ancestor is None
                        or ancestor.component_relative_path is None
                        or ancestor.local_object_id is None
                        or controller.get("name") is None
                    ):
                        continue
                    ancestor_doc = document(ancestor.component_relative_path)
                    ancestor_matches = ancestor_doc.xpath(
                        "./displayList/component[@id=$id]",
                        id=ancestor.local_object_id,
                    )
                    if len(ancestor_matches) == 1 and set_controller_override(
                        ancestor_matches[0], controller.get("name"), selected
                    ):
                        dirty.add(ancestor.component_relative_path)
    for path in dirty:
        documents[path].write(str(staged / path), encoding="utf-8", xml_declaration=True)


def _clear_instance_icon_overrides(
    staged: Path,
    inventory: FguiComponentInventory,
    mapping: HifiMappingDraft,
) -> None:
    """Let an isolated variant's replaced icon be its new default visual.

    The component instance and its Button/Label runtime API remain intact;
    only the old static `icon` parameter is removed from that one cloned
    instance so it cannot overwrite the new loader resource at construction.
    """
    accepted = {
        item.old_object_id for item in mapping.items
        if item.action in {"accept", "retarget"}
    }
    objects = {obj.object_id: obj for obj in inventory.objects}
    updates: dict[str, set[str]] = {}
    for object_id in accepted:
        obj = objects.get(object_id or "")
        if (
            obj is None
            or obj.name != "icon"
            or not obj.instance_path
            or "instance_parameters_require_preservation" not in obj.write_blockers
        ):
            continue
        instance = objects.get(obj.instance_path[-1])
        if (
            instance is not None
            and instance.component_relative_path is not None
            and instance.local_object_id is not None
        ):
            updates.setdefault(instance.component_relative_path, set()).add(instance.local_object_id)
    for path, instance_ids in updates.items():
        document = etree.parse(str(staged / path), _PARSER)
        changed = False
        for element in document.xpath("./displayList/component[@id]"):
            if element.get("id") not in instance_ids:
                continue
            parameter = element.find("Button")
            if parameter is None:
                parameter = element.find("Label")
            if parameter is not None and "icon" in parameter.attrib:
                parameter.attrib.pop("icon")
                changed = True
        if changed:
            document.write(str(staged / path), encoding="utf-8", xml_declaration=True)


def _largest_opaque_rectangle(image: Image.Image) -> tuple[int, int, int, int] | None:
    """Return the largest pixel rectangle whose alpha is exactly opaque."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    if width <= 0 or height <= 0:
        return None
    alpha = rgba.getchannel("A").tobytes()
    columns = [0] * width
    best: tuple[int, int, int, int] | None = None
    best_area = 0
    for y in range(height):
        offset = y * width
        for x in range(width):
            columns[x] = columns[x] + 1 if alpha[offset + x] == 255 else 0
        stack: list[int] = []
        for x in range(width + 1):
            current = columns[x] if x < width else 0
            while stack and columns[stack[-1]] > current:
                column = stack.pop()
                rectangle_height = columns[column]
                left = stack[-1] + 1 if stack else 0
                rectangle_width = x - left
                area = rectangle_width * rectangle_height
                candidate = (
                    left,
                    y - rectangle_height + 1,
                    rectangle_width,
                    rectangle_height,
                )
                if area > best_area or (area == best_area and best is not None and candidate < best):
                    best = candidate
                    best_area = area
            stack.append(x)
    return best


def _package_image_index(
    root: Path,
) -> tuple[dict[tuple[str, str], Path], dict[Path, str]]:
    resources: dict[tuple[str, str], Path] = {}
    packages: dict[Path, str] = {}
    for manifest_path in sorted(root.glob("assets/*/package.xml")):
        try:
            package = etree.parse(str(manifest_path), _PARSER).getroot()
        except (OSError, etree.XMLSyntaxError):
            continue
        package_id = str(package.get("id", ""))
        if not package_id:
            continue
        package_root = manifest_path.parent.resolve()
        packages[package_root] = package_id
        for resource in package.xpath("./resources/image[@id][@name]"):
            relative = (
                Path(str(resource.get("path", "/")).strip("/"))
                / str(resource.get("name"))
            )
            resources[(package_id, str(resource.get("id")))] = package_root / relative
    return resources, packages


def _mapped_raster_path(
    element: etree._Element,
    component_path: Path,
    resources: dict[tuple[str, str], Path],
    packages: dict[Path, str],
) -> Path | None:
    if element.tag == "image" and element.get("src"):
        component_parent = component_path.parent.resolve()
        package_root = next(
            (
                root
                for root in sorted(packages, key=lambda value: len(value.parts), reverse=True)
                if component_parent.is_relative_to(root)
            ),
            None,
        )
        package_id = element.get("pkg") or (
            packages.get(package_root, "") if package_root is not None else ""
        )
        return resources.get((package_id, str(element.get("src"))))
    if element.tag != "loader":
        return None
    url = str(element.get("url", ""))
    if not url.startswith("ui://"):
        return None
    payload = url[5:]
    return next(
        (
            path
            for (package_id, resource_id), path in resources.items()
            if payload == package_id + resource_id
        ),
        None,
    )


def _plain_untransformed(element: etree._Element) -> bool:
    return (
        element.get("anchor") != "true"
        and element.get("rotation", "0") == "0"
        and element.get("skew") is None
        and element.get("scale") in {None, "1,1"}
        and element.get("flip") in {None, "none"}
        and element.get("visible") != "false"
        and element.get("alpha", "1") == "1"
    )


def _fit_retained_graphs_under_owned_siblings(
    staged: Path,
    inventory: FguiComponentInventory,
    mapping: HifiMappingDraft,
) -> set[str]:
    """Keep extra legacy graphs while preventing leakage around a mapped skin.

    The old graph remains the same display-list object.  It is only resized
    into a proven fully opaque rectangle of an already-existing, higher-z
    loader/image sibling.  Ambiguous transforms, runtime geometry and
    partially opaque skins are deliberately left untouched.
    """
    from figma_to_fgui.hifi_patch import _editor_int32

    decisions = {item.old_object_id: item for item in mapping.items if item.old_object_id}
    resources, packages = _package_image_index(staged)
    siblings: dict[tuple[str, str | None], list[FguiObjectRef]] = {}
    for item in inventory.objects:
        if item.component_relative_path is not None:
            siblings.setdefault((item.component_relative_path, item.parent_id), []).append(item)

    documents: dict[str, etree._ElementTree] = {}
    changed: set[str] = set()
    processed: set[tuple[str, str]] = set()
    for graph in inventory.objects:
        decision = decisions.get(graph.object_id)
        path = graph.component_relative_path
        local_id = graph.local_object_id
        if (
            decision is None
            or decision.action != "keep_old"
            or decision.visual_disposition != "preserve"
            or graph.object_type != "graph"
            or path is None
            or local_id is None
            or (path, local_id) in processed
        ):
            continue
        document = documents.setdefault(path, etree.parse(str(staged / path), _PARSER))
        matches = document.xpath("./displayList/graph[@id=$id]", id=local_id)
        if len(matches) != 1:
            continue
        graph_element = matches[0]
        if (
            not _plain_untransformed(graph_element)
            or len(graph_element) != 0
            or graph_element.get("type", "rect") != "rect"
            or float(graph_element.get("lineSize", "0")) != 0
        ):
            continue

        best: tuple[float, float, float, float] | None = None
        best_area = 0.0
        for owner in siblings.get((path, graph.parent_id), ()):
            owner_decision = decisions.get(owner.object_id)
            if (
                owner.child_index <= graph.child_index
                or owner.object_type not in {"image", "loader"}
                or owner.local_object_id is None
                or owner_decision is None
                or owner_decision.action not in {"accept", "retarget"}
                or not (owner_decision.owned_source_ids or owner_decision.composite_source_ids)
            ):
                continue
            owner_matches = document.xpath("./displayList/*[@id=$id]", id=owner.local_object_id)
            if len(owner_matches) != 1:
                continue
            owner_element = owner_matches[0]
            if not _plain_untransformed(owner_element):
                continue
            raster_path = _mapped_raster_path(
                owner_element, staged / path, resources, packages
            )
            if raster_path is None or not raster_path.is_file():
                continue
            try:
                with Image.open(raster_path) as image:
                    image.load()
                    image_width, image_height = image.size
                    opaque = _largest_opaque_rectangle(image)
            except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
                continue
            owner_x, owner_y = _pair(owner_element.get("xy"))
            owner_width, owner_height = _pair(owner_element.get("size"))
            if (
                opaque is None
                or image_width <= 0
                or image_height <= 0
                or owner_width <= 0
                or owner_height <= 0
            ):
                continue
            opaque_x, opaque_y, opaque_width, opaque_height = opaque
            draw_x, draw_y = owner_x, owner_y
            scale_x = owner_width / image_width
            scale_y = owner_height / image_height
            if owner_element.tag == "loader":
                # FairyGUI `scale` preserves the resource aspect ratio and
                # aligns the letterboxed image inside the loader rectangle.
                fill = owner_element.get("fill")
                if fill not in {"scale", "scaleFree"}:
                    continue
                if fill == "scale":
                    scale = min(scale_x, scale_y)
                    if owner_element.get("shrinkOnly") == "true":
                        scale = min(1.0, scale)
                    drawn_width = image_width * scale
                    drawn_height = image_height * scale
                    horizontal_space = owner_width - drawn_width
                    vertical_space = owner_height - drawn_height
                    draw_x += {
                        "center": horizontal_space / 2,
                        "right": horizontal_space,
                    }.get(owner_element.get("align", "left"), 0.0)
                    draw_y += {
                        "middle": vertical_space / 2,
                        "bottom": vertical_space,
                    }.get(owner_element.get("vAlign", "top"), 0.0)
                    scale_x = scale_y = scale
            projected = (
                draw_x + opaque_x * scale_x,
                draw_y + opaque_y * scale_y,
                opaque_width * scale_x,
                opaque_height * scale_y,
            )
            area = projected[2] * projected[3]
            if area > best_area:
                best = projected
                best_area = area
        if best is None or best_area < 4:
            continue
        x, y, width, height = best
        graph_element.set("xy", f"{_editor_int32(x)},{_editor_int32(y)}")
        graph_element.set("size", f"{_editor_int32(width)},{_editor_int32(height)}")
        processed.add((path, local_id))
        changed.add(path)

    for path in changed:
        documents[path].write(
            str(staged / path), encoding="utf-8", xml_declaration=True
        )
    return changed


def _glyph_signature(path: Path):
    """Opaque-glyph bounding box and mean colour of one button icon art."""
    with Image.open(path) as art:
        pixels = art.convert("RGBA").load()
        width, height = art.size
        minx, miny, maxx, maxy = width, height, -1, -1
        total = [0, 0, 0]
        count = 0
        for y in range(height):
            for x in range(width):
                r, g, b, a = pixels[x, y]
                if a <= 60:
                    continue
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
                total[0] += r
                total[1] += g
                total[2] += b
                count += 1
    if count < 40 or maxx < 0:
        return None
    return (
        (minx, miny, maxx, maxy),
        (total[0] // count, total[1] // count, total[2] // count),
    )


def _baked_glyph_cluster(raster: Image.Image, box, origin, mean, reach: float = 48.0):
    """Largest same-colour-family paint cluster of a raster inside one box."""
    pixels = raster.load()
    width, height = raster.size
    left = int(max(0.0, box[0] - origin[0] - reach))
    top = int(max(0.0, box[1] - origin[1] - reach))
    right = int(min(width, box[2] - origin[0] + reach + 1))
    bottom = int(min(height, box[3] - origin[1] + reach + 1))
    limit = 48 * 48
    mask: set[tuple[int, int]] = set()
    for y in range(top, bottom):
        for x in range(left, right):
            r, g, b, a = pixels[x, y]
            if a <= 60:
                continue
            dr, dg, db = r - mean[0], g - mean[1], b - mean[2]
            if dr * dr + dg * dg + db * db <= limit:
                mask.add((x, y))
    best: tuple[int, tuple[int, int, int, int]] | None = None
    seen: set[tuple[int, int]] = set()
    for start in mask:
        if start in seen:
            continue
        seen.add(start)
        stack = [start]
        count = 0
        minx, miny = start
        maxx, maxy = start
        while stack:
            x, y = stack.pop()
            count += 1
            minx, maxx = min(minx, x), max(maxx, x)
            miny, maxy = min(miny, y), max(maxy, y)
            for neighbour in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbour in mask and neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        if best is None or count > best[0]:
            best = (count, (minx, miny, maxx, maxy))
    return best


def _rebase_retained_variant_children(
    staged: Path,
    root: Path,
    entries: list[tuple[str, str, str, str]],
    resources: dict[tuple[str, str], Path],
    packages: dict[Path, str],
    inventory: FguiComponentInventory | None = None,
) -> None:
    """Keep retained bundle children on their old global position.

    A reskinned bundle variant is re-anchored to its PSD group origin, so the
    instance xy moves. Mapped children are rewritten in the new frame by the
    patch plans, but retained program children (buttons, probes, retired
    paint) still carry old-frame coordinates and would drift by exactly the
    origin delta. Rebase every child the plans left untouched, then retire a
    retained button icon whose redraw the PSD baked into the bundle raster:
    the baked glyph is the target-state visual while the button object keeps
    its identity and a hit box that still covers that glyph.
    """
    from figma_to_fgui.hifi_patch import _editor_int32

    for parent_root, parent_staged, instance_id, def_staged in entries:
        before_parent = etree.parse(str(root / parent_root), _PARSER).getroot()
        after_parent = etree.parse(str(staged / parent_staged), _PARSER).getroot()
        before_instance = before_parent.xpath("./displayList/*[@id=$id]", id=instance_id)
        after_instance = after_parent.xpath("./displayList/*[@id=$id]", id=instance_id)
        if not before_instance or not after_instance:
            continue
        package_id = before_instance[0].get("pkg") or next(
            (
                pid
                for pth, pid in packages.items()
                if (root / parent_root).parent.is_relative_to(pth)
            ),
            "",
        )
        def_path = resources.get((package_id, str(before_instance[0].get("src"))))
        if def_path is None or not def_path.is_file():
            continue
        old_x, old_y = _pair(before_instance[0].get("xy"))
        new_x, new_y = _pair(after_instance[0].get("xy"))
        delta = (old_x - new_x, old_y - new_y)
        after_tree = etree.parse(str(staged / def_staged), _PARSER)
        after_def = after_tree.getroot()
        staged_def_path = staged / def_staged
        raster_info = None
        for image in after_def.xpath("./displayList/image[@src]"):
            raster_path = _mapped_raster_path(image, staged_def_path, resources, packages)
            if (
                raster_path is not None
                and "/Img/HIFI/" in raster_path.as_posix()
                and raster_path.is_file()
            ):
                raster_info = (image, raster_path)
                break
        if raster_info is None:
            # Only a reskinned bundle re-anchors its definition frame to the
            # PSD group origin. Plain isolation clones keep the old frame, so
            # their retained children need no coordinate correction.
            continue
        before_def = etree.parse(str(def_path), _PARSER).getroot()
        locked_ids = frozenset()
        if inventory is not None:
            locked_ids = frozenset(
                o.local_object_id or ""
                for o in inventory.objects
                if o.structural_only
                and o.component_relative_path is not None
                and def_path.resolve() == (staged / o.component_relative_path).resolve()
            )
        dirty = False
        for child in after_def.xpath("./displayList/*[@id]"):
            match = before_def.xpath("./displayList/*[@id=$id]", id=child.get("id"))
            if not match or child.get("xy") != match[0].get("xy"):
                continue
            if child.find("gearXY") is not None:
                continue
            if child.get("id") in locked_ids:
                continue
            if delta == (0.0, 0.0):
                continue
            x, y = _pair(child.get("xy"))
            child.set("xy", f"{_editor_int32(x + delta[0])},{_editor_int32(y + delta[1])}")
            dirty = True
        image, raster_path = raster_info
        origin_x, origin_y = _pair(image.get("xy"))
        origin = (new_x + origin_x, new_y + origin_y)
        with Image.open(raster_path) as raster_file:
            raster = raster_file.convert("RGBA")
            for comp in after_def.xpath("./displayList/component[@id]"):
                cx, cy = _pair(comp.get("xy"))
                package_id = comp.get("pkg") or next(
                    (
                        pid
                        for pth, pid in packages.items()
                        if staged_def_path.parent.is_relative_to(pth)
                    ),
                    "",
                )
                comp_path = resources.get((package_id, str(comp.get("src"))))
                if comp_path is None or not comp_path.is_file():
                    continue
                comp_tree = etree.parse(str(comp_path), _PARSER)
                cw, ch = _pair(comp.get("size"))
                if cw <= 0 or ch <= 0:
                    cw, ch = _pair(comp_tree.getroot().get("size"))
                before_comp = before_def.xpath(
                    "./displayList/component[@id=$id]", id=comp.get("id")
                )
                if before_comp:
                    bx, by = _pair(before_comp[0].get("xy"))
                    box = (old_x + bx, old_y + by, old_x + bx + cw, old_y + by + ch)
                else:
                    box = (new_x + cx, new_y + cy, new_x + cx + cw, new_y + cy + ch)
                loaders = comp_tree.getroot().xpath(
                    "./displayList/loader[@url][not(@visible='false')]"
                )
                if not loaders or loaders[0].find("gearIcon") is not None:
                    continue
                param_url = None
                for tag in ("Button", "Label"):
                    param_element = comp.find(tag)
                    if param_element is not None and param_element.get("icon"):
                        param_url = param_element.get("icon")
                        break
                art_url = param_url or loaders[0].get("url")
                art_path = None
                if str(art_url).startswith("ui://"):
                    payload = str(art_url)[5:]
                    art_path = next(
                        (
                            candidate
                            for (pid, rid), candidate in resources.items()
                            if payload == pid + rid
                        ),
                        None,
                    )
                if art_path is None or not art_path.is_file():
                    continue
                signature = _glyph_signature(art_path)
                if signature is None:
                    continue
                glyph_box, mean = signature
                glyph_w = glyph_box[2] - glyph_box[0] + 1
                glyph_h = glyph_box[3] - glyph_box[1] + 1
                cluster = _baked_glyph_cluster(raster, box, origin, mean)
                if cluster is None or cluster[0] < 150:
                    continue
                cb = (
                    cluster[1][0] + origin[0],
                    cluster[1][1] + origin[1],
                    cluster[1][2] + origin[0],
                    cluster[1][3] + origin[1],
                )
                inside = (
                    box[0] - 8 <= cb[0]
                    and cb[2] <= box[2] + 8
                    and box[1] - 8 <= cb[1]
                    and cb[3] <= box[3] + 8
                )
                sized = (
                    0.5 * glyph_w <= cb[2] - cb[0] + 1 <= 1.6 * glyph_w
                    and 0.5 * glyph_h <= cb[3] - cb[1] + 1 <= 1.6 * glyph_h
                )
                if not inside or not sized:
                    continue
                loaders[0].set("visible", "false")
                comp_tree.write(str(comp_path), encoding="utf-8", xml_declaration=True)
        if dirty:
            after_tree.write(str(staged / def_staged), encoding="utf-8", xml_declaration=True)


def _audit_xy_pair(raw: str | None) -> tuple[float, float]:
    if not raw:
        return 0.0, 0.0
    parts = raw.split(",")
    try:
        return float(parts[0]), float(parts[1])
    except (IndexError, ValueError):
        return 0.0, 0.0


def build_nested_bundle(
    root: Path,
    inventory: FguiComponentInventory,
    selection: SelectionManifest,
    mapping: HifiMappingDraft,
    *,
    job_id: str,
    selection_root: Path | None,
) -> ChangeBundle:
    from figma_to_fgui.apply import apply_bundle
    from figma_to_fgui.hifi_patch import HifiPatchError, build_hifi_change_bundle
    from figma_to_fgui.service_contracts import ChangeBundle, ChangeFile, FileOperation

    if mapping.unresolved_count:
        raise HifiPatchError("hifi_mapping_incomplete")
    if any(i.action == "add_visual" and not i.novelty_proven for i in mapping.items):
        # §12/§16: adds are legal only with recorded novelty evidence.
        raise HifiPatchError("hifi_novelty_evidence_missing")
    conflicts: set[str] = set()
    _local_plans(root, inventory, selection, mapping, conflicts=conflicts)
    shared = _external_shared_definitions(root, inventory.objects)
    objects_by_id = {o.object_id: o for o in inventory.objects}
    accepted_ids = {i.old_object_id for i in mapping.items
                    if i.action in {"accept", "retarget"}}
    excluded_ids: set[str] = set()
    deep_hidden_ids: set[str] = set()
    hidden_ids = {
        i.old_object_id
        for i in mapping.items
        if (i.action == "exception" and i.status == "fgui_only")
        or (i.action == "keep_old" and i.visual_disposition == "retire")
    }
    chains: dict[tuple[str, ...], str | None] = {}
    for obj in inventory.objects:
        if (obj.object_id not in accepted_ids
                and obj.object_id not in hidden_ids) or not obj.instance_path:
            continue
        chain = obj.instance_path
        chain_objs = _chain_objects(objects_by_id, chain)
        chain_shared = any(
            definition in shared
            for definition in (
                *(o.component_relative_path for o in chain_objs[1:] if o is not None),
                obj.component_relative_path,
            )
            if definition
        )
        own_conflict = obj.component_relative_path in conflicts
        if not chain_shared and not own_conflict:
            continue
        if len(chain) > _VARIANT_CHAIN_CAP:
            if obj.object_id in hidden_ids:
                deep_hidden_ids.add(obj.object_id)
            else:
                excluded_ids.add(obj.object_id)
            continue
        chains[chain] = obj.component_relative_path
    planned_mapping = mapping
    if excluded_ids or deep_hidden_ids:
        planned_mapping = mapping.model_copy(update={"items": tuple(
            item.model_copy(update={"action": "preserve_structure", "out_of_scope": True})
            if item.old_object_id in excluded_ids
            else (item.model_copy(update={"status": "structural"})
                  if item.old_object_id in deep_hidden_ids else item)
            for item in mapping.items
        )})
    with tempfile.TemporaryDirectory(prefix="hifi-nested-") as temporary:
        staged = Path(temporary) / "project"
        shutil.copytree(root, staged)
        variants: dict[tuple[str, ...], str] = {}
        clones: dict[tuple[str, str, str], str] = {}
        rebase_entries: list[tuple[str, str, str, str, str]] = []
        if chains:
            from figma_to_fgui.hifi_instance_variant import clone_instance_definition

            for chain in sorted(chains, key=len):
                parent = inventory.target.component_relative_path
                chain_objs = _chain_objects(objects_by_id, chain)
                conflicted = chains[chain] in conflicts
                for level in range(1, len(chain) + 1):
                    key = chain[:level]
                    if key in variants:
                        parent = variants[key]
                        continue
                    level_object = chain_objs[level - 1]
                    next_object = chain_objs[level] if level < len(chain) else None
                    referenced = (
                        next_object.component_relative_path
                        if next_object is not None
                        else chains[chain]
                    )
                    if (
                        level_object is None
                        or level_object.local_object_id is None
                        or referenced is None
                    ):
                        raise HifiPatchError("hifi_variant_inventory_incomplete")
                    if referenced not in shared and not conflicted:
                        parent = referenced
                        continue
                    clone_key = (parent, level_object.local_object_id, referenced)
                    if clone_key in clones:
                        # Two chains may ask for the same isolation switch on
                        # one shared instance; the second request reuses the
                        # existing clone instead of colliding with it.
                        variants[key] = clones[clone_key]
                        parent = clones[clone_key]
                        continue
                    variant = clone_instance_definition(
                        staged, parent_component_path=parent,
                        instance_id=level_object.local_object_id, identity=referenced,
                    )
                    parent_root = level_object.component_relative_path
                    if parent_root is None:
                        raise HifiPatchError("hifi_variant_inventory_incomplete")
                    rebase_entries.append(
                        (
                            parent_root,
                            parent,
                            str(level_object.local_object_id),
                            variant.variant_component,
                        )
                    )
                    clones[clone_key] = variant.variant_component
                    variants[key] = variant.variant_component
                    parent = variant.variant_component
            inventory = inspect_component_tree(staged, inventory.target)
            if not inventory.parse_complete:
                raise HifiPatchError("hifi_variant_inventory_incomplete")
        _clear_instance_icon_overrides(staged, inventory, planned_mapping)
        plans = _local_plans(staged, inventory, selection, planned_mapping)
        if not plans:
            raise HifiPatchError("hifi_mapping_requires_replacements")
        touched: set[str] = set()
        for local, source, local_mapping in plans:
            bundle = build_hifi_change_bundle(
                staged, local, source, local_mapping, job_id=job_id, selection_root=selection_root
            )
            apply_bundle(staged, bundle)
            touched.update(f.relative_path for f in bundle.files)
        # The historical PSD path tried to hide unmatched legacy graphs by
        # shrinking them underneath a newly mapped raster. That preserves the
        # object but also leaves old paint in the target state and was the
        # direct cause of the yellow rectangular backing seen behind Noble/Merit.
        # PSD flows now use explicit visual retirement instead. Keep the old
        # fitting heuristic only for non-PSD sources where no target-state
        # pixel authority exists.
        if not selection.top_level_nodes[0].id.startswith("psd-root:"):
            _fit_retained_graphs_under_owned_siblings(staged, inventory, planned_mapping)
        _resize_mapped_component_definitions(staged, inventory, selection, planned_mapping)
        _sync_changed_group_bounds(staged, inventory, planned_mapping, selection)
        _activate_mapped_display_states(staged, inventory, planned_mapping)
        _apply_instance_icon_updates(staged, inventory, planned_mapping)
        _apply_instance_title_updates(staged, inventory, selection, mapping)
        if rebase_entries:
            from figma_to_fgui.hifi_project_inspector import _package_resource_index

            resources, packages = _package_image_index(staged)
            component_resources, _ = _package_resource_index(staged)
            resources = {**component_resources, **resources}
            _rebase_retained_variant_children(
                staged, root, rebase_entries, resources, packages, inventory=inventory
            )
        files = []
        changed_paths = touched | {
            path.relative_to(staged).as_posix() for path in staged.rglob("*")
            if path.is_file() and ".figma-to-fgui" not in path.relative_to(staged).parts and (
                not (root / path.relative_to(staged)).is_file()
                or path.read_bytes() != (root / path.relative_to(staged)).read_bytes()
            )
        }
        for path in sorted(changed_paths):
            before = (root / path).read_bytes() if (root / path).is_file() else None
            after = (staged / path).read_bytes()
            if before == after:
                continue
            files.append(
                ChangeFile(
                    operation=FileOperation.REPLACE if before is not None else FileOperation.CREATE,
                    relative_path=path,
                    before_sha256=hashlib.sha256(before).hexdigest()
                    if before is not None
                    else None,
                    after_sha256=hashlib.sha256(after).hexdigest(),
                    content_b64=base64.b64encode(after).decode(),
                )
            )
        return ChangeBundle(
            version=1, job_id=job_id, project_id=inventory.target.project_id, files=tuple(files)
        )


def validate_nested_candidate(
    before_root: Path,
    after_root: Path,
    inventory: FguiComponentInventory,
    mapping: HifiMappingDraft,
    *,
    session_id: str,
    lossless_blockers: tuple[str, ...] = (),
    lossless_notes: tuple[str, ...] = (),
) -> HifiReplacementReview:
    from figma_to_fgui.hifi_patch import HifiPatchError, _package_manifest, validate_hifi_candidate

    root_path = inventory.target.component_relative_path
    root_before = etree.parse(str(before_root / root_path), _PARSER)
    root_after = etree.parse(str(after_root / root_path), _PARSER)
    before_instances = {e.get("id"): e for e in root_before.xpath("./displayList/component[@id]")}
    after_instances = {e.get("id"): e for e in root_after.xpath("./displayList/component[@id]")}
    after_resources, _ = _package_resource_index(after_root)
    variant_by_instance: dict[str, tuple[str, str]] = {}
    icon_variant_instances = {
        obj.instance_path[-1]
        for obj in inventory.objects
        if obj.name in {"icon", "icon_bg"} and obj.instance_path
        and any(
            item.old_object_id == obj.object_id and item.action in {"accept", "retarget"}
            for item in mapping.items
        )
    }
    mapped_instance_ids = {
        item.old_object_id
        for item in mapping.items
        if item.old_object_id in before_instances
        and item.action in {"accept", "retarget"}
    }
    title_variant_instances = {
        page_instance
        for obj in inventory.objects
        if obj.name == "title" and obj.runtime_text_override and obj.instance_path
        and any(
            item.old_object_id == obj.object_id and item.action in {"accept", "retarget"}
            for item in mapping.items
        )
        for page_instance in obj.instance_path[:1]
        if page_instance in before_instances
    }
    display_state_variant_instances = {
        ancestor_instance
        for obj in inventory.objects
        if obj.object_type == "component" and len(obj.instance_path) >= 2
        and any(
            item.old_object_id == obj.object_id and item.action in {"accept", "retarget"}
            for item in mapping.items
        )
        for ancestor_instance in obj.instance_path[-2:-1]
        if ancestor_instance in before_instances
    }
    normalized_root = copy.deepcopy(root_after)
    normalized_instances = {e.get("id"): e for e in normalized_root.xpath("./displayList/component[@id]")}
    for instance_id, before in before_instances.items():
        after = after_instances.get(instance_id)
        if after is None:
            continue
        if before.get("src") == after.get("src"):
            continue
        expected = copy.deepcopy(before)
        changed = copy.deepcopy(after)
        changed.set("src", before.get("src"))
        if before.get("fileName") is None:
            changed.attrib.pop("fileName", None)
        else:
            changed.set("fileName", before.get("fileName"))
        if instance_id in mapped_instance_ids:
            for attribute in ("xy", "size", "alpha", "rotation"):
                if before.get(attribute) is None:
                    changed.attrib.pop(attribute, None)
                else:
                    changed.set(attribute, before.get(attribute))
        if instance_id in title_variant_instances:
            before_title = before.find("Button")
            if before_title is None:
                before_title = before.find("Label")
            changed_title = changed.find("Button")
            if changed_title is None:
                changed_title = changed.find("Label")
            if before_title is not None and changed_title is not None:
                if before_title.get("title") is None:
                    changed_title.attrib.pop("title", None)
                else:
                    changed_title.set("title", before_title.get("title"))
        if instance_id in icon_variant_instances:
            before_parameter = before.find("Button")
            if before_parameter is None:
                before_parameter = before.find("Label")
            changed_parameter = changed.find("Button")
            if changed_parameter is None:
                changed_parameter = changed.find("Label")
            if before_parameter is not None and changed_parameter is not None:
                if before_parameter.get("icon") is None:
                    changed_parameter.attrib.pop("icon", None)
                else:
                    changed_parameter.set("icon", before_parameter.get("icon"))
        if instance_id in display_state_variant_instances:
            if before.get("controller") is None:
                changed.attrib.pop("controller", None)
            else:
                changed.set("controller", before.get("controller"))
        if etree.tostring(expected, method="c14n") != etree.tostring(changed, method="c14n"):
            raise HifiPatchError("hifi_variant_instance_contract_changed")
        parent_package = component_target(before_root, inventory.target, root_path).package_id
        package_id = after.get("pkg") or parent_package
        variant_file = after_resources.get((package_id, after.get("src", "")))
        if (variant_file is None or "__hifi_" not in variant_file.stem
            or not variant_file.is_file()):
            raise HifiPatchError("hifi_variant_reference_invalid")
        original = next((o.component_relative_path for o in inventory.objects
                         if o.instance_path == (instance_id,)), None)
        if original is None:
            raise HifiPatchError("hifi_variant_instance_unmapped")
        original_file = before_root / original
        if (after_root / original).read_bytes() != original_file.read_bytes():
            raise HifiPatchError("hifi_variant_original_changed")
        variant_by_instance[instance_id] = (original, variant_file.relative_to(after_root).as_posix())
        normalized = normalized_instances[instance_id]
        normalized.set("src", before.get("src"))
        if before.get("fileName") is None:
            normalized.attrib.pop("fileName", None)
        else:
            normalized.set("fileName", before.get("fileName"))
        if instance_id in icon_variant_instances:
            before_parameter = before.find("Button")
            if before_parameter is None:
                before_parameter = before.find("Label")
            normalized_parameter = normalized.find("Button")
            if normalized_parameter is None:
                normalized_parameter = normalized.find("Label")
            if before_parameter is not None and normalized_parameter is not None:
                if before_parameter.get("icon") is None:
                    normalized_parameter.attrib.pop("icon", None)
                else:
                    normalized_parameter.set("icon", before_parameter.get("icon"))
        if instance_id in title_variant_instances:
            before_parameter = before.find("Button")
            if before_parameter is None:
                before_parameter = before.find("Label")
            normalized_parameter = normalized.find("Button")
            if normalized_parameter is None:
                normalized_parameter = normalized.find("Label")
            if before_parameter is not None and normalized_parameter is not None:
                if before_parameter.get("title") is None:
                    normalized_parameter.attrib.pop("title", None)
                else:
                    normalized_parameter.set("title", before_parameter.get("title"))
        if instance_id in display_state_variant_instances:
            if before.get("controller") is None:
                normalized.attrib.pop("controller", None)
            else:
                normalized.set("controller", before.get("controller"))

    paths = sorted({path for path in (o.component_relative_path for o in inventory.objects)
                    if path is not None})
    locals_ = {
        p: inspect_component(before_root, component_target(before_root, inventory.target, p))
        for p in paths
    }
    scope = set(paths)
    prefixes = []
    for local in locals_.values():
        manifest, package = _package_manifest(before_root, local)
        scope.add(manifest.relative_to(before_root).as_posix())
        prefixes.append(f"{package}/Img/HIFI/{local.target.component_name}/")
    # Variant isolation is recursive: deep instance chains clone variants
    # inside variants, so the top-level instance map above cannot see them.
    # Every __hifi_ file is a candidate artifact by construction, so all of
    # them and their image directories stay in scope.
    for variant_file in after_root.rglob("*__hifi_*.xml"):
        variant = variant_file.relative_to(after_root).as_posix()
        scope.add(variant)
        package = variant_file.parent.parent.relative_to(after_root).as_posix()
        prefixes.append(f"{package}/Img/HIFI/{variant_file.stem}/")
    changed_paths = {
        p for p in paths if (before_root / p).read_bytes() != (after_root / p).read_bytes()
    }
    _assert_shared_scope(
        before_root, inventory, changed_paths - {inventory.target.component_relative_path}
    )
    reviews: list[HifiReplacementReview] = []
    diffs: list[HifiObjectDiff] = []
    objects = {o.object_id: o for o in inventory.objects}
    for path, local in locals_.items():
        # The local inspection cannot see instance expansion. Carry only the
        # structural proof obtained by the expanded, parsed inventory into
        # its byte-for-byte review; an unexpanded component stays visual.
        structural_ids = {
            o.local_object_id for o in inventory.objects
            if o.component_relative_path == path and o.structural_only
        }
        local = local.model_copy(update={"objects": tuple(
            o.model_copy(update={"structural_only": True})
            if o.object_id in structural_ids else o
            for o in local.objects
        )})
        items = tuple(
            (
                i
                if i.old_object_id is None
                else i.model_copy(
                    update={"old_object_id": objects[i.old_object_id].local_object_id}
                )
            )
            for i in mapping.items
            if (
                i.action == "add_visual"
                and i.old_object_id is None
                and i.figma_node_id is not None
                and path == inventory.target.component_relative_path
            )
            or (
                i.old_object_id in objects
                and objects[i.old_object_id].component_relative_path == path
                and not (objects[i.old_object_id].instance_path
                         and objects[i.old_object_id].instance_path[-1]
                         in variant_by_instance)
            )
        )
        local_mapping = mapping.model_copy(update={"items": items})
        review = validate_hifi_candidate(
            before_root,
            after_root,
            local,
            local_mapping,
            session_id=session_id,
            lossless_blockers=lossless_blockers,
            _scope_paths=frozenset(scope),
            _scope_prefixes=tuple(prefixes),
            _after_component_doc=normalized_root if path == root_path and variant_by_instance else None,
            lossless_notes=lossless_notes,
        )
        reviews.append(review)
        original_ids = {i.item_id: i.old_object_id for i in mapping.items}
        diffs.extend(
            d.model_copy(update={"old_object_id": original_ids[d.item_id]})
            for d in review.object_diffs
        )
    for instance_id, (original_path, variant_path) in variant_by_instance.items():
        local = locals_[original_path]
        structural_ids = {
            o.local_object_id for o in inventory.objects
            if o.component_relative_path == original_path and o.structural_only
        }
        local = local.model_copy(update={"objects": tuple(
            o.model_copy(update={"structural_only": o.object_id in structural_ids,
                                 "shared_resource": False})
            for o in local.objects
        )})
        items = tuple(
            i.model_copy(update={"old_object_id": objects[i.old_object_id].local_object_id})
            for i in mapping.items if i.old_object_id in objects
            and objects[i.old_object_id].instance_path == (instance_id,)
        )
        variant_doc = etree.parse(str(after_root / variant_path), _PARSER)
        frame_delta = None
        instance_object = next(
            (o for o in inventory.objects if o.object_id == instance_id), None
        )
        if (
            instance_object is not None
            and instance_object.component_relative_path is not None
            and instance_object.local_object_id is not None
        ):
            parent_path = instance_object.component_relative_path
            before_parent = etree.parse(str(before_root / parent_path), _PARSER)
            after_parent = etree.parse(str(after_root / parent_path), _PARSER)
            b_el = before_parent.xpath(
                "./displayList/*[@id=$id]", id=instance_object.local_object_id
            )
            a_el = after_parent.xpath(
                "./displayList/*[@id=$id]", id=instance_object.local_object_id
            )
            if b_el and a_el:
                def _frame_xy(element):
                    raw = (element.get("xy") or "0,0").split(",")
                    return float(raw[0]), float(raw[1])

                frame_delta = (
                    _frame_xy(b_el[0])[0] - _frame_xy(a_el[0])[0],
                    _frame_xy(b_el[0])[1] - _frame_xy(a_el[0])[1],
                )
        review = validate_hifi_candidate(
            before_root, after_root, local,
            mapping.model_copy(update={"items": items}),
            session_id=session_id, lossless_blockers=lossless_blockers,
            _scope_paths=frozenset(scope), _scope_prefixes=tuple(prefixes),
            _after_component_doc=variant_doc,
            _frame_delta=frame_delta,
            lossless_notes=lossless_notes,
        )
        reviews.append(review)
        original_ids = {i.item_id: i.old_object_id for i in mapping.items}
        diffs.extend(d.model_copy(update={"old_object_id": original_ids[d.item_id]})
                     for d in review.object_diffs)
    all_files = {f.relative_path: f for r in reviews for f in r.changed_files}
    warnings = tuple(dict.fromkeys(w for r in reviews for w in r.warnings))
    nested_changed = changed_paths - {inventory.target.component_relative_path}
    if nested_changed:
        warnings += ("嵌套组件视觉已原位改写；须验证全部受影响实例及控制器状态。",)
    def _canon(payload: bytes) -> bytes:
        return re.sub(rb"(\d+)\.0+(?=[^0-9.])", rb"\1", payload)

    from figma_to_fgui.hifi_patch import _new_object_id

    removal_ids = {
        i.old_object_id for i in mapping.items
        if i.action == "remove_old" and i.old_object_id is not None
    }
    logic_mismatches: list[str] = []
    stale_transition_refs: list[str] = []
    stale_gear_refs: list[str] = []
    relation_drifts: list[str] = []
    state_visual_changes = 0
    icon_converged = 0
    transition_keys_checked = 0
    for audit_path in sorted(p for p in scope if (before_root / p).is_file()):
        before_doc = etree.parse(str(before_root / audit_path), _PARSER)
        after_doc = etree.parse(str(after_root / audit_path), _PARSER)
        before_ctrl = _canon(
            b"".join(etree.tostring(c) for c in before_doc.xpath("./controller"))
        )
        after_ctrl = _canon(
            b"".join(etree.tostring(c) for c in after_doc.xpath("./controller"))
        )
        if before_ctrl != after_ctrl:
            logic_mismatches.append(f"{audit_path}:controller")
        before_ids = {e.get("id") for e in before_doc.xpath("./displayList/*[@id]")}
        after_ids = {e.get("id") for e in after_doc.xpath("./displayList/*[@id]")}
        # §9: user-confirmed removals leave the object set by design; every
        # other difference is a logic mismatch.
        removed_local = {
            o.local_object_id for o in inventory.objects
            if o.object_id in removal_ids and o.local_object_id is not None
            and (o.component_relative_path == audit_path
                 or (o.instance_path
                     and variant_by_instance.get(o.instance_path[0], (None, None))[1]
                     == audit_path))
        }
        added_local = {
            _new_object_id(i.figma_node_id)
            for i in mapping.items
            if i.action == "add_visual" and i.figma_node_id is not None
            and audit_path == root_path
        }
        if before_ids - removed_local != after_ids - added_local:
            logic_mismatches.append(
                f"{audit_path}:objects"
                f"{sorted((before_ids - removed_local) ^ (after_ids - added_local))[:4]}"
            )
        before_by_id = {e.get("id"): e for e in before_doc.xpath("./displayList/*[@id]")}
        reskin_ids = set()
        for element in after_doc.xpath("./displayList/*[@id]"):
            old = before_by_id.get(element.get("id"))
            if old is None:
                continue
            for attr in ("visible", "src", "fileName", "url", "xy", "size", "alpha"):
                if old.get(attr) != element.get(attr):
                    reskin_ids.add(element.get("id"))
                    break
        after_by_id = {e.get("id"): e for e in after_doc.xpath("./displayList/*[@id]")}
        # Transition keyframes store absolute geometry. A keyframe that still
        # carries the pre-reskin base value of a moved/resized object drags it
        # back to the old layout while playing; flag it for human confirmation
        # instead of silently rewriting behavior contracts.
        for transition in after_doc.xpath("./transition"):
            transition_name = str(transition.get("name") or "")
            for item in transition.xpath("./item[@target][@type]"):
                raw_type = str(item.get("type") or "")
                if raw_type.casefold() not in {"xy", "size"}:
                    continue
                target_id = str(item.get("target"))
                if target_id not in reskin_ids:
                    continue
                old_element = before_by_id.get(target_id)
                new_element = after_by_id.get(target_id)
                if old_element is None or new_element is None:
                    continue
                base_attribute = "xy" if raw_type.casefold() == "xy" else "size"
                old_base = old_element.get(base_attribute)
                new_base = new_element.get(base_attribute)
                if not old_base or old_base == new_base:
                    continue
                transition_keys_checked += 1
                for value_attribute in ("value", "value2"):
                    keyframe = item.get(value_attribute)
                    if keyframe is not None and keyframe == old_base:
                        stale_transition_refs.append(
                            f"{audit_path}:{transition_name}:{target_id}:{raw_type} "
                            f"{value_attribute}={keyframe}"
                        )
        # §7 gear geometry: a controller page that still carries the
        # pre-reskin base snaps the object back to the old layout on switch.
        for element in after_doc.xpath("./displayList/*[@id]"):
            target_id = str(element.get("id") or "")
            if target_id not in reskin_ids:
                continue
            old_element = before_by_id.get(target_id)
            if old_element is None:
                continue
            for gear_tag, base_attribute, field_count in (
                ("gearXY", "xy", 2),
                ("gearSize", "size", 2),
                ("gearWidth", "size", 1),
                ("gearHeight", "size", 1),
            ):
                gear = element.find(gear_tag)
                if gear is None:
                    continue
                old_base = old_element.get(base_attribute)
                if not old_base or old_base == element.get(base_attribute):
                    continue
                old_fields = old_base.split(",")[:field_count]
                for value_attribute in ("values", "default"):
                    raw = gear.get(value_attribute)
                    if not raw:
                        continue
                    for page in raw.split("|"):
                        if page.split(",")[:field_count] == old_fields:
                            stale_gear_refs.append(
                                f"{audit_path}:{target_id}:{gear_tag} "
                                f"{value_attribute}={page}"
                            )
        # §7 relation offset: when a relation target moved and the owner did
        # not follow by the same delta, the runtime relation can re-place the
        # owner away from its PSD-aligned position. Flag it for Editor review.
        for element in after_doc.xpath("./displayList/*[@id]"):
            owner_id = str(element.get("id") or "")
            owner_after = _audit_xy_pair(element.get("xy"))
            owner_before_el = before_by_id.get(owner_id)
            if owner_before_el is None:
                continue
            owner_before = _audit_xy_pair(owner_before_el.get("xy"))
            owner_delta = (owner_after[0] - owner_before[0],
                           owner_after[1] - owner_before[1])
            for relation in element.findall("relation"):
                target_id = str(relation.get("target") or "")
                if not target_id:
                    continue
                target_after_el = after_by_id.get(target_id)
                target_before_el = before_by_id.get(target_id)
                if target_after_el is None or target_before_el is None:
                    continue
                target_delta = (
                    _audit_xy_pair(target_after_el.get("xy"))[0]
                    - _audit_xy_pair(target_before_el.get("xy"))[0],
                    _audit_xy_pair(target_after_el.get("xy"))[1]
                    - _audit_xy_pair(target_before_el.get("xy"))[1],
                )
                if target_delta != (0.0, 0.0) and owner_delta != target_delta:
                    relation_drifts.append(
                        f"{audit_path}:{owner_id}:relation->{target_id}"
                    )
        for element in after_doc.xpath("./displayList/*[@id]"):
            old = before_by_id.get(element.get("id"))
            if old is None:
                continue
            for gear_tag in ("gearDisplay", "gearLook", "gearColor", "gearIcon", "gearText"):
                b = old.find(gear_tag)
                a = element.find(gear_tag)
                b_gear = _canon(etree.tostring(b)) if b is not None else b""
                a_gear = _canon(etree.tostring(a)) if a is not None else b""
                if b_gear != a_gear:
                    state_visual_changes += 1
            for gear_tag in ("gearSize", "gearXY", "gearWidth", "gearHeight"):
                b = old.find(gear_tag)
                a = element.find(gear_tag)
                b_gear = _canon(etree.tostring(b)) if b is not None else b""
                a_gear = _canon(etree.tostring(a)) if a is not None else b""
                if b_gear != a_gear:
                    if element.get("id") in reskin_ids:
                        state_visual_changes += 1
                    else:
                        logic_mismatches.append(
                            f"{audit_path}:{element.get('id')}:{gear_tag}"
                        )
            b_rel = _canon(b"".join(
                etree.tostring(relation)
                for relation in old.findall("relation")
                if str(relation.attrib.get("target", "")) not in removed_local
            ))
            a_rel = _canon(b"".join(
                etree.tostring(relation) for relation in element.findall("relation")
            ))
            if b_rel != a_rel:
                logic_mismatches.append(f"{audit_path}:{element.get('id')}:relation")
            for param_tag in ("Button", "Label"):
                b_param = old.find(param_tag)
                a_param = element.find(param_tag)
                b_text = _canon(etree.tostring(b_param)) if b_param is not None else b""
                a_text = _canon(etree.tostring(a_param)) if a_param is not None else b""
                if b_text == a_text:
                    continue
                if b_param is not None and a_param is not None:
                    b_copy = etree.fromstring(etree.tostring(b_param))
                    a_copy = etree.fromstring(etree.tostring(a_param))
                    b_copy.attrib.pop("icon", None)
                    a_copy.attrib.pop("title", None)
                    a_copy.attrib.pop("icon", None)
                    b_copy.attrib.pop("title", None)
                    if _canon(etree.tostring(b_copy)) == _canon(etree.tostring(a_copy)):
                        icon_converged += 1
                        continue
                logic_mismatches.append(f"{audit_path}:{element.get('id')}:{param_tag}")
    if logic_mismatches:
        warnings += (
            "程序逻辑保留审计不一致：" + ", ".join(logic_mismatches[:8]),
        )
    else:
        warnings += (
            f"程序逻辑保留审计：{len(scope)} 个定义 controllers/relations/对象集合/实例参数全部一致"
            + (f"；状态视觉 gear 变化 {state_visual_changes} 处（属状态视觉域）" if state_visual_changes else "")
            + (f"（图标参数收敛 {icon_converged} 处，均有内嵌证据）" if icon_converged else "")
            + (
                f"；transition 关键帧几何交叉核对 {transition_keys_checked} 处无陈旧引用"
                if transition_keys_checked and not stale_transition_refs
                else ""
            )
            + "。",
        )
    if removal_ids:
        warnings += (
            f"Legacy Removal Review 已确认移除 {len(removal_ids)} 个旧对象；"
            "Reference Closure 已同步清理 relation/transition 引用，"
            "运行时代码若按名称查找这些对象需同步修正。",
        )
    if stale_gear_refs:
        warnings += (
            "gear 几何仍引用换皮前基准（控制器切页会把对象拉回旧位置/旧尺寸，须人工确认或更新 gear 值）："
            + ", ".join(stale_gear_refs[:8]),
        )
    if relation_drifts:
        warnings += (
            "关系锚点与目标位移不一致（运行时关系可能把该对象带回旧相对位置，须 Editor 核验）："
            + ", ".join(relation_drifts[:8]),
        )
    if stale_transition_refs:
        warnings += (
            "transition 关键帧仍引用换皮前几何（播放会把对象拽回旧位置/旧尺寸，须人工确认或更新关键帧）："
            + ", ".join(stale_transition_refs[:8]),
        )
    if variant_by_instance:
        geometry_gears: list[str] = []
        audit_paths = sorted({root_path} | {variant for _, variant in variant_by_instance.values()})
        for audit_path in audit_paths:
            audit_doc = etree.parse(str(after_root / audit_path), _PARSER)
            for element in audit_doc.xpath("./displayList/*[@id]"):
                if element.get("visible") == "false" or element.tag == "graph":
                    continue
                for gear in element:
                    if not isinstance(gear.tag, str):
                        continue
                    if gear.tag in {"gearSize", "gearXY", "gearWidth", "gearHeight"}:
                        geometry_gears.append(
                            f"{audit_path}:{element.get('id')}:{gear.tag}"
                        )
        if geometry_gears:
            warnings += (
                "共享组件按实例建立专属定义；须在 Editor 核对各实例及全部控制器状态；检测到几何 gear："
                + ", ".join(geometry_gears[:8]),
            )
        elif not logic_mismatches:
            warnings += (
                "共享组件按实例建立专属定义：原定义程序逻辑不变（零回归已机器审计）；"
                "控制器状态已机器审计：皮肤对象无几何 gear，状态差异仅 gearDisplay 可见性契约。",
            )
        else:
            warnings += (
                "共享组件按实例建立专属定义；原定义存在程序逻辑审计差异（见审计行），其他实例回归须按审计清单人工确认。",
            )
    return reviews[0].model_copy(
        update={
            "target": inventory.target,
            "changed_files": tuple(all_files[p] for p in sorted(all_files)),
            "object_diffs": tuple(diffs),
            "parse_coverage_complete": inventory.parse_complete,
            # Nested rewrites and per-instance variants need Editor checks;
            # they are reported as warnings instead of blocking approval.
            "approvable": inventory.parse_complete
            and all(r.approvable for r in reviews),
            "warnings": warnings,
        }
    )
