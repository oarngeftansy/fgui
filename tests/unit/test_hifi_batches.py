import base64
import hashlib
import shutil
from pathlib import Path

import pytest

from figma_to_fgui.hifi_replacement_store import (
    HifiReplacementStore,
    HifiReplacementStoreError,
)
from figma_to_fgui.hifi_replacement_workflow import HifiReplacementWorkflow
from figma_to_fgui.project_package import diff_project_trees
from figma_to_fgui.project_store import ProjectStore
from figma_to_fgui.psd_source_store import PsdSourceStore, PsdSourceStoreError
from figma_to_fgui.selection_store import SelectionStore
from figma_to_fgui.apply import apply_bundle
from figma_to_fgui.hifi_replacement_models import HifiMappingDraft, HifiTargetRef


def _mapping() -> HifiMappingDraft:
    return HifiMappingDraft.model_validate(
        {
            "version": 1,
            "policy_revision": 29,
            "mapping_revision": 1,
            "items": (),
            "unresolved_count": 0,
            "stage_ledger": (),
        }
    )


def _target() -> HifiTargetRef:
    return HifiTargetRef.model_validate(
        {
            "version": 1,
            "project_id": "p" * 32,
            "project_fingerprint": "f" * 64,
            "package_id": "pkg",
            "package_name": "Pkg",
            "directory": "/",
            "component_id": "c1",
            "component_name": "Panel_A",
            "component_relative_path": "assets/Pkg/Panel_A.xml",
        }
    )


def test_scan_design_assets_honours_explicit_cutout_dir(tmp_path: Path) -> None:
    from figma_to_fgui.psd_source_store import scan_design_assets

    root = tmp_path / "delivery"
    (root / "skins").mkdir(parents=True)
    (root / "skins" / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "skins" / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    manifest = scan_design_assets("x.psd", root, cutout_dir=root / "skins")
    assert manifest["cutouts"] == ["a.png", "b.png"]
    assert manifest["cutout_dir"] == str(root / "skins")
    with pytest.raises(PsdSourceStoreError) as error:
        scan_design_assets("x.psd", root, cutout_dir=root / "missing")
    assert error.value.code == "design_assets_cutout_dir_invalid"


def test_batch_store_roundtrip_and_owner_isolation(tmp_path: Path) -> None:
    store = HifiReplacementStore(tmp_path)
    batch_id = store.begin_batch(
        "owner", "p" * 32, "f" * 64, ("a" * 64, "b" * 64), "/root", "/root/cut"
    )
    first = store.begin(
        "owner", "a" * 64, _target(), _mapping(), "k1", batch_id=batch_id
    )
    second = store.begin(
        "owner", "b" * 64, _target(), _mapping(), "k2", batch_id=batch_id
    )
    sessions = store.batch_sessions(batch_id)
    assert [s.view.session_id for s in sessions] == [
        first.view.session_id,
        second.view.session_id,
    ]
    store.set_batch_warnings(batch_id, ["a failed"])
    store.set_batch_artifact(batch_id, tmp_path / "x.zip", "x.zip", "a" * 64)
    store.set_batch_writeback(batch_id, '{"local_path": "/p"}')
    row = store.get_batch(batch_id, "owner")
    assert row["status"] == "delivered"
    assert row["artifact_sha256"] == "a" * 64
    assert row["warnings_json"] == '["a failed"]'
    with pytest.raises(HifiReplacementStoreError) as error:
        store.get_batch(batch_id, "other")
    assert error.value.code == "hifi_batch_not_found"


def test_diff_project_trees_roundtrips_through_apply(tmp_path: Path) -> None:
    base = tmp_path / "base"
    (base / "assets" / "Pkg").mkdir(parents=True)
    (base / "assets" / "Pkg" / "package.xml").write_text("<package/>", encoding="utf-8")
    (base / "assets" / "Pkg" / "A.xml").write_text("<component/>", encoding="utf-8")
    (base / ".figma-to-fgui" / "noise.txt").parent.mkdir(parents=True)
    (base / ".figma-to-fgui" / "noise.txt").write_text("old", encoding="utf-8")
    staged = tmp_path / "staged"
    shutil.copytree(base, staged)
    (staged / "assets" / "Pkg" / "A.xml").write_text(
        "<component edited=\"1\"/>", encoding="utf-8"
    )
    (staged / "assets" / "Pkg" / "Img").mkdir()
    (staged / "assets" / "Pkg" / "Img" / "new.png").write_bytes(b"\x00png")
    (staged / ".figma-to-fgui" / "noise.txt").write_text("new", encoding="utf-8")

    bundle = diff_project_trees(base, staged, job_id="j", project_id="p" * 32)
    paths = {file.relative_path: file for file in bundle.files}
    assert set(paths) == {"assets/Pkg/A.xml", "assets/Pkg/Img/new.png"}
    assert paths["assets/Pkg/A.xml"].operation == "replace"
    assert paths["assets/Pkg/Img/new.png"].operation == "create"

    replay = tmp_path / "replay"
    shutil.copytree(base, replay)
    apply_bundle(replay, bundle)
    for relative in ("assets/Pkg/A.xml", "assets/Pkg/Img/new.png"):
        assert (replay / relative).read_bytes() == (staged / relative).read_bytes()


def test_combined_package_gated_until_every_group_approved(tmp_path: Path) -> None:
    data = tmp_path / "data"
    store = HifiReplacementStore(data)
    workflow = HifiReplacementWorkflow(
        data,
        ProjectStore(data),
        SelectionStore(data),
        PsdSourceStore(data),
        store,
    )
    batch_id = store.begin_batch(
        "owner", "p" * 32, "f" * 64, ("a" * 64,), None, None
    )
    with pytest.raises(HifiReplacementStoreError) as error:
        workflow.build_combined_package("owner", batch_id)
    assert error.value.code == "hifi_batch_not_export_ready"
    with pytest.raises(HifiReplacementStoreError) as error:
        workflow.writeback_batch("owner", batch_id, str(tmp_path))
    assert error.value.code == "hifi_batch_not_export_ready"


def test_batch_id_survives_in_session_column(tmp_path: Path) -> None:
    store = HifiReplacementStore(tmp_path)
    batch_id = store.begin_batch("owner", "p" * 32, "f" * 64, (), None, None)
    stored = store.begin("owner", "a" * 64, _target(), _mapping(), "k")
    assert store.batch_sessions(batch_id) == []
    store.attach_batch(stored.view.session_id, batch_id)
    assert [s.view.session_id for s in store.batch_sessions(batch_id)] == [
        stored.view.session_id
    ]
