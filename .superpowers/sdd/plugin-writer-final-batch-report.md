# Plugin Writer final batch report

## Delivered

- Added a public plugin new-project delivery E2E using the real selection upload manifest/resource,
  commit, Writer candidate, review, adjustment, regenerate, approve, preview, and download endpoints.
- Proved approval gating, current-generation warning acknowledgement, permanent v1 invalidation,
  whole-candidate v2 approval, two identical downloads, and production archive validation.
- Recorded every E2E public path and JSON field name and asserted that no template, pairing,
  `/v1/agents/`, existing-project, or Project Binding call/field was used.
- Expanded the maintained no-special-case scan across backend, Figma plugin source, Writer source, and
  default rules. Backend and Writer-panel injection tests prove detection. The existing generic mapping
  catalog remains the only exact allowlist.
- Hardened plugin packaging acceptance: approved Writer labels/routes and Writer-default startup are
  checked, retired template/four-step startup requirements are absent from Writer startup source, and
  every ZIP member hash must equal its validated build input.
- Updated the packaging README with the actual review/adjustment/unified-approval/re-download flow.

## Automated verification

```text
plugin package/build checks: 5 passed
Python full: 1146 passed, 4 skipped
Ruff: passed
strict mypy: Success, 58 source files
Figma plugin Vitest: 171 passed
Figma plugin TypeScript: passed
Figma plugin production build: passed (scripts/build.mjs)
Web Console Vitest: 30 passed
Web Console TypeScript: passed
Web Console production build: passed
git diff --check: passed before final documentation
```

The historical handoff wording now truthfully uses the exact required phrase
`capture/re-capture **all six** PNGs`; its evidence claim is unchanged.

## Real GUI acceptance

The fresh GUI gate is blocked and is not reported as passed. The exact machine record is
`docs/validation/2026-08-21-plugin-writer-final-gui-attempt.json`; the human acceptance report is
`docs/validation/2026-08-21-plugin-writer-final-acceptance.md`.

- Figma desktop app version path `app-126.7.10` launched with exactly one `figma2fgui - Figma`
  target window. Accessibility was readable. Native capture failed with `0x80004002`, and a
  state-derived action failed with `coordinate input geometry is unavailable`.
- The current Figma selection could not be proven neutral. No selection was uploaded and no real plugin
  state/download was claimed.
- FairyGUI Editor 6.1.4 was found and launched with exactly one `FairyGUI 编辑器` window. Native
  capture failed with `0x80004002`; accessibility exposed only the title bar; `Ctrl+O` produced no
  targetable dialog or project window.
- A fresh neutral public-CLI artifact was generated and validated at 1426 bytes with SHA-256
  `bf62cd2789a7d0a44336e28a4c257d4fe91bee34c7673738bdf3f0662217c4ca`, but it was not opened in
  the Editor. No fresh save/close/reopen/modal/hash-after-save claim is made.
- No screenshots were fabricated. The older 2026-08-20 Editor transcript remains historical evidence,
  not evidence from this run.

## Self-review

- The E2E adjustment is compiler-authored and exercised exclusively through the public HTTP contract;
  it contains no direct database mutation or synthetic review injection.
- No Web Console Writer product flow, Project Binding, existing-project startup field, component ID
  guessing, village/rank branch, or broader Writer dialect was added.
- Package bytes are still regenerated only by the repository build scripts; checked-in `dist` remains
  byte-equal to a fresh build.
- The final report separates automated proof, historical GUI evidence, fresh observed GUI facts, and
  unavailable claims.

## Whole-branch review fix wave — 2026-08-21

- Replaced message-text strategy inference with a centralized diagnostic-code policy that emits typed
  `issue_kind`, closed strategies, UIR identity, and the public source Figma node ID. Unknown diagnostics
  are non-actionable. `include-contained-definition` remains unavailable/fail-closed because Selection v1
  has no validated contained definition tree.
- Persisted typed adjustments now enter the committed-selection workflow before normalization. The public
  E2E uses a real compiler-authored raster-fallback issue—no SQLite mutation—and proves that
  `preserve-editable` changes the archive SHA-256, removes the raster warning, creates generation 2, and
  invalidates generation 1.
- Successful normalize/Plan warnings now reach review and exact warning acknowledgement. Source previews
  are no longer joined by array position; absent stable resource identity yields no source URL.
- New-project JSON bodies use a 16 KiB bounded stream before JSON allocation. Start/regenerate return
  observable in-progress views, work runs asynchronously, and the plugin polls both operations. Generation
  is server-authoritative. Retrying failed/rejected requests creates a fresh build/generation.
- Review evidence now explicitly covers crop/transparency, hierarchy/geometry/text, naming conflicts,
  resource closure and integrity. Preview fetch failure is visible and blocks approval.
- Writer tabs now have tab/tabpanel linkage, roving focus and arrow navigation. Selection drift during work
  aborts/clears; selection changes caused while reviewing do not erase the active review. Added a structure
  blueprint label, collapsed generation settings, and scoped horizontal overflow to Writer.
- Corrected Writer README/deployment wording, the historical all-six-PNG handoff wording, and final review
  package links. The GUI status remains `BLOCKED_BY_LOCAL_GUI_CAPABILITY`; no evidence was fabricated.

Final verification after this wave:

```text
Python full: 1146 passed, 4 skipped
Ruff: passed
strict mypy: Success, 58 source files
Figma plugin Vitest: 171 passed
Figma plugin TypeScript: passed
Figma plugin production build/package: 5 passed
Web Console Vitest: 30 passed
Web Console TypeScript: passed
Web Console production build: passed
```
