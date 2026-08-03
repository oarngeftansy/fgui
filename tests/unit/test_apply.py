from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

import pytest

from figma_to_fgui.apply import ApplyFailed, SourceConflict, UnsafeTarget, apply_bundle
from figma_to_fgui.service_contracts import ChangeBundle, ChangeFile, FileOperation


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def change_file(path: str, before: bytes | None, after: bytes) -> ChangeFile:
    return ChangeFile(
        operation=FileOperation.CREATE if before is None else FileOperation.REPLACE,
        relative_path=path,
        before_sha256=None if before is None else digest(before),
        after_sha256=digest(after),
        content_b64=base64.b64encode(after).decode("ascii"),
    )


def bundle(*files: ChangeFile) -> ChangeBundle:
    return ChangeBundle(job_id="job-1", project_id="project-1", files=files)


def project_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".figma-to-fgui" not in path.parts
    }


def test_apply_creates_and_replaces_declared_files(tmp_path: Path) -> None:
    old = b"<component name='old'/>"
    new = b"<component name='new'/>"
    (tmp_path / "Old.xml").write_bytes(old)

    result = apply_bundle(
        tmp_path,
        bundle(
            change_file("Old.xml", old, new),
            change_file("Folder/New.xml", None, b"<component/>"),
        ),
    )

    assert result.changed_paths == ("Old.xml", "Folder/New.xml")
    assert (tmp_path / "Old.xml").read_bytes() == new
    assert (tmp_path / "Folder/New.xml").read_bytes() == b"<component/>"
    assert (tmp_path / ".figma-to-fgui/backups/job-1/Old.xml").read_bytes() == old


def test_apply_rejects_stale_replace_without_writing(tmp_path: Path) -> None:
    target = tmp_path / "Sample.xml"
    target.write_bytes(b"local edit")
    with pytest.raises(SourceConflict):
        apply_bundle(tmp_path, bundle(change_file("Sample.xml", b"expected", b"<component/>")))
    assert target.read_bytes() == b"local edit"
    assert not (tmp_path / ".figma-to-fgui").exists()


def test_invalid_xml_is_rejected_before_writing(tmp_path: Path) -> None:
    with pytest.raises(ApplyFailed):
        apply_bundle(tmp_path, bundle(change_file("Broken.xml", None, b"<component>")))
    assert project_files(tmp_path) == {}


def test_mid_commit_failure_restores_every_file(tmp_path: Path) -> None:
    first = b"<component name='first-old'/>"
    second = b"<component name='second-old'/>"
    (tmp_path / "First.xml").write_bytes(first)
    (tmp_path / "Second.xml").write_bytes(second)
    original = project_files(tmp_path)
    calls = 0

    def fail_on_second(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected failure")
        os.replace(source, target)

    with pytest.raises(ApplyFailed) as error:
        apply_bundle(
            tmp_path,
            bundle(
                change_file("First.xml", first, b"<component name='first-new'/>"),
                change_file("Second.xml", second, b"<component name='second-new'/>"),
            ),
            replace_file=fail_on_second,
        )
    assert project_files(tmp_path) == original
    assert error.value.rollback_succeeded is True


def test_apply_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows user cannot create directory symlinks")

    with pytest.raises(UnsafeTarget):
        apply_bundle(tmp_path, bundle(change_file("linked/file.xml", None, b"<component/>")))
    assert not (outside / "file.xml").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows MAX_PATH regression")
def test_apply_writes_long_asset_path_with_short_temporary_name(tmp_path: Path) -> None:
    """The final asset fits MAX_PATH but the legacy temp name did not."""
    filename = f"asset-{'a' * 80}.png"
    directory_length = max(0, 238 - len(str(tmp_path)) - len(filename) - 1)
    target = tmp_path / ("d" * directory_length) / filename
    job_id = "f" * 32
    legacy_temporary = target.with_name(f".{target.name}.{job_id}.tmp")

    assert len(str(target)) < 260
    assert len(str(legacy_temporary)) > 260

    apply_bundle(
        tmp_path,
        ChangeBundle(
            job_id=job_id,
            project_id="project-1",
            files=(change_file(target.relative_to(tmp_path).as_posix(), None, b"asset"),),
        ),
    )

    assert target.read_bytes() == b"asset"


def _windows_long_asset_targets(tmp_path: Path) -> tuple[Path, Path]:
    filename_length = len("asset-.png") + 80
    directory_length = max(0, 238 - len(str(tmp_path)) - filename_length - 1)
    directory = tmp_path / ("d" * directory_length)
    return (
        directory / f"asset-{'a' * 79}1.png",
        directory / f"asset-{'a' * 79}2.png",
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows MAX_PATH regression")
def test_apply_replaces_long_asset_path_with_short_backup_name(tmp_path: Path) -> None:
    target, _ = _windows_long_asset_targets(tmp_path)
    old = b"old asset"
    target.parent.mkdir(parents=True)
    target.write_bytes(old)
    job_id = "f" * 32
    legacy_backup = tmp_path / ".figma-to-fgui" / "backups" / job_id / target.relative_to(tmp_path)

    assert len(str(target)) < 260
    assert len(str(legacy_backup)) > 260

    result = apply_bundle(
        tmp_path,
        ChangeBundle(
            job_id=job_id,
            project_id="project-1",
            files=(change_file(target.relative_to(tmp_path).as_posix(), old, b"new asset"),),
        ),
    )

    backup_root = tmp_path / result.backup_root
    backups = tuple(path for path in backup_root.iterdir() if path.is_file())
    assert target.read_bytes() == b"new asset"
    assert len(backups) == 1
    assert backups[0].read_bytes() == old


@pytest.mark.skipif(os.name != "nt", reason="Windows MAX_PATH regression")
def test_long_asset_backups_are_unique_and_restore_on_rollback(tmp_path: Path) -> None:
    first, second = _windows_long_asset_targets(tmp_path)
    first_old = b"first old"
    second_old = b"second old"
    first.parent.mkdir(parents=True)
    first.write_bytes(first_old)
    second.write_bytes(second_old)
    calls = 0

    def fail_on_second(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected failure")
        os.replace(source, target)

    with pytest.raises(ApplyFailed) as error:
        apply_bundle(
            tmp_path,
            ChangeBundle(
                job_id="f" * 32,
                project_id="project-1",
                files=(
                    change_file(first.relative_to(tmp_path).as_posix(), first_old, b"first new"),
                    change_file(second.relative_to(tmp_path).as_posix(), second_old, b"second new"),
                ),
            ),
            replace_file=fail_on_second,
        )

    backup_root = tmp_path / ".figma-to-fgui" / "backups" / ("f" * 32)
    backups = tuple(path for path in backup_root.iterdir() if path.is_file())
    assert calls == 2
    assert len(backups) == 2
    assert first.read_bytes() == first_old
    assert second.read_bytes() == second_old
    assert error.value.rollback_succeeded is True
