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
  depth; Writer v1 permits component-reference longest paths up to 256 and rejects 257.
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

The component graph uses a Writer v1 longest-reference-path limit of 256;
a 257-node reference chain is rejected while 257 independent components are valid.

## Persistent memory

- Updated `.claude/memory/wiki.md` with the completed Task 6 boundary.
- Prepended `.claude/memory/learnings.md` with the raster-ref namespace, cross-layer
  depth, and logical-key/ID lessons.
- No new stable user preference was discovered; `.claude/memory/memory.md` is unchanged.

## Strict-review remediation

The follow-up strict review was treated as a new RED/GREEN cycle. The public manifest
contract caps object-tree and component-reference longest-path depth at 256.

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

## V3 review closure

- All Manifest source/uir/raster-consumed references now pass the public data policy;
  absolute/UNC paths, secret/binding aliases and private provenance fail at the schema
  gate without value echo. Visible user text remains exempt.
- Logical-key construction is fully exception-contained. Parts must be NFC, then are
  case-folded before UTF-8 length-prefix encoding; duplicate canonical requests fail
  closed (including `ẞ` versus `ss`).
- Plan, config and manifest contract headers require exact builtin types, preventing
  bool-as-int and hostile truth/comparison behavior.
- Component depth is documented and tested as longest component-reference path, not
  total component count: depth 257 rejects while 257 independent components pass.

V3 verification:

```text
focused suite: 110 passed
full suite: 953 passed, 3 skipped
ruff check .: All checks passed
mypy src: Success: no issues found in 54 source files
```

The first full-suite attempt used a long worktree-local Unicode basetemp and caused
four integration packaging failures. Re-running the unchanged suite with a short
system-temporary basetemp passed all 934 tests; this was an environment/path issue,
not a product-code failure.

## V2 review closure

- Manifest validation and canonical serialization now perform a strict canonical
  schema round-trip before any field access; corrupted models return/raise only the
  static public `fgui.writer.manifest.schema_invalid` contract.
- Compile canonicalizes `NewProjectConfig` before access, and the Plan adapter contains
  serializer and hostile comparison exceptions without exposing exception text.
- Every structured logical-key part must already be NFC before length-prefix encoding.
- Native mask sources require positive dimensions; non-rounded zero radii remain a
  valid Plan fact while nonzero radii are rejected.
- The report now states the verified depth contract: a reference path of 256 passes,
  257 rejects, and 257 independent components remain valid.

V2 verification:

```text
focused manifest/config/ID suite: 99 passed
full suite: 942 passed, 3 skipped
ruff check .: All checks passed
mypy src: Success: no issues found in 54 source files
```

## Final public-closure and exact-header remediation

The final Task 6 review was completed as two additional RED/GREEN slices.

RED evidence:

```text
whole-manifest/header focused selection: 12 failed, 1 passed
stateful canonical serializer recheck: 1 failed
```

The GREEN implementation now:

- checks Plan, Config and Manifest headers on raw runtime attributes and raw JSON dump
  payloads before any coercive `model_validate`; exact builtin types are required, so
  `True` cannot alias integer version `1`;
- uses one exception-contained header helper that never invokes equality or truth on
  hostile non-builtin values and catches `Exception`, not `BaseException`;
- applies the public-data policy to the complete canonical Manifest string closure,
  exempting only visible `TextPlan.content` and text-run `content` values;
- validates Manifest `projectName` with the generated-target name policy;
- rechecks every canonical serializer dump, including a stateful second-dump
  corruption case, and converts ordinary failures only to static
  `NewProjectManifestError` diagnostics without value echo.

Final verification:

```text
focused Task 6 suite: 133 passed
full suite: 976 passed, 3 skipped
ruff check .: All checks passed!
ruff format --check <changed Task 6 code/tests>: 3 files already formatted
mypy src: Success: no issues found in 54 source files
git diff --check: clean
```

The three warnings are the existing Pydantic serializer warnings from Plan tests that
intentionally inject enum strings through `model_copy`; the new tests add no warnings.
The stable architecture facts and coercion lessons were recorded in project memory;
no new stable user preference was discovered, so `memory.md` is unchanged.
