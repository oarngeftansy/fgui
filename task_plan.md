# Live Figma Selection Plugin

## Goal

Replace fixture Figma input with a paired plugin that works in desktop and browser Figma and continues through the existing ZIP, review, approval, and Windows Agent workflow.

## Phases

- [x] Confirm desktop/browser, internal HTTPS, pairing-code, and direct-selection-upload scope
- [x] Write, officially validate, self-review, and obtain approval for the specification
- [x] Write and self-review the eight-task implementation plan
- [ ] Execute Tasks 1-8 with TDD and independent review
- [ ] Final branch review, product audit, verification, and handoff

## Current

Executing Task 5: current-selection export, assets, and transactional upload.

## Decisions

- Plugin directly exports only the explicit current selection; no Figma REST token.
- Company-internal HTTPS server; six-digit one-time pairing code.
- Company-origin hosted plugin iframe avoids wildcard CORS required by a null-origin bundled UI.
- Sensitive main/UI messages use exact origin, plugin ID, and Figma target.
- Existing ZIP, conversion, review, Agent, backup, rollback, and stale-write boundaries remain.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Combined spec/plan correction patch missed an exact plan sentence | 1 | Split the correction into stable spec and plan patches |

## Task 3 Review Remediation

- [x] Add RED regressions for opaque node IDs, resource materialization, production route registration, and owned selection-job access.
- [x] Replace selection adapter IDs and resource references with deterministic opaque values; materialize assets through the existing generator.
- [x] Register fixture routes only in explicit development/test mode and require `selection:read-own-status` ownership for live jobs.
- [x] Replace fixture mutation integration proof with an isolated fixture copy; verify focused, golden, suite, Ruff, mypy, and diff; update report and commit.

- Verification note: Ruff found one import-order failure in the new integration test; sorted `shutil` before `sqlite3` before rerunning lint.

## Task 3 Second Review Remediation

- [x] Add RED coverage for package resource registration/reference resolution and streaming conversion limits.
- [x] Generate deterministic collision-free package image resources, preserve package XML structure, and reference the registered resource IDs.
- [x] Introduce internal selection asset metadata/context, chunked copying, and conversion/bundle byte limits without raw asset bytes in raw documents.
- [x] Verify, update report, and commit the second review remediation.

## Task 3 Final Review Remediation

- [x] Add RED probes for same-name resource collisions, direct public composition, and pre-join package validation.
- [x] Preserve unrelated same-name resources, restore composition safely, and use full collision-safe asset identities.
- [x] Verify, update report, and commit the final review remediation.
