import pytest

from figma_to_fgui.paths import safe_relative_path


@pytest.mark.parametrize("value", ["../package.xml", "/tmp/x", "C:/x", "Panel/../../x"])
def test_rejects_paths_outside_project(value: str) -> None:
    with pytest.raises(ValueError, match="unsafe relative path"):
        safe_relative_path(value)


def test_normalizes_windows_separators() -> None:
    assert safe_relative_path(r"Sample\Panel\Main.xml") == "Sample/Panel/Main.xml"
