"""Five-gate builder for fresh, deterministic FairyGUI project archives."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from tempfile import TemporaryDirectory

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


class BuiltNewProject(FrozenModel):
    """One validated archive that has crossed the atomic publish boundary."""

    path: Path
    download_name: str
    sha256: str
    project_name: str
    manifest: NewProjectManifest

    @classmethod
    def from_path(cls, path: Path, manifest: NewProjectManifest) -> BuiltNewProject:
        return cls(
            path=path,
            download_name=f"{manifest.project.project_name}-FairyGUI.zip",
            sha256=_sha256_file(path),
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


def _require_clean(diagnostics: tuple[Diagnostic, ...], boundary: str) -> None:
    if diagnostics:
        raise _fail(boundary)


def _is_link_or_reparse(path: Path) -> bool:
    metadata = path.lstat()
    attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & _REPARSE_POINT)


def _prepare_output_directory(output_directory: Path) -> Path:
    try:
        if output_directory.exists() or output_directory.is_symlink():
            if not output_directory.is_dir() or _is_link_or_reparse(output_directory):
                raise OSError
        else:
            output_directory.mkdir(parents=True)
        return output_directory.resolve(strict=True)
    except OSError as error:
        raise _fail("output_invalid") from error


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


def build_new_project(
    plan: FGUIPlanDocument,
    config: NewProjectConfig,
    payloads: AssetPayloadSet,
    output_directory: Path,
) -> BuiltNewProject:
    """Validate, build, reopen, and atomically publish one fresh project ZIP."""
    output = _prepare_output_directory(output_directory)
    try:
        assets = validate_asset_payloads(plan.resources, payloads)
    except Exception as error:
        raise _fail("input") from error
    try:
        manifest = compile_new_project_manifest(plan, config, assets)
    except Exception as error:
        raise _fail("manifest") from error
    try:
        files = serialize_project_files(manifest, assets)
        _require_clean(validate_xml_files(files), "xml")
    except NewProjectBuildError:
        raise
    except Exception as error:
        raise _fail("xml") from error

    with TemporaryDirectory(prefix="fgui-new-project-", dir=output) as raw:
        temporary = Path(raw)
        try:
            project_root = write_declared_files(temporary, manifest, files, assets)
        except Exception as error:
            raise _fail("directory-write") from error
        try:
            _require_clean(validate_project_directory(project_root, manifest), "directory")
        except NewProjectBuildError:
            raise
        except Exception as error:
            raise _fail("directory") from error
        candidate = temporary / "candidate.zip"
        try:
            write_deterministic_zip(temporary, candidate)
        except Exception as error:
            raise _fail("zip-write") from error
        try:
            _require_clean(validate_project_archive(candidate, manifest), "archive")
        except NewProjectBuildError:
            raise
        except Exception as error:
            raise _fail("archive") from error
        try:
            published = atomic_publish(candidate, output, manifest)
        except Exception as error:
            raise _fail("publish") from error
    return BuiltNewProject.from_path(published, manifest)
