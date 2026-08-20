from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import figma_to_fgui.fgui_new_project_workflow as workflow
from figma_to_fgui.fgui_new_project_validate import validate_project_archive
from figma_to_fgui.fgui_new_project_workflow import (
    NewProjectWorkflowError,
    _payloads_from_selection_assets,
    build_selection_new_project,
)
from figma_to_fgui.fgui_plan_models import ResourcePlan
from figma_to_fgui.figma_selection import (
    SelectionManifest,
    SelectionNode,
    SelectionResource,
)
from figma_to_fgui.models import Bounds, Diagnostic, Severity
from figma_to_fgui.normalize import SelectionAsset

DEFAULT_CATALOG = Path("rules/default/component-mapping-candidates.json")
ONE_PIXEL_PNG = (
    Path(__file__).parents[1]
    / "fixtures"
    / "fgui-new-project"
    / "resources"
    / "one-pixel.png"
).read_bytes()


def _selection_with_image(tmp_path: Path, *, instance: bool = False) -> tuple[SelectionManifest, Path]:
    resources = tmp_path / "selection-resources"
    resources.mkdir()
    (resources / "hero").write_bytes(ONE_PIXEL_PNG)
    return (
        SelectionManifest(
            display_name="Inventory",
            resources=(
                SelectionResource(key="hero", mime_type="image/png", size=len(ONE_PIXEL_PNG)),
            ),
            top_level_nodes=(
                SelectionNode(
                    id="private-node",
                    name="通用一级按钮" if instance else "InventoryPanel",
                    type="INSTANCE" if instance else "FRAME",
                    bounds=Bounds(x=0, y=0, width=1, height=1),
                    resource_keys=("hero",),
                ),
            ),
        ),
        resources,
    )


def test_builds_committed_selection_with_existing_writer(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path)

    built = build_selection_new_project(
        manifest=manifest,
        resources_root=resources,
        selection_fingerprint="a" * 64,
        project_name="Inventory",
        output_directory=tmp_path / "out",
        mapping_catalog_path=DEFAULT_CATALOG,
    )

    assert built.project_name == "Inventory"
    assert built.download_name.endswith(".zip")
    assert validate_project_archive(built.path, built.manifest) == ()


def test_component_without_definition_publishes_nothing(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path, instance=True)
    output = tmp_path / "out"

    with pytest.raises(NewProjectWorkflowError) as raised:
        build_selection_new_project(
            manifest=manifest,
            resources_root=resources,
            selection_fingerprint="b" * 64,
            project_name="Inventory",
            output_directory=output,
            mapping_catalog_path=DEFAULT_CATALOG,
        )

    assert {item.code for item in raised.value.diagnostics} == {
        "fgui.component.definition_missing"
    }
    assert list(output.glob("*.zip")) == []


def test_repeated_identical_selection_builds_are_byte_identical(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path)

    first = build_selection_new_project(
        manifest=manifest,
        resources_root=resources,
        selection_fingerprint="c" * 64,
        project_name="Inventory",
        output_directory=tmp_path / "one",
        mapping_catalog_path=DEFAULT_CATALOG,
    )
    second = build_selection_new_project(
        manifest=manifest,
        resources_root=resources,
        selection_fingerprint="c" * 64,
        project_name="Inventory",
        output_directory=tmp_path / "two",
        mapping_catalog_path=DEFAULT_CATALOG,
    )

    assert first.sha256 == second.sha256
    assert first.path.read_bytes() == second.path.read_bytes()


def test_selection_fingerprint_changes_the_built_archive(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path)

    first = build_selection_new_project(
        manifest=manifest,
        resources_root=resources,
        selection_fingerprint="d" * 64,
        project_name="Inventory",
        output_directory=tmp_path / "one",
        mapping_catalog_path=DEFAULT_CATALOG,
    )
    second = build_selection_new_project(
        manifest=manifest,
        resources_root=resources,
        selection_fingerprint="e" * 64,
        project_name="Inventory",
        output_directory=tmp_path / "two",
        mapping_catalog_path=DEFAULT_CATALOG,
    )

    assert first.sha256 != second.sha256
    assert first.path.read_bytes() != second.path.read_bytes()


def test_svg_resource_is_rejected_without_publishing_an_archive(tmp_path: Path) -> None:
    resources = tmp_path / "selection-resources"
    resources.mkdir()
    content = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
    (resources / "vector").write_bytes(content)
    manifest = SelectionManifest(
        display_name="Vector",
        resources=(
            SelectionResource(key="vector", mime_type="image/svg+xml", size=len(content)),
        ),
        top_level_nodes=(
            SelectionNode(
                id="private-vector",
                name="Vector",
                type="FRAME",
                bounds=Bounds(x=0, y=0, width=1, height=1),
                resource_keys=("vector",),
            ),
        ),
    )
    output = tmp_path / "out"

    with pytest.raises(NewProjectWorkflowError) as raised:
        build_selection_new_project(
            manifest=manifest,
            resources_root=resources,
            selection_fingerprint="f" * 64,
            project_name="Inventory",
            output_directory=output,
            mapping_catalog_path=DEFAULT_CATALOG,
        )

    assert [item.code for item in raised.value.diagnostics] == [
        "fgui.writer.workflow.build_failed"
    ]
    assert list(output.glob("*.zip")) == []


def test_private_build_exception_never_crosses_the_public_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, resources = _selection_with_image(tmp_path)
    marker = "private-workflow-build-marker"

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(marker)

    monkeypatch.setattr(workflow, "build_new_project", fail)
    with pytest.raises(NewProjectWorkflowError) as raised:
        build_selection_new_project(
            manifest=manifest,
            resources_root=resources,
            selection_fingerprint="1" * 64,
            project_name="Inventory",
            output_directory=tmp_path / "out",
            mapping_catalog_path=DEFAULT_CATALOG,
        )

    error = raised.value
    assert [item.code for item in error.diagnostics] == ["fgui.writer.workflow.build_failed"]
    assert marker not in str(error)
    assert marker not in repr(error)
    assert marker not in repr(error.diagnostics)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert list((tmp_path / "out").glob("*.zip")) == []


def test_private_validation_exception_never_crosses_the_public_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, resources = _selection_with_image(tmp_path)
    marker = "private-workflow-validation-marker"

    def fail(*_args: object, **_kwargs: object) -> tuple[Diagnostic, ...]:
        raise RuntimeError(marker)

    monkeypatch.setattr(workflow, "validate_uir", fail)
    with pytest.raises(NewProjectWorkflowError) as raised:
        build_selection_new_project(
            manifest=manifest,
            resources_root=resources,
            selection_fingerprint="3" * 64,
            project_name="Inventory",
            output_directory=tmp_path / "out",
            mapping_catalog_path=DEFAULT_CATALOG,
        )

    error = raised.value
    assert [item.code for item in error.diagnostics] == [
        "fgui.writer.workflow.conversion_failed"
    ]
    assert marker not in str(error)
    assert marker not in repr(error)
    assert marker not in repr(error.diagnostics)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert list((tmp_path / "out").glob("*.zip")) == []


def test_workflow_error_rebuilds_only_allowlisted_public_diagnostics() -> None:
    marker = "private-workflow-diagnostic-marker"
    error = NewProjectWorkflowError(
        (
            Diagnostic(
                code="untrusted.private.code",
                severity=Severity.ERROR,
                message=marker,
                evidence=(marker,),
                suggested_action=marker,
            ),
        )
    )

    assert [item.code for item in error.diagnostics] == [
        "fgui.writer.workflow.conversion_failed"
    ]
    assert marker not in str(error)
    assert marker not in repr(error)
    assert marker not in repr(error.diagnostics)


def test_invalid_output_directory_publishes_nothing(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path)
    output = tmp_path / "output-file"
    output.write_text("not a directory", "utf-8")

    with pytest.raises(NewProjectWorkflowError) as raised:
        build_selection_new_project(
            manifest=manifest,
            resources_root=resources,
            selection_fingerprint="2" * 64,
            project_name="Inventory",
            output_directory=output,
            mapping_catalog_path=DEFAULT_CATALOG,
        )

    assert [item.code for item in raised.value.diagnostics] == [
        "fgui.writer.workflow.output_failed"
    ]
    assert list(tmp_path.glob("*.zip")) == []


def _resource_plan(logical_asset_id: str, content: bytes) -> ResourcePlan:
    source_asset_ref = "asset:" + hashlib.sha256(
        json.dumps(
            {
                "exportFormat": "png",
                "height": 1,
                "logicalId": logical_asset_id,
                "mimeType": "image/png",
                "nineSlice": None,
                "sha256": hashlib.sha256(content).hexdigest(),
                "width": 1,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    return ResourcePlan(
        id="resource:hero",
        sourceAssetRef=source_asset_ref,
        logicalAssetId=logical_asset_id,
        contentSha256=hashlib.sha256(content).hexdigest(),
        exportParametersSha256="a" * 64,
        mimeType="image/png",
        exportFormat="png",
        width=1,
        height=1,
        consumers=("node:hero",),
    )


def test_payload_matching_rejects_duplicate_missing_and_changed_selection_assets(
    tmp_path: Path,
) -> None:
    source = tmp_path / "hero.png"
    source.write_bytes(ONE_PIXEL_PNG)
    selected = SelectionAsset(
        asset="asset:hero",
        mime_type="image/png",
        source_path=source,
        size=len(ONE_PIXEL_PNG),
        sha256=hashlib.sha256(ONE_PIXEL_PNG).hexdigest(),
        artifact_fingerprint="a" * 64,
    )
    resource = _resource_plan(selected.asset, ONE_PIXEL_PNG)

    with pytest.raises(ValueError):
        _payloads_from_selection_assets({resource.id: resource}, (selected, selected))
    with pytest.raises(ValueError):
        _payloads_from_selection_assets(
            {resource.id: resource},
            (selected.__class__(
                asset="asset:other",
                mime_type=selected.mime_type,
                source_path=selected.source_path,
                size=selected.size,
                sha256=selected.sha256,
                artifact_fingerprint=selected.artifact_fingerprint,
            ),),
        )
    with pytest.raises(ValueError):
        _payloads_from_selection_assets(
            {
                resource.id: resource.model_copy(
                    update={"source_asset_ref": "asset:wrong-source"}
                )
            },
            (selected,),
        )

    source.write_bytes(b"X" + ONE_PIXEL_PNG[1:])
    with pytest.raises(ValueError):
        _payloads_from_selection_assets({resource.id: resource}, (selected,))

    source.write_bytes(ONE_PIXEL_PNG + b"changed")
    with pytest.raises(ValueError):
        _payloads_from_selection_assets({resource.id: resource}, (selected,))
