# Plugin Writer frontend batch report

## Outcome

Implemented the strict Writer client and the approved 360×680 Figma-plugin flow while keeping
`ProjectWorkflowPage` in legacy mode by default. The plugin entry alone opts into Writer mode.
Existing-project update remains behind the plugin overflow menu; no Project Binding, existing-resource,
legacy-job, village/example-specific, or per-file approval behavior was added to Writer.

## RED → GREEN

- Client RED: `ProjectWorkflowClient.createNewProjectCandidate is not a function` in the first strict
  upload/start contract test. GREEN grew vertically through strict candidate/review parsing, adjustment,
  regeneration, approval/rejection, authenticated previews, deadlines/cancellation, and verified download.
- Backend-contract RED: `DesignerCheck` had no `allowed_strategies`. GREEN adds the closed server projection
  and makes the API validate the submitted strategy against that projection.
- UI RED: Vite could not resolve `NewProjectWriterPanel`. GREEN is the approved Writer state machine and
  review UI, exercised through Figma bridge messages and public client methods.
- Build RED: worktree esbuild resolution failed under the restricted dependency tree, then the package gate
  exposed unavailable `Get-FileHash` module autoload. GREEN uses repo-root absolute entries and the .NET
  SHA-256 API; deterministic dist/package parity now passes.

## Files and boundaries

- Strict client: `apps/figma-plugin/src/project-client.ts` and tests.
- Plugin bridge: 360×680 UI, active-attempt messages, locate-node action in `contracts.ts` / `code.ts`.
- Writer UI: `NewProjectWriterPanel.tsx`, `NewProjectReviewPanel.tsx`, tests and styles.
- Legacy isolation: `ExistingProjectUpdatePanel.tsx`, `ProjectWorkflowPage.tsx`; default remains `legacy`,
  `plugin-entry.tsx` passes `defaultMode="writer"`.
- Checked-in runtime: rebuilt `apps/figma-plugin/dist/code.js` and `dist/ui.html`.
- Minimal blocking backend mismatch: review checks now publish `allowed_strategies`; adjustment requests no
  longer require the private/redundant selection fingerprint. Owner, candidate ID, generation, issue/node,
  artifact, and immutable selection association remain server-validated.
- Build reliability: absolute esbuild entries and module-independent package SHA-256.

## Exact verification evidence

- Plugin full Vitest:
  `node node_modules/vitest/vitest.mjs run` → **9 files, 171 passed, 0 failed**.
- Plugin TypeScript:
  `node node_modules/typescript/bin/tsc --noEmit` → **exit 0**.
- Plugin production rebuild + package parity:
  `node scripts/build.mjs` with the public test deployment values, then
  `node --test scripts/build.check.mjs` → **5 passed, 0 failed**.
- Web Console full Vitest:
  `node node_modules/vitest/vitest.mjs run` → **3 files, 29 passed, 0 failed**.
- Web Console typecheck/build:
  `tsc --noEmit`, `tsc -b`, `vite build` → **exit 0**, 16 modules transformed.
- Minimal backend contract/API suite:
  `pytest test_fgui_new_project_review.py test_figma_selection_api.py test_service_contracts.py test_figma_plugin_new_project_writer_api.py`
  → **29 passed, 0 failed**.
- Python quality:
  targeted `ruff check` → **all checks passed**;
  targeted `ruff format --check` → **6 files already formatted**;
  strict mypy on changed source boundaries → **0 issues in 3 source files**.
- `git diff --check` → **clean**.

## Requirement/self-review

- New request body is exactly `{version:1, project_name}`; Writer has no template/version selector or old
  project/resource/job fields.
- Candidate/review/check/package response records reject missing or extra fields, unsafe URLs/names,
  unknown strategies, inconsistent generations, and malformed evidence.
- One overall deadline covers upload/start/poll; abort reaches fetch/wait; stale bridge attempts are ignored;
  unmount aborts work.
- v1 becomes visibly and structurally invalid after regeneration; v2 resets warning acknowledgement.
- Approval is whole-candidate only. Download is impossible before approval and rechecks exact filename,
  Blob size, and SHA-256; ready state offers `再次下载`.
- Review uses authenticated Blob previews with explicit `source image`, `rendered`, or `structured summary`
  labels and never presents a structured summary as a render.
- CSS uses 16px sides/8px-derived spacing, readable contrast, internal bounded scrolling, no horizontal
  plugin overflow, focus-visible outlines, and reduced-motion handling.
- Default legacy tests remain green and explicitly prove Writer controls do not replace the Web Console flow.

## Deep-user pain audit

**Real job:** inspect a generated FairyGUI candidate, correct only safe issues, make one trustworthy approval,
and hand the verified ZIP to FairyGUI Editor.

Immediate fixes made during audit:

- Added authenticated preview Blob loading/object-URL cleanup; direct `<img src="/v1/...">` would omit the
  plugin token.
- Added top-level selection name/type to the blueprint summary, public failure diagnostics, and ready-state
  filename/size/SHA evidence.
- Disabled adjustment controls until the selected strategy is durably accepted.

Residual concerns:

- `定位到图层` can only succeed when the server check carries an ID addressable by Figma. A future contract
  should expose an explicit source Figma node ID and return a locate success/failure acknowledgement.
- Very large reviews use a bounded internal review scroller. A future expert view could add issue filtering
  and a persistent “unreviewed” counter without changing whole-candidate approval semantics.

## Memory

Updated `.claude/memory/wiki.md` with the completed frontend architecture/contracts and appended the new
preview/fingerprint/strategy/build lessons to `.claude/memory/learnings.md`. No new stable user preference was
added to `memory.md`.
