from pathlib import Path

from figma_to_fgui.project_index import index_project


def test_indexes_package_resources_without_mutating_snapshot() -> None:
    root = Path("tests/fixtures/fgui")
    before = (root / "Sample/package.xml").read_bytes()
    index = index_project(root)
    assert index.packages["Sample"] == "sample01"
    assert index.by_name["Bg_Main.png"].id == "img00001"
    assert index.by_name["Existing.xml"].kind == "component"
    assert (root / "Sample/package.xml").read_bytes() == before
