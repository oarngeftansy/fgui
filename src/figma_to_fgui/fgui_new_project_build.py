"""Five-gate builder for fresh, deterministic FairyGUI project archives."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory, mkstemp
from typing import TypeVar

from figma_to_fgui.fgui_asset_payloads import ValidatedAssetPayload, validate_asset_payloads
from figma_to_fgui.fgui_new_project_compile import compile_new_project_manifest
from figma_to_fgui.fgui_new_project_models import (
    AssetPayloadSet,
    NewProjectConfig,
    NewProjectManifest,
)
from figma_to_fgui.fgui_new_project_validate import (
    canonical_manifest_bytes,
    validate_project_archive,
    validate_project_directory,
    validate_xml_files,
)
from figma_to_fgui.fgui_plan_models import FGUIPlanDocument
from figma_to_fgui.fgui_xml_dialect_614 import serialize_project_files
from figma_to_fgui.models import Diagnostic, FrozenModel, Severity
from figma_to_fgui.project_package import _sha256_file, write_deterministic_zip

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_GateResult = TypeVar("_GateResult")


class BuiltNewProject(FrozenModel):
    """One validated archive that has crossed the atomic publish boundary."""

    path: Path
    download_name: str
    sha256: str
    byte_size: int
    project_name: str
    manifest: NewProjectManifest

    @classmethod
    def from_verified(
        cls,
        path: Path,
        manifest: NewProjectManifest,
        *,
        sha256: str,
        byte_size: int,
    ) -> BuiltNewProject:
        return cls(
            path=path,
            download_name=f"{manifest.project.project_name}-FairyGUI.zip",
            sha256=sha256,
            byte_size=byte_size,
            project_name=manifest.project.project_name,
            manifest=manifest,
        )


class NewProjectBuildError(Exception):
    """A build boundary failed; diagnostics never expose private exception details."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("New FairyGUI project build failed.")


def _diagnostic(boundary: str) -> Diagnostic:
    return Diagnostic(
        code=f"fgui.writer.build.{boundary}_failed",
        severity=Severity.ERROR,
        message="A new-project build gate failed.",
        rule_id=f"fgui.writer.build.{boundary}_failed",
        rule_version=1,
        evidence=(f"gate={boundary}",),
        suggested_action="Repair the build input or destination and retry.",
        blocks_binding=True,
    )


def _fail(boundary: str) -> NewProjectBuildError:
    return NewProjectBuildError((_diagnostic(boundary),))


def _run_gate(boundary: str, operation: Callable[[], _GateResult]) -> _GateResult:
    """Close exception chaining before a public build error crosses the boundary."""
    failure: NewProjectBuildError | None = None
    try:
        return operation()
    except NewProjectBuildError as error:
        failure = error
    except Exception:  # noqa: BLE001 - public gate closes operational exception details.
        failure = _fail(boundary)
    if failure is not None:
        raise failure from None
    raise AssertionError("unreachable build gate state")


def _require_clean(diagnostics: tuple[Diagnostic, ...]) -> None:
    if diagnostics:
        raise ValueError("build gate returned diagnostics")


def _is_link_or_reparse(path: Path) -> bool:
    metadata = path.lstat()
    attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & _REPARSE_POINT)


def _prepare_output_directory(output_directory: Path) -> Path:
    failure: NewProjectBuildError | None = None
    try:
        if output_directory.exists() or output_directory.is_symlink():
            if not output_directory.is_dir() or _is_link_or_reparse(output_directory):
                raise OSError
        else:
            output_directory.mkdir(parents=True)
        return output_directory.resolve(strict=True)
    except OSError:
        failure = _fail("output_invalid")
    if failure is not None:
        raise failure from None
    raise AssertionError("unreachable output preparation state")


def write_declared_files(
    temporary: Path,
    manifest: NewProjectManifest,
    files: dict[str, bytes],
    assets: tuple[ValidatedAssetPayload, ...],
) -> Path:
    """Materialize only serializer-declared files beneath one fresh project root."""
    del assets
    project_root = temporary / manifest.project.project_name
    project_root.mkdir()
    try:
        for relative, content in files.items():
            parts = relative.split("/")
            if not parts or any(part in {"", ".", ".."} for part in parts):
                raise OSError
            target = project_root.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as destination:
                destination.write(content)
    except (OSError, ValueError) as error:
        raise RuntimeError("declared file write failed") from error
    return project_root


def atomic_publish(candidate: Path, output_directory: Path, manifest: NewProjectManifest) -> Path:
    """Publish the validated candidate in one filesystem replacement."""
    artifact_key = hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()
    published = output_directory / f"{artifact_key}.zip"
    if published.exists() and _is_link_or_reparse(published):
        raise OSError("publish target is a link")
    os.replace(candidate, published)
    return published


def _stage_validated_candidate(candidate: Path, output_directory: Path) -> Path:
    descriptor, raw_path = mkstemp(
        prefix=".fgui-new-project-", suffix=".tmp", dir=output_directory
    )
    os.close(descriptor)
    staged = Path(raw_path)
    try:
        os.replace(candidate, staged)
    except OSError:
        staged.unlink(missing_ok=True)
        raise
    return staged


def build_new_project(
    plan: FGUIPlanDocument,
    config: NewProjectConfig,
    payloads: AssetPayloadSet,
    output_directory: Path,
) -> BuiltNewProject:
    """Validate, build, reopen, and atomically publish one fresh project ZIP."""
    output = _prepare_output_directory(output_directory)
    assets = _run_gate("input", lambda: validate_asset_payloads(plan.resources, payloads))
    manifest = _run_gate(
        "manifest", lambda: compile_new_project_manifest(plan, config, assets)
    )

    def serialize_and_validate() -> dict[str, bytes]:
        files = serialize_project_files(manifest, assets)
        _require_clean(validate_xml_files(files))
        return files

    files = _run_gate("xml", serialize_and_validate)

    staged_candidate: Path | None = None

    def prepare_candidate() -> tuple[Path, str, int]:
        nonlocal staged_candidate
        with TemporaryDirectory(prefix="fgui-new-project-", dir=output) as raw:
            temporary = Path(raw)
            project_root = _run_gate(
                "directory-write",
                lambda: write_declared_files(temporary, manifest, files, assets),
            )
            _run_gate(
                "directory",
                lambda: _require_clean(validate_project_directory(project_root, manifest)),
            )
            candidate = temporary / "candidate.zip"
            _run_gate("zip-write", lambda: write_deterministic_zip(temporary, candidate))

            def validate_and_measure_archive() -> tuple[str, int]:
                _require_clean(validate_project_archive(candidate, manifest))
                return _sha256_file(candidate), candidate.stat().st_size

            archive_sha256, archive_size = _run_gate("archive", validate_and_measure_archive)
            staged_candidate = _run_gate(
                "zip-write", lambda: _stage_validated_candidate(candidate, output)
            )
        return staged_candidate, archive_sha256, archive_size

    try:
        staged, archive_sha256, archive_size = _run_gate(
            "directory-write", prepare_candidate
        )
    except NewProjectBuildError:
        if staged_candidate is not None:
            try:
                staged_candidate.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    try:
        published = _run_gate("publish", lambda: atomic_publish(staged, output, manifest))
    except NewProjectBuildError:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return BuiltNewProject.from_verified(
        published,
        manifest,
        sha256=archive_sha256,
        byte_size=archive_size,
    )
