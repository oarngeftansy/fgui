from typer.testing import CliRunner

from figma_to_fgui.cli import app


def test_help_lists_all_atomic_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("normalize", "index-project", "classify", "validate", "convert"):
        assert command in result.stdout
