# Writer Task 7 Report — FairyGUI 6.1.4 serializer/XML gate

## Outcome

Implemented the deterministic in-memory FairyGUI 6.1.4 project serializer and an independent
fail-closed XML/file-set validator.

The serializer now:

- consumes a canonically revalidated `NewProjectManifest` and an exact tuple of matching
  `ValidatedAssetPayload` values;
- builds all XML through lxml elements (no hand-built XML tags);
- emits one deterministic project marker, package declaration, component files, and the exact
  declared raster payload files;
- uses a closed dispatch table for `container`, `text`, `richText`, `image`, `loader`,
  `componentReference`, and `rasterSubtree`;
- supports the three evidence-backed component-root native mask encodings: rectangle overflow,
  rounded rectangle graph mask, and image mask;
- emits component/image package resources, same-package component `src/pkg`, loader `ui://` URLs,
  image `src/fileName`, and nine-slice `scale/scale9grid` declarations;
- canonicalizes finite decimals, normalizes negative zero, escapes all XML attribute content via
  lxml, emits UTF-8 with LF only, and preserves deterministic element/attribute order;
- converts Manifest parent-local positions to FairyGUI component-local group member positions.

The independent `validate_xml_files` gate safely reparses every XML value with entity, network, and
DTD loading disabled. It rejects DOCTYPE/entity declarations, malformed or unknown structure,
noncanonical UTF-8/LF/decimals, bad target IDs, global ID reuse, unsafe or Windows-casefold-colliding
paths, undeclared/missing files, package resource errors, component/image/loader reference errors,
group errors, mask source/ordering errors, and invalid nine-slice declarations.

## TDD evidence

- Entry-point RED: `1 failed, 45 passed, 1 skipped`; failure was the absent
  `serialize_project_marker` API.
- Eleven-object golden RED: `15 failed, 46 passed, 1 skipped`; serialization was intentionally
  still unimplemented.
- XML collision/identity RED: two focused failures proved the gate initially missed Windows
  casefold file collisions and cross-type target-ID reuse.
- Zero-size RED: one focused failure proved the gate incorrectly applied positive component-size
  rules to ordinary display objects; the real 6.1.4 corpus shows `size="0,0"` display objects.
- Focused GREEN before final polish: `63 passed, 1 skipped`.
- Final full suite: `995 passed, 3 skipped` (the three pre-existing Pydantic corruption-test
  warnings remain unchanged).
- Repository-wide Ruff: pass.
- Strict mypy: pass for 54 source files.

The approved-in-code golden matrix is under
`tests/golden/expected/minimal-new-project/` and covers container, text, rich text, image, loader,
component reference, raster subtree, nine-slice, rectangle clip, rounded clip, and image mask.
The fixed PNG payload is stored as base64 so the expected artifact remains reviewable in Git.

## Real Editor gate — explicit concern

I did **not** claim the Task 7 goldens are FairyGUI-Editor-approved.

The Task 1 neutral empty project remains the verified outer-dialect evidence. For Task 7, the local
FairyGUI Editor 6.1.4 executable was found and was already running, but Computer Use could not capture
either Editor window (`SetIsBorderRequired failed: 0x80004002`). A later accessibility-only retry was
stopped by the user with the physical Escape key, so all further Computer Use actions were stopped.
Consequently the required open/save/reopen/no-repair-or-migration-modal/structural-diff round trip is
still pending and is not represented as completed evidence here.

Until that gate can be observed, nested-container native masks remain fail-closed because no verified
6.1.4 project encoding was available. The three native paths are emitted only when their target is the
component root; raster fallback remains supported at any validated tree position.

## Self-review

- No village/business names or special cases are present in serializer or validator logic.
- Unknown node and mask enum values fail closed; no display object is silently omitted.
- Text styles not covered by observed 6.1.4 encodings (ambiguous UBB content, per-run font/stroke
  differences, inconsistent style facts) fail closed instead of degrading silently.
- Component-root container display state that cannot be represented losslessly also fails closed.
- Generated XML is reparsed before `serialize_project_files` can return success.
