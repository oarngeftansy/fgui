# Writer Acceptance Task 3 Report

## Delivered

- Added the trusted, tracked fresh GUI transcript at
  `docs/validation/2026-08-20-fgui-6.1.4-new-project-editor-transcript.json`.
  AC-01 now consumes it and is no longer marked pending.
- The transcript and AC-01 card contain only root-observed facts: FairyGUI Editor 6.1.4, returned title
  `GenericWriterFixture`, two save rounds, the delayed-close observation, zero final windows, no observed
  modal, unsupported state screenshot API (`0x80004002`), and 4/4 identical pre/post hashes.
- Added strict Markdown-report generation. It accepts only screenshot-closed results, repeats all six
  machine fields, has one relative local PNG link per section, and writes every PNG SHA-256 from the
  result. `--report` rejects `--screenshots-pending`.
- Added regression checks for transcript scope, report/result cross-matching, six resolved relative
  PNG links, PNG hashes, private/external URL absence, and strict CLI generation.
- Compacted the shared evidence-card layout, combined Actual with decisive evidence without dropping
  content, and added `data-layout-contract="1440x1000-no-scroll"`. Headless Edge measured all six cards
  at `scrollHeight == 1000` in a 1440×1000 viewport.

## TDD record

1. The initial focused RED run failed at collection because `write_acceptance_report` did not exist.
2. After implementing the fresh transcript and report flow, the focused acceptance suite passed
   (`28 passed`).
3. The layout contract test then failed because the required fixed-height/no-scroll declaration was
   absent. The compact layout and marker made that focused test pass.

## Evidence closure completed by root

The implementation task itself did not open FairyGUI or alter the then-existing evidence. Root subsequently
rendered the current cards, captured/re-captured all six PNGs at exactly 1440×1000, visually inspected every
image, and ran the strict Edge pixel-correspondence finalizer. The final JSON, Markdown, and refreshed PNGs
were published in commit `d26b57d`.

## Commands for root

Render cards without publishing a final pack:

```powershell
python scripts/run_new_project_writer_acceptance.py --workspace . --output .acceptance-work/results-pending-task3.json --cards .acceptance-work/cards --screenshots-pending
```

Capture/re-capture **all six** files — `tc-01.png`, `tc-02.png`, `ac-01.png`, `tc-03.png`, `tc-04.png`, and
`tc-05.png` — from those newly rendered local cards at 1440×1000. Then run this exact strict finalizer; it
uses the supplied Node/Playwright/Edge stack to recapture the same six current cards and compares fully
decoded RGBA pixels before writing either final artifact:

```powershell
python scripts/run_new_project_writer_acceptance.py --workspace . --output docs/validation/2026-08-20-new-project-writer-test-results.json --cards .acceptance-work/cards --report docs/validation/2026-08-20-new-project-writer-test-acceptance.md --node "C:\Users\momoca\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" --edge "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
```

## Final verification

```text
focused acceptance: 39 passed
ruff check .: passed
mypy src: Success: no issues found in 56 source files
git diff --check: clean
```

Root's final fresh full verification result is `1111 passed, 4 skipped`. The strict current-card capture
and finalization completed successfully; all six public cases are PASS and their PNG hashes close against
both the JSON and Markdown report.

## Deep User Audit: evidence capture and finalization

**Real Job**

Produce an independently reviewable acceptance pack without accidentally treating a browser card as a
FairyGUI screenshot or publishing a partial report.

**Top Pain Points**

1. A recapture can look visually correct yet fail only after the final command because browser capture
   dimensions drifted from 1440×1000.
   改进：use the rendered card's `1440x1000-no-scroll` contract and check `scrollHeight == 1000` before
   capturing; then use a viewport screenshot, not a taller full-page image.
   验收：the strict finalizer accepts all six PNGs without a dimension error.

2. The finalizer intentionally does not publish anything if one screenshot is missing or invalid, but a
   reviewer needs an immediate diagnosis rather than a partially written pack.
   改进：keep the two-command handoff: pending render first, strict JSON/report finalizer second.
   验收：the first command writes cards only; the second writes both final artifacts only after all six
   hashes close.

**Completed Final Action**

- Root re-captured all six screenshots from the current local cards at the fixed viewport and ran the
  strict finalizer successfully; no evidence-capture action remains.

**Larger Bets**

- Add a dedicated preflight CLI mode that prints each PNG's measured dimensions and missing/invalid
  status without rerunning the five Writer cases.

## Review follow-up

- Screenshot closure now requires Pillow to `verify()` and fully `load()` each PNG after checking its
  format; a 1440×1000 header-only/truncated PNG is rejected rather than hashed as valid.
- An invalid fresh GUI transcript now produces only `freshTranscriptValid=false` and AC-01 FAIL. It
  cannot publish positive version, title, save-round, modal, screenshot-API, or hash-parity evidence.
- Report tests parse Markdown PNG links from the report's actual location, resolve them under the local
  validation evidence directory, and require the referenced image to exist.
- The card fit regression launches headless Microsoft Edge through Playwright and measures every card's
  real DOM. All six have scroll width/height no greater than 1440×1000, and every decisive-evidence list
  row has a bounding box entirely inside that viewport. The card no longer uses overflow clipping.

```text
focused acceptance: 33 passed
ruff acceptance files: passed
mypy src: Success: no issues found in 56 source files
git diff --check: clean
```

## Final capture correspondence follow-up

- Strict finalization now launches the explicitly supplied Node/Playwright/Edge stack to capture each
  freshly rendered current card at 1440×1000, checks the DOM layout, then compares decoded RGBA pixels
  against the proposed PNG. A stale previous card or arbitrary solid-color PNG fails closed.
- Machine results now record the HEAD commit under test, a timezone-bearing execution timestamp, and
  FairyGUI version 6.1.4. The commit means the runner/source repository HEAD at execution time.
- TC-01 records the published ZIP filename and member list. TC-04 records the numeric payload limit,
  sparse declared byte size, and the observed pre-probe rejection boundary.
- AC-01 links the durable local transcript in the report and lists its four exact declared hashes.

## Final closure fix wave

- Every non-pending screenshot finalization or report/result write now requires a current capture root.
  The CLI creates that root itself by rendering all six current cards and capturing them through the
  explicitly supplied Node/Playwright/Edge stack.
- Each proposed evidence PNG is read exactly once. That immutable byte snapshot supplies its SHA-256,
  dimensions, complete PNG decode, and RGBA pixels before comparison with the current card capture. A
  staged-mutation regression proves the evidence file is not reopened after the snapshot.
- TC-04 now instruments the in-process production CLI's stable-file-read boundary for the exact oversized
  sparse asset. It records `oversizedAssetReadCalled=false`, derives `rejectedBeforeFullRead=true` only from
  that observation, and fails when a regression forces a read-boundary call.
- At the end of this implementation wave, screenshots and final machine JSON were deliberately left
  untouched. Root later recaptured all six cards and published the closed pack in `d26b57d`.

```text
focused acceptance: 39 passed in 34.54s
ruff check .: All checks passed!
mypy src: Success: no issues found in 56 source files
git diff --check: clean
```
