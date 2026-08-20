from __future__ import annotations

from figma_to_fgui.fgui_new_project_models import (
    ManifestComponent,
    ManifestObject,
    ManifestPackage,
    ManifestResource,
    NewProjectConfig,
    NewProjectManifest,
)
from figma_to_fgui.fgui_new_project_review import (
    build_new_project_designer_review,
)
from figma_to_fgui.models import Diagnostic, Severity


def _manifest() -> NewProjectManifest:
    resource_id = "2222bbbb"
    object_ = ManifestObject(
        id="3333cccc",
        sourceNodeRef="plan:image",
        uirNodeRef="uir:image",
        zIndex=0,
        type="image",
        transform={"bounds": {"x": 0, "y": 0, "width": 1, "height": 1}},
        resourceRef=resource_id,
    )
    return NewProjectManifest(
        project=NewProjectConfig(
            projectName="Review",
            packageName="Generated",
            fairyGuiVersion="6.1.4",
            publishTarget="unity",
        ),
        package=ManifestPackage(
            id="1111aaaa",
            sourceDocumentRef="plan:review",
            name="Generated",
            relativePath="assets/Generated",
        ),
        components=(
            ManifestComponent(
                id="4444dddd",
                sourceComponentKind="root",
                sourceComponentRef="root:review",
                name="Review",
                relativePath="components/Review-4444dddd.xml",
                size={"x": 0, "y": 0, "width": 1, "height": 1},
                objects=(object_,),
            ),
        ),
        resources=(
            ManifestResource(
                id=resource_id,
                sourceResourceRef="resource:review",
                name="Review.png",
                relativePath="assets/Review-2222bbbb.png",
                mimeType="image/png",
                contentSha256="0" * 64,
                exportParametersSha256="1" * 64,
                exportFormat="png",
                width=1,
                height=1,
                consumerObjectRefs=(object_.id,),
            ),
        ),
    )


def test_projects_manifest_into_image_component_package_and_checks() -> None:
    manifest = _manifest()
    review = build_new_project_designer_review(
        manifest,
        None,
        (
            Diagnostic(
                code="writer.warning",
                severity=Severity.WARNING,
                message="Review this node.",
                node_id="node-1",
                suggested_action="Review the generated output.",
            ),
        ),
        build_id="a" * 32,
        generation=1,
        selection_preview_urls=("/v1/figma/selections/" + "b" * 32 + "/previews/0",),
    )

    assert review.build_id == "a" * 32
    assert review.generation == 1
    assert review.package_review.components_added >= 1
    assert review.package_review.resource_closure_valid is True
    assert all(item.evidence_kind == "source-image" for item in review.image_reviews)
    assert all(
        item.evidence_kind == "structured-summary" and item.rendered_preview_url is None
        for item in review.component_reviews
    )
    assert review.warning_ids == tuple(check.id for check in review.checks)
    assert review.checks[0].allowed_strategies == ("preserve-editable",)


def test_error_check_blocks_approval_and_rendered_evidence_requires_real_bytes() -> None:
    manifest = _manifest()
    review = build_new_project_designer_review(
        manifest,
        None,
        (
            Diagnostic(
                code="writer.error",
                severity=Severity.ERROR,
                message="Blocked.",
                blocks_binding=True,
            ),
        ),
        build_id="a" * 32,
        generation=1,
        rendered_component_previews={manifest.components[0].id: b"not-an-image"},
    )

    assert review.approvable is False
    assert review.component_reviews[0].evidence_kind == "structured-summary"
    assert review.component_reviews[0].rendered_preview_url is None
