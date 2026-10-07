from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from PIL import Image, ImageChops, ImageStat

from figma_to_fgui.hifi_replacement_models import (
    HifiEditorMismatchItem,
    HifiEditorMismatchRegion,
    HifiEditorVerification,
    HifiMappingDraft,
    HifiTargetRef,
)
from figma_to_fgui.paths import safe_relative_path


class FairyGuiEditorVerificationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def discover_fairygui_editor() -> Path | None:
    configured = os.environ.get("FAIRYGUI_EDITOR_PATH")
    candidates = [
        Path(configured) if configured else None,
        Path.home() / "Tools/FairyGUI-Editor-6.1.4/FairyGUI-Editor/FairyGUI-Editor.exe",
        Path.home() / "Downloads/FairyGUI-Editor_6.1.4/FairyGUI-Editor/FairyGUI-Editor.exe",
        Path("C:/Program Files/FairyGUI-Editor/FairyGUI-Editor.exe"),
    ]
    command = shutil.which("FairyGUI-Editor.exe")
    if command:
        candidates.append(Path(command))
    return next((path.resolve() for path in candidates if path and path.is_file()), None)


def _send_command(bridge: Path, action: str, params: dict[str, object], timeout: float) -> dict[str, Any]:
    command_id = "cmd_" + uuid.uuid4().hex[:8]
    command = bridge / "commands" / f"{command_id}.json"
    result = bridge / "results" / f"{command_id}.json"
    command.parent.mkdir(parents=True, exist_ok=True)
    result.parent.mkdir(parents=True, exist_ok=True)
    temporary = command.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"id": command_id, "action": action, "params": params, "timeout": int(timeout * 1000)},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, command)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result.is_file():
            try:
                payload = json.loads(result.read_text("utf-8"))
                result.unlink(missing_ok=True)
                if not isinstance(payload, dict) or payload.get("status") != "success":
                    error = FairyGuiEditorVerificationError("fgui_editor_command_failed")
                    if isinstance(payload, dict):
                        error.add_note(f"Editor action {action}: {payload.get('error', 'unknown error')}")
                    raise error
                return payload
            except json.JSONDecodeError:
                pass
        time.sleep(0.1)
    command.unlink(missing_ok=True)
    raise FairyGuiEditorVerificationError("fgui_editor_timeout")


def _install_bridge(project: Path) -> Path:
    source = Path(__file__).with_name("editor_bridge_assets") / "MCPBridge"
    if not source.is_dir():
        raise FairyGuiEditorVerificationError("fgui_editor_bridge_missing")
    destination = project / "plugins/MCPBridge"
    shutil.copytree(source, destination, dirs_exist_ok=True)
    bridge = destination / "bridge"
    for name in ("commands", "results", "screenshots"):
        (bridge / name).mkdir(parents=True, exist_ok=True)
    return bridge


def _has_package(payload: dict[str, Any], package_name: str) -> bool:
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    packages = data.get("packages")
    values = packages if isinstance(packages, list) else packages.values() if isinstance(packages, dict) else ()
    return any(isinstance(item, dict) and item.get("name") == package_name for item in values)


def _extract_candidate(artifact: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    with ZipFile(artifact) as archive:
        for member in archive.infolist():
            relative = safe_relative_path(member.filename.rstrip("/")) if member.filename.rstrip("/") else None
            if relative is None:
                continue
            target = destination / relative
            target.resolve().relative_to(destination.resolve())
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    projects = list(destination.glob("*.fairy"))
    if len(projects) != 1:
        raise FairyGuiEditorVerificationError("fgui_editor_project_invalid")
    return projects[0]


# The byte-level Editor gate can only hold where the PSD owns the visible
# pixels. FairyGUI rasterizes text with its own font engine, kept legacy
# objects paint their old pixels, non-default controller states and
# out-of-scope regions are not the reskin's output, and retained PSD texts
# never enter a baked bundle. Those regions are excluded from the scoped
# comparison instead of failing an unreachable byte-exact expectation.
_SCOPED_MEAN_LIMIT = 0.01
_SCOPED_BLOCK_LIMIT = 0.35
_MIN_SCOPED_COVERAGE = 0.05
# §17: a block becomes a mismatch region when at least this much channel
# difference survives the scoped mask - clear visible drift, not font AA noise.
_MISMATCH_BLOCK_THRESHOLD = 0.05
_MISMATCH_REGION_KEEP = 8
_MISMATCH_ATTRIBUTE_COVERAGE = 0.25


def build_editor_compare_mask(
    mapping: HifiMappingDraft,
    layers: Any,
    viewport: tuple[int, int, int, int],
    expected_width: int,
    expected_height: int,
) -> Image.Image:
    """Where the Editor render must match the PSD reference pixel for pixel.

    ``layers`` are the PSD analysis layers (``.id`` and ``.bounds``). The mask
    is painted in mapping order, which approximates the display z-order: a
    region claimed by an accepted raster visual is compared, while regions
    painted by kept legacy visuals, editor text, non-default states,
    out-of-scope content, and retained PSD texts are cleared again.
    """
    mask = Image.new("L", (expected_width, expected_height), 0)
    view_x, view_y = viewport[0], viewport[1]
    old_w, old_h = mapping.old_canvas_size or (expected_width, expected_height)
    doc_w, doc_h = mapping.source_canvas_size or (expected_width + view_x, expected_height + view_y)
    bounds_by_id = {layer.id: tuple(layer.bounds) for layer in layers}

    def paste(box: tuple[float, float, float, float] | None, value: int) -> None:
        if not box:
            return
        left = int(max(0, round(box[0])))
        top = int(max(0, round(box[1])))
        right = int(min(expected_width, round(box[0] + box[2])))
        bottom = int(min(expected_height, round(box[1] + box[3])))
        if right <= left or bottom <= top:
            return
        mask.paste(value, (left, top, right, bottom))

    def pad(box: tuple[float, float, float, float] | None, padding: int):
        if not box:
            return None
        return (box[0] - padding, box[1] - padding, box[2] + 2 * padding, box[3] + 2 * padding)

    def old_box(item: Any):
        box = item.old_bounds
        if not box:
            return None
        return (box[0] * old_w, box[1] * old_h, box[2] * old_w, box[3] * old_h)

    def figma_box(item: Any):
        box = item.figma_bounds
        if not box:
            return None
        return (box[0] * doc_w - view_x, box[1] * doc_h - view_y, box[2] * doc_w, box[3] * doc_h)

    def layer_box(node_id: str):
        bounds = bounds_by_id.get(node_id)
        if not bounds or len(bounds) != 4:
            return None
        x0, y0, x1, y1 = bounds
        return (x0 - view_x, y0 - view_y, x1 - x0, y1 - y0)

    for item in mapping.items:
        action = item.action
        old_type = (item.old_object_type or "").casefold()
        if action in {"accept", "retarget"}:
            if old_type in {"text", "richtext"} or item.generated_state:
                # Editor font anti-aliasing can never byte-match the PSD
                # raster; state visuals only show on non-default pages.
                paste(pad(figma_box(item), 8), 0)
            elif old_type in {"image", "loader", "graph"}:
                if (item.figma_node_id or "").startswith("cutout:"):
                    # A human-paired cutout is an intentional non-PSD skin;
                    # exempt its legacy region like a kept visual.
                    paste(old_box(item), 0)
                else:
                    paste(figma_box(item), 255)
        elif action in {"keep_old", None, "preserve_structure"} and item.visual_disposition == "preserve":
            if old_type not in {"group", "component"} and item.default_visible:
                paste(old_box(item), 0)
        elif item.status == "out_of_scope":
            paste(pad(old_box(item), 4), 0)
            paste(pad(figma_box(item), 4), 0)

    for item in mapping.items:
        for node_id in item.retained_source_ids or ():
            # Retained PSD texts stay out of the baked bundle; the reference
            # keeps their pixels while the Editor never renders them.
            paste(pad(layer_box(node_id), 4), 0)
    return mask


def _image_evidence(
    screenshot: Path,
    reference: Path,
    expected_width: int,
    expected_height: int,
) -> tuple[int, int, bool, float | None, bool]:
    with Image.open(screenshot) as rendered:
        rendered.load()
        width, height = rendered.size
        rgb = rendered.convert("RGB")
        extrema = ImageStat.Stat(rgb).extrema
        # A failed test-view capture can be the correct size while containing
        # only the preview's gray/black shell. Require real image complexity,
        # not merely two different solid colors.
        has_pixels = any(high > low for low, high in extrema) and rgb.convert("L").entropy() >= 2
        dimension_match = (width, height) == (expected_width, expected_height)
        if not dimension_match or not has_pixels:
            return width, height, dimension_match, None, has_pixels
        with Image.open(reference) as source:
            if source.size != (expected_width, expected_height):
                raise FairyGuiEditorVerificationError("fgui_reference_dimensions_invalid")
            expected = source.convert("RGB")
        difference = ImageChops.difference(rgb, expected)
        mean = sum(ImageStat.Stat(difference).mean) / (3 * 255)
        return width, height, True, mean, True


def _scoped_evidence(
    screenshot: Path,
    reference: Path,
    compare_mask: Image.Image,
    expected_width: int,
    expected_height: int,
) -> tuple[float, float, float] | None:
    with Image.open(screenshot) as rendered, Image.open(reference) as source:
        rgb = rendered.convert("RGB")
        expected = source.convert("RGB")
        if rgb.size != (expected_width, expected_height) or expected.size != (expected_width, expected_height):
            return None
        diff = ImageChops.difference(rgb, expected)
    mask = compare_mask if compare_mask.size == (expected_width, expected_height) else None
    if mask is None:
        return None
    total = expected_width * expected_height
    zero = Image.new("RGB", (expected_width, expected_height), (0, 0, 0))
    active = Image.composite(diff, zero, mask)
    mask_values = list(mask.getdata())
    count = sum(1 for value in mask_values if value)
    if count == 0:
        return 0.0, 1.0, 0.0
    # Channel-average difference, exactly like the global gate: a pure hue
    # swap with equal luminance must still fail the comparison.
    stat = ImageStat.Stat(active)
    mean = sum(stat.mean) * total / (3 * 255 * count)
    worst = 0.0
    block = 40
    for top in range(0, expected_height, block):
        for left in range(0, expected_width, block):
            box = (left, top, min(left + block, expected_width), min(top + block, expected_height))
            block_active = sum(
                1 for value in mask.crop(box).getdata() if value
            )
            if block_active == 0:
                continue
            block_stat = ImageStat.Stat(active.crop(box))
            area = (box[2] - box[0]) * (box[3] - box[1])
            score = sum(block_stat.mean) * area / (3 * 255 * block_active)
            worst = max(worst, score)
    return mean, worst, count / total


def editor_mismatch_regions(
    screenshot: Path,
    reference: Path,
    compare_mask: Image.Image | None,
    expected_width: int,
    expected_height: int,
    mapping: HifiMappingDraft,
    viewport: tuple[int, int, int, int],
    *,
    block: int = 40,
) -> tuple[HifiEditorMismatchRegion, ...]:
    """Policy 28 §17: localise the pixels where the Editor render missed the
    PSD reference, merge them into connected regions, and attribute every
    region to the mapping items whose geometry covers it.

    Fail-open by design: any alignment problem returns no regions and keeps
    the numeric gates as the only verdict.
    """
    try:
        with Image.open(screenshot) as rendered:
            if rendered.size != (expected_width, expected_height):
                return ()
            rgb = rendered.convert("RGB")
        with Image.open(reference) as source:
            if source.size != (expected_width, expected_height):
                return ()
            expected = source.convert("RGB")
    except OSError:
        return ()
    mask = compare_mask
    if mask is None or mask.size != (expected_width, expected_height):
        mask = Image.new("L", (expected_width, expected_height), 255)
    diff = ImageChops.difference(rgb, expected)
    zero = Image.new("RGB", (expected_width, expected_height), (0, 0, 0))
    active = Image.composite(diff, zero, mask)

    kept: dict[tuple[int, int], float] = {}
    for top in range(0, expected_height, block):
        for left in range(0, expected_width, block):
            box = (left, top, min(left + block, expected_width),
                   min(top + block, expected_height))
            block_active = sum(1 for value in mask.crop(box).getdata() if value)
            if block_active == 0:
                continue
            block_stat = ImageStat.Stat(active.crop(box))
            area = (box[2] - box[0]) * (box[3] - box[1])
            score = sum(block_stat.mean) * area / (3 * 255 * block_active)
            if score > _MISMATCH_BLOCK_THRESHOLD:
                kept[(left // block, top // block)] = score

    visited: set[tuple[int, int]] = set()
    clusters: list[tuple[tuple[int, int, int, int], float, int]] = []
    for start in kept:
        if start in visited:
            continue
        stack = [start]
        visited.add(start)
        cells: list[tuple[int, int]] = []
        while stack:
            cell = stack.pop()
            cells.append(cell)
            cell_x, cell_y = cell
            for neighbour in ((cell_x + 1, cell_y), (cell_x - 1, cell_y),
                              (cell_x, cell_y + 1), (cell_x, cell_y - 1)):
                if neighbour in kept and neighbour not in visited:
                    visited.add(neighbour)
                    stack.append(neighbour)
        left = min(cell[0] for cell in cells) * block
        top = min(cell[1] for cell in cells) * block
        right = min((max(cell[0] for cell in cells) + 1) * block, expected_width)
        bottom = min((max(cell[1] for cell in cells) + 1) * block, expected_height)
        severity = sum(kept[cell] for cell in cells) / len(cells)
        clusters.append(((left, top, right - left, bottom - top), severity, len(cells)))
    if not clusters:
        return ()
    clusters.sort(key=lambda entry: entry[1], reverse=True)

    # Attribution geometry mirrors build_editor_compare_mask: mapping bounds
    # are canvas fractions, translated into the compared viewport space.
    view_x, view_y = viewport[0], viewport[1]
    old_w, old_h = mapping.old_canvas_size or (expected_width, expected_height)
    doc_w, doc_h = mapping.source_canvas_size or (
        expected_width + view_x, expected_height + view_y
    )
    owners: list[tuple[tuple[float, float, float, float], object]] = []
    for item in mapping.items:
        action = item.action
        if action in {"accept", "retarget", "add_visual"}:
            box = item.figma_bounds
            if box:
                owners.append((
                    (box[0] * doc_w - view_x, box[1] * doc_h - view_y,
                     box[2] * doc_w, box[3] * doc_h), item,
                ))
        elif action in {"keep_old", None, "preserve_structure"} and item.visual_disposition == "preserve":
            box = item.old_bounds
            if box and item.default_visible and (item.old_object_type or "").casefold() not in {"group", "component"}:
                owners.append(((box[0] * old_w, box[1] * old_h,
                                box[2] * old_w, box[3] * old_h), item))

    def overlap_area(region: tuple[int, int, int, int],
                     box: tuple[float, float, float, float]) -> float:
        region_x, region_y, region_w, region_h = region
        box_x, box_y, box_w, box_h = box
        width = min(region_x + region_w, box_x + box_w) - max(region_x, box_x)
        height = min(region_y + region_h, box_y + box_h) - max(region_y, box_y)
        return max(0.0, width) * max(0.0, height)

    result: list[HifiEditorMismatchRegion] = []
    for region, severity, blocks in clusters[:_MISMATCH_REGION_KEEP]:
        area = region[2] * region[3]
        attributed: list[tuple[float, object]] = []
        for box, item in owners:
            covered = overlap_area(region, box) / area if area else 0.0
            if covered >= _MISMATCH_ATTRIBUTE_COVERAGE:
                attributed.append((covered, item))
        attributed.sort(key=lambda pair: pair[0], reverse=True)
        result.append(HifiEditorMismatchRegion(
            version=1,
            x=region[0],
            y=region[1],
            width=region[2],
            height=region[3],
            severity=min(severity, 1.0),
            block_count=blocks,
            items=tuple(
                HifiEditorMismatchItem(
                    version=1,
                    item_id=owner.item_id,
                    old_name=owner.old_name,
                    figma_name=owner.figma_name,
                    action=owner.action,
                )
                for _covered, owner in attributed[:3]
            ),
        ))
    return tuple(result)


def verify_in_fairygui_editor(
    *,
    data_dir: Path,
    session_id: str,
    candidate_sha256: str,
    artifact: Path,
    target: HifiTargetRef,
    reference: Path,
    expected_width: int,
    expected_height: int,
    compare_mask: Image.Image | None = None,
) -> HifiEditorVerification:
    executable = discover_fairygui_editor()
    if executable is None:
        return HifiEditorVerification(
            version=1,
            session_id=session_id,
            candidate_sha256=candidate_sha256,
            editor_found=False,
            project_opened=False,
            component_opened=False,
            render_captured=False,
            expected_width=expected_width,
            expected_height=expected_height,
            full_frame=False,
            approvable=False,
            warnings=("未找到 FairyGUI Editor 6.1.4。",),
        )

    configured_run_root = os.environ.get("FAIRYGUI_EDITOR_RUN_ROOT")
    # FairyGUI's Lua plugin loader is unreliable when the project path contains
    # non-ASCII characters, so keep disposable verification projects in the
    # user's ASCII home path even when the application workspace is localized.
    run_root = (
        Path(configured_run_root)
        if configured_run_root
        else Path.home() / "HifiEditorRuns/figma-to-fgui"
    ) / session_id
    run_root.mkdir(parents=True, exist_ok=True)
    project_root = run_root / f"{candidate_sha256[:12]}-{uuid.uuid4().hex[:8]}"
    project_file = _extract_candidate(artifact, project_root)
    bridge = _install_bridge(project_root)
    # Editor silently opens an empty shell for relative project paths.
    process = subprocess.Popen([str(executable), str(project_file.resolve())])
    try:
        deadline = time.monotonic() + 60
        opened = False
        while time.monotonic() < deadline:
            try:
                packages = _send_command(bridge, "list_packages", {}, 2)
                if _has_package(packages, target.package_name):
                    opened = True
                    break
            except FairyGuiEditorVerificationError:
                if process.poll() not in {None, 0}:
                    break
            time.sleep(0.25)
        if not opened:
            raise FairyGuiEditorVerificationError("fgui_editor_start_failed")
        _send_command(
            bridge,
            "start_test",
            {"package_name": target.package_name, "component_name": target.component_name},
            20,
        )
        time.sleep(2)
        prime = _send_command(
            bridge,
            "capture_preview",
            {"save_name": candidate_sha256 + "-prime", "scale": 1, "offset_y": 0},
            20,
        )
        Path(str(prime.get("data", {}).get("path", ""))).unlink(missing_ok=True)
        capture = _send_command(
            bridge,
            "capture_preview",
            {
                "save_name": candidate_sha256,
                "scale": 1,
                # TestView clips tall components to the visible editor window.
                # Moving the capture object off the viewport for this one
                # render makes GetScreenShot render its complete local bounds;
                # the bridge restores the position immediately afterward.
                "offset_y": min(600, max(0, expected_height - 1)),
            },
            20,
        )
        screenshot = Path(str(capture.get("data", {}).get("path", "")))
        if not screenshot.is_file():
            raise FairyGuiEditorVerificationError("fgui_editor_capture_failed")
        evidence_dir = data_dir / "hifi-replacements/editor-evidence" / session_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence = evidence_dir / f"{candidate_sha256}.png"
        shutil.copyfile(screenshot, evidence)
        width, height, dimensions_match, difference, has_pixels = _image_evidence(
            evidence, reference, expected_width, expected_height
        )
        full_frame = dimensions_match and has_pixels
        warnings: list[str] = []
        if not has_pixels:
            warnings.append("Editor 截图为空，无法进行视觉比对。")
        if not dimensions_match:
            warnings.append(
                f"Editor 截图为 {width}×{height}，目标应为 {expected_width}×{expected_height}；尚未获得完整画面。"
            )
        if difference is not None and difference > 0:
            warnings.append(
                f"与 PSD 原图的平均像素差为 {difference:.4f}。写入内容为 PSD 栅格原件；"
                "差异通常来自按决策保留的旧对象与渲染舍入，请结合截图在 Editor 检查中核对。"
            )
        scoped = None
        if compare_mask is not None and difference is not None:
            scoped = _scoped_evidence(
                evidence, reference, compare_mask, expected_width, expected_height
            )
        if scoped is not None:
            scoped_mean, scoped_worst, scoped_coverage = scoped
            visual_match = (
                scoped_coverage >= _MIN_SCOPED_COVERAGE
                and scoped_mean <= _SCOPED_MEAN_LIMIT
                and scoped_worst <= _SCOPED_BLOCK_LIMIT
            )
            if full_frame and not visual_match:
                warnings.append(
                    f"范围化像素比对未通过：均值 {scoped_mean:.4f}（上限 {_SCOPED_MEAN_LIMIT}）、"
                    f"最大块 {scoped_worst:.3f}（上限 {_SCOPED_BLOCK_LIMIT}）、"
                    f"覆盖 {scoped_coverage:.1%}。PSD 权威区域的渲染与参考图不符，候选已阻断。"
                )
        else:
            # Without a mapping-derived scope, approval stays deliberately
            # exact. A small average can conceal a visibly wrong icon,
            # glyph, or shifted edge in an otherwise large canvas; only a
            # byte-for-byte RGB match is acceptable here.
            visual_match = difference == 0.0
            if full_frame and not visual_match:
                warnings.append(
                    "Editor 完整截图与 PSD 参考图存在任何像素差异；"
                    "候选已阻断，必须修复映射或渲染差异后重新验证。"
                )
        return HifiEditorVerification(
            version=1,
            session_id=session_id,
            candidate_sha256=candidate_sha256,
            editor_found=True,
            editor_version="6.1.4",
            project_opened=True,
            component_opened=True,
            render_captured=True,
            screenshot_url=f"/v1/hifi-replacements/{session_id}/editor-screenshot",
            screenshot_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
            screenshot_width=width,
            screenshot_height=height,
            expected_width=expected_width,
            expected_height=expected_height,
            full_frame=full_frame,
            mean_pixel_difference=difference,
            scoped_mean_difference=scoped[0] if scoped else None,
            scoped_max_block_difference=scoped[1] if scoped else None,
            scoped_coverage=scoped[2] if scoped else None,
            approvable=full_frame and visual_match,
            warnings=tuple(warnings),
        )
    except FairyGuiEditorVerificationError:
        raise
    except OSError as error:
        raise FairyGuiEditorVerificationError("fgui_editor_start_failed") from error
    finally:
        # This Editor instance belongs exclusively to automated verification.
        # Leaving it open also leaves MCPBridge polling its command directory.
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def screenshot_path(data_dir: Path, session_id: str, candidate_sha256: str) -> Path:
    return (
        data_dir
        / "hifi-replacements/editor-evidence"
        / session_id
        / f"{candidate_sha256}.png"
    )
