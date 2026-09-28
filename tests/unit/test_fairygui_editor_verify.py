from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from figma_to_fgui.fairygui_editor_verify import (
    FairyGuiEditorVerificationError,
    _image_evidence,
    discover_fairygui_editor,
)


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
