from types import SimpleNamespace

from psd_tools.constants import Tag


def shape(**changes):
    orig = SimpleNamespace(invalidated=False, origin_type=1, bbox=(0, 0, 100, 50))
    blocks = {Tag.SOLID_COLOR_SHEET_SETTING: {b"Clr ": {b"Rd  ": 17, b"Grn ": 34, b"Bl  ": 51}}}
    layer = SimpleNamespace(
        kind="shape",
        clipping=False,
        opacity=255,
        parent=None,
        bbox=(0, 0, 100, 50),
        stroke=None,
        origination=[orig],
        blend_mode=SimpleNamespace(value=b"norm"),
        vector_mask=SimpleNamespace(inverted=False, paths=[object()]),
        has_effects=lambda: False,
        has_mask=lambda: False,
        tagged_blocks=SimpleNamespace(get_data=lambda key, default=None: blocks.get(key, default)),
    )
    for key, value in changes.items():
        setattr(layer, key, value)
    return layer


def test_simple_shape_exports_native_graph_without_bitmap_or_extra_nodes():
    from figma_to_fgui.psd_native_graphs import native_graph_for_layer

    assert native_graph_for_layer(shape()) == {
        "shape": "rect",
        "fillColor": "#ff112233",
        "lineSize": 0,
    }


def test_shape_effects_and_parent_effects_never_disappear_in_native_conversion():
    from figma_to_fgui.psd_native_graphs import native_graph_for_layer

    assert native_graph_for_layer(shape(has_effects=lambda: True)) is None
    assert native_graph_for_layer(shape(parent=shape(has_effects=lambda: True))) is None
    assert native_graph_for_layer(shape(clipping=True)) is None
    assert native_graph_for_layer(shape(origination=[])) is None


def test_moved_or_composite_shape_is_not_misrepresented_as_simple_rectangle():
    from figma_to_fgui.psd_native_graphs import native_graph_for_layer

    assert native_graph_for_layer(shape(bbox=(2, 0, 102, 50))) is None
    assert (
        native_graph_for_layer(
            shape(vector_mask=SimpleNamespace(inverted=False, paths=[object(), object()]))
        )
        is None
    )
