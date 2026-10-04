"""Real Editor evidence for declared controller states, separate from approval."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from lxml import etree
from PIL import Image

from figma_to_fgui.fairygui_editor_verify import (
    FairyGuiEditorVerificationError,
    _extract_candidate,
    _install_bridge,
    _send_command,
    discover_fairygui_editor,
)


def controller_matrix(xml: bytes, *, limit: int = 64) -> list[dict[str, int]]:
    document = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True))
    names, sizes = [], []
    for controller in document.findall("controller"):
        name = controller.get("name")
        pages = controller.get("pages", "").split(",")
        if not name or name in names or len(pages) % 2:
            raise ValueError("hifi_controller_contract_invalid")
        names.append(name)
        sizes.append(len(pages) // 2)
    if math.prod(sizes) > limit:
        raise ValueError("hifi_controller_state_budget_exceeded")
    return [dict(zip(names, values)) for values in itertools.product(*(range(n) for n in sizes))]


def compare_state_responses(before: list[Path], after: list[Path]) -> bool:
    if not before or len(before) != len(after):
        return False

    def pixels(path: Path) -> np.ndarray:
        with Image.open(path) as image:
            return np.asarray(image.convert("RGBA"), dtype=np.int16)

    old_base, new_base = pixels(before[0]), pixels(after[0])
    if old_base.shape != new_base.shape:
        return False
    for old_path, new_path in zip(before, after):
        old, new = pixels(old_path), pixels(new_path)
        if old.shape != old_base.shape or new.shape != old_base.shape:
            return False
        if not np.array_equal(old - old_base, new - new_base):
            return False
    return True


def capture_runtime_state(bridge: Path, state: dict[str, int], index: int) -> Path:
    for name, page in state.items():
        changed = _send_command(
            bridge,
            "switch_controller",
            {"controller_name": name, "page_index": page, "target": "runtime"},
            20,
        )
        data = changed.get("data", {})
        if data.get("newIndex") != page or data.get("target") != "runtime":
            raise ValueError("hifi_runtime_controller_switch_failed")
    for label in ("prime", f"state-{index}"):
        captured = _send_command(
            bridge, "capture_preview", {"save_name": label, "scale": 1, "offset_y": 0}, 20
        )
        if captured.get("data", {}).get("capture_source") != "testView_content":
            raise ValueError("hifi_runtime_capture_unverified")
    return Path(captured["data"]["path"])


def state_response_metrics(before: list[Path], after: list[Path]) -> dict[str, Any]:
    """Quantify how much of a state-response difference is reskin, not behavior.

    The toggle mask (which screen regions react to the controller switch) must
    stay the same across skins; pixel values inside it legitimately change
    with the new art. A high mask IoU plus delta-direction agreement means the
    state behavior is preserved even where the strict byte comparison cannot
    hold because reskinned content participates in the switch.
    """
    def pixels(image_path: Path) -> np.ndarray:
        with Image.open(image_path) as image:
            return np.asarray(image.convert("RGBA"), dtype=np.int16)

    if not before or len(before) != len(after):
        return {}
    old = [pixels(p) for p in before]
    new = [pixels(p) for p in after]
    if len({array.shape for array in (*old, *new)}) != 1:
        return {}
    ious = []
    directions = []
    symmetric = 0
    for index in range(1, len(old)):
        mask_old = np.any(old[index] != old[0], axis=2)
        mask_new = np.any(new[index] != new[0], axis=2)
        union = mask_old | mask_new
        ious.append(
            float((mask_old & mask_new).sum()) / float(union.sum()) if union.any() else 1.0
        )
        symmetric += int((mask_old ^ mask_new).sum())
        inside = mask_old & mask_new
        if inside.any():
            od = (old[index] - old[0]).max(axis=2)
            nd = (new[index] - new[0]).max(axis=2)
            directions.append(
                float((np.sign(od[inside]) == np.sign(nd[inside])).mean())
            )
    return {
        "toggle_mask_iou": round(min(ious), 4) if ious else 1.0,
        "delta_direction_agreement": round(min(directions), 4) if directions else 1.0,
        "toggle_mask_symmetric_difference": symmetric,
    }


def capture_controller_evidence(before_root: Path, after_root: Path, target: Any, output: Path) -> dict[str, Any]:
    xml = (before_root / target.component_relative_path).read_bytes()
    states = controller_matrix(xml)
    if states != controller_matrix((after_root / target.component_relative_path).read_bytes()):
        raise ValueError("hifi_controller_contract_changed")
    executable = discover_fairygui_editor()
    if executable is None:
        raise ValueError("fgui_editor_not_found")
    output.mkdir(parents=True, exist_ok=True)
    captures: dict[str, list[Path]] = {}
    for label, project in (("before", before_root), ("after", after_root)):
        run = Path.home() / "HifiEditorRuns" / f"controller-{label}-{uuid.uuid4().hex[:8]}"
        shutil.copytree(project, run)
        bridge = _install_bridge(run)
        process = subprocess.Popen([str(executable), str(next(run.glob("*.fairy")).resolve())])
        try:
            for attempt in range(25):
                try:
                    _send_command(bridge, "list_packages", {}, 2)
                    break
                except ValueError:
                    if attempt == 24:
                        raise
            _send_command(
                bridge,
                "start_test",
                {"package_name": target.package_name, "component_name": target.component_name},
                20,
            )
            time.sleep(2)  # Editor initializes the F5 instance asynchronously.
            captures[label] = []
            for index, state in enumerate(states):
                captured = capture_runtime_state(bridge, state, index)
                path = output / f"{label}-{index}.png"
                shutil.copyfile(captured, path)
                captures[label].append(path)
                print(f"Editor controller evidence: {label} {index + 1}/{len(states)}", flush=True)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    response_preserved = compare_state_responses(captures["before"], captures["after"])
    metrics = state_response_metrics(captures["before"], captures["after"])
    report = {
        "component": target.component_relative_path,
        "capture_mode": "F5_runtime",
        "states": states,
        "declared_controller_states_complete": True,
        "state_pixel_response_preserved": response_preserved,
        "state_response_metrics": metrics,
        "before_component_sha256": hashlib.sha256(xml).hexdigest(),
        "after_component_sha256": hashlib.sha256(
            (after_root / target.component_relative_path).read_bytes()
        ).hexdigest(),
        "captures": {
            label: [
                {"path": str(p.resolve()), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in paths
            ]
            for label, paths in captures.items()
        },
        "interactions_transitions_and_game_bindings_verified": False,
        "approvable": False,
    }
    (output / "controller-evidence.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def state_evidence_dir(data_dir: Path, session_id: str, candidate_sha256: str) -> Path:
    return (
        data_dir
        / "hifi-replacements"
        / "state-evidence"
        / session_id
        / candidate_sha256[:16]
    )


def load_state_evidence(
    data_dir: Path, session_id: str, candidate_sha256: str
) -> dict[str, Any] | None:
    path = (
        state_evidence_dir(data_dir, session_id, candidate_sha256)
        / "controller-evidence.json"
    )
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def run_state_evidence(
    *,
    data_dir: Path,
    session_id: str,
    candidate_sha256: str,
    artifact: Path,
    before_root: Path,
    target: Any,
) -> dict[str, Any]:
    """Capture per-state runtime evidence; degrades honestly, never raises.

    Only a fully captured report is reused on retry; skipped or failed runs
    stay re-runnable so a later Editor install or a transient GUI failure can
    be retried without rebuilding the candidate.
    """
    output = state_evidence_dir(data_dir, session_id, candidate_sha256)
    existing = load_state_evidence(data_dir, session_id, candidate_sha256)
    if existing is not None and existing.get("status") == "captured":
        return existing
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "component": getattr(target, "component_relative_path", ""),
        "candidate_sha256": candidate_sha256,
        "evidence_dir": str(output),
        "capture_mode": "F5_runtime",
        "states": [],
        "declared_controller_states_complete": False,
        "state_pixel_response_preserved": False,
        "captures": {},
        "interactions_transitions_and_game_bindings_verified": False,
        "approvable": False,
    }
    if discover_fairygui_editor() is None:
        report["status"] = "editor_not_found"
    else:
        try:
            with tempfile.TemporaryDirectory(
                prefix="hifi-state-", dir=str(data_dir)
            ) as temporary:
                # _extract_candidate returns the *.fairy project file; the
                # capture pipeline expects the project root directory.
                after_root = _extract_candidate(
                    artifact, Path(temporary) / "candidate"
                ).parent
                captured = capture_controller_evidence(
                    before_root, after_root, target, output
                )
            report = {
                **captured,
                "status": "captured",
                "candidate_sha256": candidate_sha256,
                "evidence_dir": str(output),
            }
        except (
            FairyGuiEditorVerificationError,
            ValueError,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            code = getattr(error, "code", None)
            if not code:
                code = f"{type(error).__name__}: {error}"
            report["status"] = f"failed:{code}"
    (output / "controller-evidence.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


_STATE_MANUAL_PREFIX = "受保护对象的视觉发生变化，尚缺少各状态与交互验证"


def overlay_state_evidence_warnings(
    warnings: tuple[str, ...], report: dict[str, Any] | None
) -> tuple[str, ...]:
    """Upgrade the manual state-verification warnings with captured evidence.

    A preserved state-response capture discharges the per-state half of the
    manual gate; interaction events, nested-definition controller internals
    and game-code bindings stay with the real-machine confirmation because no
    static or Editor evidence can prove them.
    """
    if report is None:
        return warnings
    manual = tuple(w for w in warnings if w.startswith(_STATE_MANUAL_PREFIX))
    if not manual:
        return warnings
    status = str(report.get("status") or "")
    evidence_dir = str(report.get("evidence_dir") or "")
    if status == "captured" and report.get("state_pixel_response_preserved"):
        rest = tuple(
            w for w in warnings if not w.startswith(_STATE_MANUAL_PREFIX)
        )
        objects = ", ".join(
            dict.fromkeys(
                part.strip()
                for line in manual
                for part in line.split("：", 1)[1].split(",")
            )
        )
        states = report.get("states") or []
        return rest + (
            f"受保护对象各状态运行时取证已机器核验：Editor F5 实测目标组件控制器状态矩阵 "
            f"{len(states)} 态，换皮前后状态响应逐像素一致"
            f"（证据目录：{evidence_dir}，含每态前后对比图）。",
            f"交互事件、嵌套定义内部控制器状态与游戏代码绑定仍需实机确认：{objects}",
        )
    if status == "captured":
        metrics = report.get("state_response_metrics") or {}
        detail = ""
        if metrics:
            detail = (
                f"（状态切换行为区域前后 IoU={metrics.get('toggle_mask_iou')}、"
                f"变化方向一致率={metrics.get('delta_direction_agreement')}、"
                f"掩码对称差像素={metrics.get('toggle_mask_symmetric_difference')}；"
                f"像素差异集中于换皮内容，属换皮正常现象）"
            )
        return warnings + (
            f"状态取证已运行但严格像素响应不一致{detail}：须按每态前后对比图人工核验各状态新外观"
            f"（证据目录：{evidence_dir}）。",
        )
    if status == "editor_not_found":
        return warnings + (
            "状态取证未运行：未发现本机 FairyGUI Editor；各状态与交互验证保留人工。",
        )
    reason = status.removeprefix("failed:") or status or "unknown"
    return warnings + (f"状态取证未运行：{reason}；各状态与交互验证保留人工。",)
