# Writer Task 2 Report — FGUI Plan v2 Self-Contained Components

## Scope

- Baseline: `09fc433`
- Upgraded the strict generation plan to `schemaVersion=2`.
- Added self-contained `componentDefinitions` and mandatory
  `componentReference.definitionRef`.
- Preserved the v1 contract as explicit `FGUIPlanV1Document` /
  `FGUIPlanV1Node` types solely for safe migration.
- Did not add Project Binding fields, existing-project scanning, target package IDs,
  or candidate-specific behavior.

## RED evidence

1. Model/graph tests were written first. The focused model/validator run failed during
   collection because `ComponentDefinitionPlan` did not exist:

   ```text
   ImportError: cannot import name 'ComponentDefinitionPlan'
   1 error
   ```

2. The CLI rejection test was written before the migration command. It failed with
   exit code 2 because `migrate-fgui-plan-v1` did not exist, and the expected safe
   “must be recompiled” error was absent.

## GREEN implementation

### Strict models and migration

- `FGUIPlanDocument.schema_version` is now `Literal[2]` and serializes
  `componentDefinitions` canonically.
- `ComponentDefinitionPlan` owns a stable logical ID, public name, local root ref,
  and immutable local `FGUIPlanNode` table.
- Plan v2 component references require non-blank `candidateKey`, `definitionRef`,
  and concrete non-blank variant keys/values.
- `migrate_plan_v1_without_components` performs the specified pure structural
  migration. Any v1 `componentReference` raises `ValueError` and must be recompiled.

### Canonical validation

- Validates definition key/ID and local node key/ID agreement.
- Validates definition-local root, parent/child symmetry, unique parent ownership,
  reachability, cycles, and bounded tree depth.
- Enforces node ID single ownership across root trees and all definitions.
- Validates component-reference closure, unused definitions, and bounded acyclic
  definition graphs using iterative traversal.
- Runs the existing resource, mask, decision, node-payload, privacy, binding-field,
  and bindability checks across root and definition nodes together.
- Canonical privacy redaction now preserves user-visible text inside definitions as
  well as root nodes.

### Compiler and CLI

- `compile_fgui_plan` emits Plan v2.
- UIR v1 component definitions do not contain an independent root/node tree.
  Therefore verified candidate metadata is never promoted into a generated
  component. A mapping-approved PNG raster fallback remains supported; otherwise
  compilation emits blocking `fgui.component.definition_missing` diagnostics.
- Added `migrate-fgui-plan-v1 SOURCE OUTPUT`. It emits canonical v2 bytes for a
  valid component-free v1 document, rejects component-bearing v1 with exit code 2,
  does not create an output on rejection, and reports public validation codes for
  other semantic failures.
- Updated the reviewed generic Plan golden from v1 to canonical v2.

## Test evidence

- Focused task suite before the last review additions: `189 passed`.
- Full regression before final verification: `801 passed, 3 skipped`.
- The final fresh verification commands and counts are recorded below after the
  completed self-review.

## Self-review

### Standards axis

- No documented-standard violations were found.
- The reviewer identified duplicated v1/v2 node shapes, duplicated tree-validation
  structure, and an always-empty `_component_plan` helper as judgment-call smells.
- The shared node fields now live in `_FGUIPlanNodeBase`, and the compiler helper is
  an honest boolean capability check named
  `_has_generatable_component_definition`.
- Root-tree and definition-tree validators intentionally retain separate public
  diagnostic namespaces and local-root semantics; merging them now would make the
  strict error contract harder to audit.

### Spec axis

- Added direct tests for valid definitions, missing references, recursive graphs,
  key/ID agreement, local-tree ownership/reachability, cross-tree ownership,
  unused definitions, and iterative maximum reference depth.
- Tightened v2 variant keys and values to non-blank strings. The referenced Plan
  definition is already a concrete static node tree; variant values remain public
  provenance and are not interpreted as Controllers or Gears.
- No candidate mapping or village-specific special case was introduced.

## Deep-user audit

**Real job:** safely move existing component-free plans to v2 and prevent a user
from handing an un-generatable logical component reference to the new-project
Writer.

- Invalid v1 plans previously risked an opaque failure. The CLI now reports stable,
  public diagnostic codes and writes no misleading output. Acceptance is covered by
  positive canonical migration and negative component-reference CLI tests.
- A “verified” candidate can still surprise users by being blocked because it is not
  a component definition. The immediate diagnostic names the missing definition and
  recommends recompilation with a definition or raster fallback.
- Larger follow-up: introduce a future UIR schema with an independently owned,
  validated component node tree. Acceptance should require `compile_fgui_plan` to
  emit a non-empty self-contained definition and a closed `definitionRef` without
  Project Binding.

## Residual concern

Current UIR v1 cannot represent the complete generatable component tree required by
Plan v2. Consequently, current production compilation emits self-contained component
references only after a future UIR contract supplies that tree; today it correctly
uses an explicitly approved PNG fallback or fails closed. This is an upstream schema
capability gap, not a candidate-mapping or Writer inference opportunity.

## Final verification

- `python -m pytest -q`: `806 passed, 3 skipped`.
- Focused four-file task suite after commit: `192 passed`.
- `ruff check .`: passed with no errors.
- `mypy src`: passed for 49 source files with no errors.
- `git diff --check`: passed.
- Pytest reported three pre-existing Pydantic serializer warnings from tests that
  deliberately create invalid enum states through `model_copy`; there were no test
  failures.

## Review fix — depth and reviewed raster descendant ownership

### Important 1: root-originating depth

RED command:

```text
python -m pytest -q tests/unit/test_fgui_plan_validate.py \
  -k "depth_from or recursive_definition_graph"
```

RED output:

```text
2 failed, 7 passed
```

Both failures were the required reverse-ID 257-node counterexamples: the definition
reference graph omitted `fgui.plan.component_definition_depth_exceeded`, and the
definition-local tree omitted
`fgui.plan.component_definition_tree_depth_exceeded`.

GREEN implementation and evidence:

- Added iterative root-reachability plus Kahn longest-path calculation.
- Depth is calculated only along actual root-originating acyclic paths; cycle
  diagnostics remain independent.
- Added forward-ID and reverse-ID tests proving 256 is accepted and 257 is rejected
  for both graph types, plus reachable definition-cycle and local-tree-cycle tests
  proving cycles are not mislabeled as depth failures.

```text
python -m pytest -q tests/unit/test_fgui_plan_validate.py \
  -k "depth_from or recursive_definition_graph"
9 passed
```

### Important 2: reviewed component raster fallback

RED command:

```text
python -m pytest -q tests/unit/test_fgui_plan_compile.py \
  -k "reviewed_component_raster_fallback"
```

RED output:

```text
2 failed
```

The safe case emitted a `rasterSubtree` with a dangling child ID, while the behavior
case omitted `fgui.raster.descendant_non_rasterizable`.

GREEN implementation and evidence:

- Raster descendant ownership now follows the final resolved raster decision for
  both source raster conversions and reviewed component-reference fallbacks.
- Safe descendants are consumed before node compilation, so raster nodes have empty
  children and no duplicate/dangling native nodes.
- Non-rasterizable behavior descendants still block the fallback.
- The scope remains limited to raster/component source roles so existing mask target
  collision reconciliation retains its atomic diagnostics.

```text
python -m pytest -q tests/unit/test_fgui_plan_compile.py \
  -k "reviewed_component_raster_fallback"
2 passed
```

### Review-fix final verification

- Focused validator/compiler suite: `158 passed`.
- Full suite: `816 passed, 3 skipped`.
- Ruff: passed.
- mypy: 49 source files, no issues.
- `git diff --check`: passed.

## Review fix — consumed descendant raster mask ownership

### RED

Added a public-seam compiler counterexample combining a reviewed component raster
fallback with a legal complex descendant mask that independently requires
`MaskMode.RASTER_SUBTREE`.

```text
python -m pytest -q tests/unit/test_fgui_plan_compile.py \
  -k "suppresses_consumed_descendant_raster_mask"
1 failed
```

The pre-fix Plan retained the inner `MaskPlan` after the outer component fallback
had consumed its safe raster root. `validate_fgui_plan` consequently reported
`fgui.plan.mask_orphan` (and the mask referenced a resource with no emitted owner).

### GREEN

- After all resolved raster roots consume safe descendants, raster-mask
  reconciliations now re-evaluate final ownership deterministically by sorted
  container ID.
- An emitted raster mask is suppressed when its emission target or its complete
  mask scope is consumed by an outer raster root.
- Resource emission remains consumer-driven. The consumed inner mask creates no
  consumer or resource, while the outer component raster resource and its warning
  remain intact; shared resources used outside the consumed scope are not globally
  removed.
- The existing behavior-descendant counterexample still blocks the outer fallback.

```text
python -m pytest -q tests/unit/test_fgui_plan_compile.py \
  -k "reviewed_component_raster"
3 passed, 81 deselected
```

The combined result is bindable, passes `validate_fgui_plan == ()`, and contains
exactly one childless outer raster node, one outer raster resource, and no masks.

### Final verification

- Focused compiler/validator suite: `159 passed`.
- Full suite with a short Windows `--basetemp` path: `817 passed, 3 skipped`.
- Ruff: passed.
- mypy: 49 source files, no issues.
- `git diff --check`: passed.
- An initial full run used a deep worktree-local temporary path and caused existing
  package integration jobs to fail at Windows path-length-sensitive packaging.
  The failing integration case passed in isolation and the complete suite passed
  with `--basetemp C:\Users\momoca\Documents\figma转fgui\.pt-full`.

### Deep-user audit

The downstream Writer's real job is to receive one closed, bindable Plan whose
raster ownership is unambiguous. The fix removes the handoff-breaking orphan inner
mask/resource without hiding behavior diagnostics or dropping the outer visual
fallback. The remaining product boundary is unchanged: UIR v1 still cannot provide
a complete generatable component definition, so explicit raster fallback or a
blocking definition diagnostic remains required.

## Final review fix — mask closure to actually emitted targets

### RED

Added two public compiler counterexamples:

1. A reviewed component raster fallback containing a valid descendant raster mask
   plus an interaction sibling. The interaction blocks the outer raster owner.
2. A definition-missing component reference containing the same valid descendant
   raster mask. The component ancestor cannot compile.

```text
python -m pytest -q tests/unit/test_fgui_plan_compile.py \
  -k "blocked_reviewed_component_does_not_emit_nested_raster_mask or \
      definition_missing_component_does_not_emit_nested_raster_mask"
2 failed, 84 deselected
```

Both pre-fix review artifacts had `nodes == {}` but retained one raster `MaskPlan`,
so the mask was not closed to an emitted target.

### GREEN

- Mask reconciliation now performs a final deterministic pass after root/node
  compilation and retains a MaskPlan only when its target UIR node actually exists
  in the emitted Plan node table.
- Removing a non-emittable target also removes the provisional mask reference and
  MaskPlan. Resource construction remains driven by actual node consumers, so a
  mask-only resource disappears while an independently emitted shared-resource
  consumer remains authoritative.
- The original `fgui.raster.descendant_non_rasterizable`,
  `fgui.unsupported.interaction`, and `fgui.component.definition_missing`
  diagnostics are preserved. Both non-bindable review artifacts now pass
  `validate_fgui_plan(plan) == ()` with no orphan mask/resource.

```text
python -m pytest -q tests/unit/test_fgui_plan_compile.py \
  -k "blocked_reviewed_component_does_not_emit_nested_raster_mask or \
      definition_missing_component_does_not_emit_nested_raster_mask"
2 passed, 84 deselected
```

### Final verification

- Focused compiler/validator suite: `161 passed`.
- Full suite with a short Windows `--basetemp`: `819 passed, 3 skipped`.
- Ruff: passed.
- mypy: 49 source files, no issues.
- `git diff --check`: passed.

### Deep-user audit

The Writer consumes review artifacts as strict graph contracts even when binding is
blocked. A deep user must be able to inspect the original interaction or missing-
definition reason without unrelated structural validator noise. The final emitted-
target closure provides that property while preserving independently owned resource
consumers. The remaining limitation is still upstream: UIR v1 cannot yet carry a
complete generatable component definition.
