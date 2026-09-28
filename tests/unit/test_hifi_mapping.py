from __future__ import annotations

from pathlib import Path

import pytest

from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.hifi_mapping import HifiMappingError, apply_mapping_decision, build_mapping
from figma_to_fgui.hifi_project_inspector import (
    inspect_component,
    inspect_hifi_targets,
    target_from_option,
)
from figma_to_fgui.hifi_replacement_models import HifiMappingDecision
from figma_to_fgui.models import Bounds
from figma_to_fgui.uploaded_project import index_uploaded_project

FIXTURE = Path(__file__).parents[1] / "fixtures/hifi_replacement"


def _inputs():
    root = FIXTURE / "old_project"
    project = index_uploaded_project(root, "old.zip")
    tree = inspect_hifi_targets(root, project)
    package = tree.packages[0]
    directory = next(item for item in package.directories if item.path == "Panel")
    component = next(item for item in directory.components if item.resource_id == "sketch01")
    inventory = inspect_component(root, target_from_option(project, package, directory, component))
    manifest = SelectionManifest.model_validate_json(
        (FIXTURE / "hifi-selection.json").read_text("utf-8")
    )
    return inventory, manifest


def test_mapping_carries_each_canvas_size_for_full_page_preview() -> None:
    inventory, manifest = _inputs()
    source = manifest.top_level_nodes[0]
    taller = source.model_copy(update={"bounds": Bounds(x=0, y=0, width=900, height=1800)})
    draft = build_mapping(inventory, manifest.model_copy(update={"top_level_nodes": (taller,)}))
    assert draft.old_canvas_size == (inventory.width, inventory.height)
    assert draft.source_canvas_size == (900, 1800)


def test_owned_psd_leaves_join_one_existing_graph_without_hiding_text(tmp_path) -> None:
    from test_hifi_nested import nested_case

    _, inventory, _, _ = nested_case(tmp_path)
    selected = tuple(o.model_copy(update={"raster_conversion_allowed": True})
                     if o.object_id == "a:bg" else o
                     for o in inventory.objects if o.object_id in {"a:bg", "a:title"})
    inventory = inventory.model_copy(update={"objects": selected})
    visual = (
        SelectionNode(id="body", name="Background", type="RECTANGLE",
                      bounds=Bounds(x=10, y=20, width=120, height=44),
                      properties={"psdKind": "shape"}),
        SelectionNode(id="stroke", name="Stroke", type="VECTOR",
                      bounds=Bounds(x=10, y=20, width=120, height=44),
                      properties={"psdKind": "shape"}),
    )
    title = SelectionNode(id="label", name="title", type="TEXT", text="New",
                          bounds=Bounds(x=20, y=30, width=90, height=24),
                          properties={"psdKind": "type"})
    group = SelectionNode(id="button", name="Button", type="GROUP",
                          bounds=Bounds(x=10, y=20, width=120, height=44),
                          properties={"psdKind": "group"}, children=(*visual, title))
    source = SelectionManifest(version=1, display_name="PSD", top_level_nodes=(
        SelectionNode(id="psd-root:synthetic", name="PSD", type="FRAME",
                      bounds=Bounds(x=0, y=0, width=750, height=420), children=(group,)),
    ))
    validated = []

    def proof(group_id, owned, retained):
        validated.append((group_id, owned, retained))
        return True

    draft = build_mapping(inventory, source, owned_visual_validator=proof)
    body = next(i for i in draft.items if i.old_object_id == "a:bg")
    assert validated == [("button", frozenset({"body", "stroke"}), frozenset({"label"}))]
    assert body.owned_source_ids == ("body", "stroke")
    assert body.owned_group_id == "button"
    assert body.retained_source_ids == ("label",)
    assert body.action == "accept"
    assert next(i for i in draft.items if i.old_object_id == "a:title").action == "accept"
    assert not any(i.figma_node_id == "stroke" for i in draft.items)
    accepted = draft.model_copy(update={"items": tuple(i.model_copy(update={"action": "accept"})
                                                       for i in draft.items)})
    from figma_to_fgui.hifi_mapping import require_psd_coverage

    require_psd_coverage(accepted, source)
    rejected = build_mapping(inventory, source, owned_visual_validator=lambda *_: False)
    assert any(i.figma_node_id == "stroke" and i.status == "hifi_added"
               for i in rejected.items)


def test_proven_visual_owner_stays_on_its_anchor_after_resource_bounds_change(tmp_path) -> None:
    from test_hifi_nested import nested_case

    _, inventory, _, _ = nested_case(tmp_path)
    old = next(o for o in inventory.objects if o.object_id == "a:bg")
    inventory = inventory.model_copy(update={"objects": (old.model_copy(update={
        "raster_conversion_allowed": True,
    }),)})
    nodes = (
        SelectionNode(id="anchor", name="Background", type="IMAGE",
                      bounds=Bounds(x=10, y=20, width=116, height=44)),
        SelectionNode(id="sibling", name="Background", type="IMAGE",
                      bounds=Bounds(x=10, y=20, width=120, height=44)),
    )
    manifest = SelectionManifest(version=1, display_name="PSD", top_level_nodes=(
        SelectionNode(id="psd-root:test", name="PSD", type="FRAME",
                      bounds=Bounds(x=0, y=0, width=750, height=420), children=nodes),
    ))
    draft = build_mapping(inventory, manifest, proven_source_owners={old.object_id: "anchor"})
    assert next(i for i in draft.items if i.old_object_id == old.object_id).figma_node_id == "anchor"


def test_generated_state_is_tied_to_existing_object_only(tmp_path) -> None:
    from test_hifi_nested import nested_case

    _, inventory, _, _ = nested_case(tmp_path)
    old = next(o for o in inventory.objects if o.object_id == "a:title")
    inventory = inventory.model_copy(update={"objects": (old,)})
    state = SelectionNode(id="derived-state:test", name="new state", type="TEXT",
                          bounds=Bounds(x=20, y=30, width=90, height=24),
                          properties={"generatedStateOwner": old.object_id,
                                      "generatedStateRole": "text"})
    manifest = SelectionManifest(version=1, display_name="PSD", top_level_nodes=(
        SelectionNode(id="psd-root:test", name="PSD", type="FRAME",
                      bounds=Bounds(x=0, y=0, width=750, height=420), children=(state,)),
    ))
    draft = build_mapping(inventory, manifest)
    assert draft.unresolved_count == 0
    assert len(draft.items) == 1
    assert draft.items[0].generated_state and draft.items[0].action == "accept"


def test_full_bleed_visual_proof_selects_only_the_unique_matching_pixel_layer() -> None:
    inventory, _ = _inputs()
    old = next(o for o in inventory.objects if o.object_type == "image")
    old = old.model_copy(update={"x": 0, "y": -20, "width": 750, "height": 460,
                                 "name": "legacy backdrop"})
    inventory = inventory.model_copy(update={"objects": (old,), "width": 750, "height": 420})
    candidates = tuple(SelectionNode(
        id=f"backdrop-{index}", name=f"layer {index}", type="IMAGE",
        bounds=Bounds(x=0, y=-20, width=750, height=460),
        properties={"psdKind": "pixel", "blendMode": "normal",
                    "hasEffects": False, "hasPixelMask": False,
                    "hasVectorMask": False, "clipping": False},
    ) for index in range(3))
    manifest = SelectionManifest(version=1, display_name="PSD", top_level_nodes=(
        SelectionNode(id="psd-root:synthetic", name="PSD", type="FRAME",
                      bounds=Bounds(x=0, y=0, width=750, height=420), children=candidates),
    ))
    draft = build_mapping(
        inventory, manifest,
        full_bleed_visual_validator=lambda _old, node: .998 if node.id == "backdrop-2" else 0,
    )
    match = next(i for i in draft.items if i.old_object_id == old.object_id)
    assert (match.figma_node_id, match.action, match.score) == ("backdrop-2", "accept", .998)


def test_unique_renderable_psd_shape_proves_graph_conversion() -> None:
    inventory, _ = _inputs()
    old = next(o for o in inventory.objects if o.object_type == "graph")
    old = old.model_copy(update={"x": 20, "y": 50, "width": 100, "height": 400,
                                 "raster_conversion_allowed": False})
    inventory = inventory.model_copy(update={"objects": (old,), "width": 750, "height": 500})
    shape = SelectionNode(id="shape", name="new rail", type="VECTOR",
                          bounds=Bounds(x=10, y=45, width=100, height=400),
                          properties={"psdKind": "shape", "blendMode": "normal",
                                      "hasVectorMask": True})
    other = shape.model_copy(update={"id": "other", "bounds": Bounds(
        x=500, y=45, width=100, height=400)})
    manifest = SelectionManifest(version=1, display_name="PSD", top_level_nodes=(
        SelectionNode(id="psd-root:test", name="PSD", type="FRAME",
                      bounds=Bounds(x=0, y=0, width=750, height=500),
                      children=(shape, other)),
    ))
    proven = build_mapping(inventory, manifest, graph_raster_validator=lambda n: n.id == "shape")
    match = next(i for i in proven.items if i.old_object_id == old.object_id)
    assert match.action == "accept" and match.graph_conversion_proven
    assert match.figma_node_id == "shape"
    unrenderable = build_mapping(inventory, manifest, graph_raster_validator=lambda _: False)
    assert not any(i.graph_conversion_proven for i in unrenderable.items)
    competing = shape.model_copy(update={"id": "competing", "bounds": Bounds(
        x=15, y=47, width=100, height=400)})
    ambiguous = manifest.model_copy(update={"top_level_nodes": (
        manifest.top_level_nodes[0].model_copy(update={"children": (shape, competing)}),)})
    result = build_mapping(inventory, ambiguous, graph_raster_validator=lambda _: True)
    assert not any(i.graph_conversion_proven for i in result.items)
    competing_old = old.model_copy(update={"object_id": "image-over-graph",
                                            "object_type": "image", "name": "other"})
    shared_pixels = inventory.model_copy(update={"objects": (old, competing_old)})
    result = build_mapping(shared_pixels, manifest, graph_raster_validator=lambda _: True)
    assert not any(i.graph_conversion_proven for i in result.items)


def test_psd_incompatible_type_cannot_be_auto_accepted_or_offered() -> None:
    inventory, manifest = _inputs()
    old = next(item for item in inventory.objects if item.object_type == "image")
    leaf = SelectionNode(id="wrong-text", name=old.name, type="TEXT", text="Wrong",
                         bounds=Bounds(x=old.x, y=old.y, width=old.width, height=old.height))
    root = manifest.top_level_nodes[0].model_copy(update={"id": "psd-root:test", "children": (leaf,)})
    draft = build_mapping(inventory.model_copy(update={"objects": (old,)}),
                          manifest.model_copy(update={"top_level_nodes": (root,)}))
    item = next(item for item in draft.items if item.old_object_id == old.object_id)
    assert item.action is None
    assert not item.candidates


def test_zero_area_psd_layer_cannot_claim_old_image() -> None:
    inventory, manifest = _inputs()
    old = next(item for item in inventory.objects if item.object_type == "image")
    empty = SelectionNode(
        id="empty-image", name=old.name, type="IMAGE",
        bounds=Bounds(x=old.x, y=old.y, width=0, height=0),
    )
    root = manifest.top_level_nodes[0].model_copy(update={"id": "psd-root:test", "children": (empty,)})
    draft = build_mapping(
        inventory.model_copy(update={"objects": (old,)}),
        manifest.model_copy(update={"top_level_nodes": (root,)}),
    )
    item = next(item for item in draft.items if item.old_object_id == old.object_id)
    assert item.figma_node_id is None
    assert not item.candidates


def test_psd_group_does_not_hide_twenty_independent_leaf_decisions() -> None:
    inventory, manifest = _inputs()
    leaves = tuple(SelectionNode(id=f"leaf-{i}", name=f"Leaf {i}", type="IMAGE",
                                bounds=Bounds(x=i, y=0, width=10, height=10)) for i in range(20))
    group = SelectionNode(id="group", name="Section", type="GROUP",
                          bounds=Bounds(x=0, y=0, width=30, height=10), children=leaves)
    root = manifest.top_level_nodes[0].model_copy(update={"id": "psd-root:test", "children": (group,)})
    draft = build_mapping(inventory.model_copy(update={"objects": ()}),
                          manifest.model_copy(update={"top_level_nodes": (root,)}))
    assert {item.figma_node_id for item in draft.items} >= {leaf.id for leaf in leaves}
    assert draft.unresolved_count >= 20


def test_psd_exception_does_not_count_as_complete_visual_coverage() -> None:
    from figma_to_fgui.hifi_mapping import require_psd_coverage
    inventory, manifest = _inputs()
    manifest = manifest.model_copy(update={"top_level_nodes": (
        manifest.top_level_nodes[0].model_copy(update={"id": "psd-root:test"}),)})
    draft = build_mapping(inventory, manifest)
    waived = draft.model_copy(update={"items": tuple(
        item.model_copy(update={"action": "exception"}) for item in draft.items), "unresolved_count": 0})
    with pytest.raises(HifiMappingError, match="hifi_mapping_coverage_incomplete"):
        require_psd_coverage(waived, manifest)


def test_psd_mapping_geometry_uses_same_unscaled_canvas_as_patch() -> None:
    from figma_to_fgui.hifi_mapping import _figma_bounds, _selection_box

    inventory, manifest = _inputs()
    root = manifest.top_level_nodes[0].model_copy(update={
        "id": "psd-root:test", "bounds": Bounds(x=0, y=0, width=1080, height=2340),
    })
    manifest = manifest.model_copy(update={"top_level_nodes": (root,)})
    node = SelectionNode(id="bottom", name="bottom", type="IMAGE",
                         bounds=Bounds(x=-6, y=1976, width=388, height=114))
    assert _selection_box(manifest, node, inventory) == (-6, 1976, 388, 114)
    assert _figma_bounds(manifest, node, inventory) == pytest.approx(
        (0, 1976 / 2340, 388 / 1080, 114 / 2340)
    )


def test_psd_mapping_score_uses_declared_viewport_without_moving_source_highlight() -> None:
    from figma_to_fgui.hifi_mapping import _figma_bounds, _selection_box

    inventory, manifest = _inputs()
    root = manifest.top_level_nodes[0].model_copy(update={
        "id": "psd-root:test",
        "bounds": Bounds(x=0, y=0, width=1080, height=2340),
        "properties": {"psdViewportBounds": (0, 210, 1080, 1920)},
    })
    manifest = manifest.model_copy(update={"top_level_nodes": (root,)})
    node = SelectionNode(id="button", name="button", type="IMAGE",
                         bounds=Bounds(x=20, y=1976, width=388, height=114))
    assert _selection_box(manifest, node, inventory) == (20, 1766, 388, 114)
    assert _figma_bounds(manifest, node, inventory)[1] == pytest.approx(1976 / 2340)


def test_psd_viewport_translation_is_not_tied_to_homepage_dimensions() -> None:
    from figma_to_fgui.hifi_mapping import _selection_box

    inventory, manifest = _inputs()
    root = manifest.top_level_nodes[0].model_copy(update={
        "id": "psd-root:other-project",
        "bounds": Bounds(x=0, y=0, width=900, height=700),
        "properties": {"psdViewportBounds": (75, 140, 750, 420)},
    })
    manifest = manifest.model_copy(update={"top_level_nodes": (root,)})
    node = SelectionNode(id="other-button", name="other-button", type="IMAGE",
                         bounds=Bounds(x=95, y=175, width=120, height=44))
    assert _selection_box(manifest, node, inventory) == (20, 35, 120, 44)


def test_psd_unmatched_visuals_are_not_silently_approved_as_keep_old() -> None:
    inventory, manifest = _inputs()
    root = manifest.top_level_nodes[0].model_copy(update={"id": "psd-root:test"})
    draft = build_mapping(inventory, manifest.model_copy(update={"top_level_nodes": (root,)}))
    reset = next(item for item in draft.items if item.old_object_id == "btn_reset")
    assert reset.action is None



def test_mapping_classifies_matched_added_missing_and_uncertain() -> None:
    inventory, manifest = _inputs()
    draft = build_mapping(inventory, manifest)
    by_old = {item.old_object_id: item for item in draft.items if item.old_object_id}
    by_figma = {item.figma_node_id: item for item in draft.items if item.figma_node_id}
    assert by_old["silhouette_01"].status == "matched"
    assert by_old["silhouette_01"].old_object_type is not None
    assert by_figma["progress-bubble"].status == "hifi_added"
    assert by_figma["progress-bubble"].action is None
    assert by_old["btn_reset"].status == "fgui_only"
    assert by_old["old_badge"].status == "uncertain"
    assert draft.model_dump_json() == build_mapping(inventory, manifest).model_dump_json()


def test_decision_advances_revision_and_rejects_stale_or_duplicate_target() -> None:
    inventory, manifest = _inputs()
    draft = build_mapping(inventory, manifest)
    uncertain = next(item for item in draft.items if item.status == "uncertain")
    candidate = uncertain.candidates[0]
    updated = apply_mapping_decision(
        draft,
        HifiMappingDecision(
            version=1,
            mapping_revision=draft.mapping_revision,
            item_id=uncertain.item_id,
            action="retarget",
            figma_node_id=candidate,
        ),
        manifest,
    )
    assert updated.mapping_revision == draft.mapping_revision + 1
    with pytest.raises(HifiMappingError, match="stale_mapping"):
        apply_mapping_decision(
            updated,
            HifiMappingDecision(
                version=1,
                mapping_revision=draft.mapping_revision,
                item_id=uncertain.item_id,
                action="keep_old",
            ),
            manifest,
        )


def test_mapping_normalizes_absolute_figma_canvas_coordinates() -> None:
    inventory, manifest = _inputs()

    def move(node):
        return node.model_copy(
            update={
                "bounds": Bounds(
                    x=node.bounds.x + 1000,
                    y=node.bounds.y + 500,
                    width=node.bounds.width,
                    height=node.bounds.height,
                ),
                "children": tuple(move(child) for child in node.children),
            }
        )

    shifted = manifest.model_copy(update={"top_level_nodes": tuple(move(node) for node in manifest.top_level_nodes)})
    original = build_mapping(inventory, manifest)
    moved = build_mapping(inventory, shifted)
    original_silhouette = next(item for item in original.items if item.old_object_id == "silhouette_01")
    moved_silhouette = next(item for item in moved.items if item.old_object_id == "silhouette_01")
    assert moved_silhouette.status == original_silhouette.status
    assert moved_silhouette.figma_bounds == original_silhouette.figma_bounds


def test_mapping_blocks_unsupported_added_container_until_user_marks_exception() -> None:
    inventory, manifest = _inputs()
    selection_root = manifest.top_level_nodes[0]
    unsupported = SelectionNode(
        id="hifi-dialog",
        name="InteractiveDialog",
        type="FRAME",
        bounds=Bounds(x=100, y=100, width=200, height=120),
        children=(
            SelectionNode(
                id="hifi-dialog-button",
                name="DialogButton",
                type="INSTANCE",
                bounds=Bounds(x=120, y=180, width=80, height=30),
            ),
        ),
    )
    manifest = manifest.model_copy(
        update={
            "top_level_nodes": (
                selection_root.model_copy(
                    update={"children": (*selection_root.children, unsupported)}
                ),
            )
        }
    )

    mapping = build_mapping(inventory, manifest)

    blocked = next(item for item in mapping.items if item.figma_node_id == "hifi-dialog")
    assert blocked.status == "blocked"
    assert blocked.action is None
    assert mapping.unresolved_count >= 1
    with pytest.raises(HifiMappingError, match="mapping_action_not_allowed"):
        apply_mapping_decision(
            mapping,
            HifiMappingDecision(
                version=1,
                mapping_revision=mapping.mapping_revision,
                item_id=blocked.item_id,
                action="add_visual",
            ),
            manifest,
        )


def test_mapping_allows_psd_image_leaf_to_be_added_as_visual() -> None:
    inventory, manifest = _inputs()
    selection_root = manifest.top_level_nodes[0]
    psd_image = SelectionNode(
        id="psd-layer:image-leaf",
        name="Rendered smart object",
        type="IMAGE",
        bounds=Bounds(x=40, y=60, width=320, height=180),
        properties={"psdKind": "smartobject"},
    )
    manifest = manifest.model_copy(
        update={
            "top_level_nodes": (
                selection_root.model_copy(
                    update={"children": (*selection_root.children, psd_image)}
                ),
            )
        }
    )

    mapping = build_mapping(inventory, manifest)

    added = next(item for item in mapping.items if item.figma_node_id == psd_image.id)
    assert added.status == "hifi_added"
    assert added.action is None


def test_mapping_does_not_add_zero_area_psd_image() -> None:
    inventory, manifest = _inputs()
    selection_root = manifest.top_level_nodes[0]
    empty_image = SelectionNode(
        id="psd-layer:empty-image",
        name="Empty pixel layer",
        type="IMAGE",
        bounds=Bounds(x=0, y=0, width=0, height=0),
        properties={"psdKind": "pixel"},
    )
    manifest = manifest.model_copy(
        update={
            "top_level_nodes": (
                selection_root.model_copy(
                    update={"children": (*selection_root.children, empty_image)}
                ),
            )
        }
    )

    mapping = build_mapping(inventory, manifest)

    empty = next(item for item in mapping.items if item.figma_node_id == empty_image.id)
    assert empty.status == "blocked"


def test_component_instance_prefers_same_bounds_psd_group_as_its_visual_section() -> None:
    inventory, _ = _inputs()
    button = next(item for item in inventory.objects if item.object_id == "btn_next")
    focused_inventory = inventory.model_copy(update={"objects": (button,)})
    manifest = SelectionManifest(
        version=1,
        display_name="PSD",
        top_level_nodes=(
            SelectionNode(
                id="psd-root:" + "d" * 64,
                name="PSD",
                type="FRAME",
                bounds=Bounds(x=0, y=0, width=inventory.width, height=inventory.height),
                children=(
                    SelectionNode(
                        id="psd-button-group",
                        name="Primary action",
                        type="GROUP",
                        bounds=Bounds(
                            x=button.x,
                            y=button.y,
                            width=button.width,
                            height=button.height,
                        ),
                    ),
                ),
            ),
        ),
    )

    mapping = build_mapping(focused_inventory, manifest)

    item = next(item for item in mapping.items if item.old_object_id == button.object_id)
    assert item.figma_node_id == "psd-button-group"
    assert item.status == "suggested"


def test_tentative_matches_are_unique_and_not_listed_again_as_new() -> None:
    inventory, _ = _inputs()
    button = next(item for item in inventory.objects if item.object_id == "btn_next")
    duplicate = button.model_copy(update={"object_id": "other_button", "name": "other_button"})
    focused_inventory = inventory.model_copy(update={"objects": (button, duplicate)})
    node = SelectionNode(id="psd-button", name="Primary action", type="GROUP", bounds=Bounds(x=button.x, y=button.y, width=button.width, height=button.height))
    manifest = SelectionManifest(version=1, display_name="PSD", top_level_nodes=(SelectionNode(id="root", name="PSD", type="FRAME", bounds=Bounds(x=0, y=0, width=inventory.width, height=inventory.height), children=(node,)),))

    mapping = build_mapping(focused_inventory, manifest)

    assert sum(item.figma_node_id == node.id for item in mapping.items) == 1
    assert not any(item.status == "hifi_added" for item in mapping.items)


def test_unmatched_group_is_one_review_unit_instead_of_each_descendant() -> None:
    inventory, _ = _inputs()
    group = SelectionNode(id="new-group", name="New section", type="GROUP", bounds=Bounds(x=0, y=0, width=100, height=100), children=(SelectionNode(id="new-leaf", name="Artwork", type="IMAGE", bounds=Bounds(x=0, y=0, width=100, height=100)),))
    manifest = SelectionManifest(version=1, display_name="PSD", top_level_nodes=(SelectionNode(id="root", name="PSD", type="FRAME", bounds=Bounds(x=0, y=0, width=inventory.width, height=inventory.height), children=(group,)),))
    empty_inventory = inventory.model_copy(update={"objects": ()})

    mapping = build_mapping(empty_inventory, manifest)

    assert [item.figma_node_id for item in mapping.items] == ["new-group"]


def test_retargeting_an_old_object_resolves_the_same_psd_branch_as_new() -> None:
    inventory, manifest = _inputs()
    mapping = build_mapping(inventory, manifest)
    old = next(item for item in mapping.items if item.old_object_id == "btn_reset")
    new = next(item for item in mapping.items if item.figma_node_id == "progress-bubble")

    updated = apply_mapping_decision(mapping, HifiMappingDecision(version=1, mapping_revision=mapping.mapping_revision, item_id=old.item_id, action="retarget", figma_node_id=new.figma_node_id), manifest)

    assert next(item for item in updated.items if item.item_id == old.item_id).action == "retarget"
    assert next(item for item in updated.items if item.item_id == new.item_id).action == "exception"
    assert updated.unresolved_count == mapping.unresolved_count - 1
