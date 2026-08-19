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
