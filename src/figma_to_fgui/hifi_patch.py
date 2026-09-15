from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import cast

from lxml import etree

from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.hifi_replacement_models import (
    FguiComponentInventory,
    HifiDiffItem,
    HifiMappingDraft,
    HifiReplacementReview,
)
from figma_to_fgui.hifi_review import build_object_diffs
from figma_to_fgui.paths import safe_relative_path
from figma_to_fgui.service_contracts import ChangeBundle, ChangeFile, FileOperation


class HifiPatchError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
_MUTABLE_ATTRIBUTES = {"xy", "size", "text", "color", "font", "fontSize", "alpha", "rotation", "src", "fileName", "pkg"}


def _flatten(manifest: SelectionManifest) -> dict[str, SelectionNode]:
    result: dict[str, SelectionNode] = {}
    pending = list(manifest.top_level_nodes)
    while pending:
        node = pending.pop()
        result[node.id] = node
        pending.extend(node.children)
    return result


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:.3f}".rstrip("0").rstrip(".")


def _selection_box(
    root: SelectionNode,
    node: SelectionNode,
    inventory: FguiComponentInventory,
) -> tuple[float, float, float, float]:
    if root.bounds.width <= 0 or root.bounds.height <= 0:
        raise HifiPatchError("hifi_selection_root_invalid")
    scale_x = inventory.width / root.bounds.width
    scale_y = inventory.height / root.bounds.height
    return (
        (node.bounds.x - root.bounds.x) * scale_x,
        (node.bounds.y - root.bounds.y) * scale_y,
        node.bounds.width * scale_x,
        node.bounds.height * scale_y,
    )


def _set_visual(
    element: etree._Element,
    node: SelectionNode,
    root: SelectionNode,
    inventory: FguiComponentInventory,
) -> None:
    x, y, width, height = _selection_box(root, node, inventory)
    element.attrib["xy"] = f"{_number(x)},{_number(y)}"
    element.attrib["size"] = f"{_number(width)},{_number(height)}"
    if element.tag == "text" and node.text is not None:
        element.attrib["text"] = node.text
    if "opacity" in node.model_fields_set:
        element.attrib["alpha"] = _number(node.opacity)
    if "rotation" in node.model_fields_set:
        element.attrib["rotation"] = _number(node.rotation)


def _new_object_id(node_id: str) -> str:
    return "hifi_" + hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:10]


def _new_visual(
    node: SelectionNode,
    root: SelectionNode,
    inventory: FguiComponentInventory,
    resource_id: str | None = None,
    file_name: str | None = None,
) -> etree._Element:
    node_type = node.type.upper()
    if resource_id is not None:
        element = etree.Element("image")
        element.attrib["src"] = resource_id
        if file_name is not None:
            element.attrib["fileName"] = file_name
    elif node_type == "TEXT":
        element = etree.Element("text")
        if node.text is not None:
            element.attrib["text"] = node.text
    elif node_type in {"RECTANGLE", "ELLIPSE", "VECTOR", "LINE", "POLYGON", "STAR"}:
        element = etree.Element("graph")
        element.attrib["type"] = "ellipse" if node_type == "ELLIPSE" else "rect"
    else:
        raise HifiPatchError("unsupported_added_visual")
    element.attrib["id"] = _new_object_id(node.id)
    element.attrib["name"] = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]", "_", node.name)[:128] or element.attrib["id"]
    _set_visual(element, node, root, inventory)
    return element


def _package_manifest(root: Path, inventory: FguiComponentInventory) -> tuple[Path, str]:
    component_path = Path(inventory.target.component_relative_path)
    parts = component_path.parts
    if len(parts) < 3:
        raise HifiPatchError("invalid_target_package")
    package_root = Path(*parts[:2]) if parts[0] == "assets" else Path(parts[0])
    manifest = root / package_root / "package.xml"
    if not manifest.is_file():
        raise HifiPatchError("invalid_target_package")
    return manifest, package_root.as_posix()


def _resource_extension(mime_type: str) -> str:
    return {"image/png": ".png", "image/webp": ".webp", "image/svg+xml": ".svg"}[mime_type]


def build_hifi_change_bundle(
    root: Path,
    inventory: FguiComponentInventory,
    selection: SelectionManifest,
    mapping: HifiMappingDraft,
    *,
    job_id: str = "hifi-replacement",
    selection_root: Path | None = None,
) -> ChangeBundle:
    if mapping.unresolved_count:
        raise HifiPatchError("hifi_mapping_incomplete")
    if len(selection.top_level_nodes) != 1:
        raise HifiPatchError("hifi_selection_requires_single_root")
    selection_root_node = selection.top_level_nodes[0]
    relative_path = safe_relative_path(inventory.target.component_relative_path)
    source = root / relative_path
    before = source.read_bytes()
    document = etree.parse(str(source), _PARSER)
    component = document.getroot()
    display_list = component.find("displayList")
    if display_list is None:
        raise HifiPatchError("component_display_list_missing")
    by_old_id = {
        str(element.attrib["id"]): element
        for element in display_list
        if element.attrib.get("id")
    }
    nodes = _flatten(selection)
    declared_resources = {resource.key: resource for resource in selection.resources}
    generated_resources: dict[str, tuple[str, str, str, bytes]] = {}

    def material(node: SelectionNode) -> tuple[str | None, str | None]:
        if not node.resource_keys:
            return None, None
        if selection_root is None:
            raise HifiPatchError("selection_resource_unavailable")
        key = node.resource_keys[0]
        declared = declared_resources.get(key)
        if declared is None:
            raise HifiPatchError("selection_resource_unavailable")
        source_resource = selection_root / "resources" / key
        try:
            content = source_resource.read_bytes()
        except OSError as error:
            raise HifiPatchError("selection_resource_unavailable") from error
        if len(content) != declared.size:
            raise HifiPatchError("selection_resource_unavailable")
        token = hashlib.sha256((inventory.target.component_id + "\0" + key).encode("utf-8")).hexdigest()
        resource_id = "h" + token[:8]
        extension = _resource_extension(declared.mime_type)
        file_name = re.sub(r"[^A-Za-z0-9_\-]", "_", node.name)[:80] + "-" + token[:8] + extension
        virtual_path = f"/Img/HIFI/{inventory.target.component_name}/"
        relative_path = safe_relative_path(
            f"{Path(inventory.target.component_relative_path).parent.parent.as_posix()}/{virtual_path.strip('/')}/{file_name}"
        )
        generated_resources[key] = (resource_id, file_name, relative_path, content)
        return resource_id, file_name
    claimed: set[str] = set()
    for item in mapping.items:
        if item.action in {"accept", "retarget"}:
            if item.old_object_id is None or item.figma_node_id is None:
                raise HifiPatchError("invalid_mapping")
            if item.figma_node_id in claimed:
                raise HifiPatchError("duplicate_figma_mapping")
            claimed.add(item.figma_node_id)
            try:
                element = by_old_id[item.old_object_id]
                node = nodes[item.figma_node_id]
            except KeyError as error:
                raise HifiPatchError("mapping_target_missing") from error
            _set_visual(element, node, selection_root_node, inventory)
            resource_id, file_name = material(node)
            old = next((value for value in inventory.objects if value.object_id == item.old_object_id), None)
            if resource_id is not None and old is not None and not old.shared_resource:
                element.attrib["src"] = resource_id
                element.attrib.pop("pkg", None)
                if file_name is not None:
                    element.attrib["fileName"] = file_name
        elif item.action == "add_visual":
            if item.figma_node_id is None or item.figma_node_id in claimed:
                continue
            try:
                node = nodes[item.figma_node_id]
            except KeyError as error:
                raise HifiPatchError("mapping_target_missing") from error
            resource_id, file_name = material(node)
            display_list.append(
                _new_visual(node, selection_root_node, inventory, resource_id, file_name)
            )
            claimed.add(item.figma_node_id)
        elif item.action not in {"keep_old", "exception"}:
            raise HifiPatchError("invalid_mapping_action")
    after = etree.tostring(
        document,
        encoding="utf-8",
        xml_declaration=True,
        pretty_print=True,
    )
    changes: list[ChangeFile] = [
        ChangeFile(
            operation=FileOperation.REPLACE,
            relative_path=relative_path,
            before_sha256=hashlib.sha256(before).hexdigest(),
            after_sha256=hashlib.sha256(after).hexdigest(),
            content_b64=base64.b64encode(after).decode("ascii"),
        )
    ]
    if generated_resources:
        manifest_path, package_root = _package_manifest(root, inventory)
        manifest_relative = manifest_path.relative_to(root).as_posix()
        manifest_before = manifest_path.read_bytes()
        manifest_document = etree.parse(str(manifest_path), _PARSER)
        resources_element = manifest_document.getroot().find("resources")
        if resources_element is None:
            raise HifiPatchError("invalid_target_package")
        existing_ids = {str(element.attrib.get("id", "")) for element in resources_element}
        existing_names = {str(element.attrib.get("name", "")) for element in resources_element}
        for resource_id, file_name, resource_relative, content in sorted(generated_resources.values()):
            if resource_id in existing_ids or file_name in existing_names:
                raise HifiPatchError("hifi_resource_conflict")
            virtual_parent = "/" + Path(resource_relative).parent.relative_to(Path(package_root)).as_posix().strip("/") + "/"
            etree.SubElement(
                resources_element,
                "image",
                id=resource_id,
                name=file_name,
                path=virtual_parent,
            )
            changes.append(
                ChangeFile(
                    operation=FileOperation.CREATE,
                    relative_path=resource_relative,
                    after_sha256=hashlib.sha256(content).hexdigest(),
                    content_b64=base64.b64encode(content).decode("ascii"),
                )
            )
        manifest_after = etree.tostring(
            manifest_document,
            encoding="utf-8",
            xml_declaration=True,
            pretty_print=True,
        )
        changes.append(
            ChangeFile(
                operation=FileOperation.REPLACE,
                relative_path=manifest_relative,
                before_sha256=hashlib.sha256(manifest_before).hexdigest(),
                after_sha256=hashlib.sha256(manifest_after).hexdigest(),
                content_b64=base64.b64encode(manifest_after).decode("ascii"),
            )
        )
    return ChangeBundle(
        version=1,
        job_id=job_id,
        project_id=inventory.target.project_id,
        files=tuple(changes),
    )


def _protected_object(element: etree._Element) -> bytes:
    copy = etree.fromstring(etree.tostring(element))
    for node in copy.iter():
        for attribute in tuple(node.attrib):
            if attribute in _MUTABLE_ATTRIBUTES:
                del node.attrib[attribute]
    return cast(bytes, etree.tostring(copy, method="c14n", with_comments=True))


def validate_hifi_candidate(
    before_root: Path,
    after_root: Path,
    inventory: FguiComponentInventory,
    mapping: HifiMappingDraft,
    *,
    session_id: str,
) -> HifiReplacementReview:
    relative = safe_relative_path(inventory.target.component_relative_path)
    before_files = {
        path.relative_to(before_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in before_root.rglob("*")
        if path.is_file() and ".figma-to-fgui" not in path.parts
    }
    after_files = {
        path.relative_to(after_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in after_root.rglob("*")
        if path.is_file() and ".figma-to-fgui" not in path.parts
    }
    changed = sorted(path for path in set(before_files) | set(after_files) if before_files.get(path) != after_files.get(path))
    manifest_path, package_root = _package_manifest(before_root, inventory)
    manifest_relative = manifest_path.relative_to(before_root).as_posix()
    allowed_prefix = f"{package_root}/Img/HIFI/{inventory.target.component_name}/"
    if any(
        path not in {relative, manifest_relative} and not path.startswith(allowed_prefix)
        for path in changed
    ):
        raise HifiPatchError("hifi_scope_violation")
    before_doc = etree.parse(str(before_root / relative), _PARSER)
    after_doc = etree.parse(str(after_root / relative), _PARSER)
    before_by_id = {
        str(element.attrib["id"]): element
        for element in before_doc.xpath("./displayList/*[@id]")
    }
    after_by_id = {
        str(element.attrib["id"]): element
        for element in after_doc.xpath("./displayList/*[@id]")
    }
    protected_ok = True
    for object_id, before_element in before_by_id.items():
        after_element = after_by_id.get(object_id)
        if after_element is None or _protected_object(before_element) != _protected_object(after_element):
            protected_ok = False
            break
        old = next((item for item in inventory.objects if item.object_id == object_id), None)
        if old is not None and old.shared_resource and before_element.attrib.get("src") != after_element.attrib.get("src"):
            protected_ok = False
            break
    if not protected_ok:
        raise HifiPatchError("hifi_protected_structure_changed")
    package = etree.parse(str(after_root / manifest_relative), _PARSER).getroot()
    resource_ids = {str(item.attrib.get("id", "")) for item in package.xpath("./resources/*")}
    for element in after_doc.xpath("./displayList/*[@src]"):
        source_package = element.attrib.get("pkg")
        if source_package is None and str(element.attrib["src"]) not in resource_ids:
            raise HifiPatchError("hifi_resource_closure_invalid")
    diff_items = tuple(
        HifiDiffItem(
            version=1,
            relative_path=path,
            operation="replace" if path in before_files else "create",
            before_sha256=before_files.get(path),
            after_sha256=after_files[path],
            summary="更新已确认的视觉属性并保留原对象结构",
        )
        for path in changed
    )
    return HifiReplacementReview(
        version=1,
        session_id=session_id,
        mapping_revision=mapping.mapping_revision,
        target=inventory.target,
        changed_files=diff_items,
        object_diffs=build_object_diffs(before_doc, after_doc, mapping),
        protected_checks_passed=True,
        parse_coverage_complete=inventory.parse_complete,
        approvable=True,
        warnings=()
        if inventory.parse_complete
        else ("目标组件含未知标签或属性；候选保留其原始字节结构，仍需 Editor 检查。",),
        editor_check_required=True,
    )
