from __future__ import annotations

import shutil
import uuid
from hashlib import sha256
from pathlib import Path

import pytest
from lxml import etree
from PIL import Image

from figma_to_fgui.apply import apply_bundle
from figma_to_fgui.figma_selection import SelectionManifest
from figma_to_fgui.fixed_fonts import FixedFontSpec
from figma_to_fgui.hifi_mapping import apply_mapping_decision, build_mapping
from figma_to_fgui.hifi_patch import (
    HifiPatchError,
    _behavior_occlusions,
    _protected_object,
    build_hifi_change_bundle,
    validate_hifi_candidate,
)
from figma_to_fgui.hifi_project_inspector import (
    inspect_component,
    inspect_hifi_targets,
    target_from_option,
)
from figma_to_fgui.hifi_replacement_models import HifiMappingDecision
from figma_to_fgui.models import Bounds
from figma_to_fgui.uploaded_project import index_uploaded_project

FIXTURE = Path(__file__).parents[1] / "fixtures/hifi_replacement"


def _confirmed():
    root = FIXTURE / "old_project"
    project = index_uploaded_project(root, "old.zip")
    tree = inspect_hifi_targets(root, project)
    package = tree.packages[0]
    directory = next(item for item in package.directories if item.path == "Panel")
    component = next(item for item in directory.components if item.resource_id == "sketch01")
    inventory = inspect_component(root, target_from_option(project, package, directory, component))
    manifest = SelectionManifest.model_validate_json((FIXTURE / "hifi-selection.json").read_text("utf-8"))
    mapping = build_mapping(inventory, manifest)
    for item in tuple(mapping.items):
        current = next(current for current in mapping.items if current.item_id == item.item_id)
        if current.action is None:
            if current.status in {"uncertain", "suggested"}:
                action = "retarget"
            elif current.status == "hifi_added" and current.figma_node_id == "progress-bubble":
                action = "add_visual"
            elif current.status in {"hifi_added", "blocked"}:
                action = "exception"
            else:
                action = "keep_old"
            mapping = apply_mapping_decision(
                mapping,
                HifiMappingDecision(
                    version=1,
                    mapping_revision=mapping.mapping_revision,
                    item_id=current.item_id,
                    action=action,
                    figma_node_id=current.candidates[0] if action == "retarget" else None,
                ),
                manifest,
            )
    return root, inventory, manifest, mapping


def _without_unowned_additions(mapping):
    return mapping.model_copy(
        update={
            "items": tuple(
                item.model_copy(update={"action": "exception"})
                if item.action == "add_visual"
                else item
                for item in mapping.items
            )
        }
    )


def test_patch_changes_visuals_without_rebuilding_or_deleting_old_objects(tmp_path: Path) -> None:
    root, inventory, manifest, mapping = _confirmed()
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    bundle = build_hifi_change_bundle(
        candidate,
        inventory,
        manifest,
        mapping,
        job_id=uuid.uuid4().hex,
        selection_root=FIXTURE / "selection",
    )
    apply_bundle(candidate, bundle)
    relative = inventory.target.component_relative_path
    before = etree.parse(str(root / relative))
    after = etree.parse(str(candidate / relative))
    before_ids = {str(node.attrib["id"]) for node in before.xpath("./displayList/*[@id]")}
    after_ids = {str(node.attrib["id"]) for node in after.xpath("./displayList/*[@id]")}
    assert before_ids <= after_ids
    added_visuals = after.xpath("./displayList/*[starts-with(@id, 'hifi_')]")
    assert added_visuals
    assert all(item.attrib.get("touchable") == "false" for item in added_visuals)
    reset_before = before.xpath("./displayList/*[@id='btn_reset']")[0]
    reset_after = after.xpath("./displayList/*[@id='btn_reset']")[0]
    assert etree.tostring(reset_before) == etree.tostring(reset_after)
    review = validate_hifi_candidate(
        root, candidate, inventory, mapping, session_id=uuid.uuid4().hex
    )
    assert review.protected_checks_passed is True
    assert {item.kind for item in review.object_diffs} >= {"changed", "added", "kept"}
    assert review.approvable is True
    changed_paths = {item.relative_path for item in review.changed_files}
    assert relative in changed_paths
    assert "assets/MyVillage/package.xml" in changed_paths
    assert any(path.startswith("assets/MyVillage/Img/HIFI/") for path in changed_paths)
    assert review.editor_check_required is True


def test_patch_serializes_all_object_geometry_as_editor_int32_pairs(tmp_path: Path) -> None:
    root, inventory, manifest, mapping = _confirmed()
    candidate = tmp_path / "candidate-integer-geometry"
    shutil.copytree(root, candidate)
    bundle = build_hifi_change_bundle(
        candidate,
        inventory,
        manifest,
        mapping,
        job_id=uuid.uuid4().hex,
        selection_root=FIXTURE / "selection",
    )
    apply_bundle(candidate, bundle)

    component = etree.parse(str(candidate / inventory.target.component_relative_path))
    for element in component.xpath("./displayList/*[@xy or @size]"):
        for attribute in ("xy", "size"):
            value = element.attrib.get(attribute)
            if value is not None:
                assert all(part.lstrip("-").isdigit() for part in value.split(",")), (
                    element.attrib.get("id"),
                    attribute,
                    value,
                )


def test_psd_patch_preserves_full_document_coordinates_without_resizing_fgui_viewport(
    tmp_path: Path,
) -> None:
    root, inventory, manifest, mapping = _confirmed()
    mapping = _without_unowned_additions(mapping)
    source_root = manifest.top_level_nodes[0]
    source_children = tuple(
        child.model_copy(
            update={"bounds": Bounds(x=0, y=500, width=900, height=500)}
        )
        if child.id == "hifi-board"
        else child
        for child in source_root.children
    )
    psd_manifest = manifest.model_copy(
        update={
            "top_level_nodes": (
                source_root.model_copy(
                    update={
                        "id": "psd-root:" + "a" * 64,
                        "bounds": Bounds(x=0, y=0, width=1100, height=2100),
                        "children": source_children,
                    }
                ),
            )
        }
    )
    candidate = tmp_path / "candidate-psd-canvas"
    shutil.copytree(root, candidate)
    bundle = build_hifi_change_bundle(
        candidate,
        inventory,
        psd_manifest,
        mapping,
        job_id=uuid.uuid4().hex,
        selection_root=FIXTURE / "selection",
    )
    apply_bundle(candidate, bundle)

    component = etree.parse(str(candidate / inventory.target.component_relative_path))
    assert component.getroot().attrib["size"] == "750,420"
    assert component.xpath("./displayList/*[@id='board_bg']")[0].attrib["size"] == "900,500"
    assert component.xpath("./displayList/*[@id='board_bg']")[0].attrib["xy"] == "0,500"
    assert component.xpath("./displayList/*[@id='title_bar']")[0].attrib["xy"] == "48,30"
    review = validate_hifi_candidate(
        root, candidate, inventory, mapping, session_id=uuid.uuid4().hex
    )
    assert review.protected_checks_passed is True


def test_psd_reference_is_never_embedded_as_a_full_component_overlay(
    tmp_path: Path,
) -> None:
    root, inventory, manifest, mapping = _confirmed()
    mapping = _without_unowned_additions(mapping)
    source_root = manifest.top_level_nodes[0]
    psd_manifest = manifest.model_copy(
        update={
            "top_level_nodes": (
                source_root.model_copy(
                    update={
                        "id": "psd-root:" + "a" * 64,
                        "bounds": Bounds(x=0, y=0, width=750, height=420),
                    }
                ),
            )
        }
    )
    parity_reference = tmp_path / "viewport.png"
    Image.new("RGB", (750, 420), (17, 34, 51)).save(parity_reference)
    candidate = tmp_path / "candidate-parity"
    shutil.copytree(root, candidate)

    bundle = build_hifi_change_bundle(
        candidate,
        inventory,
        psd_manifest,
        mapping,
        job_id=uuid.uuid4().hex,
        selection_root=FIXTURE / "selection",
        parity_reference=parity_reference,
    )
    apply_bundle(candidate, bundle)

    component = etree.parse(str(candidate / inventory.target.component_relative_path))
    assert not component.xpath("./displayList/image[starts-with(@id, 'hifi_psd_default_')]")
    package = etree.parse(str(candidate / "assets/MyVillage/package.xml"))
    assert not package.xpath("./resources/image[starts-with(@name, 'PSD_Default_')]")

    review = validate_hifi_candidate(
        root, candidate, inventory, mapping, session_id=uuid.uuid4().hex
    )
    assert all("PSD 默认参考图" not in warning for warning in review.warnings)


def test_psd_candidate_rejects_additions_when_no_old_object_is_mapped(
    tmp_path: Path,
) -> None:
    root, inventory, manifest, mapping = _confirmed()
    source_root = manifest.top_level_nodes[0]
    psd_manifest = manifest.model_copy(
        update={
            "top_level_nodes": (
                source_root.model_copy(update={"id": "psd-root:" + "b" * 64}),
            )
        }
    )
    unmapped = mapping.model_copy(
        update={
            "items": tuple(
                item.model_copy(update={"action": "keep_old"})
                if item.old_object_id is not None
                else item
                for item in mapping.items
            )
        }
    )

    with pytest.raises(HifiPatchError, match="hifi_mapping_requires_replacements"):
        build_hifi_change_bundle(
            root,
            inventory,
            psd_manifest,
            unmapped,
            job_id=uuid.uuid4().hex,
            selection_root=FIXTURE / "selection",
        )


def test_psd_candidate_rejects_unowned_new_root_visuals(tmp_path: Path) -> None:
    root, inventory, manifest, mapping = _confirmed()
    source_root = manifest.top_level_nodes[0]
    psd_manifest = manifest.model_copy(
        update={
            "top_level_nodes": (
                source_root.model_copy(update={"id": "psd-root:" + "c" * 64}),
            )
        }
    )

    with pytest.raises(HifiPatchError, match="hifi_psd_visual_requires_owner"):
        build_hifi_change_bundle(
            root,
            inventory,
            psd_manifest,
            mapping,
            job_id=uuid.uuid4().hex,
            selection_root=FIXTURE / "selection",
        )


def test_mapped_graph_keeps_program_object_and_adds_raster_skin(
    tmp_path: Path,
) -> None:
    root, inventory, manifest, mapping = _confirmed()
    mapping = _without_unowned_additions(mapping)
    source_root = manifest.top_level_nodes[0]
    skinned_children = tuple(
        child.model_copy(
            update={
                "resource_keys": ("hifi-board",),
                "properties": {
                    **child.properties,
                    "psdDocumentIndex": 10,
                },
            }
        )
        if child.id == "hifi-silhouette"
        else child
        for child in source_root.children
    )
    psd_manifest = manifest.model_copy(
        update={
            "top_level_nodes": (
                source_root.model_copy(
                    update={
                        "id": "psd-root:" + "a" * 64,
                        "children": skinned_children,
                    }
                ),
            )
        }
    )
    candidate = tmp_path / "candidate-graph-skin"
    shutil.copytree(root, candidate)

    bundle = build_hifi_change_bundle(
        candidate,
        inventory,
        psd_manifest,
        mapping,
        job_id=uuid.uuid4().hex,
        selection_root=FIXTURE / "selection",
    )
    apply_bundle(candidate, bundle)

    component = etree.parse(str(candidate / inventory.target.component_relative_path))
    protected_graph = component.xpath("./displayList/graph[@id='silhouette_01']")[0]
    assert protected_graph.xpath("./gearDisplay")
    skin = component.xpath("./displayList/image[starts-with(@id, 'hifi_')][@src]")
    assert any(item.attrib.get("name") == "CharacterSilhouette" for item in skin)
    assert all(item.attrib.get("touchable") == "false" for item in skin)


def test_patch_registers_uploaded_hifi_image_and_retargets_private_image(tmp_path: Path) -> None:
    root, inventory, manifest, mapping = _confirmed()
    selection_root = FIXTURE / "selection"
    png = (selection_root / "resources/hifi-board").read_bytes()
    candidate = tmp_path / "candidate-with-image"
    shutil.copytree(root, candidate)
    bundle = build_hifi_change_bundle(
        candidate,
        inventory,
        manifest,
        mapping,
        job_id=uuid.uuid4().hex,
        selection_root=selection_root,
    )
    apply_bundle(candidate, bundle)
    component = etree.parse(str(candidate / inventory.target.component_relative_path))
    board_after = component.xpath("./displayList/*[@id='board_bg']")[0]
    assert str(board_after.attrib["src"]).startswith("h")
    package = etree.parse(str(candidate / "assets/MyVillage/package.xml"))
    resource = package.xpath(f"./resources/image[@id='{board_after.attrib['src']}']")
    assert len(resource) == 1
    assert resource[0].attrib["atlas"] == "0"
    assert resource[0].attrib["exported"] == "true"
    created = candidate / "assets/MyVillage" / resource[0].attrib["path"].strip("/") / resource[0].attrib["name"]
    assert created.read_bytes() == png
    review = validate_hifi_candidate(
        root, candidate, inventory, mapping, session_id=uuid.uuid4().hex
    )
    assert any(item.operation == "create" for item in review.changed_files)


def test_patch_writes_exact_psd_text_style_with_project_font_resource(
    tmp_path: Path, monkeypatch
) -> None:
    root, inventory, manifest, mapping = _confirmed()
    candidate = tmp_path / "candidate-with-text-style"
    shutil.copytree(root, candidate)

    font_bytes = b"exact-project-font"
    font_root = candidate / "assets/Fonts"
    (font_root / "Font").mkdir(parents=True)
    (font_root / "Font/Core.ttf").write_bytes(font_bytes)
    (font_root / "package.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<packageDescription id="fontpkg1"><resources>'
        '<font id="core1" name="Core.ttf" path="/Font/"/>'
        '</resources></packageDescription>',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "figma_to_fgui.hifi_patch.PROJECT_FIXED_FONTS",
        (
            FixedFontSpec(
                family="CoreSansESW01-55Medium",
                postscript_name="CoreSansESW01-55Medium",
                source_filename="core.ttf",
                sha256=sha256(font_bytes).hexdigest(),
            ),
        ),
    )

    root_node = manifest.top_level_nodes[0]
    styled_children = tuple(
        child.model_copy(
            update={
                "style": {
                    "psdTextStyle": {
                        "runs": ({
                            "start": 0,
                            "length": 14,
                            "font_name": "CoreSansESW01-55Medium",
                            "font_size": 40.0,
                            "faux_bold": True,
                            "faux_italic": False,
                            "leading": 44.0,
                            "tracking": 50.0,
                            "fill_rgba": (0.1, 0.2, 0.3, 1.0),
                        },),
                        "transform": (1.1, 0.0, 0.0, 1.1, 0.0, 0.0),
                        "paragraph_justification": 2,
                        "anti_alias": 4,
                    }
                },
                "properties": {
                    "psdEffects": ({
                        "kind": "ColorOverlay",
                        "enabled": True,
                        "blend_mode": "normal",
                        "opacity": 100.0,
                        "color_rgba": (1.0, 0.8, 0.2, 1.0),
                        "size": None,
                        "angle": None,
                        "distance": None,
                        "spread": None,
                        "choke": None,
                        "position": None,
                    }, {
                        "kind": "Stroke",
                        "enabled": True,
                        "blend_mode": "normal",
                        "opacity": 100.0,
                        "color_rgba": (0.2, 0.3, 0.4, 1.0),
                        "size": 3.0,
                        "angle": None,
                        "distance": None,
                        "spread": None,
                        "choke": None,
                        "position": "outside",
                    })
                },
            }
        ) if child.id == "hifi-title" else child
        for child in root_node.children
    )
    styled_manifest = manifest.model_copy(
        update={"top_level_nodes": (root_node.model_copy(update={"children": styled_children}),)}
    )

    bundle = build_hifi_change_bundle(
        candidate,
        inventory,
        styled_manifest,
        mapping,
        job_id=uuid.uuid4().hex,
        selection_root=FIXTURE / "selection",
    )
    apply_bundle(candidate, bundle)
    component = etree.parse(str(candidate / inventory.target.component_relative_path))
    title = component.xpath("./displayList/text[@id='title_bar']")[0]
    assert title.attrib["font"] == "ui://fontpkg1core1"
    assert title.attrib["fontSize"] == "44"
    assert title.attrib["color"] == "#ffcc33"
    assert title.attrib["align"] == "center"
    assert title.attrib["bold"] == "true"
    assert title.attrib["leading"] == "4.4"
    assert title.attrib["letterSpacing"] == "2.2"
    assert title.attrib["strokeColor"] == "#334c66"
    assert title.attrib["strokeSize"] == "3"


def test_text_visual_attributes_do_not_trip_structure_protection() -> None:
    before = etree.fromstring(
        b'<text id="title" name="Title" group="layout" text="Old" fontSize="30"/>'
    )
    after = etree.fromstring(
        b'<text id="title" name="Title" group="layout" text="New" fontSize="44" '
        b'font="ui://fontpkg1core1" color="#ffcc33" align="center" bold="true" '
        b'italic="true" leading="4.4" letterSpacing="2.2" '
        b'strokeColor="#334c66" strokeSize="3"/>'
    )

    assert _protected_object(before) == _protected_object(after)

    component_before = etree.fromstring(
        b'<component id="button" name="Button" src="component-a" xy="0,0"/>'
    )
    component_after = etree.fromstring(
        b'<component id="button" name="Button" src="component-b" xy="10,20"/>'
    )
    assert _protected_object(component_before) != _protected_object(component_after)


def test_behavior_audit_detects_new_skin_above_controller_driven_object() -> None:
    _, inventory, _, _ = _confirmed()
    document = etree.parse(
        str(FIXTURE / "old_project" / inventory.target.component_relative_path)
    )
    display_list = document.getroot().find("displayList")
    assert display_list is not None
    display_list.append(
        etree.Element(
            "image",
            id="hifi_cover",
            name="HifiCover",
            xy="50,100",
            size="210,250",
            touchable="false",
        )
    )

    assert _behavior_occlusions(document, inventory) == ("silhouette_01",)


def test_candidate_validation_rejects_existing_gear_and_transition_changes(
    tmp_path: Path,
) -> None:
    root, inventory, manifest, mapping = _confirmed()
    candidate = tmp_path / "candidate-program-protection"
    shutil.copytree(root, candidate)
    bundle = build_hifi_change_bundle(
        candidate,
        inventory,
        manifest,
        mapping,
        job_id=uuid.uuid4().hex,
        selection_root=FIXTURE / "selection",
    )
    apply_bundle(candidate, bundle)
    component_path = candidate / inventory.target.component_relative_path

    document = etree.parse(str(component_path))
    gear = document.xpath("./displayList/graph[@id='silhouette_01']/gearDisplay")[0]
    original_pages = gear.attrib["pages"]
    gear.attrib["pages"] = "0"
    document.write(str(component_path), encoding="utf-8", xml_declaration=True)
    with pytest.raises(HifiPatchError, match="hifi_protected_structure_changed"):
        validate_hifi_candidate(
            root, candidate, inventory, mapping, session_id=uuid.uuid4().hex
        )

    gear.attrib["pages"] = original_pages
    component = document.xpath("./displayList/component[@id='btn_next']")[0]
    original_component_source = component.attrib["src"]
    component.attrib["src"] = "different-component"
    document.write(str(component_path), encoding="utf-8", xml_declaration=True)
    with pytest.raises(HifiPatchError, match="hifi_protected_structure_changed"):
        validate_hifi_candidate(
            root, candidate, inventory, mapping, session_id=uuid.uuid4().hex
        )

    component.attrib["src"] = original_component_source
    transition = document.xpath("./transition[@name='intro']/item")[0]
    transition.attrib["duration"] = "9.9"
    document.write(str(component_path), encoding="utf-8", xml_declaration=True)
    with pytest.raises(HifiPatchError, match="hifi_protected_structure_changed"):
        validate_hifi_candidate(
            root, candidate, inventory, mapping, session_id=uuid.uuid4().hex
        )
