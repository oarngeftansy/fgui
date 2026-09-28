"""Instance-qualified inventory. Definition identity never replaces instance identity."""

from __future__ import annotations

import base64
import copy
import hashlib
import shutil
import tempfile
from pathlib import Path

from lxml import etree

from figma_to_fgui.hifi_project_inspector import (
    _package_resource_index,
    _pair,
    inspect_component,
    resolve_runtime_bound_geometry,
)
from figma_to_fgui.hifi_replacement_models import (
    FguiComponentInventory,
    FguiObjectRef,
    HifiTargetRef,
)

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


def _visible_on_selected_pages(element, controllers: dict[str, str]) -> bool:
    if element.get("visible") == "false":
        return False
    for gear in element.findall("gearDisplay"):
        selected = controllers.get(gear.get("controller", ""))
        if selected is None:
            continue
        pages = {page for page in gear.get("pages", "").split(",") if page}
        if pages and selected not in pages:
            return False
    return True


def component_target(root: Path, target: HifiTargetRef, path: str) -> HifiTargetRef:
    resources, _ = _package_resource_index(root)
    resolved = (root / path).resolve()
    for (package_id, resource_id), resource in resources.items():
        if resource.resolve() == resolved:
            package_root = next(p for p in resolved.parents if (p / "package.xml").is_file())
            relative = resolved.relative_to(package_root)
            return target.model_copy(
                update={
                    "package_id": package_id,
                    "package_name": package_root.name,
                    "component_id": resource_id,
                    "component_name": resolved.stem,
                    "directory": relative.parent.as_posix(),
                    "component_relative_path": path,
                }
            )
    raise ValueError("hifi_component_reference_missing")


def _qualified(prefix: tuple[str, ...], local_id: str) -> str:
    value = (prefix[-1] + ":" if prefix else "") + local_id
    return value if len(value) <= 110 else "nested:" + hashlib.sha256(value.encode()).hexdigest()


def inspect_component_tree(root: Path, target: HifiTargetRef) -> FguiComponentInventory:
    initial = inspect_component(root, target)
    result: list[FguiObjectRef] = []
    issues: list[str] = []
    complete = initial.parse_complete

    def visit(
        local: FguiComponentInventory,
        prefix: tuple[str, ...],
        origin: tuple[float, float],
        scale: tuple[float, float],
        ancestors: frozenset[str],
        inherited: tuple[str, ...],
        parent_visible: bool,
        instance_title: str | None,
        subtree_out_of_scope: bool = False,
    ) -> None:
        nonlocal complete
        path = local.target.component_relative_path
        if path in ancestors:
            issues.append("cycle:" + ":".join(prefix))
            complete = False
            return
        complete = complete and local.parse_complete
        document = etree.parse(str(root / path), _PARSER)
        elements = {e.get("id"): e for e in document.xpath("./displayList/*[@id]")}
        controllers = {e.get("name"): e.get("selected", "0")
                       for e in document.xpath("./controller[@name]")}
        instances = {i.object_id: i for i in local.behavior.instances}
        for item in local.objects:
            element = elements[item.object_id]
            default_visible = parent_visible and _visible_on_selected_pages(element, controllers)
            runtime_text_override = item.object_type in {"text", "richtext"} and item.name == "title" and instance_title is not None
            blockers = inherited
            if element.get("rotation", "0") != "0" or element.get("skew"):
                blockers += ("transformed_object_requires_editor_geometry",)
            x, y = item.x, item.y
            if element.get("anchor") == "true":
                px, py = _pair(element.get("pivot"))
                x -= px * item.width
                y -= py * item.height
            instance = instances.get(item.object_id)
            # A component whose definition lives in another package is shared
            # by every screen that references it; writing new visuals there
            # would change unrelated screens, so the instance and its subtree
            # sit outside this round's replacement scope.
            cross_package = (
                subtree_out_of_scope
                or (instance is not None and instance.referenced_component_path is not None
                    and bool(instance.package_id) and instance.package_id != target.package_id)
            )
            object_id = _qualified(prefix, item.object_id)
            global_item = item.model_copy(
                update={
                    "object_id": object_id,
                    "out_of_scope": cross_package,
                    "parent_id": _qualified(prefix, item.parent_id)
                    if item.parent_id
                    else (prefix[-1] if prefix else None),
                    "component_relative_path": path,
                    "local_object_id": item.object_id,
                    "instance_path": prefix,
                    "owner_origin": origin,
                    "owner_scale": scale,
                    "x": origin[0] + x * scale[0],
                    "y": origin[1] + y * scale[1],
                    "width": item.width * scale[0],
                    "height": item.height * scale[1],
                    "behavior_protected": item.behavior_protected or bool(prefix),
                    "behavior_roles": (*item.behavior_roles, "nested_instance")
                    if prefix
                    else item.behavior_roles,
                    "write_blockers": tuple(dict.fromkeys(blockers)),
                    "raster_conversion_allowed": False,
                    "default_visible": default_visible,
                    "effective_text": instance_title if runtime_text_override else element.get("text"),
                    "runtime_text_override": runtime_text_override,
                }
            )
            if item.object_type == "graph":
                from figma_to_fgui.hifi_type_permissions import can_convert

                global_item = global_item.model_copy(
                    update={"raster_conversion_allowed": can_convert(root, local, item.object_id)}
                )
            result.append(global_item)
            if instance is None or instance.referenced_component_path is None:
                continue
            try:
                child_target = component_target(root, target, instance.referenced_component_path)
                child = inspect_component(root, child_target)
            except (OSError, ValueError, etree.XMLSyntaxError):
                complete = False
                issues.append("unreadable:" + object_id)
                continue
            if child.objects:
                result[-1] = global_item.model_copy(update={"structural_only": True})
            if (item.width, item.height) != (child.width, child.height):
                blockers += ("resized_instance_layout_requires_editor_geometry",)
            if element.get("scale") not in {None, "1,1"}:
                blockers += ("scaled_instance_requires_editor_geometry",)
            if element.get("controller") or any(
                e.tag in {"Button", "Label", "property"} for e in element
            ):
                blockers += ("instance_parameters_require_preservation",)
            visit(
                child,
                (*prefix, object_id),
                (global_item.x, global_item.y),
                scale,
                ancestors | {path},
                tuple(dict.fromkeys(blockers)),
                default_visible,
                next((parameters.get("title") for tag in ("Button", "Label")
                      if (parameters := element.find(tag)) is not None
                      and parameters.get("title")), None),
                cross_package,
            )

    visit(initial, (), (0.0, 0.0), (1.0, 1.0), frozenset(), (), True, None, False)
    return initial.model_copy(
        update={
            "objects": resolve_runtime_bound_geometry(result),
            "expanded_instances": True,
            "parse_complete": complete,
            "scope_issues": tuple(issues),
        }
    )


def _assert_shared_scope(root, inventory, changed_paths):
    from figma_to_fgui.hifi_patch import HifiPatchError

    resources, packages = _package_resource_index(root)
    selected_files = {o.component_relative_path for o in inventory.objects}
    edges = []
    for package_root, package_id in packages.items():
        for path in package_root.rglob("*.xml"):
            if path.name == "package.xml":
                continue
            relative = path.relative_to(root.resolve()).as_posix()
            try:
                document = etree.parse(str(path), _PARSER)
            except etree.XMLSyntaxError:
                raise HifiPatchError("hifi_shared_scope_unverifiable")
            for element in document.xpath("./displayList/component[@src]"):
                referenced = resources.get((element.get("pkg", package_id), element.get("src")))
                if referenced:
                    edges.append((relative, referenced.relative_to(root).as_posix()))
    affected = set(changed_paths)
    while True:
        expanded = set(affected)
        for owner, referenced in edges:
            if referenced not in affected or referenced == inventory.target.component_relative_path:
                continue
            if owner not in selected_files:
                raise HifiPatchError("hifi_shared_scope_violation")
            expanded.add(owner)
        if expanded == affected:
            break
        affected = expanded


def _externally_shared_paths(root, inventory, changed_paths):
    """Definitions whose existing users extend beyond the selected tree."""
    resources, packages = _package_resource_index(root)
    selected = {o.component_relative_path for o in inventory.objects}
    external = set()
    for package_root, package_id in packages.items():
        for path in package_root.rglob("*.xml"):
            if path.name == "package.xml":
                continue
            owner = path.relative_to(root).as_posix()
            if owner in selected:
                continue
            document = etree.parse(str(path), _PARSER)
            for element in document.xpath("./displayList/component[@src]"):
                referenced = resources.get((element.get("pkg", package_id), element.get("src")))
                if referenced is not None:
                    relative = referenced.relative_to(root).as_posix()
                    if relative in changed_paths:
                        external.add(relative)
    return external


def _local_plans(root, inventory, selection, mapping, *, conflicts=None):
    from figma_to_fgui.hifi_patch import HifiPatchError, _flatten, _project_font_uris, _set_visual
    from figma_to_fgui.models import Bounds

    objects = {o.object_id: o for o in inventory.objects}
    decisions = {i.old_object_id: i for i in mapping.items if i.old_object_id}
    nodes = _flatten(selection)
    viewport = selection.top_level_nodes[0].properties.get("psdViewportBounds")
    viewport_offset = (viewport[0], viewport[1]) if viewport else (0, 0)
    fonts = _project_font_uris(root)
    files = {}
    seen_nodes = set()
    previews = {}
    grouped = {}
    for obj in inventory.objects:
        path = obj.component_relative_path
        if path is None:
            raise HifiPatchError("hifi_nested_inventory_invalid")
        if path not in files:
            local = inspect_component(root, component_target(root, inventory.target, path))
            doc = etree.parse(str(root / path), _PARSER)
            files[path] = local, {e.get("id"): e for e in doc.xpath("./displayList/*[@id]")}
        local, elements = files[path]
        original = elements[obj.local_object_id]
        preview = copy.deepcopy(original)
        decision = decisions.get(obj.object_id)
        new_node = None
        if decision and decision.action in {"accept", "retarget"}:
            if decision.figma_node_id in seen_nodes:
                raise HifiPatchError("duplicate_figma_mapping")
            seen_nodes.add(decision.figma_node_id)
            node = nodes.get(decision.figma_node_id)
            if node is None:
                raise HifiPatchError("mapping_target_missing")
            if decision.preserve_runtime_text:
                if (not obj.runtime_text_override or node.type.upper() != "TEXT"
                    or node.text != obj.effective_text or original.get("text") is None):
                    raise HifiPatchError("hifi_instance_override_conflict")
                node = node.model_copy(update={"text": original.get("text")})
            blockers = set(obj.write_blockers) - {"instance_parameters_require_preservation"}
            if blockers:
                raise HifiPatchError("hifi_nested_geometry_unverified")
            if (
                "instance_parameters_require_preservation" in obj.write_blockers
                and obj.name in {"title", "icon"}
                and (
                    node.resource_keys
                    or node.text is not None
                    and node.text != original.get("text")
                )
            ):
                raise HifiPatchError("hifi_instance_override_conflict")
            origin = (
                obj.owner_origin[0] + viewport_offset[0],
                obj.owner_origin[1] + viewport_offset[1],
            )
            if obj.instance_path:
                owner = objects[obj.instance_path[-1]]
                owner_decision = decisions.get(owner.object_id)
                if owner_decision and owner_decision.action in {"accept", "retarget"}:
                    owner_node = nodes.get(owner_decision.figma_node_id)
                    if owner_node is None or (
                        owner_node.bounds.width,
                        owner_node.bounds.height,
                    ) != (owner.width, owner.height):
                        raise HifiPatchError("hifi_nested_geometry_unverified")
                    origin = (owner_node.bounds.x, owner_node.bounds.y)
            bounds = node.bounds
            new_node = node.model_copy(
                update={
                    "bounds": Bounds(
                        x=bounds.x - origin[0],
                        y=bounds.y - origin[1],
                        width=bounds.width,
                        height=bounds.height,
                    ),
                    "children": () if obj.object_type == "component" else node.children,
                }
            )
            if obj.object_type == "component" and not any(
                i.old_object_id
                and i.old_object_id.startswith(obj.object_id + ":")
                and i.action in {"accept", "retarget"}
                for i in mapping.items
            ):
                raise HifiPatchError("hifi_nested_visual_mapping_required")
            frame = selection.top_level_nodes[0].model_copy(
                update={"bounds": Bounds(x=0, y=0, width=local.width, height=local.height)}
            )
            if preview.tag == "graph" and new_node.resource_keys:
                from figma_to_fgui.hifi_type_permissions import can_convert_mapping, convert_graph

                local_decision = decision.model_copy(update={"old_object_id": obj.local_object_id})
                if not can_convert_mapping(root, local, local_decision, new_node):
                    raise HifiPatchError("hifi_type_conversion_not_authorized")
                convert_graph(preview)
            _set_visual(preview, new_node, frame, local, fonts)
            # Include material identity in consensus: two different raster sources
            # must not become one shared definition merely because their boxes match.
            material = new_node.resource_keys
        else:
            material = ()
        key = (path, obj.local_object_id)
        signature = (etree.tostring(preview, method="c14n"), material)
        if key in previews and previews[key] != signature:
            if conflicts is None:
                raise HifiPatchError("hifi_shared_instance_conflict")
            conflicts.add(path)
        previews[key] = signature
        if new_node is not None:
            grouped.setdefault(path, {})[obj.local_object_id] = (decision, new_node)
    if conflicts is None:
        _assert_shared_scope(root, inventory, set(grouped) - {inventory.target.component_relative_path})
    plans = []
    for path, entries in sorted(grouped.items()):
        local, _ = files[path]
        local_items = tuple(
            d.model_copy(update={"old_object_id": local_id}) for local_id, (d, n) in entries.items()
        )
        frame = selection.top_level_nodes[0].model_copy(
            update={
                "bounds": Bounds(x=0, y=0, width=local.width, height=local.height),
                "children": tuple(n for d, n in entries.values()),
            }
        )
        plans.append(
            (
                local,
                selection.model_copy(update={"top_level_nodes": (frame,)}),
                mapping.model_copy(update={"items": local_items, "unresolved_count": 0}),
            )
        )
    return plans


def build_nested_bundle(root, inventory, selection, mapping, *, job_id, selection_root):
    from figma_to_fgui.apply import apply_bundle
    from figma_to_fgui.hifi_patch import HifiPatchError, build_hifi_change_bundle
    from figma_to_fgui.service_contracts import ChangeBundle, ChangeFile, FileOperation

    if mapping.unresolved_count:
        raise HifiPatchError("hifi_mapping_incomplete")
    if any(i.action == "add_visual" for i in mapping.items):
        raise HifiPatchError("hifi_psd_visual_requires_owner")
    conflicts = set()
    preliminary = _local_plans(root, inventory, selection, mapping, conflicts=conflicts)
    changed_definitions = {local.target.component_relative_path for local, _, _ in preliminary}
    changed_definitions.discard(inventory.target.component_relative_path)
    isolate = conflicts | _externally_shared_paths(root, inventory, changed_definitions)
    with tempfile.TemporaryDirectory(prefix="hifi-nested-") as temporary:
        staged = Path(temporary) / "project"
        shutil.copytree(root, staged)
        if isolate:
            from figma_to_fgui.hifi_instance_variant import clone_instance_definition

            accepted = {i.old_object_id for i in mapping.items
                        if i.action in {"accept", "retarget"}}
            for path in sorted(isolate):
                users = {obj.instance_path[-1] for obj in inventory.objects
                         if obj.component_relative_path == path and obj.instance_path
                         and obj.object_id in accepted}
                for instance_id in sorted(users):
                    # A shared parent would need its own variant as well. Keep
                    # this proof narrow until recursive instance isolation is
                    # implemented; never alter a definition used elsewhere.
                    if ":" in instance_id:
                        raise HifiPatchError("hifi_nested_variant_requires_ancestor_isolation")
                    clone_instance_definition(
                        staged, parent_component_path=inventory.target.component_relative_path,
                        instance_id=instance_id, identity=path,
                    )
            inventory = inspect_component_tree(staged, inventory.target)
            if not inventory.parse_complete:
                raise HifiPatchError("hifi_variant_inventory_incomplete")
        plans = _local_plans(staged, inventory, selection, mapping)
        if not plans:
            raise HifiPatchError("hifi_mapping_requires_replacements")
        touched = set()
        for local, source, local_mapping in plans:
            bundle = build_hifi_change_bundle(
                staged, local, source, local_mapping, job_id=job_id, selection_root=selection_root
            )
            apply_bundle(staged, bundle)
            touched.update(f.relative_path for f in bundle.files)
        files = []
        changed_paths = touched | {
            path.relative_to(staged).as_posix() for path in staged.rglob("*")
            if path.is_file() and ".figma-to-fgui" not in path.relative_to(staged).parts and (
                not (root / path.relative_to(staged)).is_file()
                or path.read_bytes() != (root / path.relative_to(staged)).read_bytes()
            )
        }
        for path in sorted(changed_paths):
            before = (root / path).read_bytes() if (root / path).is_file() else None
            after = (staged / path).read_bytes()
            if before == after:
                continue
            files.append(
                ChangeFile(
                    operation=FileOperation.REPLACE if before is not None else FileOperation.CREATE,
                    relative_path=path,
                    before_sha256=hashlib.sha256(before).hexdigest()
                    if before is not None
                    else None,
                    after_sha256=hashlib.sha256(after).hexdigest(),
                    content_b64=base64.b64encode(after).decode(),
                )
            )
        return ChangeBundle(
            version=1, job_id=job_id, project_id=inventory.target.project_id, files=tuple(files)
        )


def validate_nested_candidate(
    before_root, after_root, inventory, mapping, *, session_id, lossless_blockers
):
    from figma_to_fgui.hifi_patch import HifiPatchError, _package_manifest, validate_hifi_candidate

    root_path = inventory.target.component_relative_path
    root_before = etree.parse(str(before_root / root_path), _PARSER)
    root_after = etree.parse(str(after_root / root_path), _PARSER)
    before_instances = {e.get("id"): e for e in root_before.xpath("./displayList/component[@id]")}
    after_instances = {e.get("id"): e for e in root_after.xpath("./displayList/component[@id]")}
    after_resources, _ = _package_resource_index(after_root)
    variant_by_instance = {}
    normalized_root = copy.deepcopy(root_after)
    normalized_instances = {e.get("id"): e for e in normalized_root.xpath("./displayList/component[@id]")}
    for instance_id, before in before_instances.items():
        after = after_instances.get(instance_id)
        if after is None:
            continue
        if before.get("src") == after.get("src"):
            continue
        expected = copy.deepcopy(before)
        changed = copy.deepcopy(after)
        changed.set("src", before.get("src"))
        if before.get("fileName") is None:
            changed.attrib.pop("fileName", None)
        else:
            changed.set("fileName", before.get("fileName"))
        if etree.tostring(expected, method="c14n") != etree.tostring(changed, method="c14n"):
            raise HifiPatchError("hifi_variant_instance_contract_changed")
        parent_package = component_target(before_root, inventory.target, root_path).package_id
        package_id = after.get("pkg") or parent_package
        variant_file = after_resources.get((package_id, after.get("src", "")))
        if (variant_file is None or "__hifi_" not in variant_file.stem
            or not variant_file.is_file()):
            raise HifiPatchError("hifi_variant_reference_invalid")
        original = next((o.component_relative_path for o in inventory.objects
                         if o.instance_path == (instance_id,)), None)
        if original is None:
            raise HifiPatchError("hifi_variant_instance_unmapped")
        original_file = before_root / original
        if (after_root / original).read_bytes() != original_file.read_bytes():
            raise HifiPatchError("hifi_variant_original_changed")
        variant_by_instance[instance_id] = (original, variant_file.relative_to(after_root).as_posix())
        normalized = normalized_instances[instance_id]
        normalized.set("src", before.get("src"))
        if before.get("fileName") is None:
            normalized.attrib.pop("fileName", None)
        else:
            normalized.set("fileName", before.get("fileName"))

    paths = sorted({o.component_relative_path for o in inventory.objects})
    locals_ = {
        p: inspect_component(before_root, component_target(before_root, inventory.target, p))
        for p in paths
    }
    scope = set(paths)
    prefixes = []
    for local in locals_.values():
        manifest, package = _package_manifest(before_root, local)
        scope.add(manifest.relative_to(before_root).as_posix())
        prefixes.append(f"{package}/Img/HIFI/{local.target.component_name}/")
    scope.update(variant for _, variant in variant_by_instance.values())
    for _, variant in variant_by_instance.values():
        variant_path = Path(variant)
        package = variant_path.parent.parent.as_posix()
        prefixes.append(f"{package}/Img/HIFI/{variant_path.stem}/")
    changed_paths = {
        p for p in paths if (before_root / p).read_bytes() != (after_root / p).read_bytes()
    }
    _assert_shared_scope(
        before_root, inventory, changed_paths - {inventory.target.component_relative_path}
    )
    reviews = []
    diffs = []
    objects = {o.object_id: o for o in inventory.objects}
    for path, local in locals_.items():
        # The local inspection cannot see instance expansion. Carry only the
        # structural proof obtained by the expanded, parsed inventory into
        # its byte-for-byte review; an unexpanded component stays visual.
        structural_ids = {
            o.local_object_id for o in inventory.objects
            if o.component_relative_path == path and o.structural_only
        }
        local = local.model_copy(update={"objects": tuple(
            o.model_copy(update={"structural_only": True})
            if o.object_id in structural_ids else o
            for o in local.objects
        )})
        items = tuple(
            i.model_copy(update={"old_object_id": objects[i.old_object_id].local_object_id})
            for i in mapping.items
            if i.old_object_id in objects
            and objects[i.old_object_id].component_relative_path == path
            and not (objects[i.old_object_id].instance_path
                     and objects[i.old_object_id].instance_path[-1] in variant_by_instance)
        )
        local_mapping = mapping.model_copy(update={"items": items})
        review = validate_hifi_candidate(
            before_root,
            after_root,
            local,
            local_mapping,
            session_id=session_id,
            lossless_blockers=lossless_blockers,
            _scope_paths=frozenset(scope),
            _scope_prefixes=tuple(prefixes),
            _after_component_doc=normalized_root if path == root_path and variant_by_instance else None,
        )
        reviews.append(review)
        original_ids = {i.item_id: i.old_object_id for i in mapping.items}
        diffs.extend(
            d.model_copy(update={"old_object_id": original_ids[d.item_id]})
            for d in review.object_diffs
        )
    for instance_id, (original_path, variant_path) in variant_by_instance.items():
        local = locals_[original_path]
        structural_ids = {
            o.local_object_id for o in inventory.objects
            if o.component_relative_path == original_path and o.structural_only
        }
        local = local.model_copy(update={"objects": tuple(
            o.model_copy(update={"structural_only": o.object_id in structural_ids,
                                 "shared_resource": False})
            for o in local.objects
        )})
        items = tuple(
            i.model_copy(update={"old_object_id": objects[i.old_object_id].local_object_id})
            for i in mapping.items if i.old_object_id in objects
            and objects[i.old_object_id].instance_path == (instance_id,)
        )
        variant_doc = etree.parse(str(after_root / variant_path), _PARSER)
        review = validate_hifi_candidate(
            before_root, after_root, local,
            mapping.model_copy(update={"items": items}),
            session_id=session_id, lossless_blockers=lossless_blockers,
            _scope_paths=frozenset(scope), _scope_prefixes=tuple(prefixes),
            _after_component_doc=variant_doc,
        )
        reviews.append(review)
        original_ids = {i.item_id: i.old_object_id for i in mapping.items}
        diffs.extend(d.model_copy(update={"old_object_id": original_ids[d.item_id]})
                     for d in review.object_diffs)
    all_files = {f.relative_path: f for r in reviews for f in r.changed_files}
    warnings = tuple(dict.fromkeys(w for r in reviews for w in r.warnings))
    nested_changed = changed_paths - {inventory.target.component_relative_path}
    if nested_changed:
        warnings += ("嵌套组件视觉已原位改写；须验证全部受影响实例及控制器状态。",)
    if variant_by_instance:
        warnings += ("共享组件按实例建立专属定义；须在 Editor 核对各实例及全部控制器状态。",)
    return reviews[0].model_copy(
        update={
            "target": inventory.target,
            "changed_files": tuple(all_files[p] for p in sorted(all_files)),
            "object_diffs": tuple(diffs),
            "parse_coverage_complete": inventory.parse_complete,
            "approvable": inventory.parse_complete
            and not nested_changed and not variant_by_instance
            and all(r.approvable for r in reviews),
            "warnings": warnings,
        }
    )
