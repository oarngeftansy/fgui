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

## Review Remediation

- Selection-derived node IDs are now deterministic, content-and-position hashes; generated XML, diagnostics, normal previews, and advanced previews contain none of the raw manifest IDs or resource keys covered by regression tests.
- Selection resources now receive content-hash asset names and are materialized by the existing generator under the package `assets` directory, with panel XML references. Resource bytes and opaque filenames appear in the changeset without raw source keys or paths.
- Fixture routes are registered only when `allow_fixture_jobs=True`; production OpenAPI omits both paths and fixture schemas, and malformed fixture requests receive `404`.
- Live selection jobs now require an authenticated owner with `selection:read-own-status`; unauthenticated requests receive `401` and a different paired device receives a safe `404`.
- The integration test mutates only a temporary fixture copy and compares the applied panel SHA-256 against the approved artifact hash.

Remediation verification: focused plus golden 5 passed; full suite 175 passed, 1 Windows symlink-permission skip; Ruff, mypy, and `git diff --check` clean.

## Second Review Remediation

- Image resources are now appended deterministically to the target package's existing `resources` node. Existing entries, attributes, and order remain intact; IDs use the current collision-safe allocator, and generated panel XML points `src` at the registered ID.
- The selection adapter emits an opaque raw document plus an internal `SelectionAsset` context containing only a verified resolved source path, declared MIME type and size, content SHA-256, and immutable selection fingerprint. No resource bytes, path, or original resource key enters the raw document.
- Resource copies use 64 KiB chunks and compare their final size and SHA-256. A multi-resource selection larger than 8 MiB is rejected before staging; independently, generated changes above 8 MiB fail the job before base64 encoding or artifact storage.
- Repeating the same conversion yields byte-identical `package.xml`; applying a live job then re-indexing resolves the generated panel resource ID. A forced bundle-limit integration test confirms a `conversion_failed` job stores no artifact.

Second-remediation verification: 7 focused tests passed; full suite 178 passed with 1 Windows symlink-permission skip; Ruff, mypy, and `git diff --check` are clean.
