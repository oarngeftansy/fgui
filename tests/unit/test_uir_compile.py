from figma_to_fgui.models import Bounds, NormalizedNode
from figma_to_fgui.uir_compile import compile_uir


def sample_roots() -> tuple[NormalizedNode, ...]:
    return (
        NormalizedNode(
            id="frame",
            name="村庄升阶",
            type="FRAME",
            bounds=Bounds(x=100, y=200, width=1080, height=1923),
            children=(
                NormalizedNode(
                    id="title",
                    name="标题",
                    type="TEXT",
                    bounds=Bounds(x=130, y=233, width=239, height=40),
                    text="Village Ascend",
                    source_order=0,
                    raw_style={"fontSize": 36, "textAlignHorizontal": "LEFT"},
                ),
            ),
        ),
    )


def test_compile_preserves_order_source_facts_and_resolved_geometry() -> None:
    document = compile_uir(
        sample_roots(), source_revision="a" * 64, selection_id="selection_village"
    )
    root = document.nodes[document.roots[0]]
    child = document.nodes[root.children[0]]
    assert root.source.name == "村庄升阶"
    assert child.source.name == "标题"
    assert child.geometry.resolved_bounds == Bounds(
        x=30, y=33, width=239, height=40
    )
    assert child.text == {
        "content": "Village Ascend",
        "style": {"fontSize": 36, "textAlignHorizontal": "LEFT"},
    }


def test_compile_is_deterministic_for_the_same_inputs() -> None:
    first = compile_uir(
        sample_roots(), source_revision="a" * 64, selection_id="same"
    )
    second = compile_uir(
        sample_roots(), source_revision="a" * 64, selection_id="same"
    )
    assert first == second
    assert first.document_id == second.document_id


def test_compile_preserves_child_order_not_source_order_sorting() -> None:
    root = sample_roots()[0]
    later = root.children[0].model_copy(update={"id": "later", "source_order": 99})
    earlier = root.children[0].model_copy(update={"id": "earlier", "source_order": 0})
    document = compile_uir(
        (root.model_copy(update={"children": (later, earlier)}),),
        source_revision="a" * 64,
        selection_id="ordered",
    )
    compiled_root = document.nodes[document.roots[0]]
    assert [document.nodes[item].source.node_id for item in compiled_root.children] == [
        "later",
        "earlier",
    ]
