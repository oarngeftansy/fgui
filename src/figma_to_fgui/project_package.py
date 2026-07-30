from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from figma_to_fgui.apply import apply_bundle
from figma_to_fgui.models import Diagnostic, FrozenModel
from figma_to_fgui.service_contracts import ChangeBundle
from figma_to_fgui.uploaded_project import index_uploaded_project

_PROJECT_NAME = re.compile(r"^[\w\-\u4e00-\u9fff]{1,64}$")
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_GENERATED_DIRECTORIES = {".figma-to-fgui", ".figma-to-fgui-preview"}


class BuiltProjectPackage(FrozenModel):
    path: Path
    download_name: str
    sha256: str
    changed_paths: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...] = ()


def _reject_symlinks(root: Path) -> None:
    if root.is_symlink() or any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("project contains a symlink")


def _write_deterministic_zip(project_root: Path, target: Path) -> None:
    members = sorted(
        (path.relative_to(project_root).as_posix(), path)
        for path in project_root.rglob("*")
        if path.is_file()
    )
    with ZipFile(target, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for relative_path, source in members:
            info = ZipInfo(relative_path, date_time=_ZIP_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes(), compresslevel=9)


def _remove_generated_directories(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and path.name in _GENERATED_DIRECTORIES:
            shutil.rmtree(path)


def build_project_package(
    project_root: Path,
    bundle: ChangeBundle,
    mode: Literal["create", "update"],
    project_name: str,
    output_directory: Path,
    clock: Callable[[], datetime] = datetime.now,
) -> BuiltProjectPackage:
    if mode not in ("create", "update"):
        raise ValueError("invalid package mode")
    if _PROJECT_NAME.fullmatch(project_name) is None:
        raise ValueError("invalid project name")
    if not project_root.is_dir():
        raise ValueError("project root must be a directory")
    _reject_symlinks(project_root)

    action = "新建" if mode == "create" else "更新"
    download_name = f"{project_name}-Figma{action}-{clock():%Y%m%d-%H%M}.zip"
    output_directory.mkdir(parents=True, exist_ok=True)
    published = output_directory / download_name

    with tempfile.TemporaryDirectory(prefix="project-package-", dir=output_directory) as temporary:
        temporary_root = Path(temporary)
        working = temporary_root / "project"
        shutil.copytree(project_root, working)
        summary = apply_bundle(working, bundle)
        indexed = index_uploaded_project(working, download_name)
        if not indexed.packages:
            raise ValueError("project contains no FairyGUI package")
        _remove_generated_directories(working)

        archive_path = temporary_root / "package.zip"
        _write_deterministic_zip(working, archive_path)
        os.replace(archive_path, published)

    return BuiltProjectPackage(
        path=published,
        download_name=download_name,
        sha256=hashlib.sha256(published.read_bytes()).hexdigest(),
        changed_paths=summary.changed_paths,
    )
