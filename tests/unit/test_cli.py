from pathlib import Path

from pytest import MonkeyPatch
from typer.testing import CliRunner

from figma_to_fgui.agent import AgentClient, AgentConfig
from figma_to_fgui.cli import app
from figma_to_fgui.service_contracts import ApplyResult, ApplyStatus


def test_help_lists_all_atomic_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("normalize", "index-project", "classify", "validate", "convert", "serve", "agent"):
        assert command in result.stdout


def test_agent_poll_prints_terminal_result(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config = AgentConfig(agent_id="agent-1", name="Desk")
    result = ApplyResult(
        job_id="job-1",
        agent_id="agent-1",
        project_id="project-1",
        status=ApplyStatus.APPLIED,
        changed_paths=("Sample/Main.xml",),
    )
    monkeypatch.setattr(AgentConfig, "load", classmethod(lambda cls, path: config))
    monkeypatch.setattr(AgentClient, "poll_once", lambda self: result)

    invoked = CliRunner().invoke(
        app,
        ["agent", "poll", "--config-path", str(tmp_path / "agent.json")],
    )
    assert invoked.exit_code == 0
    assert '"status": "applied"' in invoked.stdout
    assert "Sample/Main.xml" in invoked.stdout
