# Live Task 3 Report: Selection-Backed Conversion and Production Job API

## Commit

`c151ed31def6761451591c5dce695973172201bf` — `feat: convert live Figma selections`

## RED Evidence

- `test_selection_document_normalizes_live_nodes_without_figma_rest_shape` initially failed at collection because `selection_document` did not exist.
- `test_convert_document_preserves_fixture_conversion_bytes` initially failed at collection because `convert_document` did not exist.
- The multi-root manifest characterization then failed with `ValueError: selection must contain exactly one top-level node` before the adapter and normalizer accepted canonical `roots`.
- `test_live_selection_job_uses_committed_selection_and_not_fixture` initially failed because the legacy project fixture route returned `200` instead of the required production-default `404`.

## Characterization and Integration Proof

- A live manifest with frames, text, auto-layout style, component properties, an instance, raster and SVG declarations normalizes deterministically, keeps resource references selection-relative, and has no dependency on REST fixture input.
- `convert_document` produces the exact same `ChangeSet` and generated XML bytes as legacy `convert` for `simple-frame.json`; the existing golden test also passes.
- The integration path pairs a device, commits a live selection, uploads a FairyGUI ZIP, creates the selection-backed job, reads a safe normal preview, approves it, and applies through the Agent to a copied local project.
- The applied XML contains `Live text wins`; mutating `tests/fixtures/figma/simple-frame.json` after job creation cannot affect the applied output.
- Fixture job endpoints are `404` by default and legacy tests plus the development CLI enable them explicitly. The job row retains the selection ID and immutable fingerprint internally; `JobSummary` does not expose either.

## Verification

```text
pytest tests/unit/test_live_selection_normalize.py tests/integration/test_selection_job_flow.py tests/golden -v: 4 passed
pytest -q: 174 passed, 1 skipped (Windows symlink privilege)
ruff check src tests: All checks passed
mypy src: Success: no issues found in 27 source files
git diff --check: passed
```

## Review and Concerns

Ponytail review: Lean already. The adapter and route reuse the current classifier/generator and add no dependency or parallel conversion path.

Resource references are carried into normalized raw style for the existing path, while actual generated asset emission remains outside this task's approved scope.
