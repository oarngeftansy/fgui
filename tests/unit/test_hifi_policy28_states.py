from figma_to_fgui.hifi_mapping import auto_legacy_state, derive_legacy_state
from figma_to_fgui.hifi_replacement_models import HifiMappingItem


def item(**overrides):
    fields = dict(
        item_id="old:x",
        old_object_id="x",
        old_name="x",
        old_object_type="image",
        status="fgui_only",
        score=0.5,
        evidence=None,
        action=None,
        default_visible=True,
        preserve_runtime_text=False,
        visual_disposition="preserve",
    )
    fields.update(overrides)
    return HifiMappingItem.model_construct(**fields)


def test_matched_actions_derive_replace_or_restyle():
    assert derive_legacy_state(item(action="accept", old_object_type="image")) == "REPLACE"
    assert derive_legacy_state(item(action="retarget", old_object_type="loader")) == "REPLACE"
    assert derive_legacy_state(item(action="accept", old_object_type="text")) == "RESTYLE"
    assert derive_legacy_state(item(action="accept", old_object_type="graph")) == "RESTYLE"
    assert derive_legacy_state(item(action="exception")) == "USER_DECISION"
    assert derive_legacy_state(item(action=None)) is None


def test_preserve_decisions_carry_explicit_policy28_states():
    assert derive_legacy_state(item(action="keep_old", visual_disposition="retire")) == "RETIRE"
    assert derive_legacy_state(item(action="keep_old", default_visible=False)) == "PRESERVE_OTHER_STATE"
    assert derive_legacy_state(item(action="keep_old", old_object_type="loader")) == "PRESERVE_RUNTIME"
    assert derive_legacy_state(item(action="keep_old", old_object_type="list")) == "PRESERVE_RUNTIME"
    assert derive_legacy_state(item(action="keep_old", preserve_runtime_text=True)) == "PRESERVE_RUNTIME"
    assert derive_legacy_state(item(action="keep_old", old_object_type="component")) == "PRESERVE_RUNTIME"
    # Policy 28 §11: keeping a visible static legacy visual conflicts with the
    # PSD target state instead of silently passing as KEEP_OLD.
    assert derive_legacy_state(item(action="keep_old", old_object_type="image")) == "USER_DECISION_CONFLICT"
    assert derive_legacy_state(item(action="keep_old", old_object_type="graph")) == "USER_DECISION_CONFLICT"


def test_unmatched_legacy_objects_are_classified_never_default_kept():
    assert auto_legacy_state(item(default_visible=False)) == ("PRESERVE_OTHER_STATE", "keep_old")
    assert auto_legacy_state(item(old_object_type="loader")) == ("PRESERVE_RUNTIME", "keep_old")
    assert auto_legacy_state(item(old_object_type="list")) == ("PRESERVE_RUNTIME", "keep_old")
    assert auto_legacy_state(item(old_object_type="component")) == ("PRESERVE_RUNTIME", "keep_old")
    assert auto_legacy_state(item(preserve_runtime_text=True, old_object_type="text")) == (
        "PRESERVE_RUNTIME",
        "keep_old",
    )
    # Static visible legacy visuals become removal candidates for the review;
    # they are never auto-kept and never auto-removed.
    assert auto_legacy_state(item(old_object_type="image")) == ("REMOVE_CANDIDATE", None)
    assert auto_legacy_state(item(old_object_type="graph")) == ("REMOVE_CANDIDATE", None)
    assert auto_legacy_state(item(old_object_type="text")) == ("REMOVE_CANDIDATE", None)
