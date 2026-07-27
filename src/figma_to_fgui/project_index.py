from pathlib import Path

from lxml import etree
from pydantic import Field

from figma_to_fgui.models import FrozenModel, ProjectResource
from figma_to_fgui.paths import safe_relative_path


class ProjectIndex(FrozenModel):
    packages: dict[str, str] = Field(default_factory=dict)
    by_name: dict[str, ProjectResource] = Field(default_factory=dict)
    ids_by_package: dict[str, frozenset[str]] = Field(default_factory=dict)


def index_project(root: Path) -> ProjectIndex:
    packages: dict[str, str] = {}
    by_name: dict[str, ProjectResource] = {}
    ids: dict[str, set[str]] = {}
    for manifest in sorted(root.glob("*/package.xml")):
        tree = etree.parse(str(manifest))
        package = tree.getroot()
        package_name = manifest.parent.name
        package_id = str(package.attrib["id"])
        packages[package_name] = package_id
        ids[package_name] = set()
        for element in package.xpath("./resources/*"):
            kind = str(element.tag)
            resource_id = str(element.attrib["id"])
            name = str(element.attrib["name"])
            path = str(element.attrib.get("path", "/"))
            relative = safe_relative_path(f"{package_name}/{path.strip('/')}/{name}")
            resource = ProjectResource(
                id=resource_id,
                name=name,
                kind=kind,
                package_id=package_id,
                relative_path=relative,
            )
            by_name[name] = resource
            ids[package_name].add(resource_id)
    return ProjectIndex(
        packages=packages,
        by_name=by_name,
        ids_by_package={name: frozenset(values) for name, values in ids.items()},
    )
