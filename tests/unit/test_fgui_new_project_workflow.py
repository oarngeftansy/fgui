from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

import figma_to_fgui.fgui_new_project_workflow as workflow
from figma_to_fgui.fgui_asset_payloads import MAX_ASSET_PAYLOAD_BYTES
from figma_to_fgui.fgui_conversion_dispositions import build_conversion_dispositions
from figma_to_fgui.fgui_new_project_validate import validate_project_archive
from figma_to_fgui.fgui_new_project_workflow import (
    NewProjectWorkflowError,
    _payloads_from_selection_assets,
    build_selection_new_project,
)
from figma_to_fgui.fgui_plan_compile import compile_fgui_plan
from figma_to_fgui.fgui_plan_models import ResourcePlan
from figma_to_fgui.figma_selection import (
    SelectionManifest,
    SelectionNode,
    SelectionResource,
)
from figma_to_fgui.models import Bounds, Diagnostic, Severity
from figma_to_fgui.normalize import (
    SelectionAsset,
    normalize_document,
    selection_conversion_document,
)
from figma_to_fgui.service_contracts import (
    NewProjectAdjustment,
    NewProjectAdjustmentStrategy,
    NewProjectIssueKind,
)
from figma_to_fgui.uir_compile import compile_uir, uir_asset_id

DEFAULT_CATALOG = Path("rules/default/component-mapping-candidates.json")
ONE_PIXEL_PNG = (
    Path(__file__).parents[1]
    / "fixtures"
    / "fgui-new-project"
    / "resources"
    / "one-pixel.png"
).read_bytes()


def _selection_with_image(
    tmp_path: Path, *, instance: bool = False, node_id: str = "private-node"
) -> tuple[SelectionManifest, Path]:
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
                    id=node_id,
                    name="Unrelated instance" if instance else "InventoryPanel",
                    type="INSTANCE" if instance else "FRAME",
                    bounds=Bounds(x=0, y=0, width=1, height=1),
                    resource_keys=("hero",),
                ),
            ),
        ),
        resources,
    )


def _mapping_catalog(tmp_path: Path, *, status: str, duplicate_match: bool = False) -> Path:
    path = tmp_path / f"{status}-mapping.json"
    component = {
        "key": "fixture_component",
        "figma": {"names": [], "nodeIds": ["private-node"]},
        "fgui": {
            "package": "Common",
            "component": "FixtureComponent",
            "path": "FixtureComponent.xml",
        },
        "properties": {},
        "source": ["test"],
        "status": status,
        "reason": f"fixture_{status}",
    }
    components = [component]
    if duplicate_match:
        components.append({**component, "key": "fixture_component_duplicate"})
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "sources": ["test"],
                "components": components,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_builds_committed_selection_with_existing_writer(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path)
    stages: list[tuple[str, int]] = []

    built = build_selection_new_project(
        manifest=manifest,
        resources_root=resources,
        selection_fingerprint="a" * 64,
        project_name="Inventory",
        output_directory=tmp_path / "out",
        mapping_catalog_path=DEFAULT_CATALOG,
        on_stage=lambda stage, progress: stages.append((stage, progress)),
    )

    assert built.project_name == "Inventory"
    assert built.download_name.endswith(".zip")
    assert validate_project_archive(built.path, built.manifest) == ()
    assert stages == [("checking", 55), ("packaging", 80)]


def test_committed_raster_uses_exported_pixel_dimensions_not_figma_bounds(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path)
    source = manifest.top_level_nodes[0].model_copy(
        update={"bounds": Bounds(x=0, y=0, width=10, height=12)}
    )
    manifest = manifest.model_copy(update={"top_level_nodes": (source,)})

    built = build_selection_new_project(
        manifest=manifest,
        resources_root=resources,
        selection_fingerprint="9" * 64,
        project_name="RenderedBounds",
        output_directory=tmp_path / "out",
        mapping_catalog_path=DEFAULT_CATALOG,
    )

    resource = next(iter(built.plan.resources.values()))
    assert (resource.width, resource.height) == (1, 1)
    assert validate_project_archive(built.path, built.manifest) == ()


def test_solid_rectangle_is_written_as_an_editable_graph_without_a_png(tmp_path: Path) -> None:
    manifest = SelectionManifest(
        display_name="EditableShape",
        resources=(),
        top_level_nodes=(
            SelectionNode(
                id="shape-1",
                name="Card",
                type="RECTANGLE",
                bounds=Bounds(x=0, y=0, width=120, height=48),
                properties={"export_strategy": "native", "stroke_weight": 2, "corner_radius": 8},
                style={
                    "fills": [{"type": "SOLID", "color": {"r": 1, "g": 0.5, "b": 0, "a": 1}}],
                    "strokes": [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}],
                },
            ),
        ),
    )
    resources = tmp_path / "selection-resources"
    resources.mkdir()

    built = build_selection_new_project(
        manifest=manifest,
        resources_root=resources,
        selection_fingerprint="e" * 64,
        project_name="EditableShape",
        output_directory=tmp_path / "out",
        mapping_catalog_path=DEFAULT_CATALOG,
    )

    assert built.manifest.resources == ()
    with zipfile.ZipFile(built.path) as archive:
        component_name = next(name for name in archive.namelist() if name.endswith(".xml") and "/components/" in name)
        component_xml = archive.read(component_name).decode("utf-8")
    assert '<graph ' in component_xml
    assert 'type="rect"' in component_xml
    assert 'fillColor="#ffff8000"' in component_xml
    assert 'lineColor="#000000"' in component_xml
    assert 'lineSize="2"' in component_xml
    assert 'corner="8"' in component_xml


def test_selected_frame_background_and_text_remain_editable_without_a_png(tmp_path: Path) -> None:
    manifest = SelectionManifest(
        display_name="EditableScreen",
        resources=(),
        top_level_nodes=(
            SelectionNode(
                id="screen-1",
                name="Screen",
                type="FRAME",
                bounds=Bounds(x=0, y=0, width=320, height=640),
                properties={"export_strategy": "native", "clips_content": False},
                style={"fills": [{"type": "SOLID", "color": {"r": 0.1, "g": 0.2, "b": 0.3}}]},
                children=(
                    SelectionNode(
                        id="label-1",
                        name="Title",
                        type="TEXT",
                        bounds=Bounds(x=20, y=24, width=120, height=32),
                        properties={"export_strategy": "native"},
                        text="Editable title",
                    ),
                ),
            ),
        ),
    )
    resources = tmp_path / "selection-resources"
    resources.mkdir()

    built = build_selection_new_project(
        manifest=manifest,
        resources_root=resources,
        selection_fingerprint="f" * 64,
        project_name="EditableScreen",
        output_directory=tmp_path / "out",
        mapping_catalog_path=DEFAULT_CATALOG,
    )

    assert built.manifest.resources == ()
    with zipfile.ZipFile(built.path) as archive:
        component_name = next(name for name in archive.namelist() if name.endswith(".xml") and "/components/" in name)
        component_xml = archive.read(component_name).decode("utf-8")
    assert '<graph ' in component_xml
    assert 'fillColor="#ff1a334c"' in component_xml
    assert '<text ' in component_xml
    assert 'text="Editable title"' in component_xml


def _reviewable_rich_text_build(tmp_path: Path):
    manifest = SelectionManifest(
        display_name="Review",
        resources=(),
        top_level_nodes=(
            SelectionNode(
                id="text-node",
                name="Mixed label",
                type="TEXT",
                bounds=Bounds(x=0, y=0, width=100, height=20),
                properties={"export_strategy": "native"},
                text="AB",
                style={
                    "fontSize": 20,
                    "runs": [
                        {"content": "A", "style": {"fontSize": 20}},
                        {"content": "B", "style": {"fontSize": 24}},
                    ],
                },
            ),
        ),
    )
    resources = tmp_path / "selection-resources"
    resources.mkdir()

    built = build_selection_new_project(
        manifest=manifest,
        resources_root=resources,
        selection_fingerprint="d" * 64,
        project_name="Review",
        output_directory=tmp_path / "out",
        mapping_catalog_path=DEFAULT_CATALOG,
    )
    return manifest, built


def test_backend_authors_editable_risk_for_reviewed_rich_text(tmp_path: Path) -> None:
    manifest, built = _reviewable_rich_text_build(tmp_path)
    dispositions = build_conversion_dispositions(
        manifest, built.plan, built.source_node_ids
    )

    assert [item.model_dump(mode="json", by_alias=True) for item in dispositions] == [
        {
            "version": 1,
            "id": dispositions[0].id,
            "sourceNodeId": "text-node",
            "sourceName": "Mixed label",
            "sourceType": "TEXT",
            "level": "editable_risk",
            "reason": "rich_text_runs",
            "defaultStrategy": "preserve-editable",
            "allowedStrategies": ["preserve-editable", "rasterize-subtree"],
            "visualImpact": "may_differ",
            "editabilityImpact": "unchanged",
            "componentImpact": "unchanged",
            "blocksApproval": False,
            "details": {
                "runCount": 2,
                "preservedProperties": ["content"],
                "unsupportedProperties": ["fontSize"],
            },
        }
    ]


@pytest.mark.parametrize(
    "evidence",
    (
        (),
        (
            "text.runs.count=2",
            "text.runs.count=3",
            "text.runs.unsupported=fontSize",
        ),
        (
            "text.runs.count=two",
            "text.runs.preserved=content",
            "text.runs.unsupported=fontSize",
        ),
        (
            "text.runs.count=10000000000",
            "text.runs.preserved=content",
            "text.runs.unsupported=fontSize",
        ),
        (
            "text.runs.count=2",
            "text.runs.preserved=content",
            "text.runs.unsupported=inventedFeature",
        ),
    ),
    ids=("missing", "duplicate-prefix", "malformed-count", "oversized-count", "unregistered"),
)
def test_reviewed_rich_text_disposition_rejects_noncanonical_evidence(
    tmp_path: Path, evidence: tuple[str, ...]
) -> None:
    manifest, built = _reviewable_rich_text_build(tmp_path)
    rich_decision = next(
        item
        for item in built.plan.decisions.values()
        if item.rule_id == "fgui.text.runs_unsupported"
    )
    malformed = rich_decision.model_copy(update={"evidence": evidence})
    plan = built.plan.model_copy(
        update={"decisions": {**built.plan.decisions, malformed.node_ref: malformed}}
    )

    with pytest.raises(ValueError):
        build_conversion_dispositions(manifest, plan, built.source_node_ids)


def test_component_without_definition_publishes_nothing(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path, instance=True, node_id="23:55")
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


def test_name_only_candidate_instance_publishes_nothing(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path, instance=True)
    manifest = manifest.model_copy(
        update={
            "top_level_nodes": (
                manifest.top_level_nodes[0].model_copy(update={"name": "通用一级按钮"}),
            )
        }
    )
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

    assert [item.code for item in raised.value.diagnostics] == [
        "fgui.component.definition_missing"
    ]
    assert list(output.glob("*.zip")) == []


def test_readable_candidate_instance_preserves_child_tree(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path, instance=True)
    child = SelectionNode(
        id="private-child",
        name="Editable label",
        type="TEXT",
        bounds=Bounds(x=0, y=0, width=1, height=1),
        text="A",
    )
    manifest = manifest.model_copy(
        update={
            "resources": (),
            "top_level_nodes": (
                manifest.top_level_nodes[0].model_copy(
                    update={
                        "name": "通用一级按钮",
                        "resource_keys": (),
                        "children": (child,),
                    }
                ),
            )
        }
    )

    built = build_selection_new_project(
        manifest=manifest,
        resources_root=resources,
        selection_fingerprint="b" * 64,
        project_name="Inventory",
        output_directory=tmp_path / "out",
        mapping_catalog_path=DEFAULT_CATALOG,
    )

    assert validate_project_archive(built.path, built.manifest) == ()
    assert set(built.source_node_ids.values()) == {"private-node", "private-child"}


def test_unmatched_instance_publishes_nothing(tmp_path: Path) -> None:
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

    assert [item.code for item in raised.value.diagnostics] == [
        "fgui.component.definition_missing"
    ]
    assert list(output.glob("*.zip")) == []


def test_missing_component_mapping_uses_raster_fallback_by_source_id(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path, instance=True)

    built = build_selection_new_project(
        manifest=manifest,
        resources_root=resources,
        selection_fingerprint="b" * 64,
        project_name="Inventory",
        output_directory=tmp_path / "out",
        mapping_catalog_path=_mapping_catalog(tmp_path, status="missing"),
    )

    assert validate_project_archive(built.path, built.manifest) == ()


def test_conflicted_component_mapping_publishes_nothing(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path, instance=True)
    output = tmp_path / "out"

    with pytest.raises(NewProjectWorkflowError) as raised:
        build_selection_new_project(
            manifest=manifest,
            resources_root=resources,
            selection_fingerprint="b" * 64,
            project_name="Inventory",
            output_directory=output,
            mapping_catalog_path=_mapping_catalog(tmp_path, status="conflict"),
        )

    assert [item.code for item in raised.value.diagnostics] == [
        "fgui.writer.workflow.mapping_conflict"
    ]
    assert list(output.glob("*.zip")) == []


def test_ambiguous_component_mapping_publishes_nothing(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path, instance=True)
    output = tmp_path / "out"

    with pytest.raises(NewProjectWorkflowError) as raised:
        build_selection_new_project(
            manifest=manifest,
            resources_root=resources,
            selection_fingerprint="b" * 64,
            project_name="Inventory",
            output_directory=output,
            mapping_catalog_path=_mapping_catalog(
                tmp_path, status="missing", duplicate_match=True
            ),
        )

    assert [item.code for item in raised.value.diagnostics] == [
        "fgui.writer.workflow.mapping_conflict"
    ]
    assert list(output.glob("*.zip")) == []


def test_unconsumed_selection_resource_fails_closed(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path)
    (resources / "unused").write_bytes(ONE_PIXEL_PNG)
    manifest = manifest.model_copy(
        update={
            "resources": (
                *manifest.resources,
                SelectionResource(
                    key="unused", mime_type="image/png", size=len(ONE_PIXEL_PNG)
                ),
            )
        }
    )
    output = tmp_path / "out"

    with pytest.raises(NewProjectWorkflowError) as raised:
        build_selection_new_project(
            manifest=manifest,
            resources_root=resources,
            selection_fingerprint="c" * 64,
            project_name="Inventory",
            output_directory=output,
            mapping_catalog_path=DEFAULT_CATALOG,
        )

    assert [item.code for item in raised.value.diagnostics] == [
        "fgui.writer.workflow.resource_mismatch"
    ]
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


def test_preserve_editable_adjustment_reaches_plan_and_changes_archive(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path)
    raster = manifest.top_level_nodes[0].model_copy(
        update={
            "properties": {
                "export_strategy": "composite_png",
                "raster_reasons": ["visual_effect"],
            }
        }
    )
    manifest = manifest.model_copy(update={"top_level_nodes": (raster,)})
    first = build_selection_new_project(
        manifest=manifest,
        resources_root=resources,
        selection_fingerprint="9" * 64,
        project_name="Inventory",
        output_directory=tmp_path / "one",
        mapping_catalog_path=DEFAULT_CATALOG,
    )

    assert any(item.code == "fgui.visual.raster_fallback" for item in first.diagnostics)
    adjusted = build_selection_new_project(
        manifest=manifest,
        resources_root=resources,
        selection_fingerprint="9" * 64,
        project_name="Inventory",
        output_directory=tmp_path / "two",
        mapping_catalog_path=DEFAULT_CATALOG,
        adjustments=(
            NewProjectAdjustment(
                issueId="review:" + "1" * 16,
                sourceNodeId="private-node",
                issueKind=NewProjectIssueKind.RASTER_FALLBACK,
                strategy=NewProjectAdjustmentStrategy.PRESERVE_EDITABLE,
            ),
        ),
    )

    assert adjusted.sha256 != first.sha256
    assert not any(item.code == "fgui.visual.raster_fallback" for item in adjusted.diagnostics)


def test_include_definition_is_rejected_without_a_contained_definition_tree(tmp_path: Path) -> None:
    manifest, resources = _selection_with_image(tmp_path, instance=True)
    with pytest.raises(NewProjectWorkflowError):
        build_selection_new_project(
            manifest=manifest,
            resources_root=resources,
            selection_fingerprint="8" * 64,
            project_name="Inventory",
            output_directory=tmp_path / "out",
            mapping_catalog_path=DEFAULT_CATALOG,
            adjustments=(
                NewProjectAdjustment(
                    issueId="review:" + "2" * 16,
                    sourceNodeId="private-node",
                    issueKind=NewProjectIssueKind.DEFINITION_MISSING,
                    strategy=NewProjectAdjustmentStrategy.INCLUDE_CONTAINED_DEFINITION,
                ),
            ),
        )


def test_svg_resource_is_rejected_without_publishing_an_archive(tmp_path: Path) -> None:
    resources = tmp_path / "selection-resources"
    resources.mkdir()
    content = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
    (resources / "vector").write_bytes(content)
    manifest = SelectionManifest(
        display_name="Vector",
        resources=(
            SelectionResource(key="vector", mime_type="image/png", size=len(content)),
        ),
        top_level_nodes=(
            SelectionNode(
                id="private-vector",
                name="Vector",
                type="FRAME",
                bounds=Bounds(x=0, y=0, width=1, height=1),
                properties={
                    "export_strategy": "composite_png",
                    "raster_reasons": ["visual_effect"],
                },
                resource_keys=("vector",),
            ),
        ),
    )
    output = tmp_path / "out"

    conversion = selection_conversion_document(manifest, resources, "f" * 64)
    roots, normalize_diagnostics = normalize_document(conversion.raw)
    assert normalize_diagnostics == ()
    plan = compile_fgui_plan(
        compile_uir(
            roots,
            source_revision="f" * 64,
            selection_id="f" * 32,
        )
    )
    assert {node.type for node in plan.nodes.values()} == {"rasterSubtree"}
    assert {resource.export_format for resource in plan.resources.values()} == {"png"}

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
    source_asset_ref = uir_asset_id(
        logical_id=logical_asset_id,
        mime_type="image/png",
        sha256=hashlib.sha256(content).hexdigest(),
        width=1,
        height=1,
        nine_slice=None,
        export_format="png",
    )
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


def test_payload_matching_rejects_declared_oversize_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "hero.png"
    source.write_bytes(ONE_PIXEL_PNG)
    selected = SelectionAsset(
        asset="asset:hero",
        mime_type="image/png",
        source_path=source,
        size=MAX_ASSET_PAYLOAD_BYTES + 1,
        sha256=hashlib.sha256(ONE_PIXEL_PNG).hexdigest(),
        artifact_fingerprint="a" * 64,
    )
    resource = _resource_plan(selected.asset, ONE_PIXEL_PNG)

    def must_not_read(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("oversized resource was read")

    monkeypatch.setattr(workflow, "read_bounded_stable_asset_file", must_not_read)
    with pytest.raises(ValueError):
        _payloads_from_selection_assets({resource.id: resource}, (selected,))
