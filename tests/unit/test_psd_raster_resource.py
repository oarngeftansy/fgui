from __future__ import annotations

import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from PIL import Image

from figma_to_fgui.psd_intake import PsdInspection, PsdLayer
from figma_to_fgui.psd_source_store import PsdSourceStore


def test_psd_store_opens_document_once_to_generate_and_reuse_layer_pngs(
    tmp_path: Path, monkeypatch
) -> None:
    source_bytes = b"8BPSstored-source"
    source_id = sha256(source_bytes).hexdigest()
    layer = PsdLayer(
        id=f"psd-layer:{source_id}:7",
        native_id=7,
        parent_id=None,
        document_index=0,
        sibling_index=0,
        name="Card",
        path=("Card",),
        kind="shape",
        bounds=(10, 20, 110, 80),
        visible=True,
        effective_visible=True,
        opacity=255,
        blend_mode="normal",
        clipping=False,
        text=None,
        has_pixel_mask=False,
        has_vector_mask=False,
        has_effects=True,
    )
    second_layer = PsdLayer(
        **{
            **asdict(layer),
            "id": f"psd-layer:{source_id}:8",
            "native_id": 8,
            "document_index": 1,
            "name": "Icon",
            "path": ("Icon",),
            "bounds": (30, 40, 130, 100),
        }
    )
    inspection = PsdInspection(
        source_name="screen.psd",
        byte_size=len(source_bytes),
        sha256=source_id,
        width=750,
        height=420,
        depth=16,
        color_mode="RGB",
        layer_count=2,
        kind_counts={"shape": 2},
        text_layer_count=0,
        smart_object_count=0,
        adjustment_layer_count=0,
        effect_layer_count=1,
        blocking_issues=("shape_styles_require_equivalence_check",),
        warnings=("16_bit_pixels_must_not_be_downconverted",),
    )
    source_root = tmp_path / "data/hifi-sources/psd" / source_id
    source_root.mkdir(parents=True)
    (source_root / "source.psd").write_bytes(source_bytes)
    (source_root / "hifi-ir.json").write_text(
        json.dumps(
            {
                "version": 1,
                "source_id": source_id,
                "inspection": asdict(inspection),
                "layers": [asdict(layer), asdict(second_layer)],
            }
        ),
        encoding="utf-8",
    )

    calls = 0

    class RasterLayer:
        def __init__(self, color):
            self.color = color

        def composite(self, **_kwargs):
            return Image.new("RGBA", (100, 60), self.color)

    class Document:
        def descendants(self):
            return [RasterLayer((12, 34, 56, 200)), RasterLayer((90, 80, 70, 255))]

    def open_document(_path):
        nonlocal calls
        calls += 1
        return Document()

    monkeypatch.setattr("figma_to_fgui.psd_source_store.PSDImage.open", open_document)
    store = PsdSourceStore(tmp_path / "data")

    batch = store.raster_resources(source_id, (layer.id, second_layer.id))
    first = batch[layer.id]
    second = store.raster_resource(source_id, layer.id)

    assert first == second
    assert set(batch) == {layer.id, second_layer.id}
    assert first.mime_type == "image/png"
    assert first.size > 0
    resource_path = store.artifact_path(source_id) / "resources" / first.key
    with Image.open(resource_path) as image:
        assert image.mode == "RGBA"
        assert image.size == (100, 60)
        assert image.getpixel((0, 0)) == (12, 34, 56, 200)
    assert calls == 1

    composite = Image.new("RGB", (750, 420))
    for y in range(420):
        for x in range(750):
            composite.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
    composite.save(source_root / "composite.png")
    viewport_path = store.composite_viewport_path(source_id, 700, 400)
    with Image.open(viewport_path) as viewport:
        assert viewport.size == (700, 400)
        assert viewport.getpixel((0, 0)) == composite.getpixel((25, 10))
        assert viewport.getpixel((699, 399)) == composite.getpixel((724, 409))


def test_psd_store_uses_matching_layer_as_effective_fgui_viewport(
    tmp_path: Path,
) -> None:
    source_bytes = b"8BPSviewport-marker"
    source_id = sha256(source_bytes).hexdigest()
    marker = PsdLayer(
        id=f"psd-layer:{source_id}:7",
        native_id=7,
        parent_id=None,
        document_index=0,
        sibling_index=0,
        name="1920*1080",
        path=("1920*1080",),
        kind="pixel",
        bounds=(-1, 210, 1079, 2130),
        visible=False,
        effective_visible=False,
        opacity=255,
        blend_mode="normal",
        clipping=False,
        text=None,
        has_pixel_mask=False,
        has_vector_mask=False,
        has_effects=False,
    )
    inspection = PsdInspection(
        source_name="screen.psd",
        byte_size=len(source_bytes),
        sha256=source_id,
        width=1080,
        height=2340,
        depth=8,
        color_mode="RGB",
        layer_count=1,
        kind_counts={"pixel": 1},
        text_layer_count=0,
        smart_object_count=0,
        adjustment_layer_count=0,
        effect_layer_count=0,
        blocking_issues=(),
        warnings=(),
    )
    source_root = tmp_path / "data/hifi-sources/psd" / source_id
    source_root.mkdir(parents=True)
    (source_root / "source.psd").write_bytes(source_bytes)
    (source_root / "hifi-ir.json").write_text(
        json.dumps(
            {
                "version": 1,
                "source_id": source_id,
                "inspection": asdict(inspection),
                "layers": [asdict(marker)],
            }
        ),
        encoding="utf-8",
    )

    store = PsdSourceStore(tmp_path / "data")

    assert store.effective_viewport_bounds(source_id, 1080, 1920) == (
        0,
        210,
        1080,
        1920,
    )


def test_psd_store_rasterizes_group_without_baking_editable_text(
    tmp_path: Path, monkeypatch
) -> None:
    source_bytes = b"8BPSgroup-source"
    source_id = sha256(source_bytes).hexdigest()
    group = PsdLayer(
        id=f"psd-layer:{source_id}:7",
        native_id=7,
        parent_id=None,
        document_index=0,
        sibling_index=0,
        name="ChallengeButton",
        path=("ChallengeButton",),
        kind="group",
        bounds=(20, 30, 220, 100),
        visible=True,
        effective_visible=True,
        opacity=255,
        blend_mode="pass_through",
        clipping=False,
        text=None,
        has_pixel_mask=False,
        has_vector_mask=False,
        has_effects=False,
    )
    label = PsdLayer(
        id=f"psd-layer:{source_id}:8",
        native_id=8,
        parent_id=group.id,
        document_index=1,
        sibling_index=0,
        name="Challenge",
        path=("ChallengeButton", "Challenge"),
        kind="type",
        bounds=(50, 40, 100, 70),
        visible=True,
        effective_visible=True,
        opacity=255,
        blend_mode="normal",
        clipping=False,
        text="Challenge",
        has_pixel_mask=False,
        has_vector_mask=False,
        has_effects=True,
    )
    inspection = PsdInspection(
        source_name="screen.psd",
        byte_size=len(source_bytes),
        sha256=source_id,
        width=750,
        height=420,
        depth=8,
        color_mode="RGB",
        layer_count=2,
        kind_counts={"group": 1, "type": 1},
        text_layer_count=1,
        smart_object_count=0,
        adjustment_layer_count=0,
        effect_layer_count=0,
        blocking_issues=(),
        warnings=(),
    )
    source_root = tmp_path / "data/hifi-sources/psd" / source_id
    source_root.mkdir(parents=True)
    (source_root / "source.psd").write_bytes(source_bytes)
    (source_root / "hifi-ir.json").write_text(
        json.dumps(
            {
                "version": 1,
                "source_id": source_id,
                "inspection": asdict(inspection),
                "layers": [asdict(group), asdict(label)],
            }
        ),
        encoding="utf-8",
    )

    class Child:
        def __init__(self, kind: str, visible: bool = True) -> None:
            self.kind = kind

            self._visible = visible

        def is_visible(self) -> bool:
            return self._visible

    class RasterGroup:
        pass

    class Document:
        def descendants(self):
            return [RasterGroup(), Child("type")]

        def composite(self, **kwargs):
            raise AssertionError("group rasterization must use the embedded merged image")

        def topil(self, **_kwargs):
            canvas = Image.new("RGBA", (750, 420), (10, 20, 30, 255))
            canvas.paste((0, 0, 0, 255), (50, 40, 100, 70))
            return canvas

    monkeypatch.setattr(
        "figma_to_fgui.psd_source_store.PSDImage.open", lambda _path: Document()
    )

    resource = PsdSourceStore(tmp_path / "data").raster_resource(source_id, group.id)

    assert resource.size > 0
    with Image.open(
        tmp_path / "data/hifi-sources/psd" / source_id / "resources" / resource.key
    ) as image:
        assert image.size == (200, 70)
        assert image.getpixel((0, 0)) == (10, 20, 30, 255)
        assert image.getpixel((30, 10)) == (10, 20, 30, 255)
        assert image.getpixel((55, 25)) == (10, 20, 30, 255)
