from figma_to_fgui.models import Bounds, NormalizedNode, Severity
from figma_to_fgui.semantic_models import ReparentSuggestion, SemanticDecision, SemanticResponse
from figma_to_fgui.semantic_validation import validate_semantic_response


def _tree() -> tuple[NormalizedNode, ...]:
    title = NormalizedNode(
        id="title",
        name="Title",
        type="TEXT",
        bounds=Bounds(x=12, y=12, width=20, height=8),
    )
    icon = NormalizedNode(
        id="icon",
        name="Icon",
        type="RECTANGLE",
        bounds=Bounds(x=35, y=12, width=8, height=8),
    )
    safe_button = NormalizedNode(
        id="safe-button",
        name="Safe button",
        type="RECTANGLE",
        bounds=Bounds(x=10, y=10, width=40, height=20),
        children=(title, icon),
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
                node_id="title",
                semantic_type="Label",
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


def test_roles_are_closed_by_semantic_type_and_valid_button_roles_are_accepted() -> None:
    valid = SemanticResponse(
        decisions=(
            SemanticDecision(
                node_id="safe-button",
                semantic_type="Button",
                confidence=0.9,
                children_roles={"title": "title", "icon": "icon"},
            ),
        )
    )
    invalid = SemanticResponse(
        decisions=(
            SemanticDecision(
                node_id="safe-button",
                semantic_type="Button",
                confidence=0.9,
                children_roles={"title": "bar"},
            ),
        )
    )

    accepted, valid_diagnostics = validate_semantic_response(_tree(), valid)
    rejected, invalid_diagnostics = validate_semantic_response(_tree(), invalid)

    assert [item.node_id for item in accepted] == ["safe-button"]
    assert valid_diagnostics == ()
    assert rejected == ()
    assert [item.code for item in invalid_diagnostics] == ["semantic.invalid_child_role"]


def test_state_pages_are_limited_to_supported_types_and_safe_page_names() -> None:
    valid = SemanticResponse(
        decisions=(
            SemanticDecision(
                node_id="safe-button",
                semantic_type="Button",
                confidence=0.9,
                state_pages={"0": "normal", "1": "pressed"},
            ),
        )
    )
    unsupported = SemanticResponse(
        decisions=(
            SemanticDecision(
                node_id="title",
                semantic_type="Text",
                confidence=0.9,
                state_pages={"0": "normal"},
            ),
        )
    )
    malformed = SemanticResponse(
        decisions=(
            SemanticDecision(
                node_id="safe-button",
                semantic_type="Button",
                confidence=0.9,
                state_pages={"first": "bad-name!"},
            ),
        )
    )

    accepted, valid_diagnostics = validate_semantic_response(_tree(), valid)
    unsupported_decisions, unsupported_diagnostics = validate_semantic_response(
        _tree(), unsupported
    )
    malformed_decisions, malformed_diagnostics = validate_semantic_response(_tree(), malformed)

    assert [item.node_id for item in accepted] == ["safe-button"]
    assert valid_diagnostics == ()
    assert unsupported_decisions == ()
    assert [item.code for item in unsupported_diagnostics] == [
        "semantic.unsupported_state_pages"
    ]
    assert malformed_decisions == ()
    assert [item.code for item in malformed_diagnostics] == ["semantic.invalid_state_page"]


def test_slider_accepts_structural_roles_and_state_pages() -> None:
    response = SemanticResponse(
        decisions=(
            SemanticDecision(
                node_id="safe-button",
                semantic_type="Slider",
                confidence=0.9,
                children_roles={"title": "bar", "icon": "grip"},
                state_pages={"0": "normal", "1": "disabled"},
            ),
        )
    )

    decisions, diagnostics = validate_semantic_response(_tree(), response)

    assert [item.node_id for item in decisions] == ["safe-button"]
    assert diagnostics == ()


def test_rejects_every_decision_for_a_duplicated_node_id() -> None:
    response = SemanticResponse(
        decisions=(
            SemanticDecision(node_id="safe-button", semantic_type="Button", confidence=0.9),
            SemanticDecision(node_id="safe-button", semantic_type="Label", confidence=0.8),
        )
    )

    decisions, diagnostics = validate_semantic_response(_tree(), response)

    assert decisions == ()
    assert [item.code for item in diagnostics] == ["semantic.duplicate_decision"]
    assert diagnostics[0].severity is Severity.WARNING


def test_rejects_all_ai_names_in_a_conflict_group() -> None:
    response = SemanticResponse(
        decisions=(
            SemanticDecision(
                node_id="safe-button",
                semantic_type="Button",
                confidence=0.9,
                fgui_name="SharedName",
            ),
            SemanticDecision(
                node_id="title",
                semantic_type="Label",
                confidence=0.8,
                fgui_name="sharedname",
            ),
        )
    )

    decisions, diagnostics = validate_semantic_response(_tree(), response)

    assert decisions == ()
    assert [item.code for item in diagnostics] == [
        "semantic.name_conflict",
        "semantic.name_conflict",
    ]


def test_existing_node_names_are_reserved_except_for_the_same_node() -> None:
    conflict = SemanticResponse(
        decisions=(
            SemanticDecision(
                node_id="safe-button",
                semantic_type="Button",
                confidence=0.9,
                fgui_name="Container",
            ),
        )
    )
    unchanged = SemanticResponse(
        decisions=(
            SemanticDecision(
                node_id="title",
                semantic_type="Label",
                confidence=0.9,
                fgui_name="Title",
            ),
        )
    )

    rejected, conflict_diagnostics = validate_semantic_response(_tree(), conflict)
    accepted, unchanged_diagnostics = validate_semantic_response(_tree(), unchanged)

    assert rejected == ()
    assert [item.code for item in conflict_diagnostics] == ["semantic.name_conflict"]
    assert [item.node_id for item in accepted] == ["title"]
    assert unchanged_diagnostics == ()
