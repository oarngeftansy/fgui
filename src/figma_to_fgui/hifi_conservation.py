"""Policy 28 Hardening: conservation invariants for the reskin pipeline.

A transformation stage may legitimately move PSD leaf ownership between
carriers (raw bundle host, semantic bundle host, direct correspondence, text
reuse, composite promotion), but it may never let an owned source leaf
silently disappear. ``record_stage`` appends a ledger entry to the mapping
draft, ``require_ownership_conservation`` proves
``before ownership = after ownership + explicit release`` and raises
``HifiConservationError`` naming the lost IDs, the carriers, the stage and
the transformation.
"""
from __future__ import annotations

from figma_to_fgui.hifi_mapping import (
    HifiMappingDraft,
    _legacy_unexplained,
    _psd_coverage,
)
from figma_to_fgui.hifi_replacement_models import HifiStageLedgerEntry

OWNERSHIP_CONSERVATION_CODE = "hifi_ownership_conservation_violation"

_OWNED_ACTIONS = frozenset({"accept", "retarget"})


class HifiConservationError(ValueError):
    """A conservation invariant was violated; the stage must block."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def ownership_carriers(draft: HifiMappingDraft) -> dict[str, frozenset[str]]:
    """Map each accepted bundle host to the source leaves it owns."""
    carriers: dict[str, frozenset[str]] = {}
    for item in draft.items:
        if item.action in _OWNED_ACTIONS and item.owned_source_ids:
            carriers[item.item_id] = frozenset(item.owned_source_ids)
    return carriers


def ownership_ids(draft: HifiMappingDraft) -> frozenset[str]:
    """The multiset-corrected union of owned source leaves."""
    return frozenset(
        source_id
        for item in draft.items
        if item.action in _OWNED_ACTIONS
        for source_id in item.owned_source_ids
    )


def ledger_releases(draft: HifiMappingDraft) -> frozenset[str]:
    """Every source leaf explicitly released by a recorded ledger entry."""
    released: set[str] = set()
    for entry in draft.stage_ledger:
        released.update(entry.released_source_ids)
    return frozenset(released)


def _is_psd(manifest) -> bool:
    return bool(manifest.top_level_nodes) and manifest.top_level_nodes[0].id.startswith(
        "psd-root:"
    )


def stage_entry(
    draft: HifiMappingDraft,
    manifest,
    *,
    transformation: str,
    stage: str | None = None,
    released: frozenset[str] = frozenset(),
    lost: frozenset[str] = frozenset(),
) -> HifiStageLedgerEntry:
    """Summarize one transformation stage for the mapping's ledger."""
    required, gaps = _psd_coverage(draft, manifest)
    owned = ownership_ids(draft)
    carriers = ownership_carriers(draft)
    legacy_items = [
        item for item in draft.items
        if item.old_object_id is not None and not item.out_of_scope
    ]
    unexplained = _legacy_unexplained(draft, strict=_is_psd(manifest))
    composite = sum(
        len(item.composite_source_ids) for item in draft.items
        if item.action in _OWNED_ACTIONS
    )
    pending = sum(
        1 for item in legacy_items if item.action is None
    )
    candidates = sum(
        1 for item in draft.items if item.legacy_state == "REMOVE_CANDIDATE"
    )
    exclusions = sum(
        1 for item in draft.items if item.out_of_scope or item.occluded
    )
    return HifiStageLedgerEntry(
        version=1,
        stage=stage or transformation,
        transformation=transformation,
        source_count=len(required),
        owned_source_count=len(owned),
        owned_carrier_count=len(carriers),
        composite_source_count=composite,
        legacy_object_count=len(legacy_items),
        legacy_settled_count=len(legacy_items) - len(unexplained),
        pending_decision_count=pending,
        remove_candidate_count=candidates,
        explicit_exclusion_count=exclusions,
        released_source_count=len(released),
        lost_source_ids=tuple(sorted(lost)),
        released_source_ids=tuple(sorted(released)),
    )


def require_ownership_conservation(
    input_owned,
    output_draft: HifiMappingDraft,
    manifest,
    *,
    transformation: str,
    released: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    """Prove ``before ownership = after ownership + explicit release``.

    Every source leaf owned by an accepted bundle entering the stage must
    leave it explained: owned by any carrier, directly matched, text-reused,
    composite, scope-excluded, or explicitly released. A silent drop raises
    ``HifiConservationError`` with the lost IDs, carriers and stage.
    """
    required, gaps = _psd_coverage(output_draft, manifest)
    covered = required - gaps
    lost = (set(input_owned) & required) - covered - set(released)
    if lost:
        carriers = ownership_carriers(output_draft)
        raise HifiConservationError(
            OWNERSHIP_CONSERVATION_CODE,
            "transformation={0} lost_source_ids={1} carriers={2} "
            "released={3}".format(
                transformation,
                sorted(lost)[:12],
                sorted(carriers)[:12],
                sorted(released)[:12],
            ),
        )
    return tuple(sorted(lost))


def record_stage(
    draft: HifiMappingDraft,
    manifest,
    *,
    transformation: str,
    before: HifiMappingDraft | None = None,
    released: frozenset[str] = frozenset(),
) -> HifiMappingDraft:
    """Append one ledger entry; with ``before`` also run the chain check."""
    lost: frozenset[str] = frozenset()
    if before is not None:
        required, gaps = _psd_coverage(draft, manifest)
        covered = required - gaps
        lost = frozenset(
            (ownership_ids(before) & required) - covered - set(released)
        )
        if lost:
            carriers = ownership_carriers(draft)
            raise HifiConservationError(
                OWNERSHIP_CONSERVATION_CODE,
                "transformation={0} lost_source_ids={1} carriers={2} "
                "released={3}".format(
                    transformation,
                    sorted(lost)[:12],
                    sorted(carriers)[:12],
                    sorted(released)[:12],
                ),
            )
    entry = stage_entry(
        draft, manifest,
        transformation=transformation,
        released=released,
        lost=lost,
    )
    return draft.model_copy(update={
        "stage_ledger": (*draft.stage_ledger, entry),
    })
