from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import figma_to_fgui.fgui_xml_dialect_614 as dialect
from figma_to_fgui.fgui_xml_dialect_614 import parse_editor_fixture

FIXTURES = Path(__file__).parents[1] / "fixtures"
VALID_FIXTURE = FIXTURES / "fgui-editor-6.1.4/minimal"


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "fixture"
    shutil.copytree(VALID_FIXTURE, root)
    return root


def _marker(root: Path) -> Path:
    return root / "Minimal.fairy"


def _package(root: Path) -> Path:
    return root / "assets/Generated/package.xml"


def _component(root: Path) -> Path:
    return root / "assets/Generated/components/Root.xml"


def test_minimal_editor_fixture_is_recognized() -> None:
    fixture = parse_editor_fixture(VALID_FIXTURE)
    assert fixture.project_name == "Minimal"
    assert fixture.package_name == "Generated"
    assert fixture.component_names == ("Root",)
    assert fixture.component_sizes == ((320, 180),)


def test_single_leading_slash_resource_path_uses_package_virtual_root() -> None:
    fixture = parse_editor_fixture(VALID_FIXTURE)

    assert fixture.component_names == ("Root",)


def test_optional_component_xml_name_does_not_define_identity(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    _component(root).write_text(
        "<component name='DisplayAlias' size='320,180'><displayList/></component>", "utf-8"
    )

    fixture = parse_editor_fixture(root)

    assert fixture.component_names == ("Root",)


def test_malformed_project_marker_is_rejected(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    _marker(root).write_text("<projectDescription", "utf-8")

    with pytest.raises(ValueError, match="project marker"):
        parse_editor_fixture(root)


@pytest.mark.parametrize(
    "marker",
    [
        "<wrong id='88496b97754345efb9173265c58ee99b' type='Unity' version='5.0'/>",
        "<projectDescription id='' type='Unity' version='5.0'/>",
        "<projectDescription id='../secret' type='Unity' version='5.0'/>",
        "<projectDescription id='88496b97754345efb9173265c58ee99b' type='Web' version='5.0'/>",
        "<projectDescription id='88496b97754345efb9173265c58ee99b' type='Unity' version='6.1.4'/>",
    ],
    ids=["root", "empty-id", "invalid-id", "type", "version"],
)
def test_invalid_project_marker_is_rejected(tmp_path: Path, marker: str) -> None:
    root = _fixture(tmp_path)
    _marker(root).write_text(marker, "utf-8")

    with pytest.raises(ValueError, match="project marker"):
        parse_editor_fixture(root)


@pytest.mark.parametrize(
    "package",
    [
        "<packageDescription",
        "<wrong id='mrz8gz9s'><resources/><publish/></wrong>",
        "<packageDescription id=''><resources/><publish/></packageDescription>",
        "<packageDescription id='bad/id'><resources/><publish/></packageDescription>",
        "<packageDescription id='mrz8gz9s'><publish/></packageDescription>",
        "<packageDescription id='mrz8gz9s'><resources/></packageDescription>",
        (
            "<packageDescription id='mrz8gz9s'><resources>"
            "<component id='frrzw' name='Root.xml' path='components/'/>"
            "<image id='frrzw' name='image.png'/>"
            "</resources><publish/></packageDescription>"
        ),
        (
            "<packageDescription id='mrz8gz9s'><resources>"
            "<component id='' name='Root.xml' path='components/'/>"
            "</resources><publish/></packageDescription>"
        ),
        (
            "<packageDescription id='mrz8gz9s'><resources>"
            "<component id='bad/id' name='Root.xml' path='components/'/>"
            "</resources><publish/></packageDescription>"
        ),
    ],
    ids=[
        "malformed",
        "root",
        "empty-id",
        "invalid-id",
        "resources",
        "publish",
        "duplicate-resource-id",
        "empty-resource-id",
        "invalid-resource-id",
    ],
)
def test_invalid_package_structure_is_rejected(tmp_path: Path, package: str) -> None:
    root = _fixture(tmp_path)
    _package(root).write_text(package, "utf-8")

    with pytest.raises(ValueError, match="package"):
        parse_editor_fixture(root)


@pytest.mark.parametrize(
    ("path", "name"),
    [
        ("../../../", "outside.xml"),
        ("//components/", "Root.xml"),
        ("/../", "Root.xml"),
        ("/components//nested/", "Root.xml"),
        ("C:/components/", "Root.xml"),
        ("/C:/components/", "Root.xml"),
        ("\\\\server\\share\\", "Root.xml"),
        ("components/", "nested/Root.xml"),
        ("components/", r"nested\Root.xml"),
        ("components/", "Root\u007f.xml"),
        ("components/Root\u007f/", "Root.xml"),
        ("components/", ""),
    ],
    ids=[
        "traversal",
        "double-leading-slash",
        "virtual-root-traversal",
        "embedded-empty-segment",
        "drive",
        "virtual-root-drive",
        "unc",
        "name-posix-dir",
        "name-win-dir",
        "name-control",
        "path-control",
        "empty-name",
    ],
)
def test_unsafe_resource_path_or_name_is_rejected(
    tmp_path: Path, path: str, name: str
) -> None:
    root = _fixture(tmp_path)
    outside = tmp_path / "outside.xml"
    outside.write_text("<component name='Outside' size='1,1'><displayList/></component>", "utf-8")
    _package(root).write_text(
        "<packageDescription id='mrz8gz9s'><resources>"
        f"<component id='frrzw' name='{name}' path='{path}'/>"
        "</resources><publish/></packageDescription>",
        "utf-8",
    )

    with pytest.raises(ValueError, match="resource"):
        parse_editor_fixture(root)

    assert outside.read_text("utf-8").startswith("<component name='Outside'")


def test_path_escape_is_rejected_before_fixture_external_xml_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fixture(tmp_path)
    outside = tmp_path / "outside.xml"
    outside.write_text("<component name='Outside' size='1,1'><displayList/></component>", "utf-8")
    _package(root).write_text(
        "<packageDescription id='mrz8gz9s'><resources>"
        "<component id='frrzw' name='outside.xml' path='../../../'/>"
        "</resources><publish/></packageDescription>",
        "utf-8",
    )
    parse_xml = dialect.etree.parse

    def guarded_parse(path: str, parser: object) -> object:
        if Path(path) == outside:
            pytest.fail("parser read XML outside the fixture")
        return parse_xml(path, parser)

    monkeypatch.setattr(dialect.etree, "parse", guarded_parse)

    with pytest.raises(ValueError, match="unsafe resource path"):
        parse_editor_fixture(root)


@pytest.mark.parametrize(
    "component",
    [
        "<component",
        "<wrong name='Root' size='320,180'><displayList/></wrong>",
        "<component name='' size='320,180'><displayList/></component>",
        "<component name='../Root' size='320,180'><displayList/></component>",
        "<component name='Root&#x7f;' size='320,180'><displayList/></component>",
        "<component name='Root' size='320'><displayList/></component>",
        "<component name='Root' size='0,180'><displayList/></component>",
        "<component name='Root' size='320,-1'><displayList/></component>",
        "<component name='Root' size='320,180'/>",
    ],
    ids=[
        "malformed",
        "root",
        "empty-name",
        "unsafe-name",
        "control-name",
        "size-arity",
        "zero-size",
        "negative-size",
        "display-list",
    ],
)
def test_invalid_component_structure_is_rejected(tmp_path: Path, component: str) -> None:
    root = _fixture(tmp_path)
    _component(root).write_text(component, "utf-8")

    with pytest.raises(ValueError, match="component"):
        parse_editor_fixture(root)


@pytest.mark.parametrize(
    "publish",
    [
        "<publish/>",
        '<publish name="" path="../Assets/Art/ui/generated" packageCount="2"/>',
    ],
    ids=["empty", "observed-attributes"],
)
def test_observed_empty_publish_shapes_are_accepted(tmp_path: Path, publish: str) -> None:
    root = _fixture(tmp_path)
    _package(root).write_text(
        "<packageDescription id='mrz8gz9s'><resources>"
        "<component id='frrzw' name='Root.xml' path='/components/'/>"
        f"</resources>{publish}</packageDescription>",
        "utf-8",
    )

    assert parse_editor_fixture(root).component_names == ("Root",)


@pytest.mark.parametrize(
    "publish",
    ["<publish><unexpected/></publish>", "<publish>unexpected text</publish>"],
    ids=["child", "text"],
)
def test_publish_rejects_unobserved_nonempty_structure(tmp_path: Path, publish: str) -> None:
    root = _fixture(tmp_path)
    _package(root).write_text(
        "<packageDescription id='mrz8gz9s'><resources>"
        "<component id='frrzw' name='Root.xml' path='/components/'/>"
        f"</resources>{publish}</packageDescription>",
        "utf-8",
    )

    with pytest.raises(ValueError, match="package publish"):
        parse_editor_fixture(root)


def test_component_symlink_escape_is_rejected(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    outside = tmp_path / "outside.xml"
    outside.write_text("<component name='Root' size='320,180'><displayList/></component>", "utf-8")
    target = _component(root)
    target.unlink()
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("Windows user cannot create file symlinks")

    with pytest.raises(ValueError, match="symlink or reparse"):
        parse_editor_fixture(root)


def test_component_reparse_point_is_rejected_without_symlink_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fixture(tmp_path)
    target = _component(root)
    original_lstat = Path.lstat
    monkeypatch.setattr(Path, "is_symlink", lambda _path: False)
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda path: (
            SimpleNamespace(st_file_attributes=0x400)
            if path == target
            else original_lstat(path)
        ),
    )

    with pytest.raises(ValueError, match="symlink or reparse"):
        parse_editor_fixture(root)
