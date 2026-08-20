"""Run the closed, privacy-safe Writer acceptance matrix.

This runner intentionally composes the existing Writer and CLI boundaries.  It
does not reproduce Writer implementation details or create Project Bindings.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

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
from figma_to_fgui.fgui_plan_validate import validate_fgui_plan
from figma_to_fgui.normalize import normalize_document
from figma_to_fgui.project_index import index_project
from figma_to_fgui.uir_compile import compile_uir

_CASE_IDS = ("TC-01", "TC-02", "AC-01", "TC-03", "TC-04", "TC-05")
_FIXTURE_DIRECTORY = Path("tests/fixtures/fgui-new-project")
_EDITOR_TRANSCRIPT = Path(
    "docs/validation/2026-08-18-fgui-6.1.4-new-project-editor-transcript.json"
)
_PRODUCTION_ROOTS = (Path("src/figma_to_fgui"), Path("rules/default"))
_PRODUCTION_SUFFIXES = frozenset({".json", ".py", ".toml", ".yaml", ".yml"})
_SAMPLE_ONLY_MARKERS = (
    "村庄升阶",
    "village-root",
    "selection_village_ascend",
    "village_background",
    "primary-button",
    "rank-before",
)
_GENERIC_MAPPING_TERMS = ("common_primary_button", "通用一级按钮", "23:55")
_GENERIC_MAPPING_ALLOWLIST = frozenset({Path("rules/default/component-mapping-candidates.json")})
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


def _run_hostile_cli(workspace: Path, asset_directory: Path, output: Path) -> tuple[bool, str]:
    fixture = workspace / _FIXTURE_DIRECTORY
    invocation = CliRunner().invoke(
        app,
        [
            "build-fgui-project",
            str(fixture / "generic-plan-v2.json"),
            str(fixture / "config.json"),
            str(asset_directory),
            str(output),
        ],
    )
    return invocation.exit_code == 2 and "ASSET_DIRECTORY" in invocation.output, invocation.output


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
        rejected, _ = _run_hostile_cli(workspace, assets, output)
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
            rejected, _ = _run_hostile_cli(workspace, assets, output)
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


def _production_special_case_violations(workspace: Path) -> tuple[tuple[str, str], ...]:
    violations: list[tuple[str, str]] = []
    for root in _PRODUCTION_ROOTS:
        for path in sorted((workspace / root).rglob("*")):
            if not path.is_file() or path.suffix.casefold() not in _PRODUCTION_SUFFIXES:
                continue
            relative = path.relative_to(workspace)
            content = path.read_text("utf-8")
            violations.extend(
                (relative.as_posix(), marker)
                for marker in _SAMPLE_ONLY_MARKERS
                if marker in content
            )
            for term in _GENERIC_MAPPING_TERMS:
                occurrences = content.count(term)
                allowed_once = relative in _GENERIC_MAPPING_ALLOWLIST and occurrences == 1
                if occurrences and not allowed_once:
                    violations.append((relative.as_posix(), term))
    return tuple(violations)


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
    special_case_scan = _production_special_case_violations(workspace) == ()
    output = evidence_root / "tc-05-output"
    published = _zip_publication_exists(output)
    passed = (
        "fgui.component.definition_missing" in codes
        and not plan.bindable
        and special_case_scan
        and not published
    )
    return (
        passed,
        [
            "diagnostic=fgui.component.definition_missing"
            if "fgui.component.definition_missing" in codes
            else "diagnostic=missing",
            f"productionSpecialCaseScan={'true' if special_case_scan else 'false'}",
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


def write_acceptance_results(workspace: Path, evidence_root: Path) -> Path:
    """Write the canonical machine result beneath an explicitly supplied evidence root."""
    evidence_root.mkdir(parents=True, exist_ok=True)
    target = evidence_root / "new-project-writer-acceptance-results.json"
    target.write_bytes(canonical_acceptance_bytes(run_acceptance(workspace, evidence_root)))
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Writer acceptance matrix.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_bytes(
        canonical_acceptance_bytes(run_acceptance(arguments.workspace, arguments.output.parent))
    )


if __name__ == "__main__":
    main()
