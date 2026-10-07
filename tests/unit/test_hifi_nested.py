import shutil
from pathlib import Path

import pytest
from PIL import Image

from figma_to_fgui.hifi_project_inspector import inspect_hifi_targets, target_from_option
from figma_to_fgui.uploaded_project import index_uploaded_project

FIXTURE = Path(__file__).parents[1] / "fixtures/hifi_replacement/old_project"


def test_largest_opaque_rectangle_excludes_transparent_skin_border() -> None:
    from figma_to_fgui.hifi_nested import _largest_opaque_rectangle

    image = Image.new("RGBA", (9, 7), (0, 0, 0, 0))
    for y in range(1, 6):
        for x in range(2, 7):
            image.putpixel((x, y), (240, 220, 180, 255))

    assert _largest_opaque_rectangle(image) == (2, 1, 5, 5)


@pytest.mark.parametrize("fill", ["scale", "scaleFree"])
def test_psd_retired_graph_is_not_geometry_fitted_under_new_skin(
    tmp_path, fill: str
) -> None:
    from lxml import etree

    from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
    from figma_to_fgui.hifi_mapping import build_mapping
    from figma_to_fgui.hifi_nested import (
        _fit_retained_graphs_under_owned_siblings,
        inspect_component_tree,
    )
    from figma_to_fgui.models import Bounds

    root, old_inventory, _, _ = nested_case(tmp_path)
    child_path = "assets/MyVillage/Common/Button_Common.xml"
    child = root / child_path
    child.write_text(
        '<component size="120,44" extention="Button"><displayList>'
        '<graph id="bg" name="Background" xy="0,0" size="120,44" '
        'type="rect" fillColor="#ffffcc00"/>'
        '<loader id="skin" name="icon" xy="0,0" size="100,40" '
        f'url="ui://myvillagskin0001" align="center" vAlign="middle" fill="{fill}"/>'
        '<text id="title" name="title" xy="10,10" size="90,24" text="Default"/>'
        '</displayList><Button downEffect="scale" downEffectValue=".99"/></component>',
        encoding="utf-8",
    )
    package = root / "assets/MyVillage/package.xml"
    package.write_text(
        package.read_text(encoding="utf-8").replace(
            "</resources>",
            '<image id="skin0001" name="Skin.png" path="/Img/HIFI/" atlas="0"/>'
            "</resources>",
        ),
        encoding="utf-8",
    )
    image_path = root / "assets/MyVillage/Img/HIFI/Skin.png"
    image_path.parent.mkdir(parents=True)
    image = Image.new("RGBA", (120, 44), (0, 0, 0, 0))
    for y in range(8, 36):
        for x in range(12, 108):
            image.putpixel((x, y), (255, 247, 237, 255))
    image.save(image_path)

    inventory = inspect_component_tree(root, old_inventory.target)
    # A relation on the component instance marks every nested child as
    # runtime-position-bound in the flattened inventory.  That must not block
    # local geometry changes inside the component definition: the instance
    # still moves as one unit and keeps the same child object identity.
    inventory = inventory.model_copy(update={
        "objects": tuple(
            item.model_copy(update={"position_runtime_bound": True})
            if item.object_id == "a:bg"
            else item
            for item in inventory.objects
        ),
    })
    source = SelectionManifest(
        version=1,
        display_name="PSD",
        top_level_nodes=(SelectionNode(
            id="psd-root:skin",
            name="PSD",
            type="FRAME",
            bounds=Bounds(x=0, y=0, width=750, height=420),
            children=(SelectionNode(
                id="skin-leaf",
                name="icon",
                type="IMAGE",
                bounds=Bounds(x=10, y=20, width=120, height=44),
            ),),
        ),),
    )
    draft = build_mapping(inventory, source)
    mapping = draft.model_copy(update={
        "items": tuple(
            item.model_copy(update={
                "action": "accept",
                "figma_node_id": "skin-leaf",
                "owned_source_ids": ("skin-leaf",),
            })
            if item.old_object_id == "a:skin"
            else item.model_copy(update={
                "action": "keep_old" if item.old_object_id else "exception",
            })
            for item in draft.items
        ),
        "unresolved_count": 0,
    })

    changed = _fit_retained_graphs_under_owned_siblings(root, inventory, mapping)

    # PSD reskins no longer mutate old geometry to tuck a legacy paint layer
    # underneath the new skin. The mapping marks that graph for visual
    # retirement and the normal patch pass turns off its default pixels.
    graph_mapping = next(i for i in mapping.items if i.old_object_id == "a:bg")
    assert graph_mapping.visual_disposition == "retire"
    assert changed == set()
    document = etree.parse(str(child))
    assert document.xpath("./displayList/*/@id") == ["bg", "skin", "title"]
    graph = document.xpath("./displayList/graph[@id='bg']")[0]
    assert graph.get("xy") == "0,0"
    assert graph.get("size") == "120,44"
    assert graph.get("alpha") is None
    assert graph.get("visible") is None
    assert graph.get("fillColor") == "#ffffcc00"
    assert document.xpath("string(./Button/@downEffect)") == "scale"


def test_changed_auto_layout_group_uses_mapped_member_gap(tmp_path) -> None:
    from lxml import etree

    from figma_to_fgui.hifi_nested import _sync_changed_group_bounds, inspect_component_tree

    root, old_inventory, _source, mapping = nested_case(tmp_path)
    child_path = "assets/MyVillage/Common/Button_Common.xml"
    child = root / child_path
    child.write_text(
        '<component size="120,44"><displayList>'
        '<graph id="bg" name="Background" xy="0,0" size="40,44" group="row" '
        'type="rect" fillColor="#ff112233"/>'
        '<text id="title" name="title" xy="39,10" size="81,24" group="row" text="Default"/>'
        '<group id="row" name="row" xy="0,0" size="120,44" advanced="true" '
        'layout="hz" colGap="5" excludeInvisibles="true"/>'
        '</displayList></component>',
        encoding="utf-8",
    )
    inventory = inspect_component_tree(root, old_inventory.target)
    mapping = mapping.model_copy(update={
        "items": tuple(
            item.model_copy(update={"action": "accept"})
            if item.old_object_id in {"a:bg", "a:title"}
            else item
            for item in mapping.items
        ),
    })

    _sync_changed_group_bounds(root, inventory, mapping)

    document = etree.parse(str(child))
    group = document.xpath("./displayList/group[@id='row']")[0]
    assert group.get("colGap") == "-1"
    assert group.get("xy") == "0,0"
    assert group.get("size") == "120,44"


def inputs(root=FIXTURE):
    project = index_uploaded_project(root, "old.zip")
    tree = inspect_hifi_targets(root, project)
    package = tree.packages[0]
    directory = next(d for d in package.directories if d.path == "Panel")
    component = next(c for c in directory.components if c.resource_id == "sketch01")
    return target_from_option(project, package, directory, component)


def test_nested_instances_have_distinct_identity_and_local_ownership():
    from figma_to_fgui.hifi_nested import inspect_component_tree

    inventory = inspect_component_tree(FIXTURE, inputs())
    labels = [o for o in inventory.objects if o.local_object_id == "shared_label"]
    assert len(labels) >= 2
    assert len({o.object_id for o in inventory.objects}) == len(inventory.objects)
    assert len({o.instance_path for o in labels}) == len(labels)
    for label in labels:
        parent = next(o for o in inventory.objects if o.object_id == label.instance_path[-1])
        assert label.x == parent.x + 12
        assert label.y == parent.y + 10
        assert label.component_relative_path.endswith("Common/Button_Common.xml")
    assert inventory.expanded_instances


def test_nested_unknown_fields_make_parse_coverage_incomplete(tmp_path):
    from figma_to_fgui.hifi_nested import inspect_component_tree

    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    child = root / "assets/MyVillage/Common/Button_Common.xml"
    child.write_text(
        child.read_text().replace('text="Common"', 'text="Common" unknownRuntimeBinding="x"')
    )
    inventory = inspect_component_tree(root, inputs(root))
    assert not inventory.parse_complete
    assert any(
        o.local_object_id == "shared_label" and o.unknown_attributes for o in inventory.objects
    )


def test_nested_cycle_is_reported_without_losing_sibling_objects(tmp_path):
    from figma_to_fgui.hifi_nested import inspect_component_tree

    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    child = root / "assets/MyVillage/Common/Button_Common.xml"
    child.write_text(
        child.read_text().replace(
            "</displayList>",
            '<component id="cycle" name="cycle" src="sharedbtn1" xy="0,0"/></displayList>',
        )
    )
    inventory = inspect_component_tree(root, inputs(root))
    assert not inventory.parse_complete
    assert any("cycle" in issue for issue in inventory.scope_issues)
    assert len(inventory.objects) < 100


def test_list_line_gap_scales_with_row_definition_height(tmp_path):
    from lxml import etree

    from figma_to_fgui.hifi_nested import _sync_list_line_gaps, inspect_component_tree

    root, inventory, _, _ = nested_case(tmp_path)
    target = inventory.target
    (root / "assets/MyVillage/Common/Row.xml").write_text(
        '<component size="120,40"><displayList>'
        '<graph id="rb" name="RowBg" xy="0,0" size="120,40" type="rect" fillColor="#ff334455"/>'
        "</displayList></component>",
        encoding="utf-8",
    )
    package = root / "assets/MyVillage/package.xml"
    package.write_text(
        package.read_text(encoding="utf-8").replace(
            "</resources>",
            '<component id="row1" name="Row.xml" path="/Common/"/>'
            "</resources>",
        ),
        encoding="utf-8",
    )
    (root / target.component_relative_path).write_text(
        '<component size="750,420"><displayList>'
        '<component id="a" name="Delegate" src="sharedbtn1" xy="10,20"/>'
        '<list id="rows" name="RowList" xy="0,100" lineGap="10" '
        'defaultItem="ui://myvillagrow1">'
        '<component id="r1" name="row" src="row1" xy="0,0"/>'
        "</list></displayList></component>",
        encoding="utf-8",
    )
    inventory = inspect_component_tree(root, target)
    assert any(o.object_type == "list" for o in inventory.objects)

    staged = tmp_path / "staged"
    shutil.copytree(root, staged)
    (staged / "assets/MyVillage/Common/Row.xml").write_text(
        '<component size="120,60"><displayList>'
        '<graph id="rb" name="RowBg" xy="0,0" size="120,60" type="rect" fillColor="#ff334455"/>'
        "</displayList></component>",
        encoding="utf-8",
    )
    _sync_list_line_gaps(staged, root, inventory)
    grown = etree.parse(str(staged / target.component_relative_path)).xpath(".//list")[0]
    assert grown.get("lineGap") == "15"  # 10 * 60 / 40

    unchanged = tmp_path / "unchanged"
    shutil.copytree(root, unchanged)
    _sync_list_line_gaps(unchanged, root, inventory)
    kept = etree.parse(str(unchanged / target.component_relative_path)).xpath(".//list")[0]
    assert kept.get("lineGap") == "10"


def nested_case(tmp_path):
    from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
    from figma_to_fgui.hifi_mapping import build_mapping
    from figma_to_fgui.hifi_nested import inspect_component_tree
    from figma_to_fgui.models import Bounds

    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    target = inputs(root)
    (root / target.component_relative_path).write_text(
        '<component size="750,420"><displayList>'
        '<component id="a" name="Delegate" src="sharedbtn1" xy="10,20"/>'
        '<component id="b" name="Reward" src="sharedbtn1" xy="200,100"/>'
        "</displayList></component>"
    )
    child = root / "assets/MyVillage/Common/Button_Common.xml"
    child.write_text(
        '<component size="120,44" extention="Button">'
        '<controller name="enabled" pages="0,on,1,off" selected="0"/>'
        '<displayList><graph id="bg" name="Background" xy="0,0" size="120,44" '
        'type="rect" fillColor="#ff112233"><gearDisplay controller="enabled" pages="0"/></graph>'
        '<text id="title" name="title" xy="10,10" size="90,24" text="Default"/></displayList>'
        '<Button downEffect="scale" downEffectValue=".99"/></component>'
    )
    inventory = inspect_component_tree(root, target)
    nodes = tuple(
        SelectionNode(
            id=f"shape-{x}",
            name="Background",
            type="RECTANGLE",
            bounds=Bounds(x=x, y=y, width=120, height=44),
            properties={"fguiGraph": {"shape": "rect", "fillColor": "#ff445566", "lineSize": 0}},
        )
        for x, y in ((10, 20), (200, 100))
    )
    source = SelectionManifest(
        version=1,
        display_name="PSD",
        top_level_nodes=(
            SelectionNode(
                id="psd-root:test",
                name="PSD",
                type="FRAME",
                bounds=Bounds(x=0, y=0, width=750, height=420),
                children=nodes,
            ),
        ),
    )
    draft = build_mapping(inventory, source)
    chosen = {"a:bg": nodes[0].id, "b:bg": nodes[1].id}
    items = tuple(
        item.model_copy(update={"action": "retarget", "figma_node_id": chosen[item.old_object_id]})
        if item.old_object_id in chosen
        else item.model_copy(update={"action": "keep_old" if item.old_object_id else "exception"})
        for item in draft.items
    )
    return root, inventory, source, draft.model_copy(update={"items": items, "unresolved_count": 0})


def test_default_visibility_propagates_through_hidden_controller_instance(tmp_path):
    from figma_to_fgui.hifi_nested import inspect_component_tree

    root, inventory, _, _ = nested_case(tmp_path)
    source = root / inventory.target.component_relative_path
    source.write_text(source.read_text().replace(
        '<component size="750,420"><displayList>',
        '<component size="750,420"><controller name="hasTab" pages="0,false,1,true" '
        'selected="0"/><displayList>').replace(
        '<component id="a" name="Delegate" src="sharedbtn1" xy="10,20"/>',
        '<component id="a" name="Delegate" src="sharedbtn1" xy="10,20">'
        '<gearDisplay controller="hasTab" pages="1"/></component>'))
    expanded = inspect_component_tree(root, inventory.target)
    assert not next(o for o in expanded.objects if o.object_id == "a").default_visible
    assert not next(o for o in expanded.objects if o.object_id == "a:bg").default_visible
    assert next(o for o in expanded.objects if o.object_id == "b:bg").default_visible


def test_nested_runtime_visibility_uses_first_page_unless_instance_overrides_controller(tmp_path):
    from figma_to_fgui.hifi_nested import inspect_component_tree

    root, inventory, _, _ = nested_case(tmp_path)
    child = root / "assets/MyVillage/Common/Button_Common.xml"
    child.write_text(
        child.read_text().replace(
            'controller name="enabled" pages="0,on,1,off" selected="0"',
            'controller name="enabled" exported="true" pages="0,on,1,off" selected="1"',
        ).replace(
            '<gearDisplay controller="enabled" pages="0"/>',
            '<gearDisplay controller="enabled" pages="1"/>',
        )
    )

    expanded = inspect_component_tree(root, inventory.target)
    assert not next(o for o in expanded.objects if o.object_id == "a:bg").default_visible
    assert not next(o for o in expanded.objects if o.object_id == "b:bg").default_visible

    panel = root / inventory.target.component_relative_path
    panel.write_text(
        panel.read_text().replace(
            '<component id="a" name="Delegate" src="sharedbtn1" xy="10,20"/>',
            '<component id="a" name="Delegate" src="sharedbtn1" xy="10,20" '
            'controller="enabled,1"/>',
        )
    )
    overridden = inspect_component_tree(root, inventory.target)
    assert next(o for o in overridden.objects if o.object_id == "a:bg").default_visible
    assert not next(o for o in overridden.objects if o.object_id == "b:bg").default_visible


def test_nested_icon_gear_updates_runtime_first_page_not_editor_selected_page():
    from lxml import etree

    from figma_to_fgui.hifi_nested import _update_runtime_gear_icon

    component = etree.fromstring(
        b'<component><controller name="type" pages="0,runtime,1,editor" selected="1"/>'
        b'<displayList><loader id="icon" url="ui://pkgnew">'
        b'<gearIcon controller="type" pages="0,1" values="ui://pkgold0|ui://pkgold1"/>'
        b'</loader></displayList></component>'
    )
    gear = component.xpath("./displayList/loader/gearIcon")[0]

    assert _update_runtime_gear_icon(component, gear, "ui://pkgnew", {})

    assert gear.get("values") == "ui://pkgnew|ui://pkgold1"
    assert component.xpath("string(./controller/@selected)") == "1"


def test_nested_icon_gear_respects_parent_runtime_controller_override():
    from lxml import etree

    from figma_to_fgui.hifi_nested import _update_runtime_gear_icon

    component = etree.fromstring(
        b'<component><controller name="type" pages="0,runtime,1,alternate" selected="0"/>'
        b'<displayList><loader id="icon" url="ui://pkgnew">'
        b'<gearIcon controller="type" pages="0,1" values="ui://pkgold0|ui://pkgold1"/>'
        b'</loader></displayList></component>'
    )
    gear = component.xpath("./displayList/loader/gearIcon")[0]

    assert _update_runtime_gear_icon(component, gear, "ui://pkgnew", {"type": "1"})

    assert gear.get("values") == "ui://pkgold0|ui://pkgnew"


def test_nested_graph_updates_definition_once_and_preserves_instances_and_states(tmp_path):
    from lxml import etree

    from figma_to_fgui.apply import apply_bundle
    from figma_to_fgui.hifi_patch import build_hifi_change_bundle, validate_hifi_candidate

    root, inventory, source, mapping = nested_case(tmp_path)
    target_bytes = (root / inventory.target.component_relative_path).read_bytes()
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    bundle = build_hifi_change_bundle(root, inventory, source, mapping)
    assert not any(".figma-to-fgui" in f.relative_path for f in bundle.files)
    apply_bundle(candidate, bundle)
    assert (candidate / inventory.target.component_relative_path).read_bytes() == target_bytes
    child = etree.parse(str(candidate / "assets/MyVillage/Common/Button_Common.xml"))
    assert child.xpath("string(./displayList/graph/@fillColor)") == "#ff445566"
    assert child.xpath("./displayList/*/@id") == ["bg", "title"]
    assert child.xpath("string(./displayList/graph/gearDisplay/@controller)") == "enabled"
    assert child.xpath("string(./Button/@downEffect)") == "scale"
    review = validate_hifi_candidate(root, candidate, inventory, mapping, session_id="a" * 32)
    assert review.protected_checks_passed
    assert {d.old_object_id for d in review.object_diffs if d.kind == "changed"} == {"a:bg", "b:bg"}
    # Rendered state evidence moved to warnings; the Editor stage discharges it.
    assert review.approvable
    assert review.warnings


def test_expanded_component_wrappers_can_be_preserved_as_structure(tmp_path):
    from figma_to_fgui.apply import apply_bundle
    from figma_to_fgui.hifi_patch import build_hifi_change_bundle, validate_hifi_candidate

    root, inventory, source, mapping = nested_case(tmp_path)
    assert all(o.structural_only for o in inventory.objects if o.object_type == "component")
    mapping = mapping.model_copy(update={"items": tuple(
        item.model_copy(update={"action": "preserve_structure"})
        if item.old_object_id in {"a", "b"} else item for item in mapping.items
    )})
    bundle = build_hifi_change_bundle(root, inventory, source, mapping)
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    apply_bundle(candidate, bundle)
    review = validate_hifi_candidate(root, candidate, inventory, mapping, session_id="a" * 32)
    assert review.protected_checks_passed


def test_nested_patch_translates_psd_viewport_to_local_component_coordinates(tmp_path):
    from figma_to_fgui.hifi_nested import _local_plans
    from figma_to_fgui.models import Bounds

    root, inventory, source, mapping = nested_case(tmp_path)
    frame = source.top_level_nodes[0]
    shifted = tuple(
        node.model_copy(update={"bounds": Bounds(
            x=node.bounds.x, y=node.bounds.y + 210,
            width=node.bounds.width, height=node.bounds.height,
        )})
        for node in frame.children
    )
    source = source.model_copy(update={"top_level_nodes": (frame.model_copy(update={
        "bounds": Bounds(x=0, y=0, width=750, height=630),
        "properties": {"psdViewportBounds": (0, 210, 750, 420)},
        "children": shifted,
    }),)})
    plans = _local_plans(root, inventory, source, mapping)
    child_source = next(selection for local, selection, _ in plans
                        if local.target.component_name == "Button_Common")
    assert [node.bounds.y for node in child_source.top_level_nodes[0].children] == [0]


def test_shared_definition_isolates_conflicting_instance_visuals(tmp_path):
    from lxml import etree

    from figma_to_fgui.apply import apply_bundle
    from figma_to_fgui.hifi_patch import build_hifi_change_bundle, validate_hifi_candidate

    root, inventory, source, mapping = nested_case(tmp_path)
    frame = source.top_level_nodes[0]
    nodes = (
        frame.children[0],
        frame.children[1].model_copy(
            update={
                "properties": {
                    "fguiGraph": {"shape": "rect", "fillColor": "#ff998877", "lineSize": 0}
                }
            }
        ),
    )
    source = source.model_copy(
        update={"top_level_nodes": (frame.model_copy(update={"children": nodes}),)}
    )
    bundle = build_hifi_change_bundle(root, inventory, source, mapping)
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    apply_bundle(candidate, bundle)
    parent = etree.parse(str(candidate / inventory.target.component_relative_path))
    instances = parent.xpath("./displayList/component")
    assert [item.get("id") for item in instances] == ["a", "b"]
    assert instances[0].get("src") != instances[1].get("src")
    original = root / "assets/MyVillage/Common/Button_Common.xml"
    assert (candidate / original.relative_to(root)).read_bytes() == original.read_bytes()
    variants = list((candidate / "assets/MyVillage/Common").glob("Button_Common__hifi_*.xml"))
    assert len(variants) == 2
    assert {etree.parse(str(path)).xpath("string(./displayList/graph/@fillColor)")
            for path in variants} == {"#ff445566", "#ff998877"}
    assert all(etree.parse(str(path)).xpath("./displayList/*/@id") == ["bg", "title"]
               for path in variants)
    review = validate_hifi_candidate(root, candidate, inventory, mapping, session_id="b" * 32)
    assert review.protected_checks_passed
    # Per-state verification moved to warnings; the Editor stage discharges it.
    assert review.approvable
    assert review.warnings
    parent_path = candidate / inventory.target.component_relative_path
    parent = etree.parse(str(parent_path))
    parent.xpath("./displayList/component[@id='a']")[0].set("touchable", "false")
    parent.write(str(parent_path))
    with pytest.raises(ValueError, match="variant_instance_contract_changed"):
        validate_hifi_candidate(root, candidate, inventory, mapping, session_id="b" * 32)


def test_shared_definition_does_not_mutate_unselected_component_users(tmp_path):
    from figma_to_fgui.apply import apply_bundle
    from figma_to_fgui.hifi_patch import build_hifi_change_bundle

    root, inventory, source, mapping = nested_case(tmp_path)
    other = root / "assets/MyVillage/Panel/Other.xml"
    other.write_text(
        '<component size="100,100"><displayList><component id="other" src="sharedbtn1" xy="0,0"/></displayList></component>'
    )
    original_other = other.read_bytes()
    original_definition = (root / "assets/MyVillage/Common/Button_Common.xml").read_bytes()
    bundle = build_hifi_change_bundle(root, inventory, source, mapping)
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    apply_bundle(candidate, bundle)
    assert (candidate / other.relative_to(root)).read_bytes() == original_other
    assert (candidate / "assets/MyVillage/Common/Button_Common.xml").read_bytes() == original_definition


def test_runtime_title_keeps_instance_value_but_uses_psd_geometry(tmp_path):
    from lxml import etree

    from figma_to_fgui.apply import apply_bundle
    from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
    from figma_to_fgui.hifi_mapping import build_mapping
    from figma_to_fgui.hifi_nested import inspect_component_tree
    from figma_to_fgui.hifi_patch import build_hifi_change_bundle
    from figma_to_fgui.models import Bounds

    root, inventory, _, _ = nested_case(tmp_path)
    panel_path = root / inventory.target.component_relative_path
    panel_path.write_text(
        panel_path.read_text().replace(
            '<component id="a" name="Delegate" src="sharedbtn1" xy="10,20"/>',
            '<component id="a" name="Delegate" src="sharedbtn1" xy="10,20">'
            '<Button title="Tower"/></component>',
        )
    )
    # Force per-instance isolation, just like the real shared title component.
    (root / "assets/MyVillage/Panel/Other.xml").write_text(
        '<component size="100,100"><displayList>'
        '<component id="other" src="sharedbtn1" xy="0,0"/>'
        '</displayList></component>'
    )
    inventory = inspect_component_tree(root, inventory.target)
    background = SelectionNode(
        id="background",
        name="Background",
        type="RECTANGLE",
        bounds=Bounds(x=10, y=20, width=120, height=44),
        properties={"fguiGraph": {"shape": "rect", "fillColor": "#ff445566", "lineSize": 0}},
    )
    title = SelectionNode(
        id="runtime-title",
        name="Village Level",
        type="TEXT",
        bounds=Bounds(x=35, y=25, width=90, height=30),
        text="Village Level",
    )
    group = SelectionNode(
        id="title-group",
        name="Delegate",
        type="GROUP",
        bounds=Bounds(x=10, y=20, width=120, height=44),
        children=(background, title),
    )
    source = SelectionManifest(
        version=1,
        display_name="PSD",
        top_level_nodes=(SelectionNode(
            id="psd-root:title",
            name="PSD",
            type="FRAME",
            bounds=Bounds(x=0, y=0, width=750, height=420),
            children=(group,),
        ),),
    )
    draft = build_mapping(inventory, source)
    chosen = {"a": group.id, "a:bg": background.id, "a:title": title.id}
    mapping = draft.model_copy(update={
        "items": tuple(
            item.model_copy(update={
                "action": "retarget",
                "figma_node_id": chosen[item.old_object_id],
            })
            if item.old_object_id in chosen
            else item.model_copy(update={"action": "keep_old" if item.old_object_id else "exception"})
            for item in draft.items
        ),
        "unresolved_count": 0,
    })
    assert next(
        item for item in mapping.items if item.old_object_id == "a:title"
    ).preserve_runtime_text
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    apply_bundle(candidate, build_hifi_change_bundle(root, inventory, source, mapping))

    parent = etree.parse(str(candidate / inventory.target.component_relative_path))
    instance = parent.xpath("./displayList/component[@id='a']")[0]
    assert instance.xpath("string(./Button/@title)") == "Village Level"
    variant_name = Path(instance.get("fileName")).name
    variant = etree.parse(str(candidate / "assets/MyVillage/Common" / variant_name))
    mapped_title = variant.xpath("./displayList/text[@id='title']")[0]
    assert mapped_title.get("xy") == "25,5"
    assert mapped_title.get("size") == "90,30"
    assert mapped_title.get("text") == "Default"


def test_nested_change_rejects_external_user_of_affected_ancestor(tmp_path):
    from figma_to_fgui.hifi_nested import _assert_shared_scope, inspect_component_tree
    from figma_to_fgui.hifi_patch import HifiPatchError

    root, inventory, _, _ = nested_case(tmp_path)
    package = root / "assets/MyVillage/package.xml"
    package.write_text(
        package.read_text().replace(
            "</resources>", '<component id="outer" name="Outer.xml" path="/Common/"/></resources>'
        )
    )
    (root / "assets/MyVillage/Common/Outer.xml").write_text(
        '<component size="120,44"><displayList><component id="inner" src="sharedbtn1" xy="0,0"/></displayList></component>'
    )
    (root / inventory.target.component_relative_path).write_text(
        '<component size="750,420"><displayList><component id="outerInstance" src="outer" xy="0,0"/></displayList></component>'
    )
    (root / "assets/MyVillage/Panel/Other.xml").write_text(
        '<component size="750,420"><displayList><component id="other" src="outer" xy="0,0"/></displayList></component>'
    )
    inventory = inspect_component_tree(root, inventory.target)
    with pytest.raises(HifiPatchError, match="shared_scope"):
        _assert_shared_scope(root, inventory, {"assets/MyVillage/Common/Button_Common.xml"})


def _rebase_skeleton(tmp_path, cluster_color):
    root = tmp_path / "root"
    staged = tmp_path / "staged"
    for base in (root, staged):
        (base / "assets/Pkg/Core").mkdir(parents=True)
        (base / "assets/Pkg/Panel").mkdir(parents=True)
        (base / "assets/Base/Img").mkdir(parents=True)
        (base / "assets/Pkg/package.xml").write_text(
            '<packageDescription id="pkg0001"><resources>'
            '<component id="win0001" name="Win.xml" path="/Core/"/>'
            '<component id="winhifi1" name="Win__hifi_abc.xml" path="/Core/"/>'
            '<component id="btn0001" name="Btn.xml" path="/Core/"/>'
            '<image id="hifi0001" name="Bake.png" path="/Img/HIFI/Win__hifi_abc/"/>'
            "</resources></packageDescription>",
            encoding="utf-8",
        )
        (base / "assets/Base/package.xml").write_text(
            '<packageDescription id="bpkg0001"><resources>'
            '<image id="icon0001" name="BtnIcon.png" path="/Img/"/>'
            "</resources></packageDescription>",
            encoding="utf-8",
        )
        (base / "assets/Pkg/Core/Btn.xml").write_text(
            '<component size="132,132" extention="Button"><displayList>'
            '<loader id="icon" name="icon" xy="2,0" size="128,132" '
            'url="ui://bpkg0001icon0001"/>'
            "</displayList><Button/></component>",
            encoding="utf-8",
        )
        icon = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
        for y in range(10, 50):
            for x in range(10, 50):
                icon.putpixel((x, y), (186, 126, 92, 255))
        icon.save(base / "assets/Base/Img/BtnIcon.png")
        (base / "assets/Pkg/Panel/Main.xml").write_text(
            '<component size="1080,1920"><displayList>'
            '<component id="n1" name="com_pop" src="WINREF" '
            'fileName="Core/Win.xml" pkg="pkg0001" xy="INSTXY" size="1080,1567"/>'
            "</displayList></component>",
            encoding="utf-8",
        )
    (root / "assets/Pkg/Core/Win.xml").write_text(
        '<component size="1080,1567"><displayList>'
        '<image id="body" name="n77" src="hifi0001" fileName="Bake.png" '
        'xy="51,65" size="978,1448"/>'
        '<graph id="probe" name="autosize" xy="0,0" size="1080,1564" '
        'type="rect" fillColor="#ff000000"/>'
        '<component id="btn" name="btn_close" src="btn0001" fileName="Core/Btn.xml" '
        'pkg="pkg0001" xy="202,97" size="132,132"/>'
        "</displayList></component>",
        encoding="utf-8",
    )
    (staged / "assets/Pkg/Core/Win__hifi_abc.xml").write_text(
        '<component size="1080,1567"><displayList>'
        '<image id="body" name="n77" src="hifi0001" fileName="Bake.png" '
        'xy="350,0" size="1043,1523"/>'
        '<graph id="probe" name="autosize" xy="0,0" size="1080,1564" '
        'type="rect" fillColor="#ff000000"/>'
        '<component id="btn" name="btn_close" src="btn0001" fileName="Core/Btn.xml" '
        'pkg="pkg0001" xy="202,97" size="132,132"/>'
        "</displayList></component>",
        encoding="utf-8",
    )
    (staged / "assets/Pkg/Core/Win.xml").write_text(
        (root / "assets/Pkg/Core/Win.xml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (staged / "assets/Pkg/Img/HIFI/Win__hifi_abc").mkdir(parents=True)
    bake = Image.new("RGBA", (700, 400), (0, 0, 0, 0))
    if cluster_color is not None:
        for y in range(110, 158):
            for x in range(200, 248):
                bake.putpixel((x, y), (*cluster_color, 255))
    bake.save(staged / "assets/Pkg/Img/HIFI/Win__hifi_abc/Bake.png")
    for base, ref, xy in (
        (root, "win0001", "0,210"),
        (staged, "winhifi1", "-337,210"),
    ):
        main = base / "assets/Pkg/Panel/Main.xml"
        main.write_text(
            main.read_text(encoding="utf-8")
            .replace("WINREF", ref)
            .replace("INSTXY", xy),
            encoding="utf-8",
        )
    return root, staged


def _run_rebase(tmp_path, cluster_color):
    from lxml import etree

    from figma_to_fgui.hifi_nested import (
        _package_image_index,
        _rebase_retained_variant_children,
    )
    from figma_to_fgui.hifi_project_inspector import _package_resource_index

    root, staged = _rebase_skeleton(tmp_path, cluster_color)
    resources, packages = _package_image_index(staged)
    component_resources, _ = _package_resource_index(staged)
    resources = {**component_resources, **resources}
    _rebase_retained_variant_children(
        staged,
        root,
        [(
            "assets/Pkg/Panel/Main.xml",
            "assets/Pkg/Panel/Main.xml",
            "n1",
            "assets/Pkg/Core/Win__hifi_abc.xml",
        )],
        resources,
        packages,
    )
    variant = etree.parse(str(staged / "assets/Pkg/Core/Win__hifi_abc.xml"))
    button = etree.parse(str(staged / "assets/Pkg/Core/Btn.xml"))
    return variant, button


def test_retained_variant_children_keep_old_global_position(tmp_path) -> None:
    variant, button = _run_rebase(tmp_path, cluster_color=None)

    children = {
        e.get("id"): e.get("xy") for e in variant.xpath("./displayList/*[@id]")
    }
    assert children["body"] == "350,0"
    assert children["btn"] == "539,97"
    assert children["probe"] == "337,0"
    assert button.xpath("./displayList/loader/@visible") == []


def test_baked_button_glyph_retires_old_icon_visual(tmp_path) -> None:
    variant, button = _run_rebase(tmp_path, cluster_color=(186, 126, 92))

    assert button.xpath("./displayList/loader/@visible") == ["false"]
    children = {
        e.get("id"): e.get("xy") for e in variant.xpath("./displayList/*[@id]")
    }
    assert children["btn"] == "539,97"


def test_unrelated_baked_paint_keeps_old_icon_visual(tmp_path) -> None:
    variant, button = _run_rebase(tmp_path, cluster_color=(40, 160, 80))

    assert button.xpath("./displayList/loader/@visible") == []


def test_program_logic_audit_keeps_byte_identical_gears_clean(tmp_path) -> None:
    from figma_to_fgui.apply import apply_bundle
    from figma_to_fgui.hifi_mapping import build_mapping
    from figma_to_fgui.hifi_nested import inspect_component_tree
    from figma_to_fgui.hifi_patch import (
        build_hifi_change_bundle,
        validate_hifi_candidate,
    )

    root, inventory, source, _ = nested_case(tmp_path)
    child = root / "assets/MyVillage/Common/Button_Common.xml"
    child.write_text(
        '<component size="120,44" extention="Button">'
        '<controller name="enabled" pages="0,on,1,off" selected="0"/>'
        '<controller name="size" pages="0,big,1,small" selected="0"/>'
        '<displayList><graph id="bg" name="Background" xy="0,0" size="120,44" '
        'type="rect" fillColor="#ff112233">'
        '<gearDisplay controller="enabled" pages="0"/>'
        '<gearSize controller="size" pages="0,1" values="120,44,1,1|90,44,1,1"/></graph>'
        '<text id="title" name="title" xy="10,10" size="90,24" text="Default"/></displayList>'
        '<Button downEffect="scale" downEffectValue=".99"/></component>'
    )
    inventory = inspect_component_tree(root, inventory.target)
    frame = source.top_level_nodes[0]
    nodes = (
        frame.children[0],
        frame.children[1].model_copy(update={"properties": {
            "fguiGraph": {"shape": "rect", "fillColor": "#ff998877", "lineSize": 0}
        }}),
    )
    source = source.model_copy(update={"top_level_nodes": (
        frame.model_copy(update={"children": nodes}),
    )})
    draft = build_mapping(inventory, source)
    chosen = {"a:bg": nodes[0].id, "b:bg": nodes[1].id}
    items = tuple(
        item.model_copy(update={"action": "retarget", "figma_node_id": chosen[item.old_object_id]})
        if item.old_object_id in chosen
        else item.model_copy(update={"action": "keep_old" if item.old_object_id else "exception"})
        for item in draft.items
    )
    mapping = draft.model_copy(update={"items": items, "unresolved_count": 0})

    bundle = build_hifi_change_bundle(root, inventory, source, mapping)
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    apply_bundle(candidate, bundle)
    assert (candidate / "assets/MyVillage/Common/Button_Common.xml").read_bytes() == child.read_bytes()

    review = validate_hifi_candidate(root, candidate, inventory, mapping, session_id="c" * 32)
    assert review.protected_checks_passed
    # Regression: a conditional-expression precedence bug made every gear that
    # exists in the "before" document compare truthy, so byte-identical gearSize
    # entries were reported as program-logic mismatches (n60/n65 false alarm).
    assert not any("程序逻辑保留审计不一致" in w for w in review.warnings)
    audit = [w for w in review.warnings if w.startswith("程序逻辑保留审计：")]
    assert audit and "全部一致" in audit[0]
    assert any("零回归已机器审计" in w and "控制器状态已机器审计" in w
               for w in review.warnings)


def test_transition_keyframes_referencing_old_geometry_are_flagged(tmp_path) -> None:
    from lxml import etree

    from figma_to_fgui.apply import apply_bundle
    from figma_to_fgui.hifi_mapping import build_mapping
    from figma_to_fgui.hifi_nested import inspect_component_tree
    from figma_to_fgui.hifi_patch import (
        build_hifi_change_bundle,
        validate_hifi_candidate,
    )

    root, inventory, source, _ = nested_case(tmp_path)
    panel = root / inventory.target.component_relative_path
    panel.write_text(
        '<component size="750,420"><displayList>'
        '<component id="a" name="Delegate" src="sharedbtn1" xy="10,20"/>'
        '<component id="b" name="Reward" src="sharedbtn1" xy="200,100"/>'
        "</displayList>"
        '<transition name="pop">'
        '<item time="0" type="XY" target="a" value="10,20" tween="true" time2="12" value2="30,40"/>'
        "</transition></component>"
    )
    inventory = inspect_component_tree(root, inventory.target)
    draft = build_mapping(inventory, source)
    nodes = source.top_level_nodes[0].children
    chosen = {"a:bg": nodes[0].id, "b:bg": nodes[1].id}
    items = tuple(
        item.model_copy(update={"action": "retarget", "figma_node_id": chosen[item.old_object_id]})
        if item.old_object_id in chosen
        else item.model_copy(update={"action": "keep_old" if item.old_object_id else "exception"})
        for item in draft.items
    )
    mapping = draft.model_copy(update={"items": items, "unresolved_count": 0})

    bundle = build_hifi_change_bundle(root, inventory, source, mapping)
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    apply_bundle(candidate, bundle)
    untouched = tmp_path / "candidate-untouched"
    shutil.copytree(candidate, untouched)

    moved = candidate / inventory.target.component_relative_path
    document = etree.parse(str(moved))
    document.xpath('./displayList/component[@id="a"]')[0].set("xy", "30,40")
    document.write(str(moved), xml_declaration=True, encoding="utf-8")

    review = validate_hifi_candidate(root, candidate, inventory, mapping, session_id="d" * 32)
    assert review.protected_checks_passed
    stale = [w for w in review.warnings if w.startswith("transition 关键帧仍引用换皮前几何")]
    assert stale, review.warnings
    assert "pop:a:XY value=10,20" in stale[0]
    assert "value2=30,40" not in stale[0]

    baseline = validate_hifi_candidate(root, untouched, inventory, mapping, session_id="e" * 32)
    assert not any(
        w.startswith("transition 关键帧仍引用换皮前几何") for w in baseline.warnings
    )


def _list_template_project(tmp_path):
    from figma_to_fgui.hifi_replacement_models import HifiTargetRef

    root = tmp_path / "proj"
    (root / "assets" / "Pkg" / "Panel").mkdir(parents=True)
    (root / "assets" / "Pkg" / "Component").mkdir(parents=True)
    (root / "assets" / "Pkg" / "package.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?><package id="pkgaa1" name="Pkg">'
        "<resources>"
        '<component id="panel1" name="Panel_One.xml" path="/Panel/"/>'
        '<component id="item1" name="Item_Row.xml" path="/Component/"/>'
        "</resources></package>",
        encoding="utf-8",
    )
    (root / "assets" / "Pkg" / "Panel" / "Panel_One.xml").write_text(
        '<component size="400,300"><displayList>'
        '<list id="lst" name="records" xy="20,30" size="360,240" defaultItem="ui://pkgaa1item1"/>'
        "</displayList></component>",
        encoding="utf-8",
    )
    (root / "assets" / "Pkg" / "Component" / "Item_Row.xml").write_text(
        '<component size="360,110"><controller name="state" pages="0,win,1,fail" selected="0"/>'
        "<displayList>"
        '<graph id="bg" name="card" xy="0,0" size="360,110" type="rect" fillColor="#fff0e0d0"/>'
        '<text id="txt" name="txt_name" xy="120,20" size="200,40" text="Row"/>'
        "</displayList></component>",
        encoding="utf-8",
    )
    target = HifiTargetRef(
        project_id="p",
        project_fingerprint="f" * 64,
        package_id="pkgaa1",
        package_name="Pkg",
        directory="Panel",
        component_id="panel1",
        component_name="Panel_One",
        component_relative_path="assets/Pkg/Panel/Panel_One.xml",
    )
    return root, target


def test_list_default_item_template_children_enter_inventory(tmp_path) -> None:
    from figma_to_fgui.hifi_nested import inspect_component_tree

    root, target = _list_template_project(tmp_path)
    inventory = inspect_component_tree(root, target)
    ids = [o.object_id for o in inventory.objects]
    assert "lst:bg" in ids and "lst:txt" in ids
    template = next(o for o in inventory.objects if o.object_id == "lst:bg")
    assert template.component_relative_path == "assets/Pkg/Component/Item_Row.xml"
    assert (template.x, template.y) == (20.0, 30.0)
    assert template.instance_path == ("lst",)
    assert "list_item_template" in template.behavior_roles
    assert template.behavior_protected
    assert "shared_list_template_requires_user_decision" not in template.write_blockers
    list_object = next(o for o in inventory.objects if o.object_id == "lst")
    assert list_object.structural_only


def test_shared_list_template_carries_user_decision_blocker(tmp_path) -> None:
    from figma_to_fgui.hifi_nested import inspect_component_tree

    root, target = _list_template_project(tmp_path)
    (root / "assets" / "Pkg" / "Panel" / "Panel_Two.xml").write_text(
        '<component size="400,300"><displayList>'
        '<list id="lst2" name="more" xy="10,10" size="360,240" defaultItem="ui://pkgaa1item1"/>'
        "</displayList></component>",
        encoding="utf-8",
    )
    package = root / "assets" / "Pkg" / "package.xml"
    package.write_text(
        package.read_text(encoding="utf-8").replace(
            "</resources>",
            '<component id="panel2" name="Panel_Two.xml" path="/Panel/"/></resources>',
        ),
        encoding="utf-8",
    )
    inventory = inspect_component_tree(root, target)
    template = next(o for o in inventory.objects if o.object_id == "lst:bg")
    assert "shared_list_template_requires_user_decision" in template.write_blockers


def test_list_row_template_visuals_are_reskinnable_in_place(tmp_path) -> None:
    from lxml import etree

    from figma_to_fgui.apply import apply_bundle
    from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
    from figma_to_fgui.hifi_mapping import build_mapping
    from figma_to_fgui.hifi_nested import inspect_component_tree
    from figma_to_fgui.hifi_patch import (
        build_hifi_change_bundle,
        validate_hifi_candidate,
    )
    from figma_to_fgui.models import Bounds

    root, target = _list_template_project(tmp_path)
    inventory = inspect_component_tree(root, target)
    node = SelectionNode(
        id="shape-row",
        name="card",
        type="RECTANGLE",
        bounds=Bounds(x=20, y=30, width=360, height=110),
        properties={"fguiGraph": {"shape": "rect", "fillColor": "#ff123456", "lineSize": 0}},
    )
    source = SelectionManifest(
        version=1,
        display_name="PSD",
        top_level_nodes=(
            SelectionNode(
                id="psd-root:test",
                name="PSD",
                type="FRAME",
                bounds=Bounds(x=0, y=0, width=400, height=300),
                children=(node,),
            ),
        ),
    )
    draft = build_mapping(inventory, source)
    items = tuple(
        item.model_copy(update={"action": "retarget", "figma_node_id": node.id})
        if item.old_object_id == "lst:bg"
        else item.model_copy(update={"action": "keep_old" if item.old_object_id else "exception"})
        for item in draft.items
    )
    mapping = draft.model_copy(update={"items": items, "unresolved_count": 0})

    bundle = build_hifi_change_bundle(root, inventory, source, mapping)
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    apply_bundle(candidate, bundle)
    template = etree.parse(str(candidate / "assets/Pkg/Component/Item_Row.xml"))
    assert template.xpath("string(./displayList/graph/@fillColor)") == "#ff123456"
    review = validate_hifi_candidate(root, candidate, inventory, mapping, session_id="f" * 32)
    assert review.protected_checks_passed
    assert review.approvable


def test_shared_list_template_write_is_fail_closed(tmp_path) -> None:
    import pytest

    from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
    from figma_to_fgui.hifi_mapping import build_mapping
    from figma_to_fgui.hifi_nested import inspect_component_tree
    from figma_to_fgui.hifi_patch import build_hifi_change_bundle
    from figma_to_fgui.models import Bounds

    root, target = _list_template_project(tmp_path)
    (root / "assets" / "Pkg" / "Panel" / "Panel_Two.xml").write_text(
        '<component size="400,300"><displayList>'
        '<list id="lst2" name="more" xy="10,10" size="360,240" defaultItem="ui://pkgaa1item1"/>'
        "</displayList></component>",
        encoding="utf-8",
    )
    package = root / "assets" / "Pkg" / "package.xml"
    package.write_text(
        package.read_text(encoding="utf-8").replace(
            "</resources>",
            '<component id="panel2" name="Panel_Two.xml" path="/Panel/"/></resources>',
        ),
        encoding="utf-8",
    )
    inventory = inspect_component_tree(root, target)
    node = SelectionNode(
        id="shape-row",
        name="card",
        type="RECTANGLE",
        bounds=Bounds(x=20, y=30, width=360, height=110),
        properties={"fguiGraph": {"shape": "rect", "fillColor": "#ff123456", "lineSize": 0}},
    )
    source = SelectionManifest(
        version=1,
        display_name="PSD",
        top_level_nodes=(
            SelectionNode(
                id="psd-root:test",
                name="PSD",
                type="FRAME",
                bounds=Bounds(x=0, y=0, width=400, height=300),
                children=(node,),
            ),
        ),
    )
    draft = build_mapping(inventory, source)
    items = tuple(
        item.model_copy(update={"action": "retarget", "figma_node_id": node.id})
        if item.old_object_id == "lst:bg"
        else item.model_copy(update={"action": "keep_old" if item.old_object_id else "exception"})
        for item in draft.items
    )
    mapping = draft.model_copy(update={"items": items, "unresolved_count": 0})
    with pytest.raises(Exception, match="geometry_unverified|user_decision"):
        build_hifi_change_bundle(root, inventory, source, mapping)


def test_isolated_variant_frame_reanchors_to_psd_group(tmp_path) -> None:
    from lxml import etree

    from figma_to_fgui.apply import apply_bundle
    from figma_to_fgui.figma_selection import SelectionNode
    from figma_to_fgui.hifi_patch import build_hifi_change_bundle
    from figma_to_fgui.models import Bounds

    root, inventory, source, mapping = nested_case(tmp_path)
    frame = source.top_level_nodes[0]

    def group(node_id, x, y, width, height, child_id):
        return SelectionNode(
            id=node_id, name="Group", type="GROUP",
            bounds=Bounds(x=x, y=y, width=width, height=height),
            children=(SelectionNode(
                id=child_id, name="Background", type="RECTANGLE",
                bounds=Bounds(x=x + 2, y=y + 2, width=width - 4, height=height - 4),
                properties={"fguiGraph": {"shape": "rect", "fillColor": "#ff445566", "lineSize": 0}},
            ),),
        )

    groups = (group("grp-a", 30, 60, 150, 50, "rect-a"),
              group("grp-b", 200, 100, 120, 44, "rect-b"))
    source = source.model_copy(
        update={"top_level_nodes": (frame.model_copy(update={"children": groups}),)}
    )
    chosen = {"a": "grp-a", "a:bg": "rect-a", "b": "grp-b", "b:bg": "rect-b"}
    items = tuple(
        item.model_copy(update={
            "action": "accept" if item.old_object_id in {"a", "b"} else "retarget",
            "figma_node_id": chosen[item.old_object_id],
        })
        if item.old_object_id in chosen
        else item.model_copy(update={"action": "keep_old" if item.old_object_id else "exception"})
        for item in mapping.items
    )
    mapping = mapping.model_copy(update={"items": items, "unresolved_count": 0})

    bundle = build_hifi_change_bundle(root, inventory, source, mapping)
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    apply_bundle(candidate, bundle)

    parent = etree.parse(str(candidate / inventory.target.component_relative_path))
    instance_a = parent.xpath("./displayList/component[@id='a']")[0]
    instance_b = parent.xpath("./displayList/component[@id='b']")[0]
    assert instance_a.get("xy") == "20,30"
    assert instance_b.get("xy") == "202,102"
    assert instance_b.get("size") == "116,40"

    variants = list((candidate / "assets/MyVillage/Common").glob("Button_Common__hifi_*.xml"))
    assert len(variants) == 2
    by_size = {etree.parse(str(path)).getroot().get("size"): path for path in variants}
    moved = etree.parse(str(by_size[instance_a.get("size")]))
    assert moved.getroot().get("size") == instance_a.get("size")
    assert moved.xpath("string(./displayList/graph/@xy)") == "12,32"
    assert moved.xpath("string(./displayList/graph/@size)") == "146,46"
    assert moved.xpath("string(./displayList/text/@xy)") == "0,0"
    stayed = etree.parse(str(by_size["116,40"]))
    assert stayed.xpath("string(./displayList/graph/@xy)") == "0,0"
    assert stayed.xpath("string(./displayList/text/@xy)") == "8,8"


def test_variant_frame_ignores_transparent_layout_proxies(tmp_path) -> None:
    from lxml import etree

    from figma_to_fgui.hifi_nested import _normalize_variant_frame

    path = tmp_path / "Button.xml"
    path.write_text(
        '<component size="412,140" extention="Button"><displayList>'
        '<graph id="proxy" name="autosize_provt" xy="0,0" size="402,132"/>'
        '<image id="bg" name="bg" xy="9,5" size="403,135" fileName="a.png"/>'
        '<text id="title" name="title" xy="91,29" size="311,60" text="t"/>'
        '</displayList><Button downEffect="scale" downEffectValue=".99"/></component>',
        encoding="utf-8",
    )
    root = etree.parse(str(path)).getroot()
    instance = etree.Element("component")
    instance.set("xy", "653,1757")
    instance.set("size", "412,140")

    assert _normalize_variant_frame(root, instance, 653.0, 1757.0)

    assert root.get("size") == "403,135"
    assert instance.get("size") == "403,135"
    assert instance.get("xy") == "662,1762"
    boxes = {
        child.get("id"): child.get("xy")
        for child in root.xpath("./displayList/*")
    }
    assert boxes["bg"] == "0,0"
    assert boxes["title"] == "82,24"
    assert boxes["proxy"] == "-9,-5"

    filled = tmp_path / "Filled.xml"
    filled.write_text(
        '<component size="402,132"><displayList>'
        '<graph id="shadow" name="shadow" xy="0,0" size="402,132" fillColor="#80120503"/>'
        '<image id="bg" name="bg" xy="9,5" size="300,100" fileName="a.png"/>'
        '</displayList></component>',
        encoding="utf-8",
    )
    filled_root = etree.parse(str(filled)).getroot()
    filled_instance = etree.Element("component")
    filled_instance.set("xy", "10,10")
    filled_instance.set("size", "402,132")
    _normalize_variant_frame(filled_root, filled_instance, 10.0, 10.0)
    assert filled_root.get("size") == "402,132"
    assert filled_instance.get("xy") == "10,10"


def test_variant_frame_relations_are_removed_and_candidate_still_validates(tmp_path) -> None:
    from lxml import etree

    from figma_to_fgui.apply import apply_bundle
    from figma_to_fgui.figma_selection import SelectionNode
    from figma_to_fgui.hifi_nested import inspect_component_tree
    from figma_to_fgui.hifi_patch import build_hifi_change_bundle, validate_hifi_candidate
    from figma_to_fgui.models import Bounds

    root, inventory, source, mapping = nested_case(tmp_path)
    child = root / "assets/MyVillage/Common/Button_Common.xml"
    child.write_text(
        '<component size="120,44" extention="Button">'
        '<controller name="enabled" pages="0,on,1,off" selected="0"/>'
        '<displayList><graph id="bg" name="Background" xy="0,0" size="120,44" '
        'type="rect" fillColor="#ff112233">'
        '<gearDisplay controller="enabled" pages="0"/>'
        '<relation target="" sidePair="center-center,middle-middle"/></graph>'
        '<text id="title" name="title" xy="10,10" size="90,24" text="Default">'
        '<relation target="" sidePair="left-left,top-top"/></text></displayList>'
        '<Button downEffect="scale" downEffectValue=".99"/></component>'
    )
    inventory = inspect_component_tree(root, inventory.target)
    frame = source.top_level_nodes[0]

    def group(node_id, x, y, width, height, child_id):
        return SelectionNode(
            id=node_id, name="Group", type="GROUP",
            bounds=Bounds(x=x, y=y, width=width, height=height),
            children=(SelectionNode(
                id=child_id, name="Background", type="RECTANGLE",
                bounds=Bounds(x=x + 2, y=y + 2, width=width - 4, height=height - 4),
                properties={"fguiGraph": {"shape": "rect", "fillColor": "#ff445566", "lineSize": 0}},
            ),),
        )

    groups = (group("grp-a", 30, 60, 150, 50, "rect-a"),
              group("grp-b", 200, 100, 120, 44, "rect-b"))
    source = source.model_copy(
        update={"top_level_nodes": (frame.model_copy(update={"children": groups}),)}
    )
    chosen = {"a": "grp-a", "a:bg": "rect-a", "b": "grp-b", "b:bg": "rect-b"}
    items = tuple(
        item.model_copy(update={
            "action": "accept" if item.old_object_id in {"a", "b"} else "retarget",
            "figma_node_id": chosen[item.old_object_id],
        })
        if item.old_object_id in chosen
        else item.model_copy(update={"action": "keep_old" if item.old_object_id else "exception"})
        for item in mapping.items
    )
    mapping = mapping.model_copy(update={"items": items, "unresolved_count": 0})

    bundle = build_hifi_change_bundle(root, inventory, source, mapping)
    candidate = tmp_path / "candidate"
    shutil.copytree(root, candidate)
    apply_bundle(candidate, bundle)

    review = validate_hifi_candidate(root, candidate, inventory, mapping, session_id="e" * 32)
    assert review.protected_checks_passed

    variants = list((candidate / "assets/MyVillage/Common").glob("Button_Common__hifi_*.xml"))
    assert variants
    for path in variants:
        document = etree.parse(str(path))
        assert document.xpath("./displayList/*/relation[not(@target) or @target='']") == []
    assert (candidate / "assets/MyVillage/Common/Button_Common.xml").read_bytes() == child.read_bytes()
