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

## Evidence constraint and root handoff

No FairyGUI application was opened or automated by this task. The five supplied PNGs were not modified.
Header inspection found TC-01 is 1440×1080 and TC-05 is 1440×1042; strict closure therefore correctly
rejects them. Root must render the current cards and capture/re-capture TC-01, TC-05, and AC-01 at exact
1440×1000 before the final strict command can publish the two final acceptance artifacts.

## Commands for root

Render cards without publishing a final pack:

```powershell
python scripts/run_new_project_writer_acceptance.py --workspace . --output .acceptance-work/results-pending-task3.json --cards .acceptance-work/cards --screenshots-pending
```

Capture/re-capture only `tc-01.png`, `tc-05.png`, and `ac-01.png` from those local cards at 1440×1000.
Then run the strict finalizer (it validates all six PNG signatures, dimensions, and hashes before writing):

```powershell
python scripts/run_new_project_writer_acceptance.py --workspace . --output docs/validation/2026-08-20-new-project-writer-test-results.json --cards .acceptance-work/cards --report docs/validation/2026-08-20-new-project-writer-test-acceptance.md
```

## Verification pending final screenshots

```text
focused acceptance: 30 passed
ruff check .: passed
mypy src: Success: no issues found in 56 source files
git diff --check: clean
```

The full suite currently has four repeatable failures, all in the untouched
`tests/integration/test_ai_semantic_package.py::test_ai_semantic_package_scenarios` parameter set. In
each case its independent `rules_baseline` package workflow ends at the sanitized
`package_failed` stage; the task diff changes only the acceptance runner, acceptance tests, fresh
transcript, and project memory. No unrelated package-flow fix was made. Final JSON/Markdown artifact
generation is intentionally deferred until the strict PNG closure can succeed; no final result or report
has been fabricated.

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

**Immediate Next Fixes**

- Re-capture TC-01, TC-05, and AC-01 from the current local cards at the fixed viewport, then run the
  strict finalizer command in this report.

**Larger Bets**

- Add a dedicated preflight CLI mode that prints each PNG's measured dimensions and missing/invalid
  status without rerunning the five Writer cases.
