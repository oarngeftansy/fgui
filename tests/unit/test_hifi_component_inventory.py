from __future__ import annotations

from pathlib import Path

from figma_to_fgui.hifi_project_inspector import (
    inspect_component,
    inspect_hifi_targets,
    target_from_option,
)
from figma_to_fgui.uploaded_project import index_uploaded_project

FIXTURE = Path(__file__).parents[1] / "fixtures/hifi_replacement/old_project"


def _inventory():
    project = index_uploaded_project(FIXTURE, "old.zip")
    tree = inspect_hifi_targets(FIXTURE, project)
    package = tree.packages[0]
    directory = next(item for item in package.directories if item.path == "Panel")
    component = next(item for item in directory.components if item.resource_id == "sketch01")
    return inspect_component(FIXTURE, target_from_option(project, package, directory, component))


def test_inventory_keeps_identity_behavior_and_unknown_xml() -> None:
    inventory = _inventory()
    reset = next(item for item in inventory.objects if item.object_id == "btn_reset")
    assert reset.name == "Btn_Reset"
    assert reset.controller_refs == ("page",)
    assert reset.transition_refs == ("intro",)
    assert len(reset.protected_sha256) == 64
    assert inventory.parse_complete is False
    assert inventory.unknown_tags == ("mystery",)


def test_shared_component_instance_is_marked_but_definition_is_not_opened() -> None:
    inventory = _inventory()
    button = next(item for item in inventory.objects if item.object_id == "btn_next")
    assert button.shared_resource is True
    assert button.resource_id == "sharedbtn1"
