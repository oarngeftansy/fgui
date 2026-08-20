"""Run the closed, privacy-safe Writer acceptance matrix.

This runner intentionally composes the existing Writer and CLI boundaries.  It
does not reproduce Writer implementation details or create Project Bindings.
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from struct import unpack
from tempfile import TemporaryDirectory
from zipfile import ZipFile

_REPOSITORY_ROOT = Path(__file__).resolve(strict=True).parents[1]
for _trusted_path in (_REPOSITORY_ROOT, _REPOSITORY_ROOT / "src"):
    if str(_trusted_path) not in sys.path:
        sys.path.insert(0, str(_trusted_path))

from typer.testing import CliRunner

from figma_to_fgui import fgui_asset_payloads
from figma_to_fgui.cli import (
    _load_new_project_config,
    _load_plan_v2,
    app,
    load_declared_asset_directory,
)
from figma_to_fgui.component_mapping import load_mapping_catalog, validate_mapping_catalog
from figma_to_fgui.fgui_new_project_build import build_new_project, validate_project_archive
from figma_to_fgui.fgui_plan_compile import compile_fgui_plan
from figma_to_fgui.fgui_plan_validate import canonical_plan_bytes, validate_fgui_plan
from figma_to_fgui.normalize import normalize_document
from figma_to_fgui.project_index import index_project
from figma_to_fgui.uir_compile import compile_uir
from tests.support.village_writer_regression import production_special_case_violations

_CASE_IDS = ("TC-01", "TC-02", "AC-01", "TC-03", "TC-04", "TC-05")
_FIXTURE_DIRECTORY = Path("tests/fixtures/fgui-new-project")
_EDITOR_TRANSCRIPT = Path(
    "docs/validation/2026-08-18-fgui-6.1.4-new-project-editor-transcript.json"
)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SCREENSHOT_DIMENSIONS = (1440, 1000)


def _cases_from_result(result: Mapping[str, object]) -> list[Mapping[str, object]]:
    """Return the only allowed six-case result set in canonical order."""
    raw_cases = result.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != len(_CASE_IDS):
        raise ValueError("Evidence requires exactly six acceptance cases.")
    if not all(isinstance(case, Mapping) for case in raw_cases):
        raise ValueError("Evidence cases must be objects.")
    cases = list(raw_cases)
    if tuple(case.get("id") for case in cases) != _CASE_IDS:
        raise ValueError("Evidence cases must use the canonical six-case order.")
    return cases


def _card_text(value: object, *, field: str) -> str:
    """Validate and escape a public card field before putting it in HTML."""
    if not isinstance(value, str):
        raise TypeError(f"Evidence card {field} must be text.")
    normalized = value.replace("\\", "/")
    is_windows_absolute = (
        len(normalized) >= 3
        and normalized[1:3] == ":/"
        and normalized[0].isalpha()
    )
    if is_windows_absolute or normalized.startswith(("//", "/Users/", "/home/", "/private/")):
        raise ValueError("Evidence cards must not include private absolute paths.")
    return html.escape(value, quote=True)


def _card_text_list(case: Mapping[str, object], field: str) -> list[str]:
    raw_items = case.get(field)
    if not isinstance(raw_items, list):
        raise TypeError(f"Evidence card {field} must be a list.")
    return [_card_text(item, field=field) for item in raw_items]


def _render_list(items: list[str]) -> str:
    return "\n".join(f"<li>{item}</li>" for item in items)


def _render_case_html(case: Mapping[str, object]) -> str:
    """Render one self-contained, fixed-viewport evidence card."""
    case_id = _card_text(case.get("id"), field="id")
    status = _card_text(case.get("status"), field="status")
    if status not in {"PASS", "FAIL"}:
        raise ValueError("Evidence card status must be PASS or FAIL.")
    status_class = "pass" if status == "PASS" else "fail"
    purpose = _card_text(case.get("purpose"), field="purpose")
    prerequisites = _card_text_list(case, "prerequisites")
    steps = _card_text_list(case, "steps")
    expected = _card_text_list(case, "expected")
    actual = _card_text_list(case, "actual")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=1440, initial-scale=1">
<title>{case_id} Writer acceptance evidence</title>
<style>
@page {{ size: 1440px 1000px; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; width: 1440px; min-height: 1000px; }}
body {{ background: #f4f7fb; color: #132238; font: 20px/1.45 Arial, sans-serif; }}
main {{ display: grid; grid-template-rows: auto auto 1fr; gap: 24px; min-height: 1000px; padding: 56px 72px; }}
header {{ display: flex; align-items: center; justify-content: space-between; border-bottom: 2px solid #b9c7d8; padding-bottom: 24px; }}
h1, h2, p {{ margin: 0; }}
h1 {{ font-size: 42px; }}
h2 {{ font-size: 22px; letter-spacing: .04em; text-transform: uppercase; }}
.status {{ border-radius: 999px; color: #fff; font-weight: 700; padding: 10px 22px; }}
.pass {{ background: #18794e; }}
.fail {{ background: #bb2d3b; }}
.purpose {{ font-size: 27px; font-weight: 600; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 22px; align-content: start; }}
section {{ background: #fff; border: 1px solid #cbd6e2; border-radius: 12px; padding: 22px 26px; }}
.decisive {{ grid-column: 1 / -1; border-left: 8px solid #2368a2; }}
ul, ol {{ margin: 12px 0 0; padding-left: 28px; }}
li {{ margin: 5px 0; overflow-wrap: anywhere; }}
</style>
</head>
<body>
<main>
  <header><h1>{case_id} · Writer acceptance</h1><span class="status {status_class}">{status}</span></header>
  <p class="purpose">{purpose}</p>
  <div class="grid">
    <section><h2>Prerequisites</h2><ul>{_render_list(prerequisites)}</ul></section>
    <section><h2>Steps</h2><ol>{_render_list(steps)}</ol></section>
    <section><h2>Expected</h2><ul>{_render_list(expected)}</ul></section>
    <section><h2>Actual</h2><ul>{_render_list(actual)}</ul></section>
    <section class="decisive"><h2>Decisive evidence</h2><ul>{_render_list(actual)}</ul></section>
  </div>
</main>
</body>
</html>
"""


def render_evidence_cards(result: Mapping[str, object], output: Path) -> tuple[Path, ...]:
    """Write the six local, self-contained HTML evidence cards in canonical order."""
    cases = _cases_from_result(result)
    output.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    for case in cases:
        case_id = case["id"]
        assert isinstance(case_id, str)
        target = output / f"{case_id.lower()}.html"
        target.write_text(_render_case_html(case), encoding="utf-8", newline="\n")
        rendered.append(target)
    return tuple(rendered)


def _png_sha256_and_dimensions(path: Path) -> tuple[str, tuple[int, int]]:
    """Read the PNG signature, IHDR dimensions, and complete-file SHA-256."""
    digest = sha256()
    with path.open("rb") as source:
        header = source.read(29)
        digest.update(header)
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    if (
        len(header) != 29
        or header[:8] != _PNG_SIGNATURE
        or unpack(">I", header[8:12])[0] != 13
        or header[12:16] != b"IHDR"
    ):
        raise ValueError("Screenshot is not a PNG with a valid IHDR header.")
    dimensions = unpack(">II", header[16:24])
    if not all(dimensions):
        raise ValueError("Screenshot PNG dimensions must be nonzero.")
    return digest.hexdigest(), dimensions


def finalize_screenshot_closure(
    result: Mapping[str, object], evidence_root: Path, *, screenshots_pending: bool = False
) -> dict[str, object]:
    """Return a result with six verified screenshot hashes, or fail closed.

    Pending mode is explicit and never records screenshot hashes. It exists only
    for Tasks 1-2, before Task 3 captures the cards with Playwright.
    """
    cases = _cases_from_result(result)
    final: dict[str, object] = dict(result)
    finalized_cases: list[dict[str, object]] = []
    for case in cases:
        case_id = case["id"]
        assert isinstance(case_id, str)
        expected_reference = f"evidence/new-project-writer/{case_id.lower()}.png"
        if case.get("screenshot") != expected_reference:
            raise ValueError(f"{case_id}: screenshot reference is not the one required PNG.")
        closed_case = dict(case)
        if screenshots_pending:
            closed_case.pop("screenshotSha256", None)
            finalized_cases.append(closed_case)
            continue
        screenshot = evidence_root / expected_reference
        if not screenshot.is_file():
            raise ValueError(f"{case_id}: required screenshot is missing.")
        try:
            actual_hash, dimensions = _png_sha256_and_dimensions(screenshot)
        except OSError as error:
            raise ValueError(f"{case_id}: required screenshot cannot be read.") from error
        except ValueError as error:
            raise ValueError(f"{case_id}: screenshot validation failed.") from error
        if dimensions != _SCREENSHOT_DIMENSIONS:
            raise ValueError(f"{case_id}: screenshot dimensions must be 1440x1000.")
        expected_hash = closed_case.get("screenshotSha256")
        if expected_hash is not None and expected_hash != actual_hash:
            raise ValueError(f"{case_id}: screenshot SHA-256 does not match.")
        closed_case["screenshotSha256"] = actual_hash
        finalized_cases.append(closed_case)
    final["cases"] = finalized_cases
    return final


def canonical_acceptance_bytes(value: Mapping[str, object]) -> bytes:
    """Encode canonical public-only acceptance results."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _case_result(
    case_id: str,
    purpose: str,
    prerequisites: list[str],
    steps: list[str],
    expected: list[str],
    actual: list[str],
    *,
    passed: bool,
) -> dict[str, object]:
    return {
        "id": case_id,
        "purpose": purpose,
        "prerequisites": prerequisites,
        "steps": steps,
        "expected": expected,
        "actual": actual,
        "screenshot": f"evidence/new-project-writer/{case_id.lower()}.png",
        "status": "PASS" if passed else "FAIL",
    }


def _safe_case(
    case_id: str,
    purpose: str,
    prerequisites: list[str],
    steps: list[str],
    expected: list[str],
    operation: Callable[[], tuple[bool, list[str]]],
) -> dict[str, object]:
    """Keep unexpected local failures out of the published public result."""
    try:
        passed, actual = operation()
    except Exception:  # noqa: BLE001 - an acceptance result must not leak local detail.
        passed, actual = False, ["result=unexpected_failure"]
    return _case_result(
        case_id,
        purpose,
        prerequisites,
        steps,
        expected,
        actual,
        passed=passed,
    )


def _load_generic_writer_input(workspace: Path):
    fixture = workspace / _FIXTURE_DIRECTORY
    plan = _load_plan_v2(fixture / "generic-plan-v2.json")
    config = _load_new_project_config(fixture / "config.json")
    payloads = load_declared_asset_directory(fixture / "assets", plan.resources)
    return plan, config, payloads


def _zip_publication_exists(output_directory: Path) -> bool:
    return output_directory.exists() and any(output_directory.glob("*.zip"))


def _tc_01(workspace: Path, evidence_root: Path) -> tuple[bool, list[str]]:
    plan, config, payloads = _load_generic_writer_input(workspace)
    built = build_new_project(plan, config, payloads, evidence_root / "tc-01")
    diagnostics = validate_project_archive(built.path, built.manifest)
    with ZipFile(built.path) as archive:
        members = archive.namelist()
        archive_ok = archive.testzip() is None
    return (
        not diagnostics and archive_ok,
        [
            f"archiveMembers={','.join(members)}",
            f"archiveValidatorClean={'true' if not diagnostics else 'false'}",
            f"archiveReopen={'true' if archive_ok else 'false'}",
        ],
    )


def _tc_02(workspace: Path, evidence_root: Path) -> tuple[bool, list[str]]:
    plan, config, payloads = _load_generic_writer_input(workspace)
    first = build_new_project(plan, config, payloads, evidence_root / "tc-02-first")
    second = build_new_project(plan, config, payloads, evidence_root / "tc-02-second")
    equal = first.path.read_bytes() == second.path.read_bytes()
    return (
        equal and first.sha256 == second.sha256,
        [
            f"firstSha256={first.sha256}",
            f"secondSha256={second.sha256}",
            f"byteEquality={'true' if equal else 'false'}",
        ],
    )


def _ac_01(workspace: Path) -> tuple[bool, list[str]]:
    transcript = json.loads((workspace / _EDITOR_TRANSCRIPT).read_text("utf-8"))
    files = transcript.get("files")
    gate = transcript.get("gate")
    valid = (
        transcript.get("schemaVersion") == 1
        and transcript.get("projectName") == "GenericWriterFixture"
        and transcript.get("editorVersion") == "6.1.4"
        and isinstance(files, list)
        and len(files) == 4
        and all(isinstance(item, dict) and item.get("match") is True for item in files)
        and gate
        == {
            "modalObserved": False,
            "rounds": ["open-save-close", "reopen-save-close"],
            "windowsAfterGate": 0,
        }
    )
    return valid, [
        "trackedTranscriptValid=true" if valid else "trackedTranscriptValid=false",
        "guiActionPending=true",
    ]


def _run_build_cli(
    plan: Path, config: Path, asset_directory: Path, output: Path, rejection: str
) -> tuple[bool, str]:
    invocation = CliRunner().invoke(
        app,
        [
            "build-fgui-project",
            str(plan),
            str(config),
            str(asset_directory),
            str(output),
        ],
    )
    return invocation.exit_code == 2 and rejection in invocation.output, invocation.output


def _tc_03(workspace: Path, evidence_root: Path) -> tuple[bool, list[str]]:
    with TemporaryDirectory(dir=evidence_root, prefix="tc-03-") as raw:
        temporary = Path(raw)
        assets = temporary / "assets"
        shutil.copytree(workspace / _FIXTURE_DIRECTORY / "assets", assets)
        manifest = json.loads((assets / "manifest.json").read_text("utf-8"))
        manifest["resources"]["resource:image"]["filename"] = "../escape.png"
        (assets / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            "utf-8",
        )
        output = temporary / "output"
        rejected, _ = _run_build_cli(
            workspace / _FIXTURE_DIRECTORY / "generic-plan-v2.json",
            workspace / _FIXTURE_DIRECTORY / "config.json",
            assets,
            output,
            "ASSET_DIRECTORY",
        )
        published = _zip_publication_exists(output)
    return (
        rejected and not published,
        [
            "rejection=ASSET_DIRECTORY" if rejected else "rejection=unexpected",
            f"zipPublished={'true' if published else 'false'}",
        ],
    )


def _tc_04(workspace: Path, evidence_root: Path) -> tuple[bool, list[str]]:
    probe_called = False

    def unexpected_probe(content: bytes) -> tuple[str, int, int] | None:
        del content
        nonlocal probe_called
        probe_called = True
        return None

    original_probe = fgui_asset_payloads._inspect_raster_in_isolated_process
    fgui_asset_payloads._inspect_raster_in_isolated_process = unexpected_probe
    try:
        with TemporaryDirectory(dir=evidence_root, prefix="tc-04-") as raw:
            temporary = Path(raw)
            assets = temporary / "assets"
            shutil.copytree(workspace / _FIXTURE_DIRECTORY / "assets", assets)
            oversized = assets / "one-pixel.png"
            with oversized.open("wb") as content:
                content.seek(fgui_asset_payloads.MAX_ASSET_PAYLOAD_BYTES)
                content.write(b"\0")
            output = temporary / "output"
            rejected, _ = _run_build_cli(
                workspace / _FIXTURE_DIRECTORY / "generic-plan-v2.json",
                workspace / _FIXTURE_DIRECTORY / "config.json",
                assets,
                output,
                "ASSET_DIRECTORY",
            )
            published = _zip_publication_exists(output)
    finally:
        fgui_asset_payloads._inspect_raster_in_isolated_process = original_probe
    return (
        rejected and not probe_called and not published,
        [
            "rejection=ASSET_DIRECTORY" if rejected else "rejection=unexpected",
            f"pillowProbeCalled={'true' if probe_called else 'false'}",
            f"zipPublished={'true' if published else 'false'}",
        ],
    )


def _tc_05(workspace: Path, evidence_root: Path) -> tuple[bool, list[str]]:
    raw = json.loads(
        (workspace / "tests/fixtures/uir/village-ascend-normalized.json").read_text("utf-8")
    )
    roots, normalize_diagnostics = normalize_document(raw)
    catalog = validate_mapping_catalog(
        load_mapping_catalog(workspace / "rules/default/component-mapping-candidates.json"),
        index_project(workspace / "tests/fixtures/uir/common-project"),
    )
    uir = compile_uir(
        roots,
        source_revision="7" * 64,
        selection_id="selection_village_ascend",
        mapping_catalog=catalog,
    )
    plan = compile_fgui_plan(uir)
    diagnostics = (*normalize_diagnostics, *plan.diagnostics, *validate_fgui_plan(plan))
    codes = {diagnostic.code for diagnostic in diagnostics}
    special_case_scan = production_special_case_violations(workspace=workspace) == ()
    output = evidence_root / "tc-05-output"
    with TemporaryDirectory(dir=evidence_root, prefix="tc-05-") as raw_directory:
        plan_path = Path(raw_directory) / "village-plan-v2.json"
        plan_path.write_bytes(canonical_plan_bytes(plan))
        rejected, _ = _run_build_cli(
            plan_path,
            workspace / _FIXTURE_DIRECTORY / "config.json",
            workspace / _FIXTURE_DIRECTORY / "assets",
            output,
            "PLAN",
        )
    published = _zip_publication_exists(output)
    passed = (
        "fgui.component.definition_missing" in codes
        and not plan.bindable
        and special_case_scan
        and rejected
        and not published
    )
    return (
        passed,
        [
            "diagnostic=fgui.component.definition_missing"
            if "fgui.component.definition_missing" in codes
            else "diagnostic=missing",
            f"productionSpecialCaseScan={'true' if special_case_scan else 'false'}",
            f"cliPublishAttempt={'true' if rejected else 'false'}",
            "rejection=PLAN" if rejected else "rejection=unexpected",
            f"zipPublished={'true' if published else 'false'}",
        ],
    )


def run_acceptance(workspace: Path, evidence_root: Path) -> dict[str, object]:
    """Execute exactly the six Writer acceptance cases using public production seams."""
    root = workspace.resolve(strict=True)
    evidence_root.mkdir(parents=True, exist_ok=True)
    cases = [
        _safe_case(
            "TC-01",
            "Build the generic neutral Writer fixture and reopen its published ZIP.",
            ["Canonical generic Plan v2, config, and declared asset manifest are tracked."],
            [
                "Load through CLI loaders.",
                "Build through Writer.",
                "Reopen through archive validator.",
            ],
            ["A valid archive has the exact deterministic member list."],
            lambda: _tc_01(root, evidence_root),
        ),
        _safe_case(
            "TC-02",
            "Prove deterministic archive bytes for the generic Writer fixture.",
            ["The generic fixture is valid for new-project generation."],
            ["Build twice into isolated output directories.", "Compare both published archives."],
            ["Both SHA-256 values match and archive bytes are equal."],
            lambda: _tc_02(root, evidence_root),
        ),
        _safe_case(
            "AC-01",
            "Preserve the durable neutral FairyGUI Editor acceptance transcript.",
            ["The tracked FairyGUI Editor 6.1.4 transcript is available."],
            ["Validate the tracked transcript structure and hash-match evidence."],
            ["Tracked transcript is valid; a fresh GUI action remains pending for Task 3."],
            lambda: _ac_01(root),
        ),
        _safe_case(
            "TC-03",
            "Reject an asset manifest path traversal before archive publication.",
            ["The generic fixture asset manifest is copied into isolated test storage."],
            [
                "Inject ../escape.png.",
                "Invoke the public build CLI.",
                "Inspect output publication.",
            ],
            ["ASSET_DIRECTORY is rejected and no ZIP is published."],
            lambda: _tc_03(root, evidence_root),
        ),
        _safe_case(
            "TC-04",
            "Reject an oversized sparse asset before any Pillow probe or archive publication.",
            ["The generic fixture asset manifest is copied into isolated test storage."],
            [
                "Create a sparse asset larger than MAX_ASSET_PAYLOAD_BYTES.",
                "Invoke the public build CLI.",
            ],
            ["ASSET_DIRECTORY is rejected, Pillow is not probed, and no ZIP is published."],
            lambda: _tc_04(root, evidence_root),
        ),
        _safe_case(
            "TC-05",
            "Fail closed for a demand-side component mapping without a generatable definition.",
            ["The village fixture remains a generic mapping regression input."],
            [
                "Compile mapping to UIR.",
                "Compile UIR to Plan.",
                "Run the production special-case scan.",
            ],
            ["fgui.component.definition_missing blocks publication without a Writer special case."],
            lambda: _tc_05(root, evidence_root),
        ),
    ]
    assert tuple(case["id"] for case in cases) == _CASE_IDS
    return {"schemaVersion": 1, "cases": cases}


def write_acceptance_results(
    workspace: Path, evidence_root: Path, *, screenshots_pending: bool = False
) -> Path:
    """Write a machine result only after explicit pending or screenshot closure."""
    evidence_root.mkdir(parents=True, exist_ok=True)
    target = evidence_root / "new-project-writer-acceptance-results.json"
    result = finalize_screenshot_closure(
        run_acceptance(workspace, evidence_root),
        evidence_root,
        screenshots_pending=screenshots_pending,
    )
    target.write_bytes(canonical_acceptance_bytes(result))
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Writer acceptance matrix.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cards", type=Path)
    parser.add_argument("--screenshots-pending", action="store_true")
    arguments = parser.parse_args()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    result = run_acceptance(arguments.workspace, arguments.output.parent)
    if arguments.cards is not None:
        render_evidence_cards(result, arguments.cards)
    try:
        final = finalize_screenshot_closure(
            result,
            arguments.output.parent,
            screenshots_pending=arguments.screenshots_pending,
        )
    except ValueError as error:
        parser.error(str(error))
    arguments.output.write_bytes(canonical_acceptance_bytes(final))


if __name__ == "__main__":
    main()
