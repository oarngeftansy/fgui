from types import SimpleNamespace

import pytest
from PIL import Image

from figma_to_fgui.psd_source_store import PsdSourceStore, PsdSourceStoreError


def test_owned_visual_resource_is_content_checked_and_keeps_leaf_partition(tmp_path, monkeypatch):
    store = PsdSourceStore(tmp_path)
    source_id = "a" * 64
    root = tmp_path / source_id
    root.mkdir()
    (root / "source.psd").write_bytes(b"psd")
    monkeypatch.setattr(store, "get", lambda _: SimpleNamespace())
    monkeypatch.setattr(store, "artifact_path", lambda _: root)
    monkeypatch.setattr("figma_to_fgui.psd_source_store.PSDImage.open", lambda _: object())
    calls = []

    def render(document, source, group, owned, retained):
        calls.append((group, owned, retained))
        return Image.new("RGBA", (12, 8), (20, 40, 60, 255)), (2, 3, 14, 11)

    monkeypatch.setattr("figma_to_fgui.psd_effect_render.render_owned_visual", render)
    arguments = {"anchor_id": "body", "group_id": "button",
                 "owned_ids": frozenset({"body", "stroke"}),
                 "retained_ids": frozenset({"label"})}
    result = store.owned_visual_resource(source_id, **arguments)
    assert result.layer_id == "body" and result.bounds == (2, 3, 14, 11)
    assert calls == [("button", frozenset({"body", "stroke"}), frozenset({"label"}))]
    store.owned_visual_resource(source_id, **arguments)
    assert len(calls) == 1
    (root / "resources" / result.key).write_bytes(b"corrupt")
    store.owned_visual_resource(source_id, **arguments)
    assert len(calls) == 2
    with pytest.raises(PsdSourceStoreError, match="ownership_incomplete"):
        store.owned_visual_resource(source_id, **{**arguments, "anchor_id": "elsewhere"})
