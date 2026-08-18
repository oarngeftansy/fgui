from __future__ import annotations

from pathlib import Path
from typing import cast

from lxml import etree

from figma_to_fgui.models import FrozenModel

FAIRYGUI_VERSION = "6.1.4"
PROJECT_SUFFIX = ".fairy"
ASSETS_DIRECTORY = "assets"

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


def parse_editor_fixture(root: Path) -> EditorDialectFixture:
    markers = tuple(root.glob(f"*{PROJECT_SUFFIX}"))
    manifests = tuple((root / ASSETS_DIRECTORY).glob("*/package.xml"))
    if len(markers) != 1 or len(manifests) != 1:
        raise ValueError("fixture must contain one project marker and one package")
    package_root = manifests[0].parent
    package = etree.parse(str(manifests[0]), SAFE_XML_PARSER).getroot()
    resources = package.find("resources")
    if resources is None:
        raise ValueError("fixture package has no resources")
    components = tuple(item for item in resources if etree.QName(item).localname == "component")
    names = tuple(Path(item.attrib["name"]).stem for item in components)
    roots = tuple(
        etree.parse(
            str(package_root / item.attrib.get("path", "/").strip("/") / item.attrib["name"]),
            SAFE_XML_PARSER,
        ).getroot()
        for item in components
    )
    sizes = tuple(tuple(int(value) for value in item.attrib["size"].split(",")) for item in roots)
    return EditorDialectFixture(
        project_name=markers[0].stem,
        package_name=package_root.name,
        component_names=names,
        component_sizes=cast(tuple[tuple[int, int], ...], sizes),
    )
