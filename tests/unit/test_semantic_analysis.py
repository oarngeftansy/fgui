from __future__ import annotations

import httpx

from figma_to_fgui.ai_client import (
    AIAnalysisError,
    AIClientConfig,
    AIReasonCode,
    OpenAICompatibleSemanticClient,
)
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
            raise AIAnalysisError(AIReasonCode.TRANSPORT)

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


def test_analysis_falls_back_when_summary_contains_non_finite_geometry() -> None:
    roots = (
        NormalizedNode(
            id="bad",
            name="Bad",
            type="FRAME",
            bounds=Bounds(x=float("nan"), y=0, width=1, height=1),
        ),
    )
    requests: list[httpx.Request] = []
    client = OpenAICompatibleSemanticClient(
        AIClientConfig(
            provider="openai",
            base_url="https://ai.example.test/v1",
            model="model",
            api_key="secret-value",
        ),
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(500)
        ),
    )

    outcome = analyze_semantics(roots, client)

    assert outcome.overrides == ()
    assert outcome.diagnostics[0].code == AIReasonCode.REQUEST_INVALID
    assert requests == []


def test_untrusted_error_code_cannot_become_a_diagnostic_code() -> None:
    class UntrustedClient:
        def analyze(self, summary: dict[str, object]) -> SemanticResponse:
            raise AIAnalysisError("attacker.controlled")  # type: ignore[arg-type]

    outcome = analyze_semantics(_roots(), UntrustedClient())

    assert outcome.diagnostics[0].code == AIReasonCode.INTERNAL
    assert "attacker" not in outcome.model_dump_json()


def test_analysis_falls_back_for_overdeep_response_json() -> None:
    overdeep_json = "[" * 5_000 + '"private response"' + "]" * 5_000
    client = OpenAICompatibleSemanticClient(
        AIClientConfig(
            provider="openai",
            base_url="https://ai.example.test/v1",
            model="model",
            api_key="secret-value",
        ),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=overdeep_json.encode("utf-8"))
        ),
    )

    outcome = analyze_semantics(_roots(), client)

    assert outcome.overrides == ()
    assert outcome.diagnostics[0].code == AIReasonCode.RESPONSE_JSON
    assert "private response" not in outcome.model_dump_json()
