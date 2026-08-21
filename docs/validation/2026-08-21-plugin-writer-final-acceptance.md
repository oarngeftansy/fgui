# Plugin Writer final acceptance — 2026-08-21

## Outcome

The public delivery path and packaged plugin passed automated acceptance. Fresh real-app GUI
acceptance is **incomplete** because the local Computer Use capture/input boundary could not control
or capture the installed Figma and FairyGUI windows. No screenshot, plugin download, Editor save, or
modal observation is claimed for this run.

The machine-readable attempt record is
[`2026-08-21-plugin-writer-final-gui-attempt.json`](2026-08-21-plugin-writer-final-gui-attempt.json).

## Public delivery E2E

The tracked integration test uploads one neutral PNG through the public selection manifest/resource
endpoints and then exercises the Writer HTTP state machine:

1. download is blocked before approval;
2. image, component/interface, Package/resource, and unified-check reviews are inspected;
3. evidence kinds are limited to `source-image`, `rendered`, or `structured-summary` as applicable;
4. one compiler-authored, typed raster-fallback issue declares `preserve-editable`; the public adjustment
   changes the generated archive and removes that warning without database mutation;
5. regeneration permanently invalidates candidate v1 for review, approval, and download;
6. the exact current warning IDs for candidate v2 are acknowledged;
7. the whole v2 candidate is approved and downloaded twice;
8. both downloads have equal bytes, filename, size, and SHA-256, and the production archive validator
   returns no diagnostics.

The observed request log contains no template, pairing, `/v1/agents/`, existing-project, or Project
Binding route/field. The demand-side mapping catalog remains allowed only at
`rules/default/component-mapping-candidates.json`.

## Packaging closure

The checked-in plugin distribution matches a fresh build made only through `scripts/build.mjs`.
Packaging tests verify approved Writer labels, the selection/new-project/review/adjustment/regenerate/
approve/download route tokens, and `defaultMode="writer"`. They also compare the SHA-256 of every
delivery ZIP member against the verified build inputs (`INSTALL.md`, `code.js`, `manifest.json`, and
`ui.html`). The Writer startup source has no template selector, FairyGUI version selector, existing ZIP
requirement, or old four-step headings; update-existing remains an isolated overflow action.

## Fresh GUI attempt

### Figma desktop

- Installed Figma launched with exactly one returned target window, `figma2fgui - Figma`.
- Accessibility text was readable, but native capture failed with
  `SetIsBorderRequired failed: 0x80004002`.
- A state-derived Figma action failed with `coordinate input geometry is unavailable`.
- The currently focused document selection could not be proven to be the authorized neutral
  representative. It was therefore not uploaded.
- No Writer selection/running/review/decision/ready state and no download or repeat download was
  observed in the real plugin.

### FairyGUI Editor 6.1.4

- The installed 6.1.4 executable launched with exactly one `FairyGUI 编辑器` window.
- Native capture failed with the same `0x80004002`; accessibility exposed only the title bar.
- `Ctrl+O` did not produce a targetable open dialog or project window.
- A fresh neutral CLI artifact was prepared and validated (`1426` bytes,
  SHA-256 `bf62cd2789a7d0a44336e28a4c257d4fe91bee34c7673738bdf3f0662217c4ca`), but it was not
  opened in the Editor. No save/close/reopen/modal/hash-after-save claim is made.

The earlier tracked
[`2026-08-20-fgui-6.1.4-new-project-editor-transcript.json`](2026-08-20-fgui-6.1.4-new-project-editor-transcript.json)
remains bounded historical evidence. It is not presented as a fresh run for this batch.

## Regression result

- Python full suite: `1146 passed, 4 skipped`.
- The historical Task 3 handoff now uses the exact truthful phrase `capture/re-capture **all six** PNGs`;
  its evidence scope is unchanged.
- Ruff: passed.
- strict mypy: `58 source files`, no issues.
- Figma plugin: `171 passed`; TypeScript and build passed; packaging checks `5 passed`.
- Web Console: `30 passed`; TypeScript and production build passed.
- `git diff --check`: passed before report finalization.
