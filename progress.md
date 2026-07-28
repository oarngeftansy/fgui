# Progress

## 2026-07-27

- Created isolated branch and worktree: `codex/conversion-core-baseline`.
- Reviewed the implementation plan; Tasks 1-3 have no critical blocking gaps.
- Planning template read failed because the installed skill has no `templates/` directory; recorded and continued with minimal local files.

## Verification Log

## 2026-07-28

- Began the next sub-project after the local apply loop was pushed.
- User selected real project upload plus Web preview/approval before live Figma integration.
- User selected the three-column review layout, target-Package ZIP scope, whole-update approval, and React/Vite architecture.
- Revised the flow after user feedback: designers upload a FairyGUI project ZIP and technical snapshot/hash language is hidden by default.
- Confirmed ZIP safety, local Agent matching, designer-facing errors, tests, and acceptance criteria.
- Wrote and self-reviewed `docs/superpowers/specs/2026-07-28-zip-project-web-console-design.md`.
- User approved the written ZIP project and Web Console specification.
- Wrote and self-reviewed `docs/superpowers/plans/2026-07-28-zip-project-web-console.md` with eight TDD tasks.
- SDD Task 1 complete: safe ZIP extraction passed 20 focused tests and independent review after fixing pre-extraction NUL validation for file and directory headers.
- SDD Task 2 complete: uploaded-project indexing, WebP thumbnails, deterministic fingerprints, and content-addressed storage passed independent review after collision and concurrent-publication hardening.

- User approved the fixture-backed API Server and Windows Agent vertical slice.
- Wrote `docs/superpowers/specs/2026-07-28-local-apply-loop-design.md`.
- First combined patch failed because mojibake in the old planning file prevented exact context matching; no partial changes were applied.
- Design self-review found no placeholders, contradictory transitions, or unbounded filesystem operations.
- User approved the written specification.
- Wrote and self-reviewed `docs/superpowers/plans/2026-07-28-local-apply-loop.md` with six TDD tasks.
- Task 1 RED: service contract and artifact tests failed because both modules were absent.
- Task 1 GREEN: 10 tests pass; Ruff and mypy are clean after narrowing the protocol constant to `Literal[1]`.
- Task 2 RED: job-store tests failed because the repository module was absent.
- Task 2 GREEN: 5 state, ownership, claim, and idempotency tests pass; Ruff and mypy are clean.
- Task 3 environment: installed declared FastAPI, HTTPX, and Uvicorn dependencies; narrowed FastAPI below 0.120 to avoid the newer Starlette TestClient deprecation.
- Task 3 RED: API tests failed because the API module was absent after dependencies were installed.
- Task 3 GREEN: 5 API workflow, ownership, path rejection, not-found, and health tests pass; Ruff and mypy are clean.
- Task 4 RED: apply tests failed because the filesystem transaction module was absent.
- Task 4 GREEN: create/replace, stale hash, malformed XML, and injected rollback pass; symlink escape test skips when Windows link privilege is unavailable.
- Task 5 RED: Agent tests failed because the polling module was absent and CLI help lacked the new groups.
- Task 5 GREEN: Agent config, success/failure reporting, empty polling, and CLI help pass; full suite is 46 passed and 1 privilege-related skip.
- Task 6 integration: the in-process API-to-Agent workflow passed on its first composition run and verifies declared output hashes plus fixture immutability.
- Added team-copyable Windows setup, server, binding, approval, polling, backup, and limitation documentation.
- Deep-user immediate fix RED/GREEN: `agent poll` now prints the terminal result instead of completing silently.
- Ponytail review: no dependency, abstraction, or duplicated layer can be removed without weakening an explicit protocol, persistence, or rollback boundary.
- Final verification: 48 passed, 1 Windows symlink-privilege skip; Ruff clean; mypy clean; CLI exposes seven top-level commands and the `agent poll --once` option.
- Packaging verification: built `figma_to_fgui_core-0.1.0-py3-none-any.whl` successfully after approved build-backend download.

| Command | Result |
|---|---|
| Baseline | Pending |
| `python -m pytest tests/unit/test_models.py -v` | Blocked: global Python has no pytest; create `.venv` and install declared dev dependencies |
| `.venv` pytest after install | Editable install encoded the Chinese workspace path incorrectly; configure pytest `pythonpath = ["src"]` |
| Task 1 tests | PASS: 2 pytest tests; mypy clean |
| Task 2 tests | PASS: 6 pytest tests; Ruff and mypy clean |
| Task 3 initial verification | pytest 9/9 and Ruff passed; mypy blocked by missing third-party `lxml` stubs |
| Task 3 type-check resolution | Added a local mypy override for `lxml.*` instead of another runtime dependency |
| Batch 1 final verification | PASS: 9 pytest tests, Ruff clean, mypy clean |
| Task 4 initial verification | Behavior test and Ruff passed; mypy blocked by missing PyYAML stubs, resolved with the existing third-party import override |
| Task 5 verification | PASS: deterministic ID test, Ruff, and mypy |
| Batch 2 final verification | PASS: 12 pytest tests, Ruff clean, mypy clean |
| Task 7 verification | PASS: validation gate tests, Ruff, and mypy |
| Task 8 verification | PASS: stable tree hash and ERROR applicability gate; Ruff and mypy clean |
| Task 9 golden generation attempt | Editable install path encoding also affects plain Python commands; run development commands with `PYTHONPATH=src` |
| Task 9 initial full verification | 18 tests, Ruff, and mypy passed; CLI without `PYTHONPATH=src` reproduced the known editable-path encoding limitation |
| Task 9 CLI verification | PASS with documented `PYTHONPATH=src`; all five commands listed and end-to-end convert returned `applicable: true` |
| Ponytail review | Removed unused Pillow dependency; clarified Windows isolated-environment and read-only source workflow |
| Final verification | PASS: 18 tests, Ruff, mypy, five-command CLI, deterministic XML/changeset, and source fixture immutability |
