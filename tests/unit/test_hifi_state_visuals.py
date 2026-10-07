from lxml import etree
from PIL import Image
from test_hifi_nested import nested_case

from figma_to_fgui.hifi_nested import inspect_component_tree
from figma_to_fgui.hifi_state_visuals import _palette, _state_roles, derive_state_nodes


def test_state_roles_require_a_complete_controller_scoped_visual_definition():
    document = etree.fromstring(
        '<component><controller name="badge" pages="0,Normal,1,Num,2,New"/>'
        '<displayList><image id="a"><gearDisplay controller="badge" pages="0"/></image>'
        '<text id="b"><gearDisplay controller="badge" pages="1,2"/></text>'
        '</displayList></component>'
    )
    assert _state_roles(document) == {"a": "normal", "b": "text"}
    document.xpath("./displayList/image")[0].find("gearDisplay").set("controller", "other")
    assert _state_roles(document) is None


def test_derived_state_art_is_new_and_only_for_eligible_components(tmp_path):
    root, inventory, _, _ = nested_case(tmp_path)
    child = root / "assets/MyVillage/Common/Button_Common.xml"
    child.write_text(
        '<component size="120,44"><controller name="badge" pages="0,Normal,1,Num,2,New"/>'
        '<displayList><image id="bg" name="bg" xy="0,0" size="40,40" src="old">'
        '<gearDisplay controller="badge" pages="0"/></image>'
        '<text id="title" name="title" xy="40,10" size="70,24" text="99">'
        '<gearDisplay controller="badge" pages="1,2"/></text></displayList></component>',
        encoding="utf-8",
    )
    inventory = inspect_component_tree(root, inventory.target)
    style = tmp_path / "style.png"
    image = Image.new("RGBA", (60, 20), (249, 202, 129, 255))
    for x in range(20):
        for y in range(20):
            image.putpixel((x, y), (253, 243, 233, 255))
    image.save(style)
    nodes, resources, blocked = derive_state_nodes(root, inventory, style, tmp_path / "generated")
    assert blocked == ()
    assert len(nodes) == 4  # two instances, each with an image and dynamic text
    assert len(resources) == 1  # shared definition has one new image asset
    assert {node.properties["generatedStateRole"] for node in nodes} == {"normal", "text"}
    assert all(node.properties["generatedStateOwner"] for node in nodes)
    assert (tmp_path / "generated" / resources[0].key).read_bytes().startswith(b"\x89PNG")
    assert _palette(style)[0] != _palette(style)[1]

def test_sibling_states_derive_from_family_colour_variant(tmp_path):
    """When the base state matched a new PSD raster, sibling states inherit
    the old colour relationship instead of a procedural placeholder."""
    from PIL import Image, ImageDraw

    root, inventory, _, _ = nested_case(tmp_path)
    child = root / "assets/MyVillage/Common/Button_Common.xml"
    child.write_text(
        '<component size="120,44"><controller name="badge" pages="0,Normal,1,Num,2,New"/>'
        '<displayList><image id="bg" name="bg" xy="0,0" size="40,40" src="bgold001">'
        '<gearDisplay controller="badge" pages="0"/></image>'
        '<image id="num" name="num" xy="0,0" size="40,40" src="bgnum001">'
        '<gearDisplay controller="badge" pages="1"/></image>'
        '<image id="new" name="new" xy="0,0" size="40,40" src="bgwht001">'
        '<gearDisplay controller="badge" pages="2"/></image></displayList></component>',
        encoding="utf-8",
    )
    image_dir = root / "assets/MyVillage/Common/Img"
    image_dir.mkdir(parents=True, exist_ok=True)

    def badge(path: str, fill: tuple[int, int, int]) -> None:
        art = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        draw = ImageDraw.Draw(art)
        draw.ellipse((2, 2, 38, 38), fill=(*fill, 255))
        draw.ellipse((10, 10, 30, 30), fill=(255, 255, 255, 255))
        art.save(path)

    badge(str(image_dir / "old.png"), (20, 160, 90))
    badge(str(image_dir / "num.png"), (200, 160, 30))
    Image.new("RGBA", (40, 40), (255, 255, 255, 255)).save(
        str(image_dir / "white.png")
    )
    package = root / "assets/MyVillage/package.xml"
    package.write_text(
        package.read_text(encoding="utf-8").replace(
            "</resources>",
            '<image id="bgold001" name="old.png" path="/Common/Img/" atlas="0"/>'
            '<image id="bgnum001" name="num.png" path="/Common/Img/" atlas="0"/>'
            '<image id="bgwht001" name="white.png" path="/Common/Img/" atlas="0"/>'
            "</resources>",
        ),
        encoding="utf-8",
    )
    inventory = inspect_component_tree(root, inventory.target)
    style = tmp_path / "style.png"
    style_image = Image.new("RGBA", (60, 20), (249, 202, 129, 255))
    for x in range(20):
        for y in range(20):
            style_image.putpixel((x, y), (253, 243, 233, 255))
    style_image.save(style)

    new_base = tmp_path / "new_base.png"
    badge(str(new_base), (30, 60, 200))

    bg_object = next(
        item for item in inventory.objects if item.local_object_id == "bg"
    )
    nodes, resources, blocked = derive_state_nodes(
        root, inventory, style, tmp_path / "generated",
        variant_sources={bg_object.object_id: new_base},
    )
    assert all(warning.code == "state_variant_guard" for warning in blocked)
    by_owner = {
        node.properties["generatedStateOwner"]: node for node in nodes
    }
    num_node = by_owner[next(
        item.object_id for item in inventory.objects
        if item.local_object_id == "num"
    )]
    assert num_node.resource_keys and num_node.resource_keys[0].startswith(
        "state-variant-"
    )
    derived = Image.open(
        tmp_path / "generated" / num_node.resource_keys[0]
    ).convert("RGBA")
    # The old relationship shifted green -> gold; applied to a blue base the
    # derived sibling must stay a structured, non-placeholder colour variant.
    pixels = [p for p in derived.getdata() if p[3] > 200]
    assert pixels
    reds = [p[0] for p in pixels]
    assert max(reds) - min(reds) > 40  # structure preserved, not flat colour
    new_node = by_owner[next(
        item.object_id for item in inventory.objects
        if item.local_object_id == "new"
    )]
    # The solid-white sibling collapses structure; it must NOT adopt the
    # variant path and must fall back to the placeholder.
    assert not new_node.resource_keys[0].startswith("state-variant-")
    assert any(
        "#new" in warning.message and "遮罩重合度" in warning.message
        for warning in blocked
    ), blocked
    num_ids = [
        item.object_id for item in inventory.objects
        if item.local_object_id == "num"
    ]
    assert len(num_ids) > 1
    sibling_keys = {
        by_owner[object_id].resource_keys[0] for object_id in num_ids
    }
    assert len(sibling_keys) == 1, sibling_keys
    base_ids = [
        item.object_id for item in inventory.objects
        if item.local_object_id == "bg"
    ]
    base_keys = {
        by_owner[object_id].resource_keys[0] for object_id in base_ids
    }
    assert base_keys == {new_base.name}, base_keys
