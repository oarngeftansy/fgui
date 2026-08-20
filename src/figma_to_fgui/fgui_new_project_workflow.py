"""Build a fresh FairyGUI project from one committed Figma selection."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypeVar

from figma_to_fgui.component_mapping import ComponentMappingCatalog, load_mapping_catalog
from figma_to_fgui.fgui_new_project_build import (
    BuiltNewProject,
    NewProjectBuildError,
    build_new_project,
)
from figma_to_fgui.fgui_new_project_models import (
    AssetPayload,
    AssetPayloadSet,
    NewProjectConfig,
)
from figma_to_fgui.fgui_plan_compile import compile_fgui_plan
from figma_to_fgui.fgui_plan_models import FGUIPlanDocument, ResourcePlan
from figma_to_fgui.fgui_plan_validate import validate_fgui_plan
from figma_to_fgui.figma_selection import SelectionManifest
from figma_to_fgui.models import Diagnostic, Severity
from figma_to_fgui.normalize import (
    SelectionAsset,
    normalize_document,
    selection_conversion_document,
)
from figma_to_fgui.uir_compile import compile_uir
from figma_to_fgui.uir_models import UIRDocument
from figma_to_fgui.uir_validate import validate_uir
from figma_to_fgui.validate import has_errors

DEFAULT_MAPPING_CATALOG_PATH = Path("rules/default/component-mapping-candidates.json")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_WorkflowResult = TypeVar("_WorkflowResult")

_PUBLIC_MESSAGES = {
    "fgui.component.definition_missing": (
        "A selected component needs a complete generated definition.",
        "Add the component definition or use an approved raster fallback.",
    ),
    "fgui.writer.workflow.conversion_failed": (
        "The committed selection could not be converted into a new project.",
        "Review the selection and retry.",
    ),
    "fgui.writer.workflow.validation_failed": (
        "The converted selection did not pass the new-project validation gates.",
        "Repair the selection and retry.",
    ),
    "fgui.writer.workflow.resource_mismatch": (
        "The committed selection resources no longer match the conversion plan.",
        "Re-export the selection resources and retry.",
    ),
    "fgui.writer.workflow.output_failed": (
        "The new-project archive could not be published to the requested destination.",
        "Choose a valid output destination and retry.",
    ),
    "fgui.writer.workflow.build_failed": (
        "The new-project writer could not produce a validated archive.",
        "Repair the selection or destination and retry.",
    ),
}


class NewProjectWorkflowError(Exception):
    """A committed-selection workflow failure with fresh public diagnostics only."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        codes: set[str] = set()
        try:
            codes = {
                item.code
                for item in diagnostics
                if type(item) is Diagnostic and item.code in _PUBLIC_MESSAGES
            }
        except Exception:  # noqa: BLE001 - hostile diagnostic containers fail closed.
            codes = set()
        if not codes:
            codes = {"fgui.writer.workflow.conversion_failed"}
        self.diagnostics = tuple(_public_diagnostic(code) for code in sorted(codes))
        super().__init__("New FairyGUI project workflow failed.")


def _public_diagnostic(code: str) -> Diagnostic:
    message, suggested_action = _PUBLIC_MESSAGES[code]
    return Diagnostic(
        code=code,
        severity=Severity.ERROR,
        message=message,
        rule_id=code,
        rule_version=1,
        evidence=(f"workflow.code={code}",),
        suggested_action=suggested_action,
        blocks_binding=True,
    )


def _public_diagnostics(diagnostics: tuple[Diagnostic, ...]) -> tuple[Diagnostic, ...]:
    """Copy only workflow allow-listed diagnostic categories into a public error."""
    codes = {
        "fgui.component.definition_missing"
        for item in diagnostics
        if type(item) is Diagnostic and item.code == "fgui.component.definition_missing"
    }
    if not codes:
        codes = {"fgui.writer.workflow.validation_failed"}
    return tuple(_public_diagnostic(code) for code in sorted(codes))


def _workflow_error(code: str) -> NewProjectWorkflowError:
    return NewProjectWorkflowError((_public_diagnostic(code),))


def _run_conversion_gate(
    operation: Callable[[], _WorkflowResult], *, code: str = "fgui.writer.workflow.conversion_failed"
) -> _WorkflowResult:
    """Convert operational failures without allowing their exception chain to escape."""
    failure: NewProjectWorkflowError | None = None
    try:
        return operation()
    except Exception:  # noqa: BLE001 - conversion internals are not public evidence.
        failure = _workflow_error(code)
    if failure is not None:
        raise failure from None
    raise AssertionError("unreachable workflow gate state")


def _iter_nodes(roots: tuple[object, ...]) -> tuple[object, ...]:
    pending = list(roots)
    nodes: list[object] = []
    while pending:
        node = pending.pop()
        nodes.append(node)
        children = getattr(node, "children", ())
        if isinstance(children, tuple):
            pending.extend(children)
    return tuple(nodes)


def _selection_mapping_catalog(catalog: ComponentMappingCatalog) -> ComponentMappingCatalog:
    """Exclude unverified candidates without changing their mapping semantics."""
    return catalog.model_copy(
        update={
            "components": tuple(
                item for item in catalog.components if item.status != "candidate"
            )
        }
    )


def _candidate_definition_diagnostics(
    catalog: ComponentMappingCatalog, roots: tuple[object, ...]
) -> tuple[Diagnostic, ...]:
    """Fail closed when a selected instance has only a candidate mapping.

    Candidate mappings are not verified reusable components and the committed
    selection contract supplies no component-definition tree.  The workflow
    therefore never upgrades their status; it reports the same missing-
    definition boundary that Plan compilation uses for an unbacked component.
    """
    selected_instances = tuple(
        node for node in _iter_nodes(roots) if getattr(node, "type", None) == "INSTANCE"
    )
    if any(
        item.status == "candidate"
        and any(
            getattr(node, "id", None) in item.figma.node_ids
            or getattr(node, "name", None) in item.figma.names
            for node in selected_instances
        )
        for item in catalog.components
    ):
        return (_public_diagnostic("fgui.component.definition_missing"),)
    return ()


def _payloads_from_selection_assets(
    resources: Mapping[str, ResourcePlan], assets: tuple[SelectionAsset, ...]
) -> AssetPayloadSet:
    """Read exactly the selected resource bytes declared by the compiled Plan."""
    assets_by_logical_id: dict[str, SelectionAsset] = {}
    for asset in assets:
        if asset.asset in assets_by_logical_id:
            raise ValueError("duplicate selected resource")
        assets_by_logical_id[asset.asset] = asset

    payloads: list[AssetPayload] = []
    for resource_id in sorted(resources):
        resource = resources[resource_id]
        # ``source_asset_ref`` is the UIR-derived ID.  The Plan retains the
        # committed selection asset identity in ``logical_asset_id``.
        selected_asset = assets_by_logical_id.get(resource.logical_asset_id)
        source_asset_ref = (
            None
            if selected_asset is None
            else "asset:"
            + hashlib.sha256(
                json.dumps(
                    {
                        "exportFormat": resource.export_format,
                        "height": resource.height,
                        "logicalId": selected_asset.asset,
                        "mimeType": selected_asset.mime_type,
                        "nineSlice": (
                            None
                            if resource.nine_slice is None
                            else resource.nine_slice.model_dump(mode="json")
                        ),
                        "sha256": selected_asset.sha256,
                        "width": resource.width,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:24]
        )
        if (
            resource.id != resource_id
            or selected_asset is None
            or resource.source_asset_ref != source_asset_ref
            or resource.content_sha256 is None
            or resource.mime_type != selected_asset.mime_type
            or resource.content_sha256 != selected_asset.sha256
        ):
            raise ValueError("selection resource does not match plan")
        content = selected_asset.source_path.read_bytes()
        if (
            len(content) != selected_asset.size
            or hashlib.sha256(content).hexdigest() != selected_asset.sha256
        ):
            raise ValueError("selection resource bytes changed")
        payloads.append(
            AssetPayload(
                resourceId=resource_id,
                declaredMimeType=selected_asset.mime_type,
                content=content,
            )
        )
    return AssetPayloadSet.from_items(payloads)


def _build_error_code(error: NewProjectBuildError) -> str:
    """Map only one exact known build boundary to a fresh workflow diagnostic."""
    try:
        diagnostics = error.diagnostics
        if (
            type(diagnostics) is tuple
            and len(diagnostics) == 1
            and type(diagnostics[0]) is Diagnostic
            and diagnostics[0].code == "fgui.writer.build.output_invalid_failed"
        ):
            return "fgui.writer.workflow.output_failed"
    except Exception:  # noqa: BLE001 - hostile error objects fail closed.
        return "fgui.writer.workflow.build_failed"
    return "fgui.writer.workflow.build_failed"


def _workflow_validation(
    uir: UIRDocument,
    plan: FGUIPlanDocument,
    normalize_diagnostics: tuple[Diagnostic, ...],
    candidate_diagnostics: tuple[Diagnostic, ...],
) -> tuple[tuple[Diagnostic, ...], bool]:
    diagnostics = (
        *normalize_diagnostics,
        *candidate_diagnostics,
        *validate_uir(uir),
        *plan.diagnostics,
        *validate_fgui_plan(plan),
    )
    return diagnostics, not plan.bindable or has_errors(diagnostics)


def build_selection_new_project(
    *,
    manifest: SelectionManifest,
    resources_root: Path,
    selection_fingerprint: str,
    project_name: str,
    output_directory: Path,
    mapping_catalog_path: Path = DEFAULT_MAPPING_CATALOG_PATH,
) -> BuiltNewProject:
    """Build a validated new FairyGUI project from one committed selection."""
    if _FINGERPRINT.fullmatch(selection_fingerprint) is None:
        raise _workflow_error("fgui.writer.workflow.conversion_failed")

    conversion = _run_conversion_gate(
        lambda: selection_conversion_document(manifest, resources_root, selection_fingerprint)
    )
    roots, normalize_diagnostics = _run_conversion_gate(
        lambda: normalize_document(conversion.raw)
    )
    catalog = _run_conversion_gate(lambda: load_mapping_catalog(mapping_catalog_path))
    candidate_diagnostics = _run_conversion_gate(
        lambda: _candidate_definition_diagnostics(catalog, roots)
    )
    selection_catalog = _run_conversion_gate(
        lambda: _selection_mapping_catalog(catalog)
    )
    uir = _run_conversion_gate(
        lambda: compile_uir(
            roots,
            source_revision=selection_fingerprint,
            selection_id=selection_fingerprint[:32],
            mapping_catalog=selection_catalog,
        )
    )
    plan = _run_conversion_gate(
        lambda: compile_fgui_plan(uir, profile_version="fgui-6.1.4-v1", rule_version=1)
    )
    diagnostics, failed_validation = _run_conversion_gate(
        lambda: _workflow_validation(
            uir, plan, normalize_diagnostics, candidate_diagnostics
        )
    )
    if failed_validation:
        raise NewProjectWorkflowError(_public_diagnostics(diagnostics))

    payloads = _run_conversion_gate(
        lambda: _payloads_from_selection_assets(plan.resources, conversion.assets),
        code="fgui.writer.workflow.resource_mismatch",
    )
    config = _run_conversion_gate(
        lambda: NewProjectConfig(
            projectName=project_name,
            packageName="Generated",
            fairyGuiVersion="6.1.4",
            publishTarget="unity",
        )
    )

    failure: NewProjectWorkflowError | None = None
    try:
        return build_new_project(plan, config, payloads, output_directory)
    except NewProjectBuildError as error:
        failure = _workflow_error(_build_error_code(error))
    except Exception:  # noqa: BLE001 - build internals are never public workflow evidence.
        failure = _workflow_error("fgui.writer.workflow.build_failed")
    if failure is not None:
        raise failure from None
    raise AssertionError("unreachable new-project build state")
