# Conversion Core Execution

## Goal

Implement `docs/superpowers/plans/2026-07-27-conversion-core-baseline.md` on branch `codex/conversion-core-baseline` with TDD and per-task verification.

## Phases

- [x] Batch 1: Tasks 1-3 — contracts, normalization, project index
- [x] Batch 2: Tasks 4-6 — rules, resources, XML generation
- [x] Batch 3: Tasks 7-9 — validation, changesets, CLI/golden test
- [x] Final review: ponytail review, complete verification, branch handoff

## Current

All baseline tasks and final verification are complete.

## Decisions

- Work only in `.worktrees/conversion-core-baseline`.
- Preserve the approved implementation plan unless a runnable test demonstrates a needed correction.
- Use Python 3.11 and an in-worktree `.venv`.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Referenced planning templates were absent from the installed skill directory | 1 | Created concise project-local files directly |
