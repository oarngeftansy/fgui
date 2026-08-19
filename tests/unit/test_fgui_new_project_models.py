import json

import pytest
from pydantic import ValidationError

from figma_to_fgui.fgui_new_project_models import (
    AssetPayload,
    AssetPayloadSet,
    ManifestComponent,
    ManifestObject,
    ManifestPackage,
    ManifestResource,
    NewProjectConfig,
    NewProjectManifest,
)


def payload(resource_id: str) -> AssetPayload:
    return AssetPayload(
        resourceId=resource_id,
        declaredMimeType="image/png",
        content=b"\x89PNG\r\n\x1a\n",
    )


@pytest.mark.parametrize("version,target", [("6.1.5", "unity"), ("6.1.4", "unreal")])
def test_config_rejects_unsupported_dialect(version: str, target: str) -> None:
    with pytest.raises(ValidationError):
        NewProjectConfig(
            projectName="Demo",
            packageName="Generated",
            fairyGuiVersion=version,
            publishTarget=target,
        )


def test_asset_payload_set_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="duplicate resource id"):
        AssetPayloadSet.from_items((payload("image:a"), payload("image:a")))


def test_config_is_strict_immutable_and_supports_python_names() -> None:
    config = NewProjectConfig(
        project_name="Demo",
        package_name="Generated",
        fairy_gui_version="6.1.4",
        publish_target="unity",
    )

    assert config.model_dump(by_alias=True) == {
        "projectName": "Demo",
        "packageName": "Generated",
        "fairyGuiVersion": "6.1.4",
        "publishTarget": "unity",
        "namingPolicyVersion": 1,
    }
    with pytest.raises(ValidationError):
        NewProjectConfig.model_validate({**config.model_dump(by_alias=True), "packageId": "old"})
    with pytest.raises(ValidationError):
        config.project_name = "Changed"


def test_payload_set_is_canonical_and_its_lookup_is_immutable() -> None:
    payloads = AssetPayloadSet.from_items((payload("image:b"), payload("image:a")))

    assert tuple(item.resource_id for item in payloads.items) == ("image:a", "image:b")
    assert payloads.payload_for("image:a") == payload("image:a")
    with pytest.raises(KeyError):
        payloads.payload_for("image:missing")
    with pytest.raises(TypeError):
        payloads.by_resource_id["image:c"] = payload("image:c")


def test_manifest_is_strict_immutable_and_keeps_bytes_out_of_canonical_json() -> None:
    config = NewProjectConfig(
        projectName="Demo",
        packageName="Generated",
        fairyGuiVersion="6.1.4",
        publishTarget="unity",
    )
    object_ = ManifestObject(
        id="object:root",
        sourceNodeRef="plan-node:root",
        zIndex=0,
        type="container",
        transform={"bounds": {"x": 0, "y": 0, "width": 100, "height": 50}},
    )
    component = ManifestComponent(
        id="component:root",
        sourceComponentRef="plan-root:root",
        name="Root",
        relativePath="components/Root.xml",
        size={"x": 0, "y": 0, "width": 100, "height": 50},
        objects=(object_,),
    )
    resource = ManifestResource(
        id="resource:image",
        sourceResourceRef="image:a",
        name="Hero",
        relativePath="resources/Hero.png",
        mimeType="image/png",
        contentSha256="a" * 64,
        exportFormat="png",
        consumerObjectRefs=("object:root",),
    )
    manifest = NewProjectManifest(
        project=config,
        package=ManifestPackage(
            id="package:demo",
            name="Generated",
            relativePath="assets/Generated",
        ),
        components=(component,),
        resources=(resource,),
    )

    dumped = manifest.model_dump(mode="json", by_alias=True)
    encoded = json.dumps(dumped)
    assert "content" not in dumped["resources"][0]
    assert "PNG" not in encoded
    assert manifest.components[0].objects[0].source_node_ref == "plan-node:root"
    with pytest.raises(ValidationError):
        NewProjectManifest.model_validate({**manifest.model_dump(by_alias=True), "componentId": "old"})
    with pytest.raises(ValidationError):
        manifest.package = manifest.package


@pytest.mark.parametrize("reference", ("", " "))
def test_manifest_reference_fields_reject_blank_values(reference: str) -> None:
    with pytest.raises(ValidationError):
        ManifestResource(
            id="resource:image",
            sourceResourceRef=reference,
            name="Hero",
            relativePath="resources/Hero.png",
            mimeType="image/png",
            contentSha256="a" * 64,
            exportFormat="png",
            consumerObjectRefs=("object:root",),
        )


def test_public_provenance_is_immutable_and_rejects_private_or_raw_data() -> None:
    component = ManifestComponent(
        id="component:root",
        sourceComponentRef="plan-root:root",
        name="Root",
        relativePath="components/Root.xml",
        size={"x": 0, "y": 0, "width": 1, "height": 1},
        publicProvenance={"candidateKey": "common_button", "facts": {"version": 1}},
    )

    with pytest.raises(TypeError):
        component.public_provenance["candidateKey"] = "changed"
    with pytest.raises(TypeError):
        component.public_provenance["facts"]["version"] = 2
    with pytest.raises(ValidationError):
        ManifestComponent(
            id="component:root",
            sourceComponentRef="plan-root:root",
            name="Root",
            relativePath="components/Root.xml",
            size={"x": 0, "y": 0, "width": 1, "height": 1},
            publicProvenance={"rawBytes": b"private"},
        )
    with pytest.raises(ValidationError):
        ManifestComponent(
            id="component:root",
            sourceComponentRef="plan-root:root",
            name="Root",
            relativePath="components/Root.xml",
            size={"x": 0, "y": 0, "width": 1, "height": 1},
            publicProvenance={"packageId": "existing-project"},
        )
