from __future__ import annotations

import base64
import hashlib
import math
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import cast

from lxml import etree

from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.fixed_fonts import PROJECT_FIXED_FONTS
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
_COMMON_VISUAL_ATTRIBUTES = {
    "alpha",
    "rotation",
    "size",
    "xy",
}
_TEXT_VISUAL_ATTRIBUTES = {
    "align",
    "bold",
    "color",
    "font",
    "fontSize",
    "italic",
    "leading",
    "letterSpacing",
    "strokeColor",
    "strokeSize",
    "text",
}
_IMAGE_VISUAL_ATTRIBUTES = {"fileName", "pkg", "src"}


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


def _editor_int32(value: float) -> str:
    """Serialize geometry in the integer form required by FairyGUI Editor 6.1.4."""
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise HifiPatchError("hifi_geometry_invalid")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise HifiPatchError("hifi_geometry_invalid")
    rounded = int(Decimal(str(value)).to_integral_value(rounding=ROUND_HALF_UP))
    if not -(2**31) <= rounded < 2**31:
        raise HifiPatchError("hifi_geometry_invalid")
    return str(rounded)


def _project_font_uris(root: Path) -> dict[str, str]:
    """Return exact font SHA-256 to FairyGUI resource URI mappings."""
    result: dict[str, str] = {}
    for manifest_path in sorted(root.glob("assets/*/package.xml")):
        try:
            package = etree.parse(str(manifest_path), _PARSER).getroot()
        except (OSError, etree.XMLSyntaxError):
            continue
        package_id = str(package.attrib.get("id", ""))
        if not package_id:
            continue
        for resource in package.xpath("./resources/font[@id][@name]"):
            resource_id = str(resource.attrib["id"])
            resource_path = str(resource.attrib.get("path", "/")).strip("/")
            font_path = manifest_path.parent / resource_path / str(resource.attrib["name"])
            try:
                digest = hashlib.sha256(font_path.read_bytes()).hexdigest()
            except OSError:
                continue
            result.setdefault(digest, f"ui://{package_id}{resource_id}")
    return result


def _color(value: object, opacity: float = 1.0) -> str | None:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        return None
    try:
        red, green, blue, alpha = (max(0.0, min(1.0, float(item))) for item in value)
    except (TypeError, ValueError):
        return None
    channels = tuple(round(item * 255) for item in (red, green, blue))
    resolved_alpha = round(max(0.0, min(1.0, alpha * opacity)) * 255)
    if resolved_alpha < 255:
        return f"#{resolved_alpha:02x}{channels[0]:02x}{channels[1]:02x}{channels[2]:02x}"
    return f"#{channels[0]:02x}{channels[1]:02x}{channels[2]:02x}"


def _fixed_font_uri(font_name: object, font_uris: dict[str, str]) -> str | None:
    if not isinstance(font_name, str):
        return None
    normalized = font_name.casefold()
    spec = next(
        (
            item
            for item in PROJECT_FIXED_FONTS
            if normalized in {item.family.casefold(), item.postscript_name.casefold()}
        ),
        None,
    )
    return font_uris.get(spec.sha256) if spec is not None else None


def _apply_psd_text_style(
    element: etree._Element,
    node: SelectionNode,
    font_uris: dict[str, str],
) -> None:
    if element.tag not in {"text", "richtext"}:
        return
    style = node.style.get("psdTextStyle")
    if not isinstance(style, dict):
        return
    runs = style.get("runs")
    if not isinstance(runs, (tuple, list)) or len(runs) != 1 or not isinstance(runs[0], dict):
        return
    run = runs[0]
    transform = style.get("transform")
    if not isinstance(transform, (tuple, list)) or len(transform) != 6:
        return
    try:
        scale_x = math.hypot(float(transform[0]), float(transform[1]))
        scale_y = math.hypot(float(transform[2]), float(transform[3]))
    except (TypeError, ValueError):
        return
    font_size = run.get("font_size")
    if isinstance(font_size, (int, float)) and not isinstance(font_size, bool):
        effective_font_size = float(font_size) * scale_y
        element.attrib["fontSize"] = _number(effective_font_size)
        leading = run.get("leading")
        if isinstance(leading, (int, float)) and not isinstance(leading, bool):
            element.attrib["leading"] = _number((float(leading) - float(font_size)) * scale_y)
        tracking = run.get("tracking")
        if isinstance(tracking, (int, float)) and not isinstance(tracking, bool):
            letter_spacing = float(tracking) / 1000 * float(font_size) * scale_x
            element.attrib["letterSpacing"] = _number(letter_spacing)
    font_uri = _fixed_font_uri(run.get("font_name"), font_uris)
    if font_uri is not None:
        element.attrib["font"] = font_uri
    if run.get("faux_bold") is True:
        element.attrib["bold"] = "true"
    if run.get("faux_italic") is True:
        element.attrib["italic"] = "true"
    justification = style.get("paragraph_justification")
    alignment = {0: "left", 1: "right", 2: "center"}.get(justification)
    if alignment is not None:
        element.attrib["align"] = alignment

    text_color = _color(run.get("fill_rgba"))
    effects = node.properties.get("psdEffects", ())
    if isinstance(effects, (tuple, list)):
        for effect in effects:
            if not isinstance(effect, dict) or effect.get("enabled") is not True:
                continue
            opacity_value = effect.get("opacity")
            opacity = (
                max(0.0, min(1.0, float(opacity_value) / 100))
                if isinstance(opacity_value, (int, float)) and not isinstance(opacity_value, bool)
                else 1.0
            )
            if effect.get("kind") == "ColorOverlay" and effect.get("blend_mode") == "normal":
                text_color = _color(effect.get("color_rgba"), opacity)
            elif (
                effect.get("kind") == "Stroke"
                and effect.get("blend_mode") == "normal"
                and effect.get("position") in {"outside", "center"}
            ):
                stroke_color = _color(effect.get("color_rgba"), opacity)
                if stroke_color is not None:
                    element.attrib["strokeColor"] = stroke_color
                size = effect.get("size")
                if isinstance(size, (int, float)) and not isinstance(size, bool):
                    element.attrib["strokeSize"] = _number(float(size))
    if text_color is not None:
        element.attrib["color"] = text_color


def _selection_box(
    root: SelectionNode,
    node: SelectionNode,
    inventory: FguiComponentInventory,
) -> tuple[float, float, float, float]:
    if root.bounds.width <= 0 or root.bounds.height <= 0:
        raise HifiPatchError("hifi_selection_root_invalid")
    if root.id.startswith("psd-root:"):
        return (
            node.bounds.x - root.bounds.x,
            node.bounds.y - root.bounds.y,
            node.bounds.width,
            node.bounds.height,
        )
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
    font_uris: dict[str, str],
) -> None:
    x, y, width, height = _selection_box(root, node, inventory)
    # FairyGUI 6.1.4 parses xy/size as Int32 pairs. Decimal geometry makes the
    # whole component open as an empty canvas, even when every referenced file
    # exists, so round at the XML boundary just like the new-project writer.
    element.attrib["xy"] = f"{_editor_int32(x)},{_editor_int32(y)}"
    element.attrib["size"] = f"{_editor_int32(width)},{_editor_int32(height)}"
    if element.tag == "text" and node.text is not None:
        element.attrib["text"] = node.text
    _apply_psd_text_style(element, node, font_uris)
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
    font_uris: dict[str, str] | None = None,
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
    # These nodes are visual skins layered over the protected legacy objects.
    # Input must continue to reach the original button/component listeners.
    element.attrib["touchable"] = "false"
    _set_visual(element, node, root, inventory, font_uris or {})
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
    parity_reference: Path | None = None,
) -> ChangeBundle:
    if mapping.unresolved_count:
        raise HifiPatchError("hifi_mapping_incomplete")
    if len(selection.top_level_nodes) != 1:
        raise HifiPatchError("hifi_selection_requires_single_root")
    selection_root_node = selection.top_level_nodes[0]
    if (
        selection_root_node.id.startswith("psd-root:")
        and not any(item.action in {"accept", "retarget"} for item in mapping.items)
    ):
        raise HifiPatchError("hifi_mapping_requires_replacements")
    if selection_root_node.id.startswith("psd-root:") and any(
        item.action == "add_visual" for item in mapping.items
    ):
        raise HifiPatchError("hifi_psd_visual_requires_owner")
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
    font_uris = _project_font_uris(root)
    psd_visuals: list[tuple[int, int, etree._Element]] = []

    def stage_psd_visual(node: SelectionNode, element: etree._Element) -> bool:
        if not selection_root_node.id.startswith("psd-root:"):
            return False
        document_index = node.properties.get("psdDocumentIndex")
        if isinstance(document_index, bool) or not isinstance(document_index, int):
            return False
        text_priority = 1 if node.type.upper() == "TEXT" else 0
        psd_visuals.append((text_priority, document_index, element))
        return True

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
            _set_visual(element, node, selection_root_node, inventory, font_uris)
            old = next((value for value in inventory.objects if value.object_id == item.old_object_id), None)
            stage_psd_visual(node, element)
            resource_id, file_name = material(node)
            if resource_id is not None and old is not None:
                if element.tag == "image" and not old.shared_resource:
                    element.attrib["src"] = resource_id
                    element.attrib.pop("pkg", None)
                    if file_name is not None:
                        element.attrib["fileName"] = file_name
                else:
                    skin = _new_visual(
                        node,
                        selection_root_node,
                        inventory,
                        resource_id,
                        file_name,
                        font_uris,
                    )
                    if not stage_psd_visual(node, skin):
                        display_list.append(skin)
        elif item.action == "add_visual":
            if item.figma_node_id is None or item.figma_node_id in claimed:
                continue
            try:
                node = nodes[item.figma_node_id]
            except KeyError as error:
                raise HifiPatchError("mapping_target_missing") from error
            resource_id, file_name = material(node)
            element = _new_visual(
                node,
                selection_root_node,
                inventory,
                resource_id,
                file_name,
                font_uris,
            )
            if not stage_psd_visual(node, element):
                display_list.append(element)
            claimed.add(item.figma_node_id)
        elif item.action not in {"keep_old", "exception"}:
            raise HifiPatchError("invalid_mapping_action")
    for _, _, element in sorted(psd_visuals, key=lambda item: (item[0], item[1])):
        if element.getparent() is display_list:
            display_list.remove(element)
        display_list.append(element)
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
                exported="true",
                # PSD fragments are already exact raster evidence. Keeping them
                # outside an atlas avoids editor repacking/cropping (notably for
                # layers taller than the default 2048 texture limit).
                atlas="0",
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
    mutable = set(_COMMON_VISUAL_ATTRIBUTES)
    if copy.tag in {"text", "richtext"}:
        mutable.update(_TEXT_VISUAL_ATTRIBUTES)
    elif copy.tag == "image":
        mutable.update(_IMAGE_VISUAL_ATTRIBUTES)
    for attribute in tuple(copy.attrib):
        if attribute in mutable:
            del copy.attrib[attribute]
    return cast(bytes, etree.tostring(copy, method="c14n", with_comments=True))


def _protected_component_structure(document: etree._ElementTree) -> bytes:
    copy = etree.fromstring(etree.tostring(document.getroot()))
    copy.attrib.pop("size", None)
    display_list = copy.find("displayList")
    if display_list is not None:
        for child in tuple(display_list):
            display_list.remove(child)
    return cast(bytes, etree.tostring(copy, method="c14n", with_comments=True))


def _xml_bounds(element: etree._Element) -> tuple[float, float, float, float]:
    def pair(value: str | None) -> tuple[float, float]:
        if value is None:
            return 0.0, 0.0
        try:
            first, second = value.split(",", 1)
            return float(first), float(second)
        except (TypeError, ValueError):
            return 0.0, 0.0

    x, y = pair(element.attrib.get("xy"))
    width, height = pair(element.attrib.get("size"))
    return x, y, max(0.0, width), max(0.0, height)


def _overlaps(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> bool:
    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second
    if min(first_width, first_height, second_width, second_height) <= 0:
        return False
    return (
        first_x < second_x + second_width
        and second_x < first_x + first_width
        and first_y < second_y + second_height
        and second_y < first_y + first_height
    )


def _behavior_occlusions(
    document: etree._ElementTree,
    inventory: FguiComponentInventory,
) -> tuple[str, ...]:
    display_list = document.getroot().find("displayList")
    if display_list is None:
        return ()
    ordered = tuple(display_list)
    indexes = {str(element.attrib.get("id", "")): index for index, element in enumerate(ordered)}
    added = tuple(
        (index, element)
        for index, element in enumerate(ordered)
        if str(element.attrib.get("id", "")).startswith("hifi_")
        and element.attrib.get("visible", "true") != "false"
        and element.attrib.get("alpha", "1") != "0"
    )
    blocked: list[str] = []
    for item in inventory.objects:
        if not item.behavior_protected:
            continue
        old_index = indexes.get(item.object_id)
        if old_index is None:
            continue
        old_bounds = (item.x, item.y, item.width, item.height)
        if any(index > old_index and _overlaps(old_bounds, _xml_bounds(element)) for index, element in added):
            blocked.append(item.object_id)
    return tuple(blocked)


def validate_hifi_candidate(
    before_root: Path,
    after_root: Path,
    inventory: FguiComponentInventory,
    mapping: HifiMappingDraft,
    *,
    session_id: str,
    lossless_blockers: tuple[str, ...] = (),
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
    if _protected_component_structure(before_doc) != _protected_component_structure(after_doc):
        raise HifiPatchError("hifi_protected_structure_changed")
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
    warnings = tuple(f"PSD 无损证据待验证：{code}" for code in lossless_blockers)
    behavior_occlusions = _behavior_occlusions(after_doc, inventory)
    if behavior_occlusions:
        warnings += (
            "新增 HIFI 图层遮挡受状态、实例参数、关系或动画控制的旧对象："
            + ", ".join(behavior_occlusions),
        )
    if not inventory.parse_complete:
        warnings += ("目标组件含未知标签或属性；候选保留其原始字节结构，仍需 Editor 检查。",)
    return HifiReplacementReview(
        version=1,
        session_id=session_id,
        mapping_revision=mapping.mapping_revision,
        target=inventory.target,
        changed_files=diff_items,
        object_diffs=build_object_diffs(before_doc, after_doc, mapping),
        protected_checks_passed=True,
        parse_coverage_complete=inventory.parse_complete,
        approvable=not lossless_blockers and not behavior_occlusions,
        warnings=warnings,
        editor_check_required=True,
    )
