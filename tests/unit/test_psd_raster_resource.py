from __future__ import annotations

import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from PIL import Image

from figma_to_fgui.psd_intake import PsdInspection, PsdLayer
from figma_to_fgui.psd_source_store import PsdSourceStore


def test_psd_store_lazily_generates_and_reuses_layer_png(
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
    inspection = PsdInspection(
        source_name="screen.psd",
        byte_size=len(source_bytes),
        sha256=source_id,
        width=750,
        height=420,
        depth=16,
        color_mode="RGB",
        layer_count=1,
        kind_counts={"shape": 1},
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
                "layers": [asdict(layer)],
            }
        ),
        encoding="utf-8",
    )

    calls = 0

    class RasterLayer:
        def composite(self, **_kwargs):
            return Image.new("RGBA", (100, 60), (12, 34, 56, 200))

    class Document:
        def descendants(self):
            return [RasterLayer()]

    def open_document(_path):
        nonlocal calls
        calls += 1
        return Document()

    monkeypatch.setattr("figma_to_fgui.psd_source_store.PSDImage.open", open_document)
    store = PsdSourceStore(tmp_path / "data")

    first = store.raster_resource(source_id, layer.id)
    second = store.raster_resource(source_id, layer.id)

    assert first == second
    assert first.mime_type == "image/png"
    assert first.size > 0
    resource_path = store.artifact_path(source_id) / "resources" / first.key
    with Image.open(resource_path) as image:
        assert image.mode == "RGBA"
        assert image.size == (100, 60)
        assert image.getpixel((0, 0)) == (12, 34, 56, 200)
    assert calls == 1
