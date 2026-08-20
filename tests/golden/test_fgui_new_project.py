from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from figma_to_fgui.cli import (
    _load_new_project_config,
    _load_plan_v2,
    load_declared_asset_directory,
)
from figma_to_fgui.fgui_new_project_build import (
    build_new_project,
    validate_project_archive,
)

FIXTURE = Path("tests/fixtures/fgui-new-project")
# This is deliberately a reviewed byte-level oracle, not a second generated file.
GENERIC_ARCHIVE_SHA256 = "bf62cd2789a7d0a44336e28a4c257d4fe91bee34c7673738bdf3f0662217c4ca"
EDITOR_TRANSCRIPT = Path(
    "docs/validation/2026-08-18-fgui-6.1.4-new-project-editor-transcript.json"
)


def test_generic_project_zip_matches_reviewed_byte_golden(tmp_path: Path) -> None:
    plan = _load_plan_v2(FIXTURE / "generic-plan-v2.json")
    config = _load_new_project_config(FIXTURE / "config.json")
    payloads = load_declared_asset_directory(FIXTURE / "assets", plan.resources)

    built = build_new_project(plan, config, payloads, tmp_path)
    content = built.path.read_bytes()

    assert hashlib.sha256(content).hexdigest() == GENERIC_ARCHIVE_SHA256
    assert built.sha256 == GENERIC_ARCHIVE_SHA256
    assert validate_project_archive(built.path, built.manifest) == ()
    with ZipFile(built.path) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == sorted(archive.namelist())
        component = next(
            name
            for name in archive.namelist()
            if name.endswith(".xml") and not name.endswith("package.xml")
        )
        assert b"<image " in archive.read(component)


def test_editor_hash_transcript_matches_representative_golden() -> None:
    transcript = json.loads(EDITOR_TRANSCRIPT.read_text("utf-8"))

    assert transcript["schemaVersion"] == 1
    assert transcript["projectName"] == "GenericWriterFixture"
    assert transcript["editorVersion"] == "6.1.4"
    assert transcript["artifact"] == {
        "byteSize": 1426,
        "sha256": GENERIC_ARCHIVE_SHA256,
    }
    assert transcript["gate"] == {
        "modalObserved": False,
        "rounds": ["open-save-close", "reopen-save-close"],
        "windowsAfterGate": 0,
    }
    assert len(transcript["files"]) == 4
    assert all(item["match"] is True for item in transcript["files"])
