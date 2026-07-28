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

Executing Task 3: selection-backed conversion and production Job API.

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
