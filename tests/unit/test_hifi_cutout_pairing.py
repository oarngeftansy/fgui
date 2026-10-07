from __future__ import annotations

"""Designer cutout pairing: the 切图 pool is operator-only evidence.

A cutout enters the mapping exclusively through a human retarget decision.
It is never an automatic candidate, never required by PSD closure, never
stolen by the semantic allocator, and it replaces only the texture while
the legacy element keeps its layout contract verbatim.
"""

import io
import json
import sqlite3
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from psd_tools import PSDImage

from figma_to_fgui.api import create_app
from figma_to_fgui.figma_selection import SelectionManifest, SelectionNode
from figma_to_fgui.hifi_mapping import _psd_coverage
from figma_to_fgui.hifi_replacement_models import (
    FguiBehaviorSummary,
    FguiComponentInventory,
    FguiObjectRef,
    HifiMappingDraft,
    HifiMappingEvidence,
    HifiMappingItem,
    HifiTargetRef,
)
from figma_to_fgui.hifi_replacement_store import HifiReplacementStore
from figma_to_fgui.hifi_replacement_workflow import HifiReplacementWorkflow
from figma_to_fgui.hifi_semantic_reskin import normalize_psd_semantic_reskin
from figma_to_fgui.models import Bounds
from figma_to_fgui.project_store import ProjectStore
from figma_to_fgui.psd_source_store import (
    PsdSourceStore,
    PsdSourceStoreError,
    cutout_families,
)
from figma_to_fgui.selection_store import SelectionStore

HEADERS = {"x-figma-plugin-token": "test-token"}
_SHA = "0" * 64
_ROOT_ID = "psd-root:" + "a" * 64


def _evidence() -> HifiMappingEvidence:
    return HifiMappingEvidence(
        version=1, name_score=0.0, position_score=0.0, size_score=0.0,
        type_score=0.0, parent_score=0.0, order_score=0.0,
    )


def _item(
    item_id: str,
    *,
    old_object_id: str | None = None,
    old_object_type: str | None = "image",
    node_id: str | None = None,
    status: str = "fgui_only",
    action: str | None = None,
    old_bounds: tuple[float, float, float, float] | None = None,
    figma_bounds: tuple[float, float, float, float] | None = None,
) -> HifiMappingItem:
    return HifiMappingItem(
        version=1,
        item_id=item_id,
        old_object_id=old_object_id,
        old_object_type=old_object_type,
        figma_node_id=node_id,
        status=status,
        score=0.5,
        evidence=_evidence(),
        action=action,
        old_bounds=old_bounds,
        figma_bounds=figma_bounds,
    )


def _draft(*items: HifiMappingItem, revision: int = 1) -> HifiMappingDraft:
    return HifiMappingDraft(
        version=1,
        mapping_revision=revision,
        items=items,
        unresolved_count=sum(1 for item in items if item.action is None),
    )


def _cutout_node(name: str = "coin.png") -> SelectionNode:
    return SelectionNode(
        id=f"cutout:{name}",
        name="coin",
        type="IMAGE",
        bounds=Bounds(x=0.0, y=0.0, width=44.0, height=44.0),
        visible=True,
        properties={"hifiCutoutPool": True},
    )


def _png_bytes(size: tuple[int, int], fill: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", size, (*fill, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _store_with_pool(tmp_path: Path) -> tuple[PsdSourceStore, str]:
    data = tmp_path / "data"
    store = PsdSourceStore(data)
    psd = tmp_path / "screen.psd"
    PSDImage.new(mode="RGB", size=(100, 80), depth=8).save(psd)
    source = store.admit(psd, source_name="screen.psd")
    root = tmp_path / "design"
    (root / "切图").mkdir(parents=True)
    art = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
    draw = ImageDraw.Draw(art)
    draw.ellipse((2, 2, 42, 42), fill=(212, 175, 55, 255))
    art.save(root / "切图" / "coin.png")
    store.link_design_assets(source.source_id, root)
    return store, source.source_id


def test_cutout_pool_splits_into_psd_families() -> None:
    names = [
        "P-BVP塔-失败的蓝色底-放大100%.png",
        "P-BVP塔-无信息文档图标.png",
        "PVP塔_按钮_套装属性.png",
        "PVP塔_按钮_箭头.png",
        "PVP塔_防御背景底黄.png",
        "PVP塔_防御背景绿.png",
        "PVP爬塔_icon_角色失败的显示.png",
        "PVP爬塔_临时_icon1.png",
        "PVP爬塔_主页_商店icon.png",
        "PVP爬塔_主页_排名icon.png",
        "PVP爬塔_主页_记录icon.png",
        "P_PVP爬塔_主页背景.png",
        "P_PVP爬塔_战斗_名字血条底板.png",
        "P_PVP爬塔_爬塔背景.png",
        "通用_按钮_跳过.png",
        "通用_标题图标_PVP爬塔.png",
        "爬塔币.png",
    ]
    records = {
        record["name"]: record
        for record in cutout_families("P_PVP爬塔_主页.psd", names)
    }
    assert len(records) == len(names)
    assert records["P_PVP爬塔_主页背景.png"]["relevance"] == "this_psd"
    assert records["PVP爬塔_主页_商店icon.png"]["relevance"] == "this_psd"
    assert records["PVP爬塔_临时_icon1.png"]["relevance"] == "other"
    assert records["P_PVP爬塔_战斗_名字血条底板.png"]["relevance"] == "other"
    assert records["P-BVP塔-无信息文档图标.png"]["relevance"] == "other"
    assert records["通用_按钮_跳过.png"]["relevance"] == "shared"
    families = {record["family"] for record in records.values()}
    assert families == {
        "P-BVP塔", "PVP塔", "PVP爬塔", "P_PVP爬塔", "爬塔币", "通用",
    }
    assert records["PVP塔_防御背景绿.png"]["family"] == "PVP塔"
    assert records["P_PVP爬塔_爬塔背景.png"]["family"] == "P_PVP爬塔"

    single = cutout_families("screen.psd", ["coin.png"])
    assert single == [
        {"name": "coin.png", "family": "coin", "relevance": "other"}
    ]
    assert cutout_families("screen.psd", []) == []


def test_cutout_resource_is_content_addressed_and_idempotent(tmp_path) -> None:
    store, source_id = _store_with_pool(tmp_path)

    resource = store.cutout_resource(source_id, "coin.png")
    assert resource.key.startswith("psd-cutout-") and len(resource.key) == 43
    assert resource.bounds == (0, 0, 44, 44)
    destination = store.artifact_path(source_id) / "resources" / resource.key
    assert destination.is_file()
    with Image.open(destination) as image:
        assert image.size == (44, 44)

    again = store.cutout_resource(source_id, "coin.png")
    assert again.key == resource.key
    assert again.size == destination.stat().st_size

    art = Image.new("RGBA", (44, 44), (10, 200, 90, 255))
    art.save(tmp_path / "design" / "切图" / "coin.png")
    store._cutout_cache.pop(source_id, None)
    store.link_design_assets(source_id, tmp_path / "design")
    updated = store.cutout_resource(source_id, "coin.png")
    assert updated.key != resource.key

    with pytest.raises(PsdSourceStoreError) as info:
        store.cutout_resource(source_id, "missing.png")
    assert info.value.code == "psd_cutout_unknown"


def test_new_sources_auto_adopt_the_remembered_design_root(tmp_path) -> None:
    import shutil as _shutil

    store, _linked = _store_with_pool(tmp_path)
    psd = tmp_path / "screen2.psd"
    PSDImage.new(mode="RGB", size=(120, 90), depth=8).save(psd)
    second = store.admit(psd, source_name="screen2.psd")
    manifest = store.design_assets(second.source_id)
    assert manifest is not None
    assert "coin.png" in manifest.get("cutouts", [])
    resource = store.cutout_resource(second.source_id, "coin.png")
    assert resource.key.startswith("psd-cutout-")

    _shutil.rmtree(tmp_path / "design")
    psd3 = tmp_path / "screen3.psd"
    PSDImage.new(mode="RGB", size=(130, 90), depth=8).save(psd3)
    third = store.admit(psd3, source_name="screen3.psd")
    assert store.design_assets(third.source_id) is None


def test_composite_crop_serves_native_resolution_evidence(tmp_path) -> None:
    store, source_id = _store_with_pool(tmp_path)
    path = store.composite_crop_path(source_id, (10, 10, 50, 40))
    with Image.open(path) as image:
        assert image.size == (40, 30)
    assert store.composite_crop_path(source_id, (10, 10, 50, 40)) == path
    with pytest.raises(PsdSourceStoreError) as info:
        store.composite_crop_path(source_id, (0, 0, 200, 40))
    assert info.value.code == "psd_viewport_dimensions_invalid"


def test_legacy_design_manifest_gains_cutout_groups_on_read(tmp_path) -> None:
    store, source_id = _store_with_pool(tmp_path)
    fingerprint_before = store._design_assets_fingerprint(source_id)
    path = store.design_assets_path(source_id)
    legacy = json.loads(path.read_text(encoding="utf-8"))
    legacy.pop("cutout_groups", None)
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    manifest = store.design_assets(source_id)
    assert manifest is not None
    assert manifest["cutout_groups"] == [
        {"family": "coin", "relevance": "other", "count": 1}
    ]
    assert store._design_assets_fingerprint(source_id) == fingerprint_before


def test_psd_closure_never_requires_cutout_pool_nodes() -> None:
    layer = SelectionNode(
        id="psd-layer:1", name="l", type="IMAGE",
        bounds=Bounds(x=0.0, y=0.0, width=50.0, height=50.0), visible=True,
    )
    root = SelectionNode(
        id=_ROOT_ID, name="PSD", type="FRAME",
        bounds=Bounds(x=0.0, y=0.0, width=100.0, height=100.0),
        children=(layer, _cutout_node()),
    )
    manifest = SelectionManifest(
        version=1, display_name="PSD", top_level_nodes=(root,),
    )
    paired = _draft(
        _item("old:1", old_object_id="1", node_id="psd-layer:1",
              status="matched", action="accept"),
        _item("old:2", old_object_id="2", node_id="cutout:coin.png",
              status="fgui_only", action="retarget"),
    )
    required, unexplained = _psd_coverage(paired, manifest)
    assert required == {"psd-layer:1"}
    assert unexplained == set()

    unpaired = _draft(
        _item("old:1", old_object_id="1", node_id="psd-layer:1",
              status="matched", action="accept"),
    )
    required, unexplained = _psd_coverage(unpaired, manifest)
    assert "cutout:coin.png" not in required
    assert unexplained == set()


def _inventory(*objects: FguiObjectRef) -> FguiComponentInventory:
    return FguiComponentInventory(
        version=1,
        target=HifiTargetRef(
            project_id="project", project_fingerprint=_SHA, package_id="pkg",
            package_name="Package", directory="/", component_id="root",
            component_name="Root", component_relative_path="assets/Package/Root.xml",
        ),
        width=1080.0,
        height=1920.0,
        objects=objects,
        behavior=FguiBehaviorSummary(
            version=1, protected_sha256=_SHA, gear_count=0,
            relation_count=0, action_count=0,
        ),
        parse_complete=True,
        expanded_instances=True,
    )


def _old(object_id: str, object_type: str, *, parent_id: str | None = None) -> FguiObjectRef:
    return FguiObjectRef(
        object_id=object_id, name=object_id, object_type=object_type,
        parent_id=parent_id, child_index=0, x=100.0, y=100.0,
        width=300.0, height=80.0, protected_sha256=_SHA,
    )


def test_semantic_allocator_keeps_a_cutout_pin_verbatim() -> None:
    skin = SelectionNode(
        id="skin-1", name="skin", type="IMAGE",
        bounds=Bounds(x=100.0, y=100.0, width=60.0, height=60.0),
        visible=True, properties={"psdKind": "pixel"},
    )
    group = SelectionNode(
        id="grp-1", name="Card", type="GROUP",
        bounds=Bounds(x=100.0, y=100.0, width=60.0, height=60.0),
        children=(skin,),
    )
    root = SelectionNode(
        id=_ROOT_ID, name="PSD", type="FRAME",
        bounds=Bounds(x=0.0, y=0.0, width=1080.0, height=1920.0),
        children=(group, _cutout_node()),
    )
    manifest = SelectionManifest(version=1, display_name="PSD", top_level_nodes=(root,))
    inventory = _inventory(
        _old("card", "component"),
        _old("coin", "image", parent_id="card"),
    )
    draft = _draft(
        _item("old:card", old_object_id="card", old_object_type="component",
              node_id="grp-1", status="matched", action="accept"),
        _item("old:coin", old_object_id="coin", node_id="cutout:coin.png",
              status="fgui_only", action="retarget"),
    )
    result = normalize_psd_semantic_reskin(inventory, manifest, draft, renormalize=True)
    pinned = next(
        item for item in result.items if item.old_object_id == "coin"
    )
    assert pinned.action == "retarget"
    assert pinned.figma_node_id == "cutout:coin.png"


def test_variant_sources_resolve_cutout_bases(tmp_path) -> None:
    store, source_id = _store_with_pool(tmp_path)
    data = tmp_path / "data"
    workflow = HifiReplacementWorkflow(
        data, ProjectStore(data), SelectionStore(data), store,
        HifiReplacementStore(data),
    )
    mapping = _draft(
        _item("old:coin", old_object_id="coin", node_id="cutout:coin.png",
              status="fgui_only", action="retarget"),
    )
    sources = workflow._variant_sources(mapping, source_id)
    assert sources is not None
    resource = store.cutout_resource(source_id, "coin.png")
    assert sources["coin"] == store.artifact_path(source_id) / "resources" / resource.key


def test_editor_compare_mask_exempts_cutout_regions() -> None:
    from figma_to_fgui.fairygui_editor_verify import build_editor_compare_mask

    class Layer:
        def __init__(self, layer_id: str) -> None:
            self.id = layer_id
            self.bounds = (0, 0, 100, 100)

    mapping = _draft(
        _item("old:pinned", old_object_id="pinned",
              node_id="cutout:coin.png", status="fgui_only", action="retarget",
              old_bounds=(0.2, 0.2, 0.3, 0.3)),
    )
    mapping = mapping.model_copy(update={"old_canvas_size": (100, 100)})
    mask = build_editor_compare_mask(mapping, [Layer("psd-layer:1")], (0, 0), 100, 100)
    assert mask.getpixel((35, 35)) == 0
    assert mask.getpixel((35, 35)) != 255


PANEL = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<component size="750,420" opaque="false"><displayList>'
    '<image id="bg" name="BoardBg" src="bgimg001" fileName="bg.png" xy="0,0" size="750,420"/>'
    '<image id="coin" name="Coin" src="coinimg1" fileName="coin.png" xy="600,20" size="40,40"/>'
    "</displayList></component>"
)
PACKAGE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<packageDescription id="myvilla01" name="MyVillage"><resources>'
    '<image id="bgimg001" name="bg.png" path="/Img/Lowfi/"/>'
    '<image id="coinimg1" name="coin.png" path="/Img/Lowfi/"/>'
    '<component id="panel0011" name="Panel_Coin.xml" path="/Panel/" exported="true"/>'
    "</resources><publish/></packageDescription>"
)


def _upload_coin_project(client: TestClient, tmp_path: Path) -> dict:
    archive = tmp_path / "CoinVillage.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        output.writestr(
            "OldVillage.fairy",
            '<?xml version="1.0" encoding="utf-8"?>'
            '<projectDescription id="4bb86d1c7302417c85fcb27afad16e44" '
            'type="Unity" version="5.0"/>',
        )
        output.writestr("assets/MyVillage/package.xml", PACKAGE)
        output.writestr("assets/MyVillage/Panel/Panel_Coin.xml", PANEL)
        output.writestr(
            "assets/MyVillage/Img/Lowfi/bg.png", _png_bytes((750, 420), (240, 240, 240))
        )
        output.writestr(
            "assets/MyVillage/Img/Lowfi/coin.png", _png_bytes((40, 40), (198, 90, 42))
        )
    with archive.open("rb") as content:
        response = client.post(
            "/v1/projects/uploads",
            files={"project": (archive.name, content, "application/zip")},
            headers=HEADERS,
        )
    assert response.status_code == 201, response.text
    project_id = response.json()["project_id"]
    tree = client.get(
        f"/v1/projects/{project_id}/hifi-targets", headers=HEADERS
    ).json()
    package = next(item for item in tree["packages"] if item["name"] == "MyVillage")
    directory = next(item for item in package["directories"] if item["path"] == "Panel")
    component = next(
        item for item in directory["components"] if item["resource_id"] == "panel0011"
    )
    return {
        "version": 1,
        "project_id": project_id,
        "project_fingerprint": tree["project_fingerprint"],
        "package_id": package["package_id"],
        "package_name": package["name"],
        "directory": directory["path"],
        "component_id": component["resource_id"],
        "component_name": component["name"],
        "component_relative_path": component["relative_path"],
    }


def test_cutout_pairing_end_to_end(tmp_path) -> None:
    client = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            fixtures_root=Path("tests/fixtures"),
            rules_path=Path("rules/default/classification.yaml"),
            plugin_access_token=b"test-token",
        )
    )
    target = _upload_coin_project(client, tmp_path)

    document = PSDImage.new(mode="RGB", size=(750, 420), depth=8)
    document.create_pixel_layer(
        Image.new("RGBA", (750, 420), (240, 240, 240, 255)),
        name="BoardBg", left=0, top=0,
    )
    psd = tmp_path / "screen.psd"
    document.save(psd)
    with psd.open("rb") as content:
        uploaded = client.post(
            "/v1/hifi-sources/psd",
            files={"psd": (psd.name, content, "image/vnd.adobe.photoshop")},
            headers=HEADERS,
        )
    assert uploaded.status_code == 201, uploaded.text
    source_id = uploaded.json()["source_id"]

    design = tmp_path / "design"
    (design / "切图").mkdir(parents=True)
    coin_art = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
    ImageDraw.Draw(coin_art).ellipse((2, 2, 42, 42), fill=(212, 175, 55, 255))
    coin_art.save(design / "切图" / "PVP金币底.png")
    linked = client.post(
        f"/v1/hifi-sources/psd/{source_id}/design-assets",
        json={"root": str(design)},
        headers=HEADERS,
    )
    assert linked.status_code == 200, linked.text
    assert "PVP金币底.png" in linked.json()["manifest"]["cutouts"]
    assert linked.json()["manifest"]["cutout_groups"] == [
        {"family": "PVP金币底", "relevance": "other", "count": 1}
    ]

    pool = client.get(
        f"/v1/hifi-sources/psd/{source_id}/cutouts", headers=HEADERS
    )
    assert pool.status_code == 200, pool.text
    entries = pool.json()["cutouts"]
    assert len(entries) == 1
    assert entries[0]["name"] == "PVP金币底.png"
    assert entries[0]["thumbnail"].startswith("data:image/png;base64,")
    assert entries[0]["family"] == "PVP金币底"
    assert entries[0]["relevance"] == "other"


    created = client.post(
        "/v1/hifi-replacements/from-psd",
        json={
            "version": 1,
            "project_id": target["project_id"],
            "psd_source_id": source_id,
            "target": target,
            "idempotency_key": "cutout-pairing",
        },
        headers=HEADERS,
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]

    def mapping_view() -> dict:
        response = client.get(
            f"/v1/hifi-replacements/{session_id}/mapping", headers=HEADERS
        )
        assert response.status_code == 200, response.text
        return response.json()

    mapping = mapping_view()
    items = mapping["items"]
    assert not [
        item for item in items
        if (item.get("figma_node_id") or "").startswith("cutout:")
    ]
    assert not [item for item in items if item["status"] == "hifi_added"]
    coin_item = next(item for item in items if item["old_object_id"] == "coin")
    bg_item = next(item for item in items if item["old_object_id"] == "bg")
    assert coin_item["status"] == "fgui_only"
    assert "cutout:" not in (coin_item.get("candidates") or [])

    if bg_item["action"] is None:
        decided = client.post(
            f"/v1/hifi-replacements/{session_id}/mapping-decisions",
            json={
                "version": 1,
                "mapping_revision": mapping["mapping_revision"],
                "item_id": bg_item["item_id"],
                "action": "accept",
            },
            headers=HEADERS,
        )
        assert decided.status_code == 200, decided.text
        mapping = mapping_view()

    pinned = client.post(
        f"/v1/hifi-replacements/{session_id}/mapping-decisions",
        json={
            "version": 1,
            "mapping_revision": mapping["mapping_revision"],
            "item_id": coin_item["item_id"],
            "action": "retarget",
            "figma_node_id": "cutout:PVP金币底.png",
        },
        headers=HEADERS,
    )
    assert pinned.status_code == 200, pinned.text

    mapping = mapping_view()
    saved = next(
        item for item in mapping["items"] if item["old_object_id"] == "coin"
    )
    assert saved["action"] == "retarget"
    assert saved["figma_node_id"] == "cutout:PVP金币底.png"
    pending = [item for item in mapping["items"] if item["action"] is None]
    assert not pending, pending

    built = client.post(
        f"/v1/hifi-replacements/{session_id}/build",
        json={"version": 1, "mapping_revision": mapping["mapping_revision"]},
        headers=HEADERS,
    )
    assert built.status_code == 200, built.text

    conn = sqlite3.connect(tmp_path / "data" / "hifi-replacements.db")
    row = conn.execute(
        "SELECT artifact_path FROM hifi_replacements WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    assert row is not None and row[0]
    artifact = Path(row[0])
    with ZipFile(artifact) as bundle:
        names = bundle.namelist()
        from lxml import etree

        panel_name = next(
            name for name in names if name.endswith("Panel_Coin.xml")
        )
        panel = etree.fromstring(bundle.read(panel_name))
        coin = panel.xpath("./displayList/image[@id='coin']")[0]
        assert coin.get("xy") == "600,20"
        assert coin.get("size") == "40,40"
        assert coin.get("src") not in {None, "coinimg1"}
        assert coin.get("pkg") is None
        textures = [
            name for name in names
            if "/Img/HIFI/" in name and name.endswith(".png")
        ]
        matched = []
        for name in textures:
            with Image.open(io.BytesIO(bundle.read(name))) as texture:
                if texture.size == (44, 44):
                    matched.append(name)
                    pixels = texture.convert("RGBA").getpixel((22, 22))
                    assert pixels[:3] == (212, 175, 55)
        assert matched, textures
