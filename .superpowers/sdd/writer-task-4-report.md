# Writer Task 4 — Resource Payload Validation

## Delivered

- Added `fgui_asset_payloads.py` with the `validate_asset_payloads` input gate,
  `ValidatedAssetPayload`, public deterministic diagnostics, and
  `NewProjectInputError`.
- Requires exact ResourcePlan/payload key sets; validates the streamed SHA-256,
  Pillow-detected raster format/MIME/dimensions, declared export facts, and
  nine-slice bounds.
- Rejects invalid or truncated rasters, decompression bombs, unsupported formats,
  and SVG in Writer v1. Diagnostics and exception text do not contain asset bytes.
- Added a real one-pixel PNG fixture and focused public-boundary tests.

## Verification

- `python -m pytest -q tests/unit/test_fgui_asset_payloads.py --basetemp C:\Users\momoca\Documents\figma转fgui\pytest-task4-final`
- `python -m ruff check src/figma_to_fgui/fgui_asset_payloads.py tests/unit/test_fgui_asset_payloads.py`
- `python -m mypy src/figma_to_fgui/fgui_asset_payloads.py`
- `python -m pytest -q --basetemp C:\Users\momoca\Documents\figma转fgui\pytest-task4-full`
- `git diff --check`

All commands completed with exit code 0.

## Self-review

- Scope is limited to the asset-payload input gate; it does not add naming,
  manifest compilation, or serialization behavior.
- The validator returns resources by sorted key and sorts all diagnostics using
  public fields, so mapping order and payload contents cannot affect reporting.
