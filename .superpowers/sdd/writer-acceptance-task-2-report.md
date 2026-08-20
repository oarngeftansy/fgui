# Writer Acceptance Task 2 Report

## Delivered

- Added six deterministic, local HTML evidence cards through `render_evidence_cards`.
- Each card is sized for a `1440x1000` Playwright capture and shows the case ID, status, purpose,
  prerequisites, steps, expected outcome, actual outcome, and decisive evidence.
- All dynamic card fields use `html.escape`; the renderer has no external assets and rejects private
  absolute paths.
- Added strict `finalize_screenshot_closure`: canonical one-PNG-per-case references, PNG/IHDR
  validation, exact `1440x1000` dimensions, SHA-256 recording, and mismatch failure.
- Added explicit `--screenshots-pending` development mode. Normal result writing and the CLI fail
  closed until all six screenshots are available; pending output contains no screenshot hashes.
- Added the tracked evidence directory placeholder.

## TDD record

1. Renderer/closure imports first failed during test collection because the interfaces did not exist.
2. The first implementation made the new renderer and closure tests pass (`10 passed`).
3. Strict result writing tests then failed because pending mode and final screenshot closure were not
   connected; after wiring them, the focused suite passed (`11 passed`).

## Verification

```text
python -m pytest tests/acceptance/test_new_project_writer_acceptance.py -q --basetemp .pt-task2-final
11 passed

python -m ruff check scripts/run_new_project_writer_acceptance.py tests/acceptance/test_new_project_writer_acceptance.py
All checks passed!

python -m mypy src
Success: no issues found in 56 source files

git diff --check
clean
```

## Scope and concern

No screenshots were created or inspected. Task 3 must use the explicit pending mode while generating
cards, then invoke the default strict closure after Playwright has created all six PNGs.

## Privacy review follow-up

- Replaced the card-only path-prefix check with a shared recursive public-text validator.
- The validator fail-closes on embedded POSIX absolute paths, Windows drive-rooted and rooted-backslash
  paths, plus UNC paths before either HTML or canonical JSON can be written.
- Parametrized hostile-field tests cover purpose, prerequisites, steps, expected, and actual. They prove
  no card HTML and no result file is written for the private marker; safe result bytes also exclude it.
- Re-verification: focused acceptance suite `16 passed`; Ruff, strict mypy (56 files), and diff-check
  clean.

## Privacy re-review follow-up

- Replaced the slash negative-lookbehind regex with a token-aware scanner. It detects POSIX root,
  normalized dot segments, repeated separators, `file:` URIs, Windows roots, drive paths, and UNC paths.
- The only URI exemptions are constrained public `ui://`, `http://`, and `https://` forms; common
  public codes such as `image/png` remain valid. Literal closing HTML tags remain safe because card
  content is escaped.
- Added hostile paths for `/./`, `/../`, `//`, `file:///`, and embedded dot-segment paths across all
  public evidence fields. Both HTML and canonical-result boundaries fail closed without producing output.
- Re-verification: focused acceptance suite `22 passed`; Ruff, strict mypy (56 files), and diff-check
  clean.
