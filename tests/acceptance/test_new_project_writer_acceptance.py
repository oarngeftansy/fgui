from __future__ import annotations

import json
from pathlib import Path

import scripts.run_new_project_writer_acceptance as acceptance_runner
from scripts.run_new_project_writer_acceptance import (
    canonical_acceptance_bytes,
    run_acceptance,
    write_acceptance_results,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_CASES = {"TC-01", "TC-02", "AC-01", "TC-03", "TC-04", "TC-05"}
REQUIRED_CASE_FIELDS = {
    "id",
    "purpose",
    "prerequisites",
    "steps",
    "expected",
    "actual",
    "screenshot",
    "status",
}


def _cases_by_id(result: dict[str, object]) -> dict[str, dict[str, object]]:
    cases = result["cases"]
    assert isinstance(cases, list)
    return {str(case["id"]): case for case in cases if isinstance(case, dict)}


def test_acceptance_runner_has_exact_closed_case_set(tmp_path: Path) -> None:
    result = run_acceptance(REPO_ROOT, tmp_path)

    cases = _cases_by_id(result)
    assert set(cases) == EXPECTED_CASES
    assert all(set(case) >= REQUIRED_CASE_FIELDS for case in cases.values())
    assert all(case["status"] in {"PASS", "FAIL"} for case in cases.values())
    assert all(isinstance(case["purpose"], str) and case["purpose"] for case in cases.values())
    assert all(isinstance(case["prerequisites"], list) for case in cases.values())
    assert all(isinstance(case["steps"], list) and case["steps"] for case in cases.values())
    assert all(isinstance(case["expected"], list) and case["expected"] for case in cases.values())
    assert all(isinstance(case["actual"], list) and case["actual"] for case in cases.values())
    assert all(
        isinstance(case["screenshot"], str) and case["screenshot"] for case in cases.values()
    )


def test_acceptance_result_is_privacy_safe_and_canonical(tmp_path: Path) -> None:
    result_path = write_acceptance_results(REPO_ROOT, tmp_path)
    content = result_path.read_bytes()

    assert content.endswith(b"\n")
    assert b"C:\\\\Users" not in content
    assert b"Traceback" not in content
    assert content == canonical_acceptance_bytes(json.loads(content))


def test_runner_records_each_required_production_boundary(tmp_path: Path) -> None:
    cases = _cases_by_id(run_acceptance(REPO_ROOT, tmp_path))

    assert cases["TC-01"]["status"] == "PASS"
    assert any(item.startswith("archiveMembers=") for item in cases["TC-01"]["actual"])
    assert cases["TC-02"]["status"] == "PASS"
    assert any(item.startswith("firstSha256=") for item in cases["TC-02"]["actual"])
    assert any(item.startswith("secondSha256=") for item in cases["TC-02"]["actual"])
    assert "byteEquality=true" in cases["TC-02"]["actual"]
    assert cases["AC-01"]["status"] == "PASS"
    assert "guiActionPending=true" in cases["AC-01"]["actual"]
    assert cases["TC-03"]["status"] == "PASS"
    assert "rejection=ASSET_DIRECTORY" in cases["TC-03"]["actual"]
    assert "zipPublished=false" in cases["TC-03"]["actual"]
    assert cases["TC-04"]["status"] == "PASS"
    assert "rejection=ASSET_DIRECTORY" in cases["TC-04"]["actual"]
    assert "pillowProbeCalled=false" in cases["TC-04"]["actual"]
    assert "zipPublished=false" in cases["TC-04"]["actual"]
    assert cases["TC-05"]["status"] == "PASS"
    assert "diagnostic=fgui.component.definition_missing" in cases["TC-05"]["actual"]
    assert "productionSpecialCaseScan=true" in cases["TC-05"]["actual"]
    assert "zipPublished=false" in cases["TC-05"]["actual"]


def test_tc_05_attempts_public_cli_publish_with_the_unbindable_village_plan(
    tmp_path: Path, monkeypatch
) -> None:
    attempts: list[tuple[dict[str, object], Path]] = []
    original_invoke = acceptance_runner.CliRunner.invoke

    def invoke_spy(self, command, args=None, **kwargs):
        assert args is not None
        if args[0] == "build-fgui-project":
            plan = json.loads(Path(args[1]).read_text("utf-8"))
            if plan["bindable"] is False:
                attempts.append((plan, Path(args[4])))
        return original_invoke(self, command, args, **kwargs)

    monkeypatch.setattr(acceptance_runner.CliRunner, "invoke", invoke_spy)

    cases = _cases_by_id(run_acceptance(REPO_ROOT, tmp_path))

    assert len(attempts) == 1
    plan, output = attempts[0]
    assert "fgui.component.definition_missing" in {
        item["code"] for item in plan["diagnostics"]
    }
    assert output == tmp_path / "tc-05-output"
    assert not output.exists() or list(output.glob("*.zip")) == []
    assert "cliPublishAttempt=true" in cases["TC-05"]["actual"]
    assert "rejection=PLAN" in cases["TC-05"]["actual"]
