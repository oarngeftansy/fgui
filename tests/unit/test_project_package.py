from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest
from lxml import etree

from figma_to_fgui.project_package import build_project_package
from figma_to_fgui.service_contracts import ChangeBundle, ChangeFile, FileOperation


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _project(root: Path) -> Path:
    package = root / "Quiz"
    package.mkdir(parents=True)
    (package / "package.xml").write_text(
        "<package id='quiz'><resources><component id='main' name='Main.xml'/></resources></package>",
        "utf-8",
    )
    (package / "Main.xml").write_text("<component name='old'/>", "utf-8")
    return root


def _bundle(before: bytes, after: bytes) -> ChangeBundle:
    return ChangeBundle(
        job_id="job-1",
        project_id="project-1",
        files=(
            ChangeFile(
                operation=FileOperation.REPLACE,
                relative_path="Quiz/Main.xml",
                before_sha256=_digest(before),
                after_sha256=_digest(after),
                content_b64=base64.b64encode(after).decode("ascii"),
            ),
        ),
    )


def _fingerprint(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _clock() -> datetime:
    return datetime(2026, 7, 30, 15, 30, tzinfo=UTC)


def _empty_bundle() -> ChangeBundle:
    return ChangeBundle(job_id="job-empty", project_id="project-1", files=())


def test_package_applies_bundle_to_copy_and_keeps_source_unchanged(tmp_path: Path) -> None:
    source = _project(tmp_path / "source")
    before = _fingerprint(source)
    replacement = b"<component name='new'/>"

    built = build_project_package(
        source,
        _bundle((source / "Quiz/Main.xml").read_bytes(), replacement),
        "update",
        "Quiz",
        tmp_path / "out",
        _clock,
    )

    assert _fingerprint(source) == before
    with ZipFile(built.path) as archive:
        assert etree.fromstring(archive.read("Quiz/Main.xml")).attrib["name"] == "new"
        assert etree.fromstring(archive.read("Quiz/package.xml")).tag == "package"
    assert built.download_name == "Quiz-Figma更新-20260730-1530.zip"
    assert built.changed_paths == ("Quiz/Main.xml",)


def test_create_name_sha256_and_diagnostics_match_published_archive(tmp_path: Path) -> None:
    built = build_project_package(
        _project(tmp_path / "source"),
        _empty_bundle(),
        "create",
        "Quiz",
        tmp_path / "out",
        _clock,
    )

    assert built.download_name == "Quiz-Figma新建-20260730-1530.zip"
    assert built.path.name == built.download_name
    assert built.sha256 == hashlib.sha256(built.path.read_bytes()).hexdigest()
    assert built.changed_paths == ()
    assert built.diagnostics == ()


def test_zip_is_deterministic_and_excludes_generated_directories(tmp_path: Path) -> None:
    source = _project(tmp_path / "source")
    (source / ".figma-to-fgui" / "backups" / "old").mkdir(parents=True)
    (source / ".figma-to-fgui" / "backups" / "old" / "Main.xml").write_text("old", "utf-8")
    (source / "Quiz" / ".figma-to-fgui-preview").mkdir()
    (source / "Quiz" / ".figma-to-fgui-preview" / "preview.webp").write_bytes(b"preview")

    first = build_project_package(
        source, _empty_bundle(), "update", "Quiz", tmp_path / "first", _clock
    )
    second = build_project_package(
        source, _empty_bundle(), "update", "Quiz", tmp_path / "second", _clock
    )

    assert first.path.read_bytes() == second.path.read_bytes()
    with ZipFile(first.path) as archive:
        assert archive.namelist() == sorted(archive.namelist())
        assert {item.date_time for item in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        assert not any(".figma-to-fgui" in name for name in archive.namelist())
    assert (source / ".figma-to-fgui/backups/old/Main.xml").read_text("utf-8") == "old"
    assert (source / "Quiz/.figma-to-fgui-preview/preview.webp").read_bytes() == b"preview"


def test_invalid_project_fails_without_publishing_partial_zip(tmp_path: Path) -> None:
    source = _project(tmp_path / "source")
    (source / "Quiz" / "package.xml").write_text("<package>", "utf-8")
    output = tmp_path / "out"

    with pytest.raises((etree.XMLSyntaxError, ValueError)):
        build_project_package(source, _empty_bundle(), "update", "Quiz", output, _clock)

    assert not list(output.glob("*.zip"))


@pytest.mark.parametrize("project_name", ("../Quiz", "Quiz/Other", "", "x" * 65))
def test_unsafe_project_name_is_rejected(project_name: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid project name"):
        build_project_package(
            _project(tmp_path / "source"),
            _empty_bundle(),
            "create",
            project_name,
            tmp_path / "out",
            _clock,
        )

    assert not (tmp_path / "out").exists()


def test_source_symlink_is_rejected_without_reading_outside_project(tmp_path: Path) -> None:
    source = _project(tmp_path / "source")
    outside = tmp_path / "outside.txt"
    outside.write_text("private", "utf-8")
    link = source / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Windows user cannot create symlinks")

    with pytest.raises(ValueError, match="symlink"):
        build_project_package(source, _empty_bundle(), "update", "Quiz", tmp_path / "out", _clock)

    assert not (tmp_path / "out").exists()
