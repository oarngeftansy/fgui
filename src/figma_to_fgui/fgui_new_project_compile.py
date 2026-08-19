"""Pure compilation from a validated FGUI Plan into a target manifest."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import NoReturn

from figma_to_fgui.fgui_asset_payloads import (
    NewProjectInputError,
    ValidatedAssetPayload,
    diagnostic_sort_key,
)
from figma_to_fgui.fgui_new_project_ids import (
    TargetIdAllocator,
    TargetIdCollisionError,
    TargetNamingError,
    component_path,
    resource_path,
    validate_target_name,
)
from figma_to_fgui.fgui_new_project_models import (
    ManifestComponent,
    ManifestObject,
    ManifestPackage,
    ManifestResource,
    NewProjectConfig,
    NewProjectManifest,
)
from figma_to_fgui.fgui_new_project_validate import (
    NewProjectManifestError,
    validate_new_project_manifest,
)
from figma_to_fgui.fgui_plan_models import (
    FGUIPlanDocument,
    FGUIPlanNode,
    MaskMode,
    ResourcePlan,
)
from figma_to_fgui.fgui_plan_validate import validate_fgui_plan
from figma_to_fgui.models import Bounds, Diagnostic, Severity
from figma_to_fgui.validate import has_errors


def _input_diagnostic(code: str, message: str, *, node_id: str | None = None) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=Severity.ERROR,
        message=message,
        node_id=node_id,
        rule_id=code,
        rule_version=1,
        suggested_action="Repair or recompile the Writer inputs.",
        blocks_binding=True,
    )


def _raise_input(diagnostics: list[Diagnostic]) -> NoReturn:
    raise NewProjectInputError(tuple(sorted(diagnostics, key=diagnostic_sort_key)))


def _writer_input_diagnostics(diagnostics: tuple[Diagnostic, ...]) -> list[Diagnostic]:
    """Translate Plan-gate details into static public Writer diagnostics."""
    return [
        _input_diagnostic(
            "fgui.writer.input.plan_invalid",
            "The FGUI Plan failed semantic revalidation.",
        ).model_copy(update={"evidence": (f"source.code={diagnostic.code}",)})
        for diagnostic in diagnostics
    ]


def _validate_inputs(
    plan: FGUIPlanDocument,
    config: NewProjectConfig,
    assets: tuple[ValidatedAssetPayload, ...],
) -> dict[str, ValidatedAssetPayload]:
    plan_diagnostics = validate_fgui_plan(plan)
    if not plan.bindable or has_errors(plan_diagnostics):
        public = _writer_input_diagnostics(plan_diagnostics)
        if not plan.bindable:
            public.append(
                _input_diagnostic(
                    "fgui.writer.input.plan_not_bindable",
                    "The FGUI Plan is not bindable and cannot enter the project writer.",
                )
            )
        _raise_input(public)

    try:
        validate_target_name(config.project_name, "project")
        validate_target_name(config.package_name, "package")
    except TargetNamingError:
        _raise_input(
            [
                _input_diagnostic(
                    "fgui.writer.input.target_name_invalid",
                    "Project and package names must be safe generated target names.",
                )
            ]
        )

    indexed: dict[str, ValidatedAssetPayload] = {}
    diagnostics: list[Diagnostic] = []
    for asset in assets:
        resource_id = asset.resource.id
        if resource_id in indexed:
            diagnostics.append(
                _input_diagnostic(
                    "fgui.writer.input.asset_duplicate",
                    "A validated resource payload is supplied more than once.",
                    node_id=resource_id,
                )
            )
            continue
        indexed[resource_id] = asset
    for resource_id in sorted(set(plan.resources) - set(indexed)):
        diagnostics.append(
            _input_diagnostic(
                "fgui.writer.input.asset_missing",
                "A Plan resource has no validated payload.",
                node_id=resource_id,
            )
        )
    for resource_id in sorted(set(indexed) - set(plan.resources)):
        diagnostics.append(
            _input_diagnostic(
                "fgui.writer.input.asset_unexpected",
                "A validated payload is not declared by the Plan.",
                node_id=resource_id,
            )
        )
    for resource_id in sorted(set(indexed) & set(plan.resources)):
        asset = indexed[resource_id]
        if (
            asset.resource != plan.resources[resource_id]
            or asset.payload.resource_id != resource_id
            or asset.payload.declared_mime_type != asset.resource.mime_type
        ):
            diagnostics.append(
                _input_diagnostic(
                    "fgui.writer.input.asset_incoherent",
                    "A validated payload no longer agrees with its Plan resource.",
                    node_id=resource_id,
                )
            )
    if diagnostics:
        _raise_input(diagnostics)
    return indexed


def _target_name_from_logical_ref(value: str) -> str:
    """Use the final logical identity segment without silently rewriting it."""
    return validate_target_name(value.rsplit(":", maxsplit=1)[-1], "component")


def _component_source_refs(plan: FGUIPlanDocument) -> tuple[str, ...]:
    return (*sorted(plan.component_definitions), *sorted(plan.roots))


def _owner_tables(
    plan: FGUIPlanDocument,
) -> tuple[dict[str, str], dict[str, Mapping[str, FGUIPlanNode]], dict[str, str]]:
    """Keep document roots and each definition in distinct ownership domains."""
    nodes_by_component: dict[str, Mapping[str, FGUIPlanNode]] = {}
    root_by_component: dict[str, str] = {}
    node_owner: dict[str, str] = {}

    for definition_id in sorted(plan.component_definitions):
        definition = plan.component_definitions[definition_id]
        nodes_by_component[definition_id] = definition.nodes
        root_by_component[definition_id] = definition.root_node_ref
        for node_id in definition.nodes:
            node_owner[node_id] = definition_id

    for root_id in sorted(plan.roots):
        reachable: dict[str, FGUIPlanNode] = {}
        pending = [root_id]
        while pending:
            node_id = pending.pop()
            if node_id in reachable:
                continue
            node = plan.nodes[node_id]
            reachable[node_id] = node
            pending.extend(reversed(node.children))
        nodes_by_component[root_id] = reachable
        root_by_component[root_id] = root_id
        for node_id in reachable:
            node_owner[node_id] = root_id
    return node_owner, nodes_by_component, root_by_component


def _allocation_requests(
    plan: FGUIPlanDocument,
    config: NewProjectConfig,
    nodes_by_component: Mapping[str, Mapping[str, FGUIPlanNode]],
) -> tuple[tuple[str, str], ...]:
    requests: list[tuple[str, str]] = [("package", f"{plan.document_id}:{config.package_name}")]
    requests.extend(("component", source_ref) for source_ref in _component_source_refs(plan))
    for component_source_ref in sorted(nodes_by_component):
        requests.extend(
            ("object", f"{component_source_ref}:{node_id}")
            for node_id in sorted(nodes_by_component[component_source_ref])
        )
    for resource_id in sorted(plan.resources):
        resource = plan.resources[resource_id]
        if resource.content_sha256 is None:
            _raise_input(
                [
                    _input_diagnostic(
                        "fgui.writer.input.resource_hash_missing",
                        "A Writer resource requires a validated content hash.",
                        node_id=resource_id,
                    )
                ]
            )
        requests.append(
            (
                "resource",
                f"{resource.id}:{resource.content_sha256}:{resource.export_parameters_sha256}",
            )
        )
    return tuple(requests)


def _target_ids(
    plan: FGUIPlanDocument,
    config: NewProjectConfig,
    nodes_by_component: Mapping[str, Mapping[str, FGUIPlanNode]],
) -> dict[tuple[str, str], str]:
    try:
        return TargetIdAllocator().allocate_all(
            _allocation_requests(plan, config, nodes_by_component)
        )
    except (TargetIdCollisionError, TargetNamingError):
        _raise_input(
            [
                _input_diagnostic(
                    "fgui.writer.input.target_identity_invalid",
                    "The input cannot be assigned unambiguous Writer v1 target identities.",
                )
            ]
        )


def _object_id(ids: Mapping[tuple[str, str], str], component_source_ref: str, node_id: str) -> str:
    return ids[("object", f"{component_source_ref}:{node_id}")]


def _resource_id(ids: Mapping[tuple[str, str], str], resource: ResourcePlan) -> str:
    assert resource.content_sha256 is not None
    return ids[
        (
            "resource",
            f"{resource.id}:{resource.content_sha256}:{resource.export_parameters_sha256}",
        )
    ]


def _component_public_provenance(node: FGUIPlanNode) -> dict[str, object]:
    provenance: dict[str, object] = {"uirNodeRef": node.uir_node_ref}
    if node.component is not None:
        provenance.update(
            {
                "candidateKey": node.component.candidate_key,
                "variantProperties": node.component.variant_properties,
                "overrides": node.component.overrides,
            }
        )
    return provenance


def _compile_objects(
    plan: FGUIPlanDocument,
    component_source_ref: str,
    nodes: Mapping[str, FGUIPlanNode],
    root_node_ref: str,
    ids: Mapping[tuple[str, str], str],
) -> tuple[ManifestObject, ...]:
    by_uir_ref = {node.uir_node_ref: node for node in nodes.values()}
    ordered_nodes: list[FGUIPlanNode] = []
    pending = [root_node_ref]
    while pending:
        node_id = pending.pop()
        node = nodes[node_id]
        ordered_nodes.append(node)
        pending.extend(reversed(node.children))

    objects: list[ManifestObject] = []
    for node in ordered_nodes:
        mask_mode = None
        mask_kind = None
        mask_object_ref = None
        mask_content_object_refs: tuple[str, ...] = ()
        raster_consumed_node_refs: tuple[str, ...] = ()
        public_provenance = _component_public_provenance(node)
        if node.mask_ref is not None:
            mask = plan.masks[node.mask_ref]
            mask_mode = mask.mode
            mask_kind = mask.kind
            if mask.corner_radii is not None:
                public_provenance = {
                    **public_provenance,
                    "maskCornerRadii": mask.corner_radii,
                }
            if mask.mode in {MaskMode.NATIVE_CLIP, MaskMode.NATIVE_MASK}:
                mask_source = by_uir_ref[mask.mask_node_ref]
                mask_object_ref = _object_id(ids, component_source_ref, mask_source.id)
                mask_content_object_refs = tuple(
                    _object_id(ids, component_source_ref, by_uir_ref[source_ref].id)
                    for source_ref in mask.content_node_refs
                )
            else:
                raster_consumed_node_refs = tuple(
                    source_ref
                    for source_ref in dict.fromkeys((mask.mask_node_ref, *mask.content_node_refs))
                    if source_ref != node.uir_node_ref
                )

        resource_ref = (
            None
            if node.resource_ref is None
            else _resource_id(ids, plan.resources[node.resource_ref])
        )
        component_ref = (
            None if node.component is None else ids[("component", node.component.definition_ref)]
        )
        objects.append(
            ManifestObject(
                id=_object_id(ids, component_source_ref, node.id),
                sourceNodeRef=node.id,
                parentObjectRef=(
                    None
                    if node.parent_id is None
                    else _object_id(ids, component_source_ref, node.parent_id)
                ),
                childObjectRefs=tuple(
                    _object_id(ids, component_source_ref, child_id) for child_id in node.children
                ),
                zIndex=node.z_index,
                type=node.type,
                transform=node.transform,
                text=node.text,
                resourceRef=resource_ref,
                componentRef=component_ref,
                maskMode=mask_mode,
                maskKind=mask_kind,
                maskObjectRef=mask_object_ref,
                maskContentObjectRefs=mask_content_object_refs,
                rasterConsumedNodeRefs=raster_consumed_node_refs,
                publicProvenance=public_provenance,
            )
        )
    return tuple(objects)


def _definition_order(
    plan: FGUIPlanDocument, ids: Mapping[tuple[str, str], str]
) -> tuple[str, ...]:
    dependencies: dict[str, set[str]] = {
        definition_id: {
            node.component.definition_ref
            for node in definition.nodes.values()
            if node.component is not None
        }
        for definition_id, definition in plan.component_definitions.items()
    }
    dependents: dict[str, set[str]] = defaultdict(set)
    remaining = {definition_id: len(refs) for definition_id, refs in dependencies.items()}
    for definition_id, refs in dependencies.items():
        for dependency in refs:
            dependents[dependency].add(definition_id)
    ready = sorted(
        (definition_id for definition_id, count in remaining.items() if count == 0),
        key=lambda item: ids[("component", item)],
        reverse=True,
    )
    ordered: list[str] = []
    while ready:
        definition_id = ready.pop()
        ordered.append(definition_id)
        for dependent in sorted(
            dependents[definition_id],
            key=lambda item: ids[("component", item)],
        ):
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                ready.append(dependent)
                ready.sort(key=lambda item: ids[("component", item)], reverse=True)
    return tuple(ordered)


def _compile_component(
    plan: FGUIPlanDocument,
    source_ref: str,
    name: str,
    nodes: Mapping[str, FGUIPlanNode],
    root_node_ref: str,
    ids: Mapping[tuple[str, str], str],
) -> ManifestComponent:
    target_id = ids[("component", source_ref)]
    safe_name = validate_target_name(name, "component")
    root_bounds = nodes[root_node_ref].transform.bounds
    return ManifestComponent(
        id=target_id,
        sourceComponentRef=source_ref,
        name=safe_name,
        relativePath=component_path(safe_name, target_id).as_posix(),
        size=Bounds(x=0, y=0, width=root_bounds.width, height=root_bounds.height),
        objects=_compile_objects(plan, source_ref, nodes, root_node_ref, ids),
    )


def _compile_components(
    plan: FGUIPlanDocument,
    nodes_by_component: Mapping[str, Mapping[str, FGUIPlanNode]],
    root_by_component: Mapping[str, str],
    ids: Mapping[tuple[str, str], str],
) -> tuple[ManifestComponent, ...]:
    definitions = tuple(
        _compile_component(
            plan,
            definition_id,
            plan.component_definitions[definition_id].name,
            nodes_by_component[definition_id],
            root_by_component[definition_id],
            ids,
        )
        for definition_id in _definition_order(plan, ids)
    )
    sorted_roots = sorted(plan.roots, key=lambda item: ids[("component", item)])
    roots = tuple(
        _compile_component(
            plan,
            root_id,
            _target_name_from_logical_ref(plan.nodes[root_id].uir_node_ref),
            nodes_by_component[root_id],
            root_by_component[root_id],
            ids,
        )
        for root_id in sorted_roots
    )
    return (*definitions, *roots)


def _compile_resources(
    plan: FGUIPlanDocument,
    node_owner: Mapping[str, str],
    ids: Mapping[tuple[str, str], str],
) -> tuple[ManifestResource, ...]:
    resources: list[ManifestResource] = []
    for resource in plan.resources.values():
        target_id = _resource_id(ids, resource)
        name = _target_name_from_logical_ref(resource.logical_asset_id)
        suffix = ".jpg" if resource.export_format == "jpg" else f".{resource.export_format}"
        consumer_refs = tuple(
            sorted(
                _object_id(ids, node_owner[consumer], consumer) for consumer in resource.consumers
            )
        )
        provenance: dict[str, object] = {
            "exportParametersSha256": resource.export_parameters_sha256
        }
        if resource.reason is not None:
            provenance["reason"] = resource.reason
        assert resource.content_sha256 is not None
        resources.append(
            ManifestResource(
                id=target_id,
                sourceResourceRef=resource.id,
                name=name,
                relativePath=resource_path(name, target_id, suffix).as_posix(),
                mimeType=resource.mime_type,
                contentSha256=resource.content_sha256,
                exportFormat=resource.export_format,
                width=resource.width,
                height=resource.height,
                nineSlice=resource.nine_slice,
                consumerObjectRefs=consumer_refs,
                publicProvenance=provenance,
            )
        )
    return tuple(sorted(resources, key=lambda item: item.id))


def compile_new_project_manifest(
    plan: FGUIPlanDocument,
    config: NewProjectConfig,
    assets: tuple[ValidatedAssetPayload, ...],
) -> NewProjectManifest:
    """Compile validated inputs without reading or writing a target project."""
    _validate_inputs(plan, config, assets)
    node_owner, nodes_by_component, root_by_component = _owner_tables(plan)
    ids = _target_ids(plan, config, nodes_by_component)
    try:
        package_id = ids[("package", f"{plan.document_id}:{config.package_name}")]
        manifest = NewProjectManifest(
            project=config,
            package=ManifestPackage(
                id=package_id,
                name=config.package_name,
                relativePath=PurePosixPath("assets", config.package_name).as_posix(),
                publicProvenance={"sourceDocumentRef": plan.document_id},
            ),
            components=_compile_components(plan, nodes_by_component, root_by_component, ids),
            resources=_compile_resources(plan, node_owner, ids),
        )
    except TargetNamingError:
        _raise_input(
            [
                _input_diagnostic(
                    "fgui.writer.input.target_name_invalid",
                    "Plan names cannot be represented as safe generated target names.",
                )
            ]
        )
    diagnostics = validate_new_project_manifest(manifest)
    if has_errors(diagnostics):
        raise NewProjectManifestError(diagnostics)
    return manifest
