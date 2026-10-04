from pathlib import Path

from PIL import Image

from figma_to_fgui.psd_intake import PsdLayer
from figma_to_fgui.psd_lossless_evidence import (
    BundleRasterProbe,
    probe_lossless_evidence,
)


def _layer(layer_id, name, kind, bounds, **kw):
    return PsdLayer(
        id=layer_id,
        native_id=1,
        parent_id="g",
        document_index=1,
        sibling_index=1,
        name=name,
        path=("g", name),
        kind=kind,
        bounds=bounds,
        visible=True,
        effective_visible=True,
        opacity=255,
        blend_mode="normal",
        clipping=False,
        text=None,
        has_pixel_mask=False,
        has_vector_mask=False,
        has_effects=kw.get("effects", False),
    )


def _export(tmp: Path, layer_id: str, size, color) -> Path:
    path = tmp / f"{layer_id}.png"
    image = Image.new("RGBA", size, (*color, 255))
    image.save(path)
    return path


def test_sole_contributor_layers_are_pixel_proven(tmp_path) -> None:
    a = _export(tmp_path, "a", (10, 10), (200, 30, 30))
    b = _export(tmp_path, "b", (10, 10), (30, 30, 200))
    raster = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    raster.paste(Image.open(a), (0, 0))
    raster.paste(Image.open(b), (10, 10))
    layers = (
        _layer("a", "red", "pixel", (0, 0, 10, 10)),
        _layer("b", "blue", "pixel", (10, 10, 20, 20)),
    )
    evidence = probe_lossless_evidence(
        layers=layers,
        bundles=[BundleRasterProbe((0, 0, 20, 20), raster, ("a", "b"))],
        document_size=(20, 20),
        raster_resource=lambda lid: tmp_path / f"{lid}.png",
    )
    assert all(record.proven for record in evidence.records)
    assert evidence.cleared_codes(
        ("pixel_layers_require_equivalence_check",)
    ) == ("pixel_layers_require_equivalence_check",)


def test_overlap_and_delta_stay_residual(tmp_path) -> None:
    a = _export(tmp_path, "a", (10, 10), (60, 190, 60))
    _export(tmp_path, "b", (8, 8), (30, 30, 200))
    _export(tmp_path, "c", (8, 8), (30, 30, 200))
    raster = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
    raster.paste(Image.open(_export(tmp_path, "a_real", (10, 10), (200, 30, 30))), (0, 0))
    layers = (
        _layer("a", "red", "pixel", (0, 0, 10, 10)),
        _layer("b", "blue", "pixel", (12, 12, 20, 20)),
        _layer("c", "cyan", "pixel", (16, 16, 24, 24)),
    )
    evidence = probe_lossless_evidence(
        layers=layers,
        bundles=[BundleRasterProbe((0, 0, 24, 24), raster, ("a", "b", "c"))],
        document_size=(24, 24),
        raster_resource=lambda lid: tmp_path / f"{lid}.png",
    )
    reasons = {record.layer_id: record.reason for record in evidence.records}
    assert reasons["a"].startswith("pixel_delta")
    assert reasons["b"].startswith("overlapped_by")
    assert reasons["c"].startswith("overlapped_by")
    assert evidence.cleared_codes(("pixel_layers_require_equivalence_check",)) == ()


def test_out_of_canvas_bake_coverage_proven(tmp_path) -> None:
    raster = Image.new("RGBA", (30, 20), (7, 7, 7, 255))
    evidence = probe_lossless_evidence(
        layers=(),
        bundles=[BundleRasterProbe((-5, 0, 25, 20), raster, ())],
        document_size=(20, 20),
        raster_resource=lambda lid: None,
    )
    assert evidence.outside_proven
    assert evidence.cleared_codes(
        ("outside_canvas_content_requires_equivalence_check",)
    ) == ("outside_canvas_content_requires_equivalence_check",)
