# Writer Task 6 Report — Manifest Compiler and Validator

## Outcome

Implemented the pure, byte-free `FGUIPlanDocument + NewProjectConfig +
ValidatedAssetPayload` to `NewProjectManifest` stage. No XML or filesystem writes
were introduced.

Public entry points:

- `compile_new_project_manifest(plan, config, assets) -> NewProjectManifest`
- `validate_new_project_manifest(manifest) -> tuple[Diagnostic, ...]`
- `canonical_manifest_bytes(manifest) -> bytes`

## Implemented behavior

- Revalidates Plan semantics and `bindable`, translates failures into static public
  `fgui.writer.input.*` diagnostics, and rechecks the exact validated payload set.
- Allocates every package/component/object/resource target ID in this layer only;
  the Manifest gate recomputes typed logical keys and rejects arbitrary valid-looking
  IDs.
- Keeps document roots and every component definition in separate ownership domains.
- Emits definitions dependency-first, then roots; deterministic target IDs break ties.
- Preserves parent-local transforms, visibility/opacity/rotation, exact children and
  z-index, text, component/resource refs, native mask scope/order, and raster mask
  consumption facts.
- Compiles reciprocal resource consumer object IDs and canonical, case-fold-safe paths.
- Iteratively validates object/component ownership, tree/graph closure, cycles and
  depth; the component limit intentionally allows one root component above the Plan's
  valid 256-definition chain.
- Rejects duplicate raster consumption in the UIR-ref namespace and retains emitted
  `uirNodeRef` provenance so raster-consumed-vs-emitted duplication is detectable.
- Returns deterministic, static public diagnostics with suggested actions.

## TDD evidence

Initial RED:

```text
ModuleNotFoundError: No module named 'figma_to_fgui.fgui_new_project_compile'
ModuleNotFoundError: No module named 'figma_to_fgui.fgui_new_project_validate'
```

Final focused suite:

```text
11 passed
```

Coverage includes mapping-order canonicalization, single ownership, definition-local
topology, geometry/visibility, input revalidation, native/raster masks, target-key/ID
agreement, mask order, path collisions, consumer closure, raster duplication, and
iterative object/component depth and cycles.

## Final verification

```text
python -m pytest -q
917 passed, 3 skipped

ruff check .
All checks passed!

ruff format --check <Task 6 files>
4 files already formatted

mypy src
Success: no issues found in 54 source files
```

The three pytest warnings are pre-existing Pydantic warnings from tests that
deliberately bypass enum validation with `model_copy`; Task 6 tests add no warnings.

## Self-review

The two-axis code review found no documented-standard violations and no scope creep.
Judgment-call duplication/data-clump suggestions were left local because the object
tree and component graph have deliberately different ownership/depth semantics; the
misleading `_readable_name` helper was renamed.

The spec-axis review identified four real gaps, all fixed before final verification:

1. Target ID syntax/uniqueness existed without logical-key agreement.
2. Raster consumed refs and emitted refs were compared in different namespaces.
3. Native masks lacked direct-child scope and contiguous display-order validation.
4. Writer/Manifest diagnostics lacked a public adapter and suggested actions.

The reported component-depth concern was audited but not applied: upstream permits
256 referenced definitions, and the Manifest graph necessarily adds their consuming
root component, so its corresponding finite bound is 257.

## Persistent memory

- Updated `.claude/memory/wiki.md` with the completed Task 6 boundary.
- Prepended `.claude/memory/learnings.md` with the raster-ref namespace, cross-layer
  depth, and logical-key/ID lessons.
- No new stable user preference was discovered; `.claude/memory/memory.md` is unchanged.

## Strict-review remediation

The follow-up strict review was treated as a new RED/GREEN cycle. The earlier
257-component interpretation was rejected as an off-by-one: the public manifest
contract now caps both object and component graph depth at 256.

Additional RED coverage was added for unsupported Plan schema/profile/rule versions,
canonical round-trip corruption, root/definition identity aliasing, colon-ambiguous
keys, allocator case-fold collisions, malformed export hashes, mandatory UIR identity,
raster namespace confusion, native mask/clip roles and radii, malicious locators,
diagnostic tuple ordering, exact name/path agreement, and noncanonical object tuples.

The GREEN implementation now:

- round-trips Plan v2 through alias/JSON serialization and strict model validation;
- uses shared length-prefixed logical-key helpers and the complete allocator policy;
- makes component source domains and object UIR identities typed and mandatory;
- validates native clip/image-mask roles, source resources, scope, contiguity and radii;
- sanitizes public diagnostic locators and requires evidence/actions;
- recomputes exact generated names/paths and canonical component/object ordering.

Final strict-review verification:

```text
focused Task 6 suite: 47 passed
full suite: 934 passed, 3 skipped
ruff check src + Task 6 tests: All checks passed
mypy src: Success: no issues found in 54 source files
```

The first full-suite attempt used a long worktree-local Unicode basetemp and caused
four integration packaging failures. Re-running the unchanged suite with a short
system-temporary basetemp passed all 934 tests; this was an environment/path issue,
not a product-code failure.
