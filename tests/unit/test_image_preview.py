from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from figma_to_fgui.image_preview import encode_webp_preview


def small_png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), "red").save(output, "PNG")
    return output.getvalue()


@pytest.mark.parametrize("pixel_limit", [3, 1])
def test_preview_safely_rejects_pillow_bomb_warning_and_error(
    monkeypatch: pytest.MonkeyPatch, pixel_limit: int
) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", pixel_limit)

    assert encode_webp_preview(small_png()) is None
