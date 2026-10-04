import pytest
from test_hifi_nested import nested_case


def test_fgui_only_item_is_classified_and_human_keep_old_still_allowed(tmp_path):
    from figma_to_fgui.hifi_mapping import apply_mapping_decision, build_mapping
    from figma_to_fgui.hifi_nested import inspect_component_tree
    from figma_to_fgui.hifi_replacement_models import HifiMappingDecision

    root, inventory, source, _ = nested_case(tmp_path)
    draft = build_mapping(inspect_component_tree(root, inventory.target), source)
    item = next(
        i for i in draft.items
        if i.status == "fgui_only" and i.old_object_id and not i.figma_node_id
    )
    assert item.action is None and item.legacy_state == "REMOVE_CANDIDATE"
    decided = apply_mapping_decision(
        draft,
        HifiMappingDecision(
            version=1,
            mapping_revision=draft.mapping_revision,
            item_id=item.item_id,
            action="keep_old",
        ),
        source,
    )
    resolved = next(i for i in decided.items if i.item_id == item.item_id)
    assert resolved.action == "keep_old"
    assert resolved.legacy_state == "USER_DECISION_CONFLICT"
    assert decided.unresolved_count == draft.unresolved_count - 1


def test_fgui_only_item_rejects_exception_in_psd_flow(tmp_path):
    from figma_to_fgui.hifi_mapping import HifiMappingError, apply_mapping_decision, build_mapping
    from figma_to_fgui.hifi_nested import inspect_component_tree
    from figma_to_fgui.hifi_replacement_models import HifiMappingDecision

    root, inventory, source, _ = nested_case(tmp_path)
    draft = build_mapping(inspect_component_tree(root, inventory.target), source)
    item = next(
        i for i in draft.items
        if i.status == "fgui_only" and i.old_object_id and not i.figma_node_id
    )
    with pytest.raises(HifiMappingError, match="hifi_old_visual_retention_not_allowed"):
        apply_mapping_decision(
            draft,
            HifiMappingDecision(
                version=1,
                mapping_revision=draft.mapping_revision,
                item_id=item.item_id,
                action="exception",
            ),
            source,
        )


def test_matched_item_still_rejects_exception_in_psd_flow(tmp_path):
    from figma_to_fgui.hifi_mapping import HifiMappingError, apply_mapping_decision, build_mapping
    from figma_to_fgui.hifi_nested import inspect_component_tree
    from figma_to_fgui.hifi_replacement_models import HifiMappingDecision

    root, inventory, source, _ = nested_case(tmp_path)
    draft = build_mapping(inspect_component_tree(root, inventory.target), source)
    item = next(
        i for i in draft.items
        if i.old_object_id and i.figma_node_id and i.status in {"matched", "suggested", "uncertain"}
    )
    with pytest.raises(HifiMappingError, match="hifi_old_visual_retention_not_allowed"):
        apply_mapping_decision(
            draft,
            HifiMappingDecision(
                version=1,
                mapping_revision=draft.mapping_revision,
                item_id=item.item_id,
                action="exception",
            ),
            source,
        )
