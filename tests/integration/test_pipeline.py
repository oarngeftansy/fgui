import hashlib
import json
import shutil
from pathlib import Path

from figma_to_fgui.models import ClassificationDecision, DecisionSource, Diagnostic, Severity
from figma_to_fgui.pipeline import convert_document
from figma_to_fgui.semantic_models import SemanticAnalysisOutcome


def _raw_document() -> dict[str, object]:
    return json.loads(Path("tests/fixtures/figma/simple-frame.json").read_text("utf-8"))


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    shutil.copytree(Path("tests/fixtures/fgui"), project)
    return project


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(path for path in root.rglob("*") if path.is_file())
    }


def test_valid_ai_override_changes_component_type_and_receives_only_roots_and_screenshot(
    tmp_path: Path,
) -> None:
    class FakeAnalyzer:
        calls = 0

        def analyze(
            self, roots: tuple[object, ...], *, screenshot: bytes | None = None
        ) -> SemanticAnalysisOutcome:
            self.calls += 1
            assert len(roots) == 1
            assert screenshot == b"png"
            return SemanticAnalysisOutcome(
                overrides=(
                    ClassificationDecision(
                        node_id="1:1",
                        output_type="COMPONENT",
                        rule_id="ai.semantic.v1",
                        rule_version=1,
                        evidence=("validated structured AI decision",),
                        confidence=0.9,
                        source=DecisionSource.AI,
                    ),
                )
            )

    analyzer = FakeAnalyzer()
    result = convert_document(
        _raw_document(),
        _project(tmp_path),
        "Sample",
        tmp_path / "staging",
        Path("rules/default/classification.yaml"),
        semantic_analyzer=analyzer,
        screenshot=b"png",
    )

    assert analyzer.calls == 1
    assert any(item.code == "semantic.ai_applied" for item in result.diagnostics)
    assert result.files == ()


def test_ai_failure_generates_same_files_as_rules_only(tmp_path: Path) -> None:
    class FailingAnalyzer:
        def analyze(
            self, roots: tuple[object, ...], *, screenshot: bytes | None = None
        ) -> SemanticAnalysisOutcome:
            raise RuntimeError("remote failure with sensitive details")

    baseline_root = tmp_path / "baseline"
    degraded_root = tmp_path / "degraded"
    baseline = convert_document(
        _raw_document(),
        _project(tmp_path / "baseline-project"),
        "Sample",
        baseline_root,
        Path("rules/default/classification.yaml"),
    )
    degraded = convert_document(
        _raw_document(),
        _project(tmp_path / "degraded-project"),
        "Sample",
        degraded_root,
        Path("rules/default/classification.yaml"),
        semantic_analyzer=FailingAnalyzer(),
    )

    assert _file_hashes(degraded_root) == _file_hashes(baseline_root)
    assert any(item.code == "semantic.fallback" for item in degraded.diagnostics)
    assert all(item.severity is not Severity.ERROR for item in degraded.diagnostics)
    assert "sensitive details" not in degraded.model_dump_json()
    assert baseline.files == degraded.files


def test_merges_analyzer_failure_diagnostics_with_pipeline_fallback(tmp_path: Path) -> None:
    class DegradedAnalyzer:
        def analyze(
            self, roots: tuple[object, ...], *, screenshot: bytes | None = None
        ) -> SemanticAnalysisOutcome:
            return SemanticAnalysisOutcome(
                diagnostics=(
                    Diagnostic(
                        code="ai.transport",
                        severity=Severity.WARNING,
                        message="Safe analyzer failure.",
                    ),
                ),
                used_fallback=True,
            )

    result = convert_document(
        _raw_document(),
        _project(tmp_path),
        "Sample",
        tmp_path / "staging",
        Path("rules/default/classification.yaml"),
        semantic_analyzer=DegradedAnalyzer(),
    )

    assert [item.code for item in result.diagnostics if item.code.startswith(("ai.", "semantic."))] == [
        "ai.transport",
        "semantic.fallback",
    ]


def test_failed_analyzer_outcome_cannot_apply_returned_overrides(tmp_path: Path) -> None:
    class FailedAnalyzer:
        def analyze(
            self, roots: tuple[object, ...], *, screenshot: bytes | None = None
        ) -> SemanticAnalysisOutcome:
            return SemanticAnalysisOutcome(
                overrides=(
                    ClassificationDecision(
                        node_id="1:1",
                        output_type="COMPONENT",
                        rule_id="ai.semantic.v1",
                        rule_version=1,
                        evidence=("must not be applied",),
                        confidence=0.9,
                        source=DecisionSource.AI,
                    ),
                ),
                diagnostics=(
                    Diagnostic(
                        code="custom.provider_failure",
                        severity=Severity.WARNING,
                        message="Safe custom failure.",
                    ),
                ),
                used_fallback=True,
            )

    baseline_root = tmp_path / "baseline"
    degraded_root = tmp_path / "degraded"
    baseline = convert_document(
        _raw_document(),
        _project(tmp_path / "baseline-project"),
        "Sample",
        baseline_root,
        Path("rules/default/classification.yaml"),
    )
    degraded = convert_document(
        _raw_document(),
        _project(tmp_path / "degraded-project"),
        "Sample",
        degraded_root,
        Path("rules/default/classification.yaml"),
        semantic_analyzer=FailedAnalyzer(),
    )

    assert _file_hashes(degraded_root) == _file_hashes(baseline_root)
    assert baseline.files == degraded.files
    assert "custom.provider_failure" in {item.code for item in degraded.diagnostics}
    assert "semantic.fallback" in {item.code for item in degraded.diagnostics}
    assert "semantic.ai_applied" not in {item.code for item in degraded.diagnostics}


def test_custom_analyzer_cannot_bypass_semantic_name_validation(tmp_path: Path) -> None:
    class UnsafeAnalyzer:
        def analyze(
            self, roots: tuple[object, ...], *, screenshot: bytes | None = None
        ) -> SemanticAnalysisOutcome:
            return SemanticAnalysisOutcome(
                overrides=(
                    ClassificationDecision(
                        node_id="1:1",
                        output_type="PANEL",
                        rule_id="custom.semantic",
                        rule_version=1,
                        evidence=("untrusted custom analyzer",),
                        confidence=1,
                        source=DecisionSource.AI,
                        semantic_name="../escape",
                    ),
                    ClassificationDecision(
                        node_id="1:2",
                        output_type="TEXT",
                        rule_id="custom.semantic",
                        rule_version=1,
                        evidence=("untrusted custom analyzer",),
                        confidence=1,
                        source=DecisionSource.AI,
                        semantic_name="main",
                    ),
                )
            )

    baseline_root = tmp_path / "baseline"
    guarded_root = tmp_path / "guarded"
    baseline = convert_document(
        _raw_document(),
        _project(tmp_path / "baseline-project"),
        "Sample",
        baseline_root,
        Path("rules/default/classification.yaml"),
    )
    guarded = convert_document(
        _raw_document(),
        _project(tmp_path / "guarded-project"),
        "Sample",
        guarded_root,
        Path("rules/default/classification.yaml"),
        semantic_analyzer=UnsafeAnalyzer(),
    )

    assert _file_hashes(guarded_root) == _file_hashes(baseline_root)
    assert guarded.files == baseline.files
    assert "semantic.invalid_name" in {item.code for item in guarded.diagnostics}
    assert "semantic.name_conflict" in {item.code for item in guarded.diagnostics}
    assert "semantic.ai_applied" not in {item.code for item in guarded.diagnostics}
