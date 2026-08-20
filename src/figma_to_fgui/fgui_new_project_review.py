"""Strict, byte-free designer review projection for Writer candidates."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from figma_to_fgui.fgui_new_project_models import NewProjectManifest
from figma_to_fgui.fgui_plan_models import FGUIPlanDocument
from figma_to_fgui.image_preview import encode_webp_preview
from figma_to_fgui.models import Diagnostic, FrozenModel, Severity
from figma_to_fgui.service_contracts import NewProjectAdjustmentStrategy


class _StrictReviewModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False, strict=True)


class NewProjectImageReview(_StrictReviewModel):
    resource_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=160)
    evidence_kind: Literal["source-image"]
    source_preview_url: str | None = Field(default=None, pattern=r"^/v1/[A-Za-z0-9_./-]+$")
    generated_asset_url: str = Field(pattern=r"^/v1/[A-Za-z0-9_./-]+$")
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    nine_slice: bool


class NewProjectComponentReview(_StrictReviewModel):
    component_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=160)
    evidence_kind: Literal["rendered", "structured-summary"]
    rendered_preview_url: str | None = Field(default=None, pattern=r"^/v1/[A-Za-z0-9_./-]+$")
    object_count: int = Field(ge=0)
    text_count: int = Field(ge=0)
    resource_refs: int = Field(ge=0)
    component_refs: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_evidence(self) -> NewProjectComponentReview:
        if (self.evidence_kind == "rendered") != (self.rendered_preview_url is not None):
            raise ValueError("rendered evidence requires one real preview URL")
        return self


class NewProjectPackageReview(_StrictReviewModel):
    package_name: str = Field(min_length=1, max_length=128)
    fairy_gui_version: Literal["6.1.4"]
    publish_target: Literal["unity"]
    components_added: int = Field(ge=0)
    resources_added: int = Field(ge=0)
    resource_closure_valid: bool


class DesignerCheck(_StrictReviewModel):
    id: str = Field(pattern=r"^review:[0-9a-f]{16}$")
    severity: Severity
    message: str = Field(min_length=1, max_length=500)
    issue_id: str = Field(pattern=r"^review:[0-9a-f]{16}$")
    uir_node_id: str | None = Field(default=None, min_length=1, max_length=256)
    actionable: bool


class NewProjectDesignerReview(_StrictReviewModel):
    version: Literal[1] = 1
    build_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    generation: int = Field(ge=1)
    image_reviews: tuple[NewProjectImageReview, ...]
    component_reviews: tuple[NewProjectComponentReview, ...]
    package_review: NewProjectPackageReview
    checks: tuple[DesignerCheck, ...]
    warning_ids: tuple[str, ...]
    approvable: bool

    @model_validator(mode="after")
    def validate_check_projection(self) -> NewProjectDesignerReview:
        ids = tuple(check.id for check in self.checks)
        if len(ids) != len(set(ids)):
            raise ValueError("review check IDs must be unique")
        expected_warnings = tuple(
            check.id for check in self.checks if check.severity is Severity.WARNING
        )
        if self.warning_ids != expected_warnings:
            raise ValueError("warning_ids must exactly project warning checks")
        if self.approvable and (
            not self.package_review.resource_closure_valid
            or any(check.severity is Severity.ERROR for check in self.checks)
        ):
            raise ValueError("an invalid review cannot be approvable")
        return self


def _check_id(diagnostic: Diagnostic, index: int) -> str:
    payload = "\0".join((diagnostic.code, diagnostic.node_id or "", str(index))).encode("utf-8")
    return f"review:{hashlib.sha256(payload).hexdigest()[:16]}"


def _resource_closure_valid(manifest: NewProjectManifest) -> bool:
    objects = {item.id: item for component in manifest.components for item in component.objects}
    referenced = {item.resource_ref for item in objects.values() if item.resource_ref is not None}
    resources = {item.id: item for item in manifest.resources}
    if referenced != set(resources):
        return False
    return all(
        set(resource.consumer_object_refs)
        == {item.id for item in objects.values() if item.resource_ref == resource.id}
        for resource in resources.values()
    )


def strategy_allowed_for_check(
    check: DesignerCheck, strategy: NewProjectAdjustmentStrategy
) -> bool:
    """Return the deliberately closed strategy set for one actionable issue."""
    if not check.actionable or check.uir_node_id is None:
        return False
    if "definition" in check.message.lower():
        return strategy in {
            NewProjectAdjustmentStrategy.RASTERIZE_SUBTREE,
            NewProjectAdjustmentStrategy.INCLUDE_CONTAINED_DEFINITION,
        }
    return strategy is NewProjectAdjustmentStrategy.PRESERVE_EDITABLE


def build_new_project_designer_review(
    manifest: NewProjectManifest,
    plan: FGUIPlanDocument | None = None,
    diagnostics: tuple[Diagnostic, ...] = (),
    *,
    build_id: str,
    generation: int,
    selection_preview_urls: tuple[str, ...] = (),
    rendered_component_previews: Mapping[str, bytes] | None = None,
) -> NewProjectDesignerReview:
    """Project immutable candidate facts without inventing rendered evidence."""
    del plan  # The canonical manifest is the review's emitted-output authority.
    rendered_component_previews = rendered_component_previews or {}
    image_reviews = tuple(
        NewProjectImageReview(
            resource_id=resource.id,
            label=resource.name,
            evidence_kind="source-image",
            source_preview_url=(
                selection_preview_urls[index] if index < len(selection_preview_urls) else None
            ),
            generated_asset_url=(
                f"/v1/new-fgui-projects/{build_id}/previews/resources/{resource.id}"
            ),
            width=resource.width or 0,
            height=resource.height or 0,
            nine_slice=resource.nine_slice is not None,
        )
        for index, resource in enumerate(manifest.resources)
    )

    component_reviews: list[NewProjectComponentReview] = []
    for component in manifest.components:
        rendered = rendered_component_previews.get(component.id)
        has_real_preview = type(rendered) is bytes and encode_webp_preview(rendered) is not None
        component_reviews.append(
            NewProjectComponentReview(
                component_id=component.id,
                label=component.name,
                evidence_kind="rendered" if has_real_preview else "structured-summary",
                rendered_preview_url=(
                    f"/v1/new-fgui-projects/{build_id}/previews/components/{component.id}"
                    if has_real_preview
                    else None
                ),
                object_count=len(component.objects),
                text_count=sum(item.text is not None for item in component.objects),
                resource_refs=sum(item.resource_ref is not None for item in component.objects),
                component_refs=sum(item.component_ref is not None for item in component.objects),
            )
        )

    checks = tuple(
        DesignerCheck(
            id=_check_id(diagnostic, index),
            severity=diagnostic.severity,
            message=diagnostic.message,
            issue_id=_check_id(diagnostic, index),
            uir_node_id=diagnostic.node_id,
            actionable=(diagnostic.suggested_action is not None and diagnostic.node_id is not None),
        )
        for index, diagnostic in enumerate(diagnostics)
    )
    closure_valid = _resource_closure_valid(manifest)
    return NewProjectDesignerReview(
        build_id=build_id,
        generation=generation,
        image_reviews=image_reviews,
        component_reviews=tuple(component_reviews),
        package_review=NewProjectPackageReview(
            package_name=manifest.package.name,
            fairy_gui_version=manifest.project.fairy_gui_version,
            publish_target=manifest.project.publish_target,
            components_added=len(manifest.components),
            resources_added=len(manifest.resources),
            resource_closure_valid=closure_valid,
        ),
        checks=checks,
        warning_ids=tuple(check.id for check in checks if check.severity is Severity.WARNING),
        approvable=closure_valid and all(check.severity is not Severity.ERROR for check in checks),
    )
