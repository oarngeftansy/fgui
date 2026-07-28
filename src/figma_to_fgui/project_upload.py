from __future__ import annotations

import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile, ZipInfo

from lxml import etree

from figma_to_fgui.paths import safe_relative_path


@dataclass(frozen=True)
class UploadLimits:
    max_compressed_bytes: int = 500 * 1024 * 1024
    max_total_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024
    max_entries: int = 20_000
    max_file_bytes: int = 100 * 1024 * 1024
    max_compression_ratio: float = 20.0


class UploadError(RuntimeError):
    def __init__(self, code: str, user_message: str) -> None:
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message


@dataclass(frozen=True)
class ExtractedProject:
    root: Path
    files: tuple[str, ...]


_INVALID_PROJECT = "这个 ZIP 不是有效的 FairyGUI 工程。"
_ARCHIVE_TOO_LARGE = "压缩包过大或包含过多文件，请缩小后重试。"
_UNSAFE_ARCHIVE = "无法安全读取这个压缩包。"
DEFAULT_UPLOAD_LIMITS = UploadLimits()


def _project_root(files: tuple[str, ...], extracted_root: Path) -> tuple[Path, tuple[str, ...]]:
    package_paths = tuple(path for path in files if path.endswith("/package.xml"))
    if not package_paths:
        raise UploadError("invalid_fgui_project", _INVALID_PROJECT)

    package_depths = {len(PurePosixPath(path).parts) - 2 for path in package_paths}
    if package_depths - {0, 1} or len(package_depths) != 1:
        raise UploadError("invalid_fgui_project", _INVALID_PROJECT)

    depth = package_depths.pop()
    wrapper = "" if depth == 0 else PurePosixPath(package_paths[0]).parts[0]
    if wrapper and any(PurePosixPath(path).parts[0] != wrapper for path in files):
        raise UploadError("invalid_fgui_project", _INVALID_PROJECT)

    relative_files = tuple(path if not wrapper else "/".join(PurePosixPath(path).parts[1:]) for path in files)
    root = extracted_root / wrapper if wrapper else extracted_root
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        for path in relative_files:
            if path.endswith("/package.xml"):
                document = etree.parse(str(root / path), parser)
                if etree.QName(document.getroot()).localname != "package":
                    raise UploadError("invalid_fgui_project", _INVALID_PROJECT)
    except etree.XMLSyntaxError as error:
        raise UploadError("invalid_fgui_project", _INVALID_PROJECT) from error
    return root, relative_files


def _upload_error(code: str) -> UploadError:
    messages = {
        "archive_too_large": _ARCHIVE_TOO_LARGE,
        "invalid_fgui_project": _INVALID_PROJECT,
        "unsafe_archive": _UNSAFE_ARCHIVE,
    }
    return UploadError(code, messages[code])


def _safe_name(entry_name: str) -> str:
    if "\x00" in entry_name:
        raise _upload_error("unsafe_archive")
    try:
        relative = safe_relative_path(entry_name)
    except ValueError as error:
        raise _upload_error("unsafe_archive") from error
    if relative == ".":
        raise _upload_error("unsafe_archive")
    return relative


def _validate_entries(archive: ZipFile, limits: UploadLimits) -> tuple[tuple[ZipInfo, str], ...]:
    entries = archive.infolist()
    if len(entries) > limits.max_entries:
        raise _upload_error("archive_too_large")

    normalized: set[str] = set()
    total_uncompressed = 0
    total_compressed = 0
    safe_entries: list[tuple[ZipInfo, str]] = []
    for entry in entries:
        original_name = getattr(entry, "orig_filename", entry.filename)
        relative = _safe_name(original_name)
        if relative in normalized or stat.S_ISLNK(entry.external_attr >> 16):
            raise _upload_error("unsafe_archive")
        normalized.add(relative)
        if entry.is_dir():
            continue
        if entry.file_size > limits.max_file_bytes:
            raise _upload_error("archive_too_large")
        with archive.open(entry):
            pass
        total_uncompressed += entry.file_size
        total_compressed += entry.compress_size
        if total_uncompressed > limits.max_total_uncompressed_bytes:
            raise _upload_error("archive_too_large")
        safe_entries.append((entry, relative))

    if total_uncompressed and (
        not total_compressed or total_uncompressed / total_compressed > limits.max_compression_ratio
    ):
        raise _upload_error("archive_too_large")
    return tuple(safe_entries)


def _copy_entry(archive: ZipFile, entry: ZipInfo, target: Path, limits: UploadLimits) -> int:
    written = 0
    with archive.open(entry) as zipped, target.open("wb") as output:
        while chunk := zipped.read(64 * 1024):
            written += len(chunk)
            if written > limits.max_file_bytes:
                raise _upload_error("archive_too_large")
            output.write(chunk)
    return written


def extract_project_zip(
    source: Path,
    destination: Path,
    limits: UploadLimits = DEFAULT_UPLOAD_LIMITS,
) -> ExtractedProject:
    destination = destination.absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        if source.stat().st_size > limits.max_compressed_bytes:
            raise _upload_error("archive_too_large")
        files: list[str] = []
        with ZipFile(source) as archive:
            entries = _validate_entries(archive, limits)
            total_uncompressed = 0
            for entry, relative in entries:
                files.append(relative)
                target = temporary / relative
                try:
                    target.resolve(strict=False).relative_to(temporary.resolve())
                except ValueError as error:
                    raise _upload_error("unsafe_archive") from error
                target.parent.mkdir(parents=True, exist_ok=True)
                total_uncompressed += _copy_entry(archive, entry, target, limits)
                if total_uncompressed > limits.max_total_uncompressed_bytes:
                    raise _upload_error("archive_too_large")

        root, relative_files = _project_root(tuple(files), temporary)
        relative_root = root.relative_to(temporary)
        os.replace(temporary, destination)
        return ExtractedProject(destination / relative_root, relative_files)
    except UploadError:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    except (BadZipFile, EOFError, OSError, RuntimeError) as error:
        shutil.rmtree(temporary, ignore_errors=True)
        raise _upload_error("unsafe_archive") from error
