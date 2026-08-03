from __future__ import annotations

from figma_to_fgui.ai_client import AIAnalysisError
from figma_to_fgui.models import Bounds, NormalizedNode, Severity
from figma_to_fgui.semantic_analysis import analyze_semantics, build_selection_summary
from figma_to_fgui.semantic_models import SemanticDecision, SemanticResponse


def _roots() -> tuple[NormalizedNode, ...]:
    return (
        NormalizedNode(
            id="root",
            name="Main",
            type="FRAME",
            bounds=Bounds(x=0, y=0, width=100, height=100),
            children=(
                NormalizedNode(
                    id="button",
                    name="Submit",
                    type="RECTANGLE",
                    bounds=Bounds(x=10, y=10, width=40, height=20),
                    text="private node text",
                    properties={"private": "property"},
                    raw_style={"private": "style"},
                ),
            ),
        ),
    )


def test_summary_is_deterministic_minimal_tree_structure() -> None:
    summary = build_selection_summary(_roots())

    assert summary == {
        "version": 1,
        "nodes": [
            {
                "id": "root",
                "parent_id": None,
                "name": "Main",
                "type": "FRAME",
                "bounds": {"x": 0.0, "y": 0.0, "width": 100.0, "height": 100.0},
            },
            {
                "id": "button",
                "parent_id": "root",
                "name": "Submit",
                "type": "RECTANGLE",
                "bounds": {"x": 10.0, "y": 10.0, "width": 40.0, "height": 20.0},
            },
        ],
    }


def test_analysis_without_client_uses_deterministic_warning() -> None:
    outcome = analyze_semantics(_roots(), None)

    assert outcome.overrides == ()
    assert [(item.code, item.severity, item.message) for item in outcome.diagnostics] == [
        ("ai.disabled", Severity.WARNING, "AI semantic analysis was unavailable; rule classification remains active.")
    ]


def test_analysis_falls_back_without_exposing_node_text() -> None:
    class FailingClient:
        def analyze(self, summary: dict[str, object]) -> SemanticResponse:
            raise AIAnalysisError("ai.transport")

    outcome = analyze_semantics(_roots(), FailingClient())

    assert outcome.overrides == ()
    assert outcome.diagnostics[0].code == "ai.transport"
    assert "private node text" not in outcome.diagnostics[0].message


def test_analysis_validates_client_response_and_preserves_screenshot_signal() -> None:
    class Client:
        def analyze(self, summary: dict[str, object]) -> SemanticResponse:
            assert summary["nodes"]
            return SemanticResponse(
                decisions=(SemanticDecision(node_id="button", semantic_type="Button", confidence=0.9),),
                screenshot_recommended=True,
                screenshot_reason="Ambiguous grouping.",
            )

    outcome = analyze_semantics(_roots(), Client())

    assert [item.node_id for item in outcome.overrides] == ["button"]
    assert outcome.diagnostics == ()
    assert outcome.screenshot_recommended is True
    assert outcome.screenshot_reason == "Ambiguous grouping."
