from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from figma_to_fgui.ai_client import AIAnalysisError
from figma_to_fgui.models import Diagnostic, NormalizedNode, Severity
from figma_to_fgui.semantic_models import SemanticAnalysisOutcome, SemanticResponse
from figma_to_fgui.semantic_validation import validate_semantic_response


class SemanticClient(Protocol):
    def analyze(
        self, summary: dict[str, object], screenshot: bytes | None = None
    ) -> SemanticResponse: ...


def _summarize(node: NormalizedNode, parent_id: str | None) -> dict[str, object]:
    return {
        "id": node.id,
        "parent_id": parent_id,
        "name": node.name,
        "type": node.type,
        "bounds": node.bounds.model_dump(mode="json"),
    }


def build_selection_summary(roots: Iterable[NormalizedNode]) -> dict[str, object]:
    """Produce a deterministic structural-only description; text, styles, and properties stay local."""
    nodes: list[dict[str, object]] = []

    def visit(node: NormalizedNode, parent_id: str | None) -> None:
        nodes.append(_summarize(node, parent_id))
        for child in node.children:
            visit(child, node.id)

    for root in roots:
        visit(root, None)
    return {"version": 1, "nodes": nodes}


def fallback_warning(reason: str) -> Diagnostic:
    code = reason if reason.startswith("ai.") else f"ai.{reason}"
    return Diagnostic(
        code=code,
        severity=Severity.WARNING,
        message="AI semantic analysis was unavailable; rule classification remains active.",
    )


def analyze_semantics(
    roots: tuple[NormalizedNode, ...], client: SemanticClient | None
) -> SemanticAnalysisOutcome:
    if client is None:
        return SemanticAnalysisOutcome(overrides=(), diagnostics=(fallback_warning("disabled"),))
    try:
        response = client.analyze(build_selection_summary(roots))
    except AIAnalysisError as error:
        return SemanticAnalysisOutcome(overrides=(), diagnostics=(fallback_warning(error.code),))
    overrides, diagnostics = validate_semantic_response(roots, response)
    return SemanticAnalysisOutcome(
        overrides=overrides,
        diagnostics=diagnostics,
        screenshot_recommended=response.screenshot_recommended,
        screenshot_reason=response.screenshot_reason,
    )
