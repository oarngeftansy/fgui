import pytest
from PIL import Image


def test_state_capture_uses_runtime_and_rejects_editor_fallback(monkeypatch, tmp_path):
    import figma_to_fgui.hifi_controller_states as module

    calls = []

    def send(bridge, action, params, timeout):
        calls.append((action, params))
        if action == "switch_controller":
            return {"data": {"newIndex": 1, "target": "runtime"}}
        return {
            "data": {"path": str(tmp_path / "capture.png"), "capture_source": "testView_content"}
        }

    monkeypatch.setattr(module, "_send_command", send)
    assert module.capture_runtime_state(tmp_path, {"red": 1}, 0) == tmp_path / "capture.png"
    assert calls[0] == (
        "switch_controller",
        {"controller_name": "red", "page_index": 1, "target": "runtime"},
    )
    assert all(c[0] != "screenshot" for c in calls)
    monkeypatch.setattr(
        module, "_send_command", lambda *args: {"data": {"newIndex": 1, "target": "editor"}}
    )
    with pytest.raises(ValueError, match="runtime_controller"):
        module.capture_runtime_state(tmp_path, {"red": 1}, 0)


def test_controller_matrix_covers_combinations_and_does_not_truncate():
    from figma_to_fgui.hifi_controller_states import controller_matrix

    xml = b'<component><controller name="a" pages="0,on,1,off"/><controller name="b" pages="x,one,y,two,z,three"/></component>'
    assert len(controller_matrix(xml)) == 6
    assert {tuple(s.values()) for s in controller_matrix(xml)} == {
        (a, b) for a in range(2) for b in range(3)
    }
    with pytest.raises(ValueError, match="state_budget"):
        controller_matrix(xml, limit=5)


def test_visual_changes_do_not_hide_lost_state_behavior(tmp_path):
    from figma_to_fgui.hifi_controller_states import compare_state_responses

    paths = []
    for name, color, dot in [
        ("old0", "red", False),
        ("old1", "red", True),
        ("new0", "blue", False),
        ("new1", "blue", True),
    ]:
        canvas = Image.new("RGB", (20, 20), "white")
        canvas.paste(color, (0, 10, 20, 20))
        if dot:
            canvas.paste("black", (2, 2, 5, 5))
        path = tmp_path / (name + ".png")
        canvas.save(path)
        paths.append(path)
    assert compare_state_responses(paths[:2], paths[2:])
    Image.open(paths[2]).save(paths[3])
    assert not compare_state_responses(paths[:2], paths[2:])


def test_state_direction_is_preserved_not_just_difference_bbox(tmp_path):
    from figma_to_fgui.hifi_controller_states import compare_state_responses

    paths = []
    for n, c in enumerate(["white", "black", "black", "white"]):
        p = tmp_path / f"{n}.png"
        Image.new("RGB", (4, 4), c).save(p)
        paths.append(p)
    assert not compare_state_responses(paths[:2], paths[2:])


def test_run_state_evidence_degrades_without_editor(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import figma_to_fgui.hifi_controller_states as module

    monkeypatch.setattr(module, "discover_fairygui_editor", lambda: None)
    report = module.run_state_evidence(
        data_dir=tmp_path,
        session_id="s" * 32,
        candidate_sha256="ab" * 32,
        artifact=tmp_path / "missing.zip",
        before_root=tmp_path,
        target=SimpleNamespace(component_relative_path="assets/P/C.xml"),
    )
    assert report["status"] == "editor_not_found"
    assert report["state_pixel_response_preserved"] is False
    assert report["interactions_transitions_and_game_bindings_verified"] is False
    persisted = module.load_state_evidence(tmp_path, "s" * 32, "ab" * 32)
    assert persisted is not None
    assert persisted["status"] == "editor_not_found"


def test_run_state_evidence_captures_and_caches(monkeypatch, tmp_path):
    from pathlib import Path as _Path
    from types import SimpleNamespace

    import figma_to_fgui.hifi_controller_states as module

    monkeypatch.setattr(module, "discover_fairygui_editor", lambda: _Path("editor.exe"))
    monkeypatch.setattr(
        module, "_extract_candidate", lambda artifact, destination: destination
    )
    calls = []

    def fake_capture(before_root, after_root, target, output):
        calls.append(output)
        return {
            "component": target.component_relative_path,
            "capture_mode": "F5_runtime",
            "states": [{}, {"state": 1}],
            "declared_controller_states_complete": True,
            "state_pixel_response_preserved": True,
            "captures": {},
            "interactions_transitions_and_game_bindings_verified": False,
            "approvable": False,
        }

    monkeypatch.setattr(module, "capture_controller_evidence", fake_capture)
    kwargs = dict(
        data_dir=tmp_path,
        session_id="s" * 32,
        candidate_sha256="ab" * 32,
        artifact=tmp_path / "candidate.zip",
        before_root=tmp_path,
        target=SimpleNamespace(component_relative_path="assets/P/C.xml"),
    )
    report = module.run_state_evidence(**kwargs)
    assert report["status"] == "captured"
    assert report["state_pixel_response_preserved"] is True
    assert len(report["states"]) == 2
    assert calls and calls[0] == module.state_evidence_dir(tmp_path, "s" * 32, "ab" * 32)

    def relaunch(*args):
        raise AssertionError("captured evidence must be reused, not recaptured")

    monkeypatch.setattr(module, "capture_controller_evidence", relaunch)
    assert module.run_state_evidence(**kwargs)["status"] == "captured"
    assert len(calls) == 1


def test_run_state_evidence_records_failure_without_caching(monkeypatch, tmp_path):
    from pathlib import Path as _Path
    from types import SimpleNamespace

    import figma_to_fgui.hifi_controller_states as module
    from figma_to_fgui.fairygui_editor_verify import FairyGuiEditorVerificationError

    monkeypatch.setattr(module, "discover_fairygui_editor", lambda: _Path("editor.exe"))
    monkeypatch.setattr(
        module, "_extract_candidate", lambda artifact, destination: destination
    )
    attempts = []

    def boom(*args):
        attempts.append(1)
        raise FairyGuiEditorVerificationError("fgui_editor_timeout")

    monkeypatch.setattr(module, "capture_controller_evidence", boom)
    kwargs = dict(
        data_dir=tmp_path,
        session_id="s" * 32,
        candidate_sha256="cd" * 32,
        artifact=tmp_path / "candidate.zip",
        before_root=tmp_path,
        target=SimpleNamespace(component_relative_path="assets/P/C.xml"),
    )
    report = module.run_state_evidence(**kwargs)
    assert report["status"] == "failed:fgui_editor_timeout"
    assert report["state_pixel_response_preserved"] is False
    persisted = module.load_state_evidence(tmp_path, "s" * 32, "cd" * 32)
    assert persisted is not None and persisted["status"] == "failed:fgui_editor_timeout"
    module.run_state_evidence(**kwargs)
    assert len(attempts) == 2


def test_overlay_upgrades_manual_state_warnings_when_preserved():
    from figma_to_fgui.hifi_controller_states import overlay_state_evidence_warnings

    warnings = (
        "PSD 无损证据待 Editor 验证：pixel_layers_require_equivalence_check",
        "受保护对象的视觉发生变化，尚缺少各状态与交互验证：n1, n2_x1",
        "受保护对象的视觉发生变化，尚缺少各状态与交互验证：n3_y2",
    )
    result = overlay_state_evidence_warnings(warnings, {
        "status": "captured",
        "state_pixel_response_preserved": True,
        "states": [{}, {"c": 1}],
        "evidence_dir": "D:/evidence",
    })
    assert not any(w.startswith("受保护对象的视觉发生变化") for w in result)
    assert any(
        "已机器核验" in w and "2 态" in w and "D:/evidence" in w for w in result
    )
    assert any("仍需实机确认：n1, n2_x1, n3_y2" in w for w in result)
    assert (
        "PSD 无损证据待 Editor 验证：pixel_layers_require_equivalence_check" in result
    )


def test_overlay_keeps_manual_warnings_without_preserved_evidence():
    from figma_to_fgui.hifi_controller_states import overlay_state_evidence_warnings

    manual = "受保护对象的视觉发生变化，尚缺少各状态与交互验证：n1"
    warnings = (manual,)

    kept = overlay_state_evidence_warnings(warnings, {
        "status": "captured",
        "state_pixel_response_preserved": False,
        "evidence_dir": "D:/e",
    })
    assert kept[0] == manual
    assert any("响应不一致" in w and "D:/e" in w for w in kept)

    missing = overlay_state_evidence_warnings(warnings, {"status": "editor_not_found"})
    assert missing[0] == manual
    assert any("未发现本机 FairyGUI Editor" in w for w in missing)

    failed = overlay_state_evidence_warnings(
        warnings, {"status": "failed:fgui_editor_timeout"}
    )
    assert failed[0] == manual
    assert any("fgui_editor_timeout" in w for w in failed)

    assert overlay_state_evidence_warnings(
        ("其他警告",), {"status": "captured", "state_pixel_response_preserved": True}
    ) == ("其他警告",)
    assert overlay_state_evidence_warnings(warnings, None) == warnings


def test_state_response_metrics_separate_reskin_from_behavior(tmp_path):
    from figma_to_fgui.hifi_controller_states import state_response_metrics

    paths = []
    for name, color, dot in [
        ("old0", "red", False),
        ("old1", "red", True),
        ("new0", "blue", False),
        ("new1", "blue", True),
    ]:
        canvas = Image.new("RGB", (20, 20), "white")
        canvas.paste(color, (0, 10, 20, 20))
        if dot:
            canvas.paste("black", (2, 2, 5, 5))
        path = tmp_path / (name + ".png")
        canvas.save(path)
        paths.append(path)
    metrics = state_response_metrics(paths[:2], paths[2:])
    assert metrics["toggle_mask_iou"] == 1.0
    assert metrics["delta_direction_agreement"] == 1.0
    assert metrics["toggle_mask_symmetric_difference"] == 0

    shifted = Image.new("RGB", (20, 20), "white")
    shifted.paste("blue", (0, 10, 20, 20))
    shifted.paste("black", (8, 8, 11, 11))
    moved = tmp_path / "new1-moved.png"
    shifted.save(moved)
    metrics = state_response_metrics(paths[:2], [paths[2], moved])
    assert metrics["toggle_mask_iou"] == 0.0
    assert metrics["toggle_mask_symmetric_difference"] == 18
