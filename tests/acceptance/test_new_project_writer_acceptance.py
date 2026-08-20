from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from struct import pack

import pytest

import scripts.run_new_project_writer_acceptance as acceptance_runner
from scripts.run_new_project_writer_acceptance import (
    canonical_acceptance_bytes,
    finalize_screenshot_closure,
    render_evidence_cards,
    run_acceptance,
    write_acceptance_report,
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
FRESH_EDITOR_TRANSCRIPT = REPO_ROOT / (
    "docs/validation/2026-08-20-fgui-6.1.4-new-project-editor-transcript.json"
)


def _cases_by_id(result: dict[str, object]) -> dict[str, dict[str, object]]:
    cases = result["cases"]
    assert isinstance(cases, list)
    return {str(case["id"]): case for case in cases if isinstance(case, dict)}


def _write_png(path: Path, *, width: int = 1440, height: int = 1000) -> None:
    """Write the PNG header needed by the evidence-closure contract."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + pack(">I", 13) + b"IHDR" + pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    )


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
    result_path = write_acceptance_results(REPO_ROOT, tmp_path, screenshots_pending=True)
    content = result_path.read_bytes()

    assert content.endswith(b"\n")
    assert b"C:\\\\Users" not in content
    assert b"Traceback" not in content
    assert content == canonical_acceptance_bytes(json.loads(content))


def test_result_writing_requires_screenshot_closure_unless_explicitly_pending(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="TC-01"):
        write_acceptance_results(REPO_ROOT, tmp_path)


def test_each_case_has_one_closed_evidence_card(tmp_path: Path) -> None:
    result = run_acceptance(REPO_ROOT, tmp_path)

    cards = render_evidence_cards(result, tmp_path / "cards")

    cases = result["cases"]
    assert isinstance(cases, list)
    assert len(cards) == 6
    assert {path.stem for path in cards} == {str(case["id"]).lower() for case in cases}
    for case in cases:
        assert isinstance(case, dict)
        html = (tmp_path / "cards" / f"{case['id'].lower()}.html").read_text("utf-8")
        assert str(case["id"]) in html
        assert str(case["status"]) in html
        assert str(case["purpose"]) in html
        assert "Expected" in html
        assert "Actual" in html
        assert "Decisive evidence" in html
        assert all(str(item) in html for item in case["expected"])
        assert all(str(item) in html for item in case["actual"])
        assert "https://" not in html
        assert "http://" not in html
        assert "<script" not in html.lower()
        assert "height: 1000px; overflow: hidden;" in html
        assert 'data-layout-contract="1440x1000-no-scroll"' in html


def test_evidence_cards_escape_dynamic_content(tmp_path: Path) -> None:
    result = run_acceptance(REPO_ROOT, tmp_path)
    copied = json.loads(json.dumps(result))
    cases = _cases_by_id(copied)
    cases["TC-01"]["purpose"] = '<img src=x onerror="alert(1)">'
    cases["TC-01"]["actual"] = ["<b>unsafe</b>"]

    render_evidence_cards(copied, tmp_path / "cards")

    html = (tmp_path / "cards" / "tc-01.html").read_text("utf-8")
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "&lt;b&gt;unsafe&lt;/b&gt;" in html
    assert '<img src=x onerror="alert(1)">' not in html


@pytest.mark.parametrize(
    ("field", "private_value", "marker"),
    [
        ("purpose", "purpose=/tmp/private-run/output.zip", "private-run"),
        ("prerequisites", r"prerequisite=C:\private-run\output.zip", "private-run"),
        ("steps", r"step=\\server\private-run\output.zip", "private-run"),
        ("expected", "expected=//server/private-run/output.zip", "private-run"),
        ("actual", "actual=/root/private-run", "private-run"),
        ("purpose", "purpose=/./private-run", "private-run"),
        ("prerequisites", "prerequisite=/../private-run", "private-run"),
        ("steps", "step=//private-run", "private-run"),
        ("expected", "expected=file:///private-run", "private-run"),
        ("actual", "actual=x /../private-run y", "private-run"),
        ("purpose", "purpose=https://example.test/C:/Users/private-run", "private-run"),
        ("prerequisites", "prerequisite=https://example.test//server/private-run", "private-run"),
        ("steps", "step=https://example.test/../private-run", "private-run"),
        ("expected", "expected=https://example.test/public", "example.test"),
    ],
)
def test_public_result_boundaries_fail_closed_for_private_absolute_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    private_value: str,
    marker: str,
) -> None:
    result = json.loads(json.dumps(run_acceptance(REPO_ROOT, tmp_path)))
    case = _cases_by_id(result)["TC-01"]
    if field == "purpose":
        case[field] = private_value
    else:
        case[field] = [private_value]

    cards = tmp_path / "cards"
    with pytest.raises(ValueError, match="private absolute paths"):
        render_evidence_cards(result, cards)
    assert not list(cards.glob("*.html"))

    with pytest.raises(ValueError, match="private absolute paths"):
        canonical_acceptance_bytes(result)

    monkeypatch.setattr(acceptance_runner, "run_acceptance", lambda _workspace, _root: result)
    with pytest.raises(ValueError, match="private absolute paths"):
        write_acceptance_results(REPO_ROOT, tmp_path / "results", screenshots_pending=True)
    assert not (tmp_path / "results" / "new-project-writer-acceptance-results.json").exists()
    assert marker.encode("utf-8") not in canonical_acceptance_bytes(
        run_acceptance(REPO_ROOT, tmp_path)
    )


def test_public_result_boundaries_allow_public_codes_and_ui_uris(tmp_path: Path) -> None:
    result = json.loads(json.dumps(run_acceptance(REPO_ROOT, tmp_path)))
    case = _cases_by_id(result)["TC-01"]
    case["purpose"] = "Consume image/png through ui://PkgComponent."
    case["prerequisites"] = ["resource=image/png"]
    case["steps"] = ["reference=ui://PkgComponent"]
    case["expected"] = ["code=image/png"]
    case["actual"] = ["reference=ui://PkgComponent"]

    render_evidence_cards(result, tmp_path / "cards")

    assert b"ui://PkgComponent" in canonical_acceptance_bytes(result)


def test_final_screenshot_closure_records_matching_hashes(tmp_path: Path) -> None:
    result = run_acceptance(REPO_ROOT, tmp_path)
    evidence_root = tmp_path / "validation"
    for case in result["cases"]:
        assert isinstance(case, dict)
        _write_png(evidence_root / str(case["screenshot"]))

    closed = finalize_screenshot_closure(result, evidence_root)

    cases = _cases_by_id(closed)
    assert set(cases) == EXPECTED_CASES
    for case in cases.values():
        screenshot = evidence_root / str(case["screenshot"])
        assert case["screenshotSha256"] == sha256(screenshot.read_bytes()).hexdigest()


def test_final_screenshot_closure_only_allows_missing_pngs_when_explicitly_pending(
    tmp_path: Path,
) -> None:
    result = run_acceptance(REPO_ROOT, tmp_path)

    pending = finalize_screenshot_closure(
        result, tmp_path / "validation", screenshots_pending=True
    )
    assert all("screenshotSha256" not in case for case in pending["cases"])

    with pytest.raises(ValueError, match="TC-01"):
        finalize_screenshot_closure(result, tmp_path / "validation")


def test_final_screenshot_closure_rejects_invalid_dimensions_and_hash_mismatches(
    tmp_path: Path,
) -> None:
    result = run_acceptance(REPO_ROOT, tmp_path)
    evidence_root = tmp_path / "validation"
    for case in result["cases"]:
        assert isinstance(case, dict)
        _write_png(
            evidence_root / str(case["screenshot"]),
            width=1 if case["id"] == "TC-01" else 1440,
        )

    with pytest.raises(ValueError, match="TC-01"):
        finalize_screenshot_closure(result, evidence_root)

    _write_png(evidence_root / "evidence/new-project-writer/tc-01.png")
    _cases_by_id(result)["TC-01"]["screenshotSha256"] = "0" * 64
    with pytest.raises(ValueError, match="TC-01"):
        finalize_screenshot_closure(result, evidence_root)


def test_ac_01_consumes_the_tracked_fresh_editor_transcript(tmp_path: Path) -> None:
    """AC-01 records only the root-observed Editor facts, with no pending placeholder."""
    transcript = json.loads(FRESH_EDITOR_TRANSCRIPT.read_text("utf-8"))
    case = _cases_by_id(run_acceptance(REPO_ROOT, tmp_path))["AC-01"]

    assert transcript["editorVersion"] == "6.1.4"
    assert transcript["returnedWindowTitles"] == [
        "GenericWriterFixture",
        "GenericWriterFixture",
    ]
    assert transcript["saveRounds"] == ["open-save-close", "reopen-save-close"]
    assert transcript["delayedCloseObservation"] is True
    assert transcript["finalWindowCount"] == 0
    assert transcript["modalObserved"] is False
    assert transcript["stateScreenshot"] == {
        "supported": False,
        "errorCode": "0x80004002",
    }
    assert all(item["match"] is True for item in transcript["files"])
    assert case["status"] == "PASS"
    assert "guiActionPending=true" not in case["actual"]
    assert "editorVersion=6.1.4" in case["actual"]
    assert "returnedWindowTitle=GenericWriterFixture" in case["actual"]
    assert "saveRounds=open-save-close,reopen-save-close" in case["actual"]
    assert "delayedCloseObservation=true" in case["actual"]
    assert "finalWindowCount=0" in case["actual"]
    assert "modalObserved=false" in case["actual"]
    assert "stateScreenshot=unsupported(0x80004002)" in case["actual"]
    assert "fileHashParity=4/4" in case["actual"]


def test_fresh_gui_transcript_rejects_an_unobserved_gui_claim(tmp_path: Path) -> None:
    transcript = acceptance_runner._fresh_gui_transcript()
    transcript["thirdSaveRound"] = True
    target = tmp_path / "docs/validation"
    target.mkdir(parents=True)
    (target / FRESH_EDITOR_TRANSCRIPT.name).write_text(
        json.dumps(transcript, ensure_ascii=False, sort_keys=True) + "\n", "utf-8"
    )

    assert acceptance_runner._read_fresh_gui_transcript(tmp_path) is False


def test_final_report_is_generated_from_closed_machine_result_and_cross_matches(
    tmp_path: Path,
) -> None:
    result = run_acceptance(REPO_ROOT, tmp_path)
    evidence_root = tmp_path / "validation"
    for case in result["cases"]:
        assert isinstance(case, dict)
        _write_png(evidence_root / str(case["screenshot"]))
    closed = finalize_screenshot_closure(result, evidence_root)
    report = tmp_path / "new-project-writer-test-acceptance.md"

    write_acceptance_report(closed, report)

    content = report.read_text("utf-8")
    links = re.findall(r"\[[^\]]+\]\(([^)]+\.png)\)", content)
    assert len(links) == len(EXPECTED_CASES)
    assert set(links) == {
        str(case["screenshot"])
        for case in closed["cases"]
        if isinstance(case, dict)
    }
    for case in closed["cases"]:
        assert isinstance(case, dict)
        assert f"## {case['id']} — {case['status']}" in content
        assert str(case["purpose"]) in content
        assert all(str(item) in content for item in case["prerequisites"])
        assert all(str(item) in content for item in case["steps"])
        assert all(str(item) in content for item in case["expected"])
        assert all(str(item) in content for item in case["actual"])
        assert str(case["screenshotSha256"]) in content
        screenshot = evidence_root / str(case["screenshot"])
        assert screenshot.is_file()
        assert case["screenshotSha256"] == sha256(screenshot.read_bytes()).hexdigest()
    assert "http://" not in content
    assert "https://" not in content
    assert "C:\\Users" not in content


def test_strict_cli_writes_machine_result_and_report_only_after_screenshot_closure(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "validation"
    for case_id in EXPECTED_CASES:
        _write_png(evidence_root / f"evidence/new-project-writer/{case_id.lower()}.png")
    output = evidence_root / "new-project-writer-test-results.json"
    report = evidence_root / "new-project-writer-test-acceptance.md"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_new_project_writer_acceptance.py",
            "--workspace",
            ".",
            "--output",
            str(output),
            "--report",
            str(report),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(output.read_text("utf-8"))
    assert all("screenshotSha256" in case for case in result["cases"])
    assert report.is_file()


def test_runner_records_each_required_production_boundary(tmp_path: Path) -> None:
    cases = _cases_by_id(run_acceptance(REPO_ROOT, tmp_path))

    assert cases["TC-01"]["status"] == "PASS"
    assert any(item.startswith("archiveMembers=") for item in cases["TC-01"]["actual"])
    assert cases["TC-02"]["status"] == "PASS"
    assert any(item.startswith("firstSha256=") for item in cases["TC-02"]["actual"])
    assert any(item.startswith("secondSha256=") for item in cases["TC-02"]["actual"])
    assert "byteEquality=true" in cases["TC-02"]["actual"]
    assert cases["AC-01"]["status"] == "PASS"
    assert "freshTranscriptValid=true" in cases["AC-01"]["actual"]
    assert "fileHashParity=4/4" in cases["AC-01"]["actual"]
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


def test_runner_is_directly_invocable_without_ambient_pythonpath(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    output = tmp_path / "acceptance-results.json"
    command = [
        sys.executable,
        "scripts/run_new_project_writer_acceptance.py",
        "--workspace",
        ".",
        "--output",
        str(output),
        "--screenshots-pending",
    ]

    help_result = subprocess.run(
        [sys.executable, "scripts/run_new_project_writer_acceptance.py", "--help"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    run_result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert help_result.returncode == 0, help_result.stderr
    assert "--workspace" in help_result.stdout
    assert run_result.returncode == 0, run_result.stderr
    assert _cases_by_id(json.loads(output.read_text("utf-8")))["AC-01"]["actual"] == [
        "freshTranscriptValid=true",
        "editorVersion=6.1.4",
        "returnedWindowTitle=GenericWriterFixture",
        "saveRounds=open-save-close,reopen-save-close",
        "delayedCloseObservation=true",
        "finalWindowCount=0",
        "modalObserved=false",
        "stateScreenshot=unsupported(0x80004002)",
        "fileHashParity=4/4",
    ]
