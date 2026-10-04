from __future__ import annotations

from pathlib import Path

from figma_to_fgui.hifi_project_inspector import (
    inspect_component,
    inspect_hifi_targets,
    target_from_option,
)
from figma_to_fgui.uploaded_project import index_uploaded_project

FIXTURE = Path(__file__).parents[1] / "fixtures/hifi_replacement/old_project"


def test_inspector_returns_package_directory_and_component_identity() -> None:
    project = index_uploaded_project(FIXTURE, "old.zip")
    tree = inspect_hifi_targets(FIXTURE, project)
    package = next(item for item in tree.packages if item.name == "MyVillage")
    panel = next(node for node in package.directories if node.path == "Panel")
    component = next(node for node in panel.components if node.name == "Panel_MyVillage_Sketchboard")
    target = target_from_option(project, package, panel, component)
    assert target.component_id == "sketch01"
    assert target.component_relative_path == (
        "assets/MyVillage/Panel/Panel_MyVillage_Sketchboard.xml"
    )
    assert "C:" not in tree.model_dump_json()


def test_invalid_component_is_visible_but_not_selectable(tmp_path: Path) -> None:
    root = tmp_path / "project"
    package_root = root / "assets/Bad"
    package_root.mkdir(parents=True)
    (root / "Bad.fairy").write_text(
        '<projectDescription id="1234567890abcdef1234567890abcdef" type="Unity" version="5.0"/>',
        "utf-8",
    )
    (package_root / "package.xml").write_text(
        '<packageDescription id="bad01"><resources>'
        '<component id="badcmp" name="Broken.xml" path="/Panel/"/>'
        '</resources><publish/></packageDescription>',
        "utf-8",
    )
    (package_root / "Panel").mkdir()
    (package_root / "Panel/Broken.xml").write_text("<component", "utf-8")
    project = index_uploaded_project(root, "bad.zip")
    component = inspect_hifi_targets(root, project).packages[0].directories[0].components[0]
    assert component.selectable is False
    assert component.reason == "component_unavailable"


def test_unsupported_editor_version_disables_every_component(tmp_path: Path) -> None:
    root = tmp_path / "project"
    package_root = root / "assets/Old"
    (package_root / "Panel").mkdir(parents=True)
    (root / "Old.fairy").write_text(
        '<projectDescription id="1234567890abcdef1234567890abcdef" type="Unity" version="4.0"/>',
        "utf-8",
    )
    (package_root / "package.xml").write_text(
        '<packageDescription id="old01"><resources>'
        '<component id="oldcmp" name="Root.xml" path="/Panel/"/>'
        '</resources><publish/></packageDescription>',
        "utf-8",
    )
    (package_root / "Panel/Root.xml").write_text(
        '<component size="10,10"><displayList/></component>', "utf-8"
    )
    project = index_uploaded_project(root, "old.zip")
    component = inspect_hifi_targets(root, project).packages[0].directories[0].components[0]
    assert component.selectable is False
    assert component.reason == "unsupported_fairygui_version"


def _loader_project(tmp_path: Path, loader_url: str) -> Path:
    root = tmp_path / "project"
    (root / "assets/Lab/Panel").mkdir(parents=True)
    (root / "assets/Lab/Images").mkdir(parents=True)
    (root / "Lab.fairy").write_text(
        '<projectDescription id="1234567890abcdef1234567890abcdef" type="Unity" version="5.0"/>',
        "utf-8",
    )
    (root / "assets/Lab/package.xml").write_text(
        '<packageDescription id="lab01"><resources>'
        '<image id="img01" name="Icon.png" path="/Images/"/>'
        '<component id="panel01" name="Panel_L.xml" path="/Panel/"/>'
        "</resources><publish/></packageDescription>",
        "utf-8",
    )
    (root / "assets/Lab/Panel/Panel_L.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<component size="100,100"><displayList>'
        f'<loader id="ldr" name="icon" xy="0,0" size="40,40" url="{loader_url}" fill="scale"/>'
        "</displayList></component>",
        "utf-8",
    )
    return root


def _loader_object(root: Path):
    project = index_uploaded_project(root, "lab.zip")
    tree = inspect_hifi_targets(root, project)
    package = tree.packages[0]
    directory = next(item for item in package.directories if item.path == "Panel")
    component = next(item for item in directory.components if item.resource_id == "panel01")
    inventory = inspect_component(
        root, target_from_option(project, package, directory, component)
    )
    return next(obj for obj in inventory.objects if obj.object_id == "ldr")


def test_loader_resource_id_resolves_from_url_image_reference(tmp_path: Path) -> None:
    root = _loader_project(tmp_path, "ui://lab01img01")
    loader = _loader_object(root)
    assert loader.object_type == "loader"
    assert loader.resource_id == "img01"


def test_loader_resource_id_is_none_when_url_has_no_image_match(tmp_path: Path) -> None:
    root = _loader_project(tmp_path, "ui://lab01missing")
    loader = _loader_object(root)
    assert loader.resource_id is None
