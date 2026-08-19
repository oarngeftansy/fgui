from __future__ import annotations

import re
import stat
import unicodedata
from pathlib import Path, PurePosixPath

from lxml import etree

from figma_to_fgui.models import FrozenModel

FAIRYGUI_VERSION = "6.1.4"
PROJECT_SUFFIX = ".fairy"
ASSETS_DIRECTORY = "assets"

_PROJECT_FILE_VERSION = "5.0"
_UNITY_TARGET = "Unity"
_ID = re.compile(r"^[a-z0-9]+$")
_SIZE = re.compile(r"^([1-9][0-9]*),([1-9][0-9]*)$")
_DRIVE_PATH = re.compile(r"^[A-Za-z]:")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

SAFE_XML_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    load_dtd=False,
    huge_tree=False,
)


class EditorDialectFixture(FrozenModel):
    project_name: str
    package_name: str
    component_names: tuple[str, ...]
    component_sizes: tuple[tuple[int, int], ...]


def _contains_control_character(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _is_link_or_reparse(path: Path) -> bool:
    metadata = path.lstat()
    attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & _REPARSE_POINT)


def _reject_link_or_reparse(path: Path) -> None:
    if _is_link_or_reparse(path):
        raise ValueError("fixture contains a symlink or reparse point")


def _require_directory(path: Path, label: str) -> None:
    try:
        _reject_link_or_reparse(path)
        metadata = path.lstat()
    except OSError as error:
        raise ValueError(f"fixture {label} is missing") from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"fixture {label} must be a directory")


def _require_regular_file(path: Path, label: str) -> None:
    try:
        _reject_link_or_reparse(path)
        metadata = path.lstat()
    except OSError as error:
        raise ValueError(f"fixture {label} is missing") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"fixture {label} must be a regular file")


def _parse_xml(path: Path, label: str) -> etree._Element:
    _require_regular_file(path, label)
    try:
        return etree.parse(str(path), SAFE_XML_PARSER.copy()).getroot()
    except (OSError, etree.XMLSyntaxError) as error:
        raise ValueError(f"invalid {label} XML") from error


def _validate_id(value: str | None, label: str) -> str:
    if value is None or _ID.fullmatch(value) is None:
        raise ValueError(f"invalid {label} id")
    return value


def _resource_relative_path(path_value: str, name: str) -> PurePosixPath:
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or ":" in name
        or _contains_control_character(name)
    ):
        raise ValueError("invalid resource name")
    if (
        "\\" in path_value
        or _contains_control_character(path_value)
        or path_value.startswith("/")
        or _DRIVE_PATH.match(path_value)
    ):
        raise ValueError("unsafe resource path")

    if path_value:
        without_trailing_slash = path_value.removesuffix("/")
        parts = without_trailing_slash.split("/")
        if not without_trailing_slash or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("unsafe resource path")
    else:
        parts = []
    return PurePosixPath(*parts, name)


def _require_contained_resource(package_root: Path, relative: PurePosixPath) -> Path:
    target = package_root.joinpath(*relative.parts)
    current = package_root
    for part in relative.parts:
        current /= part
        _require_regular_file(current, "resource") if current == target else _require_directory(
            current, "resource directory"
        )

    package_resolved = package_root.resolve(strict=True)
    try:
        target.resolve(strict=True).relative_to(package_resolved)
    except (OSError, ValueError) as error:
        raise ValueError("resource path escapes package root") from error
    return target


def _project_marker(marker_path: Path) -> None:
    marker = _parse_xml(marker_path, "project marker")
    if marker.tag != "projectDescription":
        raise ValueError("invalid project marker root")
    _validate_id(marker.attrib.get("id"), "project marker")
    if marker.attrib.get("type") != _UNITY_TARGET:
        raise ValueError("invalid project marker type")
    if marker.attrib.get("version") != _PROJECT_FILE_VERSION:
        raise ValueError("invalid project marker version")


def _component_details(path: Path, expected_name: str) -> tuple[str, tuple[int, int]]:
    component = _parse_xml(path, "component")
    if component.tag != "component":
        raise ValueError("invalid component root")
    name = component.attrib.get("name", "")
    if not name or _contains_control_character(name) or name != expected_name:
        raise ValueError("invalid component name")
    size = component.attrib.get("size", "")
    match = _SIZE.fullmatch(size)
    if match is None:
        raise ValueError("invalid component size")
    if len(component.findall("displayList")) != 1:
        raise ValueError("invalid component displayList")
    return name, (int(match.group(1)), int(match.group(2)))


def parse_editor_fixture(root: Path) -> EditorDialectFixture:
    _require_directory(root, "root")
    markers = tuple(path for path in root.iterdir() if path.name.endswith(PROJECT_SUFFIX))
    assets = root / ASSETS_DIRECTORY
    _require_directory(assets, "assets directory")

    manifests: list[Path] = []
    for candidate in assets.iterdir():
        _reject_link_or_reparse(candidate)
        if not candidate.is_dir():
            continue
        manifest = candidate / "package.xml"
        if manifest.exists() or manifest.is_symlink():
            manifests.append(manifest)

    if len(markers) != 1 or len(manifests) != 1:
        raise ValueError("fixture must contain one project marker and one package")
    marker_path = markers[0]
    manifest_path = manifests[0]
    _project_marker(marker_path)

    package_root = manifest_path.parent
    package = _parse_xml(manifest_path, "package")
    if package.tag != "packageDescription":
        raise ValueError("invalid package root")
    _validate_id(package.attrib.get("id"), "package")
    resource_elements = package.findall("resources")
    publish_elements = package.findall("publish")
    if len(resource_elements) != 1:
        raise ValueError("invalid package resources")
    if len(publish_elements) != 1:
        raise ValueError("invalid package publish")

    resources = resource_elements[0]
    resource_ids: set[str] = set()
    components: list[tuple[Path, str]] = []
    for resource in resources:
        resource_id = _validate_id(resource.attrib.get("id"), "package resource")
        if resource_id in resource_ids:
            raise ValueError("duplicate package resource id")
        resource_ids.add(resource_id)
        name = resource.attrib.get("name", "")
        relative = _resource_relative_path(resource.attrib.get("path", ""), name)
        target = _require_contained_resource(package_root, relative)
        if resource.tag == "component":
            components.append((target, Path(name).stem))

    component_details = tuple(
        _component_details(component_path, expected_name)
        for component_path, expected_name in components
    )
    return EditorDialectFixture(
        project_name=marker_path.stem,
        package_name=package_root.name,
        component_names=tuple(name for name, _size in component_details),
        component_sizes=tuple(size for _name, size in component_details),
    )
