from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image

from figma_to_fgui.fairygui_editor_verify import (
    FairyGuiEditorVerificationError,
    _image_evidence,
    discover_fairygui_editor,
    editor_mismatch_regions,
    verify_in_fairygui_editor,
)
from figma_to_fgui.hifi_replacement_models import HifiTargetRef


def test_discovers_configured_editor(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "FairyGUI-Editor.exe"
    executable.write_bytes(b"editor")
    monkeypatch.setenv("FAIRYGUI_EDITOR_PATH", str(executable))

    assert discover_fairygui_editor() == executable.resolve()


def test_image_evidence_requires_a_nonempty_full_size_capture(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    exact = tmp_path / "exact.png"
    cropped = tmp_path / "cropped.png"
    blank = tmp_path / "blank.png"
    preview_shell = tmp_path / "preview-shell.png"
    source = Image.new("RGB", (20, 10), (20, 30, 40))
    for y in range(10):
        for x in range(20):
            source.putpixel((x, y), (x * 12, y * 24, (x + y) * 8))
    source.save(reference)
    source.save(exact)
    source.crop((0, 0, 18, 10)).save(cropped)
    Image.new("RGB", (20, 10), (0, 0, 0)).save(blank)
    shell = Image.new("RGB", (20, 10), (0, 0, 0))
    for y in range(5):
        for x in range(20):
            shell.putpixel((x, y), (160, 160, 160))
    shell.save(preview_shell)

    assert _image_evidence(exact, reference, 20, 10)[:3] == (20, 10, True)
    assert _image_evidence(exact, reference, 20, 10)[4] is True
    assert _image_evidence(cropped, reference, 20, 10) == (18, 10, False, None, True)
    assert _image_evidence(blank, reference, 20, 10) == (20, 10, True, None, False)
    assert _image_evidence(preview_shell, reference, 20, 10) == (
        20,
        10,
        True,
        None,
        False,
    )


def test_image_evidence_never_resizes_the_psd_reference(tmp_path: Path) -> None:
    rendered = tmp_path / "rendered.png"
    wrong_size_reference = tmp_path / "wrong-size-reference.png"
    image = Image.new("RGB", (20, 10), (20, 30, 40))
    for y in range(10):
        for x in range(20):
            image.putpixel((x, y), (x * 12, y * 24, (x + y) * 8))
    image.save(rendered)
    Image.new("RGB", (10, 5), (20, 30, 40)).save(wrong_size_reference)

    with pytest.raises(
        FairyGuiEditorVerificationError,
        match="fgui_reference_dimensions_invalid",
    ):
        _image_evidence(rendered, wrong_size_reference, 20, 10)


def test_editor_verification_rejects_a_full_frame_with_visible_pixel_difference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "FairyGUI-Editor.exe"
    executable.write_bytes(b"editor")
    artifact = tmp_path / "candidate.zip"
    with ZipFile(artifact, "w") as archive:
        archive.writestr(
            "Candidate.fairy",
            '<projectDescription id="1234567890abcdef1234567890abcdef" '
            'type="Unity" version="5.0"/>',
        )
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    source = Image.new("RGB", (20, 10))
    different = Image.new("RGB", (20, 10))
    for y in range(10):
        for x in range(20):
            source.putpixel((x, y), (x * 12, y * 24, (x + y) * 8))
            different.putpixel((x, y), (255 - x * 12, 255 - y * 24, 255 - (x + y) * 8))
    source.save(reference)
    different.save(rendered)
    prime = tmp_path / "prime.png"
    source.save(prime)

    class FinishedEditor:
        def poll(self) -> int:
            return 0

        def terminate(self) -> None:
            pass

        def wait(self, timeout: float) -> int:
            return 0

    captures = iter((prime, rendered))

    def send_command(_bridge: Path, action: str, _params: dict[str, object], _timeout: float):
        if action == "list_packages":
            return {"data": {"packages": [{"name": "Tower"}]}}
        if action == "capture_preview":
            return {"data": {"path": str(next(captures))}}
        if action == "test_state":
            return {"data": {"running": True}}
        return {"data": {}}

    monkeypatch.setattr(
        "figma_to_fgui.fairygui_editor_verify.discover_fairygui_editor",
        lambda: executable,
    )
    monkeypatch.setattr("figma_to_fgui.fairygui_editor_verify._send_command", send_command)
    monkeypatch.setattr(
        "figma_to_fgui.fairygui_editor_verify.subprocess.Popen",
        lambda _args: FinishedEditor(),
    )
    monkeypatch.setattr("figma_to_fgui.fairygui_editor_verify.time.sleep", lambda _seconds: None)
    monkeypatch.setenv("FAIRYGUI_EDITOR_RUN_ROOT", str(tmp_path / "runs"))
    target = HifiTargetRef(
        project_id="a" * 32,
        project_fingerprint="b" * 64,
        package_id="tower123",
        package_name="Tower",
        directory="Panel",
        component_id="panel123",
        component_name="Panel_Tower_Main",
        component_relative_path="assets/Tower/Panel/Panel_Tower_Main.xml",
    )

    verification = verify_in_fairygui_editor(
        data_dir=tmp_path / "data",
        session_id="c" * 32,
        candidate_sha256="d" * 64,
        artifact=artifact,
        target=target,
        reference=reference,
        expected_width=20,
        expected_height=10,
    )

    assert verification.full_frame is True
    assert verification.mean_pixel_difference is not None
    assert verification.mean_pixel_difference > 0.01
    assert verification.approvable is False


def test_editor_verification_rejects_even_one_changed_channel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "FairyGUI-Editor.exe"
    executable.write_bytes(b"editor")
    artifact = tmp_path / "candidate.zip"
    with ZipFile(artifact, "w") as archive:
        archive.writestr(
            "Candidate.fairy",
            '<projectDescription id="1234567890abcdef1234567890abcdef" '
            'type="Unity" version="5.0"/>',
        )
    reference = tmp_path / "reference.png"
    rendered = tmp_path / "rendered.png"
    source = Image.new("RGB", (20, 10), (20, 30, 40))
    for y in range(10):
        for x in range(20):
            source.putpixel((x, y), (x * 12, y * 24, (x + y) * 8))
    changed = source.copy()
    red, green, blue = changed.getpixel((10, 5))
    changed.putpixel((10, 5), (red + 1, green, blue))
    source.save(reference)
    changed.save(rendered)
    prime = tmp_path / "prime.png"
    source.save(prime)

    class FinishedEditor:
        def poll(self) -> int:
            return 0

        def terminate(self) -> None:
            pass

        def wait(self, timeout: float) -> int:
            return 0

    captures = iter((prime, rendered))

    def send_command(_bridge: Path, action: str, _params: dict[str, object], _timeout: float):
        if action == "list_packages":
            return {"data": {"packages": [{"name": "Tower"}]}}
        if action == "capture_preview":
            return {"data": {"path": str(next(captures))}}
        if action == "test_state":
            return {"data": {"running": True}}
        return {"data": {}}

    monkeypatch.setattr(
        "figma_to_fgui.fairygui_editor_verify.discover_fairygui_editor",
        lambda: executable,
    )
    monkeypatch.setattr("figma_to_fgui.fairygui_editor_verify._send_command", send_command)
    monkeypatch.setattr(
        "figma_to_fgui.fairygui_editor_verify.subprocess.Popen",
        lambda _args: FinishedEditor(),
    )
    monkeypatch.setattr("figma_to_fgui.fairygui_editor_verify.time.sleep", lambda _seconds: None)
    monkeypatch.setenv("FAIRYGUI_EDITOR_RUN_ROOT", str(tmp_path / "runs"))
    target = HifiTargetRef(
        project_id="a" * 32,
        project_fingerprint="b" * 64,
        package_id="tower123",
        package_name="Tower",
        directory="Panel",
        component_id="panel123",
        component_name="Panel_Tower_Main",
        component_relative_path="assets/Tower/Panel/Panel_Tower_Main.xml",
    )

    verification = verify_in_fairygui_editor(
        data_dir=tmp_path / "data",
        session_id="e" * 32,
        candidate_sha256="f" * 64,
        artifact=artifact,
        target=target,
        reference=reference,
        expected_width=20,
        expected_height=10,
    )

    assert verification.mean_pixel_difference is not None
    assert 0 < verification.mean_pixel_difference < 0.01
    assert verification.approvable is False


def _run_scoped_verification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    rendered: Image.Image,
    reference: Image.Image,
    mask: Image.Image,
) -> HifiEditorVerification:
    executable = tmp_path / "FairyGUI-Editor.exe"
    executable.write_bytes(b"editor")
    artifact = tmp_path / "candidate.zip"
    with ZipFile(artifact, "w") as archive:
        archive.writestr(
            "Candidate.fairy",
            '<projectDescription id="1234567890abcdef1234567890abcdef" '
            'type="Unity" version="5.0"/>',
        )
    reference_path = tmp_path / "reference.png"
    rendered_path = tmp_path / "rendered.png"
    prime = tmp_path / "prime.png"
    reference.save(reference_path)
    rendered.save(rendered_path)
    reference.save(prime)

    class FinishedEditor:
        def poll(self) -> int:
            return 0

        def terminate(self) -> None:
            pass

        def wait(self, timeout: float) -> int:
            return 0

    captures = iter((prime, rendered_path))

    def send_command(_bridge: Path, action: str, _params: dict[str, object], _timeout: float):
        if action == "list_packages":
            return {"data": {"packages": [{"name": "Tower"}]}}
        if action == "capture_preview":
            return {"data": {"path": str(next(captures))}}
        if action == "test_state":
            return {"data": {"running": True}}
        return {"data": {}}

    monkeypatch.setattr(
        "figma_to_fgui.fairygui_editor_verify.discover_fairygui_editor",
        lambda: executable,
    )
    monkeypatch.setattr("figma_to_fgui.fairygui_editor_verify._send_command", send_command)
    monkeypatch.setattr(
        "figma_to_fgui.fairygui_editor_verify.subprocess.Popen",
        lambda _args: FinishedEditor(),
    )
    monkeypatch.setattr("figma_to_fgui.fairygui_editor_verify.time.sleep", lambda _seconds: None)
    monkeypatch.setenv("FAIRYGUI_EDITOR_RUN_ROOT", str(tmp_path / "runs"))
    target = HifiTargetRef(
        project_id="a" * 32,
        project_fingerprint="b" * 64,
        package_id="tower123",
        package_name="Tower",
        directory="Panel",
        component_id="panel123",
        component_name="Panel_Tower_Main",
        component_relative_path="assets/Tower/Panel/Panel_Tower_Main.xml",
    )
    return verify_in_fairygui_editor(
        data_dir=tmp_path / "data",
        session_id="c" * 32,
        candidate_sha256="d" * 64,
        artifact=artifact,
        target=target,
        reference=reference_path,
        expected_width=20,
        expected_height=10,
        compare_mask=mask,
    )


def test_scoped_editor_gate_allows_legacy_regions_and_antialiasing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    reference = Image.new("RGB", (20, 10))
    rendered = Image.new("RGB", (20, 10))
    for y in range(10):
        for x in range(20):
            base = (x * 12, y * 24, (x + y) * 8)
            reference.putpixel((x, y), base)
            if x < 10:
                rendered.putpixel((x, y), (base[0] + 1, base[1], base[2]))
            else:
                # Kept legacy content: completely different pixels outside
                # the PSD-owned comparison scope.
                rendered.putpixel((x, y), (255 - base[0], 255 - base[1], 255 - base[2]))
    mask = Image.new("L", (20, 10), 0)
    mask.paste(255, (0, 0, 10, 10))

    verification = _run_scoped_verification(monkeypatch, tmp_path, rendered, reference, mask)

    assert verification.full_frame is True
    assert verification.approvable is True
    assert verification.scoped_mean_difference is not None
    assert verification.scoped_mean_difference <= 0.01
    assert verification.scoped_coverage is not None
    assert verification.scoped_coverage > 0.4
    assert verification.mean_pixel_difference > 0.1


def test_scoped_editor_gate_blocks_a_wrong_skin_inside_psd_regions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    reference = Image.new("RGB", (20, 10))
    rendered = Image.new("RGB", (20, 10))
    for y in range(10):
        for x in range(20):
            base = (x * 12, y * 24, (x + y) * 8)
            reference.putpixel((x, y), base)
            if x < 10:
                # A completely wrong skin painted across the PSD-owned
                # region: same luminance profile, different colors.
                rendered.putpixel((x, y), (250 - base[2], 10 + base[1] // 4, 20 + base[0] // 4))
            else:
                rendered.putpixel((x, y), base)
    mask = Image.new("L", (20, 10), 0)
    mask.paste(255, (0, 0, 10, 10))

    verification = _run_scoped_verification(monkeypatch, tmp_path, rendered, reference, mask)

    assert verification.full_frame is True
    assert verification.approvable is False
    assert verification.scoped_mean_difference is not None
    assert verification.scoped_mean_difference > 0.2
    assert any("范围化" in warning for warning in verification.warnings)


def test_editor_mismatch_regions_localises_and_attributes(tmp_path: Path) -> None:
    from figma_to_fgui.hifi_replacement_models import (
        HifiMappingDraft,
        HifiMappingEvidence,
        HifiMappingItem,
    )

    size = (120, 120)
    reference = tmp_path / "reference.png"
    screenshot = tmp_path / "screenshot.png"
    Image.new("RGB", size, (255, 255, 255)).save(reference)
    rendered = Image.new("RGB", size, (255, 255, 255))
    for x in range(20, 60):
        for y in range(20, 60):
            rendered.putpixel((x, y), (255, 0, 0))
    rendered.save(screenshot)

    evidence = HifiMappingEvidence(
        version=1, name_score=0, position_score=0, size_score=0,
        type_score=1, parent_score=0, order_score=0,
    )
    mapping = HifiMappingDraft(
        version=1, policy_revision=28, mapping_revision=1,
        old_canvas_size=(120.0, 120.0), source_canvas_size=(120.0, 120.0),
        items=(
            HifiMappingItem(
                version=1, item_id="old:card", old_object_id="card",
                old_name="card", old_object_type="image",
                figma_node_id="psd-card", figma_name="card",
                status="matched", score=1.0, evidence=evidence,
                action="accept", figma_bounds=(0.1, 0.1, 0.4, 0.4),
                old_bounds=(0.1, 0.1, 0.4, 0.4),
            ),
        ),
        unresolved_count=0,
    )

    regions = editor_mismatch_regions(
        screenshot, reference, Image.new("L", size, 255),
        120, 120, mapping, (0, 0, 120, 120),
    )

    assert len(regions) == 1
    region = regions[0]
    # The 40px block grid merges the four touched blocks around the red
    # square into one connected region.
    assert (region.x, region.y, region.width, region.height) == (0, 0, 80, 80)
    assert region.block_count == 4
    assert region.severity == pytest.approx(0.1667, abs=1e-3)
    assert [item.item_id for item in region.items] == ["old:card"]
    assert region.items[0].action == "accept"
    assert region.items[0].old_name == "card"

    # Masked-out differences never become regions: the scoped mask already
    # excludes those pixels from the comparison contract.
    assert editor_mismatch_regions(
        screenshot, reference, Image.new("L", size, 0),
        120, 120, mapping, (0, 0, 120, 120),
    ) == ()

    # Alignment problems stay fail-open instead of guessing regions.
    assert editor_mismatch_regions(
        screenshot, reference, None, 100, 100, mapping, (0, 0, 100, 100),
    ) == ()


def test_editor_mismatch_regions_attributes_kept_legacy_paint(tmp_path: Path) -> None:
    from figma_to_fgui.hifi_replacement_models import (
        HifiMappingDraft,
        HifiMappingEvidence,
        HifiMappingItem,
    )

    size = (80, 80)
    reference = tmp_path / "reference.png"
    screenshot = tmp_path / "screenshot.png"
    Image.new("RGB", size, (0, 0, 0)).save(reference)
    Image.new("RGB", size, (255, 255, 255)).save(screenshot)

    evidence = HifiMappingEvidence(
        version=1, name_score=0, position_score=0, size_score=0,
        type_score=1, parent_score=0, order_score=0,
    )
    mapping = HifiMappingDraft(
        version=1, policy_revision=28, mapping_revision=1,
        old_canvas_size=(80.0, 80.0), source_canvas_size=(80.0, 80.0),
        items=(
            HifiMappingItem(
                version=1, item_id="old:legacy", old_object_id="legacy",
                old_name="Legacy", old_object_type="image",
                status="fgui_only", score=0.0, evidence=evidence,
                action="keep_old", old_bounds=(0.0, 0.0, 1.0, 1.0),
                default_visible=True,
            ),
        ),
        unresolved_count=0,
    )

    regions = editor_mismatch_regions(
        screenshot, reference, Image.new("L", size, 255),
        80, 80, mapping, (0, 0, 80, 80),
    )

    assert len(regions) >= 1
    assert regions[0].items[0].item_id == "old:legacy"
    assert regions[0].items[0].action == "keep_old"
