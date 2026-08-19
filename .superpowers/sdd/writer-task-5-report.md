# Writer Task 5 Report — Deterministic Target IDs and Safe Paths

## Scope

- Baseline: `6dc11ce`.
- Added `fgui_new_project_ids.py` and its focused unit tests only; this task does
  not compile a manifest or serialize XML.

## 6.1.4 ID Evidence and Policy

The Task 1 Editor 6.1.4 fixture proves only the observed lowercase
alphanumeric ID charset. Its observed project, package, and component-resource
IDs have different lengths, so this task does not infer or extend a supposedly
universal Editor ID format.

Writer v1 instead has an explicit deterministic policy: the first eight
lowercase hexadecimal characters of a SHA-256 digest over `kind:logical_key`.
This is a subset of the observed charset, has a fixed documented width, and is
never widened, randomized, or time-qualified. A truncated-prefix collision is
rejected with `TargetIdCollisionError`.

## Behaviour Implemented

- `TargetIdAllocator` canonicalizes request sets, retains previous allocations,
  and rejects digest or NFC/casefold logical-key collisions deterministically.
- Visible names retain their validated original spelling. Comparison uses NFC
  and casefold only; Windows device names, controls, invalid path characters,
  traversal, drive/UNC syntax, and trailing dot/space aliases fail closed.
- Component and resource paths are `PurePosixPath` values under `components/`
  and `resources/`, and each filename retains its readable name plus its stable
  digest-derived ID.
- Project/package names are supported by the same validator and are never
  silently normalized or rewritten.

## TDD and Verification

### RED

```text
ModuleNotFoundError: No module named 'figma_to_fgui.fgui_new_project_ids'
```

The focused tests were written first and failed during collection because the
production module did not exist.

### GREEN

```text
26 passed in 0.05s
```

Command:

```powershell
& 'C:\Users\momoca\Documents\figma转fgui\source\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_fgui_new_project_ids.py
```

### Final checks

- Full pytest: `888 passed, 3 skipped, 3 pre-existing Pydantic serializer warnings`.
- Ruff: `All checks passed!`.
- mypy: `Success: no issues found in 52 source files`.
- `git diff --check`: passed.

No new durable project memory was identified beyond this task-specific report.
