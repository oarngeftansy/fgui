from __future__ import annotations

from pathlib import Path

from figma_to_fgui.fgui_xml_dialect_614 import parse_editor_fixture

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_minimal_editor_fixture_is_recognized() -> None:
    fixture = parse_editor_fixture(FIXTURES / "fgui-editor-6.1.4/minimal")
    assert fixture.project_name == "Minimal"
    assert fixture.package_name == "Generated"
    assert fixture.component_names == ("Root",)
    assert fixture.component_sizes == ((320, 180),)
