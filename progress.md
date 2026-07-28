# Progress

## 2026-07-27

- Created isolated branch and worktree: `codex/conversion-core-baseline`.
- Reviewed the implementation plan; Tasks 1-3 have no critical blocking gaps.
- Planning template read failed because the installed skill has no `templates/` directory; recorded and continued with minimal local files.

## Verification Log

## 2026-07-28

- User approved the fixture-backed API Server and Windows Agent vertical slice.
- Wrote `docs/superpowers/specs/2026-07-28-local-apply-loop-design.md`.
- First combined patch failed because mojibake in the old planning file prevented exact context matching; no partial changes were applied.
- Design self-review found no placeholders, contradictory transitions, or unbounded filesystem operations.
- User approved the written specification.
- Wrote and self-reviewed `docs/superpowers/plans/2026-07-28-local-apply-loop.md` with six TDD tasks.
- Task 1 RED: service contract and artifact tests failed because both modules were absent.
- Task 1 GREEN: 10 tests pass; Ruff and mypy are clean after narrowing the protocol constant to `Literal[1]`.

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
