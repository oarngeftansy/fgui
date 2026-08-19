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
- Added a Pillow-generated, real one-pixel PNG fixture and focused
  public-boundary tests.

## TDD evidence

### RED

The intended RED command was:

```text
python -m pytest -q tests/unit/test_fgui_asset_payloads.py
```

It was run before the production module existed. The expected failure was test
collection with `ModuleNotFoundError` for `figma_to_fgui.fgui_asset_payloads`.
The actual recorded failure occurred earlier: the shell could not start
`C:\Users\momoca\AppData\Local\Microsoft\WindowsApps\python.exe`
(`ResourceUnavailable`, access denied), so pytest never collected the test and
there is no module-not-found output to report. Reproducing that RED state now
would require checking out the parent commit and is intentionally not done: it
would disturb the completed worktree and would not add new evidence.

### First real venv run and correction

After locating the repository venv at
`C:\Users\momoca\Documents\figma转fgui\source\.venv\Scripts\python.exe`,
the first focused run was **8 passed, 4 failed in 0.31s**; the corresponding
full run was **846 passed, 3 skipped, 3 warnings, 4 failed in 18.42s**. The
failure was real: the initially hand-decoded 70-byte PNG could be identified by
Pillow but its IDAT stream could not be fully loaded, so successful MIME,
dimension, and nine-slice cases correctly stopped at `invalid_image`.

The fixture was regenerated with Pillow, the truncated-image test was made to
remove image data rather than only the optional terminal byte, and Ruff's import
ordering correction was applied. This is a fixture/test correction, not a
relaxation of the input gate.

## Final verification

Commands used the repository venv explicitly:

```text
C:\Users\momoca\Documents\figma转fgui\source\.venv\Scripts\python.exe -m pytest -q tests/unit/test_fgui_asset_payloads.py --basetemp C:\Users\momoca\Documents\figma转fgui\pytest-task4-focused-final
# 12 passed in 0.22s

C:\Users\momoca\Documents\figma转fgui\source\.venv\Scripts\python.exe -m ruff check src/figma_to_fgui/fgui_asset_payloads.py tests/unit/test_fgui_asset_payloads.py
# All checks passed!

C:\Users\momoca\Documents\figma转fgui\source\.venv\Scripts\python.exe -m mypy src/figma_to_fgui/fgui_asset_payloads.py
# Success: no issues found in 1 source file

C:\Users\momoca\Documents\figma转fgui\source\.venv\Scripts\python.exe -m pytest -q --basetemp C:\Users\momoca\Documents\figma转fgui\pytest-task4-full-final
# 850 passed, 3 skipped, 3 warnings in 18.79s

git diff --check
# exit 0
```

The three full-suite warnings are Pydantic serializer warnings emitted from
existing `test_fgui_plan_validate.py` cases; no Task 4 test or source file is
named in them.

## Files changed

Implementation deliverables:

- `src/figma_to_fgui/fgui_asset_payloads.py`
- `tests/unit/test_fgui_asset_payloads.py`
- `tests/fixtures/fgui-new-project/resources/one-pixel.png`

Required task bookkeeping:

- `.claude/memory/wiki.md`
- `.claude/memory/learnings.md`
- `.superpowers/sdd/writer-task-4-report.md`

## Self-review and concerns

- Scope is limited to the asset-payload input gate; it does not add naming,
  manifest compilation, or serialization behavior.
- The validator returns resources by sorted key and sorts all diagnostics using
  public fields, so mapping order and payload contents cannot affect reporting.
- Pillow's image limits, truncated-image setting, and warning filter are
  process-global. The validator now performs all Pillow decoding and policy
  setup in a disposable child process, so it does not read, lock, set, restore,
  or otherwise overwrite any caller-process Pillow state. The parent sends raw
  bytes only through child stdin; it writes no payload to disk, discards child
  stderr, applies a two-second timeout, terminates a timed-out child, and
  fail-closes malformed/non-zero/non-JSON child responses as `invalid_image`.
- Raw bytes remain necessary on `ValidatedAssetPayload` for a later serializer,
  but are omitted from its repr and never included in diagnostics or exception
  text.

## Review follow-up — isolated Pillow probe

### TDD evidence

The review required a process boundary rather than the former in-process
lock-and-restore approach. There is no saved pre-patch RED output for the three
new state-preservation tests, so this report does not claim one. Reconstructing
the obsolete implementation solely to manufacture a RED result was not done.

The added public-behavior coverage verifies that:

- `Image.MAX_IMAGE_PIXELS = None` in the caller does not permit a 30,000 ×
  30,000 payload and remains `None` after validation.
- `ImageFile.LOAD_TRUNCATED_IMAGES = True` in the caller does not permit a
  truncated payload and remains `True` after validation.
- A concurrent external update to both caller Pillow globals, synchronized
  while the child is being launched, remains intact after successful validation.
  The test restores all globals in `finally`.

The focused GREEN command was:

```text
C:\Users\momoca\Documents\figma转fgui\source\.venv\Scripts\python.exe -m pytest -q tests/unit/test_fgui_asset_payloads.py --basetemp C:\Users\momoca\Documents\figma转fgui\pytest-task4-subprocess-focused-final
# 15 passed in 3.03s
```

The same revision passed:

```text
C:\Users\momoca\Documents\figma转fgui\source\.venv\Scripts\python.exe -m ruff check src/figma_to_fgui/fgui_asset_payloads.py tests/unit/test_fgui_asset_payloads.py
# All checks passed!

C:\Users\momoca\Documents\figma转fgui\source\.venv\Scripts\python.exe -m mypy src/figma_to_fgui/fgui_asset_payloads.py
# Success: no issues found in 1 source file

C:\Users\momoca\Documents\figma转fgui\source\.venv\Scripts\python.exe -m pytest -q --basetemp C:\Users\momoca\Documents\figma转fgui\t4
# 853 passed, 3 skipped, 3 warnings in 23.82s
```

Two attempts with long `--basetemp` names failed only in three pre-existing AI
package integration scenarios; running that module with a short temporary path
passed `4 passed in 2.50s`, and the short-path full run passed. This follows the
known Windows path-length limitation recorded in project memory, rather than a
payload-validator failure.
