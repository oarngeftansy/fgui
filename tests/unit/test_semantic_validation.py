from figma_to_fgui.models import Bounds, NormalizedNode, Severity
from figma_to_fgui.semantic_models import ReparentSuggestion, SemanticDecision, SemanticResponse
from figma_to_fgui.semantic_validation import validate_semantic_response


def _tree() -> tuple[NormalizedNode, ...]:
    safe_button = NormalizedNode(
        id="safe-button",
        name="Safe button",
        type="RECTANGLE",
        bounds=Bounds(x=10, y=10, width=40, height=20),
    )
    container = NormalizedNode(
        id="container",
        name="Container",
        type="FRAME",
        bounds=Bounds(x=0, y=0, width=100, height=100),
        children=(safe_button,),
    )
    return (container,)


def test_rejects_unknown_nodes_cycles_and_out_of_bounds_reparent() -> None:
    response = SemanticResponse(
        decisions=(
            SemanticDecision(node_id="safe-button", semantic_type="Button", confidence=0.9),
            SemanticDecision(node_id="missing", semantic_type="Button", confidence=0.9),
            SemanticDecision(
                node_id="container",
                semantic_type="Panel",
                confidence=0.9,
                reparent=ReparentSuggestion(new_parent="safe-button"),
            ),
            SemanticDecision(
                node_id="safe-button",
                semantic_type="Button",
                confidence=0.9,
                reparent=ReparentSuggestion(new_parent="missing"),
            ),
        )
    )

    decisions, diagnostics = validate_semantic_response(_tree(), response)

    assert {item.node_id for item in decisions} == {"safe-button"}
    assert {item.code for item in diagnostics} == {
        "semantic.unknown_node",
        "semantic.reparent_cycle",
        "semantic.reparent_outside",
    }
    assert all(item.severity is Severity.WARNING for item in diagnostics)


def test_rejects_roles_that_do_not_belong_to_the_decision_node() -> None:
    response = SemanticResponse(
        decisions=(
            SemanticDecision(
                node_id="safe-button",
                semantic_type="Button",
                confidence=0.9,
                children_roles={"container": "title"},
            ),
        )
    )

    decisions, diagnostics = validate_semantic_response(_tree(), response)

    assert decisions == ()
    assert [item.code for item in diagnostics] == ["semantic.invalid_child_role"]
    assert diagnostics[0].severity is Severity.WARNING
