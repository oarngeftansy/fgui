from types import SimpleNamespace as NS

import pytest
from PIL import Image


def shadow(**changes):
    args = {
        "kind": "DropShadow", "enabled": True, "blend_mode": "normal", "opacity": 50.0,
        "color_rgba": (0.,0.,0.,1.), "size": 0., "angle": 0., "distance": 3.,
        "spread": None, "choke": 0., "position": None,
    }
    args.update(changes)
    return NS(**args)


def test_hard_shadow_extends_alpha_without_wrapping_or_filling_transparency():
    from figma_to_fgui.psd_effect_render import composite_hard_shadow

    body = Image.new("RGBA", (12, 10), (0, 0, 0, 0))
    body.paste((255, 200, 100, 255), (5, 3, 8, 7))
    result = composite_hard_shadow(body, shadow())
    assert result.getpixel((3, 4)) == (0, 0, 0, 128)
    assert result.getpixel((6, 4)) == (255, 200, 100, 255)
    assert result.getpixel((11, 4))[3] == 0
    assert result.getpixel((3, 0))[3] == 0


@pytest.mark.parametrize("change", [{"size": 2.0}, {"choke": 4.0}, {"blend_mode": "multiply"}])
def test_shadow_rejects_features_it_cannot_render(change):
    from figma_to_fgui.psd_effect_render import composite_hard_shadow

    with pytest.raises(ValueError, match="unsupported"):
        composite_hard_shadow(Image.new("RGBA", (10, 10)), shadow(**change))


def test_owned_visual_requires_an_exact_partition_and_keeps_text_separate():
    from figma_to_fgui.psd_effect_render import validate_owned_partition

    leaves = [
        NS(id="bg", kind="shape", effective_visible=True),
        NS(id="label", kind="type", effective_visible=True),
    ]
    validate_owned_partition(leaves, frozenset({"bg"}), frozenset({"label"}))
    for owned, retained in [
        ({"bg"}, set()),
        ({"bg", "label"}, set()),
        ({"bg", "elsewhere"}, {"label"}),
        ({"bg"}, {"bg", "label"}),
    ]:
        with pytest.raises(ValueError, match="ownership"):
            validate_owned_partition(leaves, frozenset(owned), frozenset(retained))


def test_owned_partition_ignores_only_nonpainting_empty_groups():
    from figma_to_fgui.psd_effect_render import validate_owned_partition

    empty = NS(id="empty", kind="group", effective_visible=True, has_effects=False,
               has_pixel_mask=False, has_vector_mask=False, clipping=False,
               opacity=255, blend_mode="pass_through")
    body = NS(id="body", kind="shape", effective_visible=True)
    validate_owned_partition([empty, body], frozenset({"body"}), frozenset())
    empty.has_pixel_mask = True
    validate_owned_partition([empty, body], frozenset({"body"}), frozenset())
    empty.has_effects = True
    with pytest.raises(ValueError, match="ownership"):
        validate_owned_partition([empty, body], frozenset({"body"}), frozenset())


def test_leaf_inherits_opaque_normal_color_overlay_without_losing_alpha():
    from figma_to_fgui.psd_effect_render import render_leaf

    effect = NS(
        enabled=True,
        opacity=100.0,
        blend_mode=b"norm",
        color={b"Rd  ": 250.0, b"Grn ": 180.0, b"Bl  ": 70.0},
    )

    class Effects(list):
        enabled = True

        def find(self, name):
            return iter(self if name == "ColorOverlay" else ())

    parent = NS(
        parent=None,
        opacity=255,
        clipping=False,
        blend_mode=NS(value=b"pass"),
        has_mask=lambda: False,
        has_vector_mask=lambda: False,
        effects=Effects([effect]),
    )
    leaf = NS(parent=parent, composite=lambda **kw: Image.new("RGBA", (3, 3), (255, 0, 0, 128)))
    metadata = NS(bounds=(0, 0, 3, 3), effects=())
    image, _ = render_leaf(leaf, metadata)
    assert image.getpixel((1, 1)) == (250, 180, 70, 128)
    parent.opacity = 128
    with pytest.raises(ValueError, match="context"):
        render_leaf(leaf, metadata)
