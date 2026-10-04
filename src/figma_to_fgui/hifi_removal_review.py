"""Policy 28 §8-§11: Legacy Removal Review.

A REMOVE_CANDIDATE is never deleted silently. Candidates are grouped by
semantic root and page region, ordered by runtime risk, and at most five
groups are presented for user confirmation (§10). Overflow groups of pure
low-risk visuals auto-adopt their recommendation and stay fully recorded in
the report; objects bound to program logic, controllers, gears, transitions
or runtime parameters are never auto-removed.
"""
from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field

from figma_to_fgui.hifi_replacement_models import (
    FguiComponentInventory,
    FguiObjectRef,
    HifiMappingDraft,
)
from figma_to_fgui.service_contracts import StrictVersionedModel

RemovalDecision = Literal["remove", "preserve"]

MAX_USER_FACING_GROUPS = 5

_TIER_RUNTIME = 1
_TIER_CONTROLLER = 2
_TIER_COMPONENT = 3
_TIER_VISIBLE = 4
_TIER_PLAIN = 5


class HifiRemovalObject(StrictVersionedModel):
    item_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    object_id: str = Field(min_length=1, max_length=128)
    name: str = Field(max_length=256)
    object_type: str = Field(max_length=32)
    risk_tier: int = Field(ge=1, le=5)
    reason: str = Field(min_length=1, max_length=500)
    controller_refs: tuple[str, ...] = ()
    transition_refs: tuple[str, ...] = ()
    relation_refs: tuple[str, ...] = ()
    referenced_by: tuple[str, ...] = ()
    runtime_bound: bool = False


class HifiRemovalGroup(StrictVersionedModel):
    group_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    semantic_root: str = Field(min_length=1, max_length=256)
    region: str = Field(default="", max_length=256)
    risk_tier: int = Field(ge=1, le=5)
    recommendation: RemovalDecision
    auto_resolved: bool = False
    objects: tuple[HifiRemovalObject, ...]


class HifiRemovalReview(StrictVersionedModel):
    pending: bool = False
    total_candidate_count: int = Field(default=0, ge=0)
    groups: tuple[HifiRemovalGroup, ...] = ()
    auto_resolved_groups: tuple[HifiRemovalGroup, ...] = ()


class HifiRemovalGroupDecision(StrictVersionedModel):
    group_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    decision: RemovalDecision


class HifiRemovalDecisionRequest(StrictVersionedModel):
    mapping_revision: int = Field(ge=1)
    decisions: tuple[HifiRemovalGroupDecision, ...]


def _referenced_by_map(inventory: FguiComponentInventory) -> dict[str, tuple[str, ...]]:
    references: dict[str, list[str]] = {}
    for obj in inventory.objects:
        for target in obj.relation_refs:
            if target:
                references.setdefault(target, []).append(obj.object_id)
    return {key: tuple(dict.fromkeys(value)) for key, value in references.items()}


def _runtime_bound(obj: FguiObjectRef, referenced_by: tuple[str, ...]) -> bool:
    # §10 tier 1 is real runtime logic, not mere layout grouping. A plain
    # group_member carries behavior_protected, but deleting it only shrinks an
    # advanced group's bounds; it stays an ordinary visual. The genuine tier-1
    # signals are transition keyframes targeting the object, relations it owns
    # or that other objects pin to it, and exported instance parameters.
    # Gear/controller-driven visibility is tier 2 via controller_refs.
    return bool(
        obj.instance_parameters
        or obj.transition_refs
        or obj.relation_refs
        or referenced_by
    )


def _object_risk(obj: FguiObjectRef, referenced_by: tuple[str, ...]) -> int:
    # §10 ordering: runtime logic first, then controller/gear bindings,
    # independent components, visible visuals, plain legacy visuals.
    if _runtime_bound(obj, referenced_by):
        return _TIER_RUNTIME
    if obj.controller_refs:
        return _TIER_CONTROLLER
    if obj.object_type == "component":
        return _TIER_COMPONENT
    if obj.default_visible:
        return _TIER_VISIBLE
    return _TIER_PLAIN


def _reason(obj: FguiObjectRef, referenced_by: tuple[str, ...]) -> str:
    parts = ["PSD 目标态未找到对应内容，疑似被 UX 淘汰的旧视觉（§8 REMOVE_CANDIDATE）"]
    if referenced_by:
        parts.append("被关系引用：" + ", ".join(referenced_by[:4]))
    if obj.transition_refs:
        parts.append("被动画引用：" + ", ".join(obj.transition_refs[:4]))
    if obj.controller_refs:
        parts.append("控制器绑定：" + ", ".join(obj.controller_refs[:4]))
    return "；".join(parts)


def build_removal_review(
    mapping: HifiMappingDraft,
    inventory: FguiComponentInventory,
) -> HifiRemovalReview:
    """Group every undecided REMOVE_CANDIDATE into ≤ 5 user-facing groups."""
    candidates = [
        item for item in mapping.items
        if item.legacy_state == "REMOVE_CANDIDATE" and item.action is None
    ]
    if not candidates:
        return HifiRemovalReview(version=1)
    objects_by_id = {obj.object_id: obj for obj in inventory.objects}
    referenced = _referenced_by_map(inventory)
    grouped: dict[tuple[str, str], list[HifiRemovalObject]] = {}
    for item in candidates:
        obj = objects_by_id.get(item.old_object_id or "")
        if obj is None:
            continue
        refs = referenced.get(obj.object_id, ())
        semantic_root = (
            obj.component_relative_path
            or inventory.target.component_relative_path
        )
        key = (semantic_root, obj.parent_id or "")
        grouped.setdefault(key, []).append(HifiRemovalObject(
            version=1,
            item_id=item.item_id,
            object_id=obj.object_id,
            name=obj.name,
            object_type=obj.object_type,
            risk_tier=_object_risk(obj, refs),
            reason=_reason(obj, refs),
            controller_refs=obj.controller_refs,
            transition_refs=obj.transition_refs,
            relation_refs=obj.relation_refs,
            referenced_by=refs,
            runtime_bound=_runtime_bound(obj, refs),
        ))
    groups: list[HifiRemovalGroup] = []
    for (semantic_root, region), members in sorted(grouped.items()):
        tier = min(member.risk_tier for member in members)
        group_id = "grp-" + hashlib.sha256(
            f"{semantic_root}\x00{region}".encode("utf-8")
        ).hexdigest()[:10]
        groups.append(HifiRemovalGroup(
            version=1,
            group_id=group_id,
            semantic_root=semantic_root,
            region=region,
            risk_tier=tier,
            # Runtime-bound groups are never recommended for silent removal;
            # preserving keeps the object addressable while §11 stops its
            # target-state visual contribution.
            recommendation="preserve" if tier <= _TIER_COMPONENT else "remove",
            objects=tuple(sorted(members, key=lambda m: m.object_id)),
        ))
    groups.sort(key=lambda group: (group.risk_tier, group.semantic_root, group.group_id))
    overflow = [
        group.model_copy(update={"auto_resolved": True})
        for group in groups[MAX_USER_FACING_GROUPS:]
    ]
    return HifiRemovalReview(
        version=1,
        pending=True,
        total_candidate_count=len(candidates),
        groups=tuple(groups[:MAX_USER_FACING_GROUPS]),
        auto_resolved_groups=tuple(overflow),
    )
