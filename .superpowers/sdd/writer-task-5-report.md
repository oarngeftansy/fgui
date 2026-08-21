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

---

## 2026-08-19 Review Remediation

### Added fail-closed path namespace validation

- Added `validate_unique_target_paths(paths)`, which compares every complete
  POSIX path segment using NFC plus casefold. It rejects both exact duplicate
  destinations and paths that collide only under Windows comparison; equal
  filenames in different directories remain valid.
- The generated component/resource paths pass through the same validator, so
  their internal relative paths are constrained before later manifest use.

### Tightened target-platform filename rules

- Resource suffixes are a closed Writer v1 set: `.png`, `.jpg`, and `.webp`.
  Dotless, compound, uppercase, traversal, and SVG suffixes are rejected; no
  suffix is normalized silently.
- Reserved Windows device names now include the `COM¹`–`COM³` and
  `LPT¹`–`LPT³` forms, including case and extension variants.
- Every target path segment, including final digest-qualified filenames, is
  limited to 255 UTF-16 code units. The check counts astral Unicode characters
  as surrogate pairs and rejects rather than truncating overlong names.

### TDD and verification

- RED: focused collection failed with missing
  `validate_unique_target_paths` import.
- GREEN: `38 passed in 0.07s` for the focused ID/path module.
- Final pytest: `900 passed, 3 skipped, 3 pre-existing Pydantic serializer warnings`.
- Ruff, mypy, and `git diff --check` passed.

---

## 2026-08-19 P2 Public Path-Boundary Remediation

`validate_unique_target_paths` now reuses the same Windows-safe segment
validator as visible target names. Every public input segment rejects empty,
`.`/`..`, controls, forbidden path characters, trailing ASCII dot/space,
reserved device aliases (including superscript COM/LPT forms), and more than
255 UTF-16 code units before NFC/casefold collision comparison.

TDD evidence:

- RED: six focused failures showed `Hero.`, `Hero `, `CON`, and `COM¹.txt`
  paths were accepted by the public collection API.
- GREEN: `44 passed in 0.07s` focused.
- Final pytest: `906 passed, 3 skipped, 3 pre-existing Pydantic serializer warnings`.
- Ruff, mypy, and `git diff --check` passed.
