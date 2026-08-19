from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from typer.testing import CliRunner

from figma_to_fgui.cli import app

FIXTURE = Path("tests/fixtures/fgui-new-project")


def _invoke(tmp_path: Path, *, plan: Path | None = None):
    return CliRunner().invoke(
        app,
        [
            "build-fgui-project",
            str(plan or FIXTURE / "generic-plan-v2.json"),
            str(FIXTURE / "config.json"),
            str(FIXTURE / "assets"),
            str(tmp_path),
        ],
    )


def test_build_fgui_project_cli_emits_verified_zip(tmp_path: Path) -> None:
    result = _invoke(tmp_path)

    assert result.exit_code == 0, result.output
    artifacts = list(tmp_path.glob("*.zip"))
    assert len(artifacts) == 1
    with ZipFile(artifacts[0]) as archive:
        assert archive.testzip() is None
    public_result = json.loads(result.stdout)
    assert public_result["project_name"] == "GenericWriterFixture"
    assert public_result["sha256"]
    assert "path" not in public_result


def test_build_fgui_project_cli_publishes_nothing_for_unbindable_plan(
    tmp_path: Path,
) -> None:
    source = json.loads((FIXTURE / "generic-plan-v2.json").read_text("utf-8"))
    source["bindable"] = False
    blocked = tmp_path / "blocked.json"
    blocked.write_text(json.dumps(source), "utf-8")

    result = _invoke(tmp_path / "out", plan=blocked)

    assert result.exit_code == 2
    output = tmp_path / "out"
    assert not output.exists() or list(output.glob("*.zip")) == []
    assert "Traceback" not in result.output
