# Writer Review Workbench Layout Design

## Goal

Replace the cramped 360×680 Writer review with a 520×720 single-column review workbench that keeps conversion evidence readable and actions reachable without overlap. Produce an interactive standalone HTML demo first; after user approval, apply the same layout contract to the Figma plugin.

## Scope

- New-project Writer review only.
- No Project Binding or existing-project workflow changes.
- No village, page-name, or node-ID special cases; village content is demo data only.
- The demo covers selection, project setup, progress, conversion summary, evidence tabs, warning review, blocked review, rejection, and approval/download states.

## Viewport and Scrolling

- Fixed Figma plugin content viewport: 520×720 CSS pixels.
- Header, compact selection/project summary, workflow stage strip, and footer actions remain visible.
- Exactly one central review-content scroll surface.
- Tabs and their panels never create nested vertical scrolling.
- The footer reserves layout space and must never cover review content.

## Information Architecture

1. Header: product direction, mode, overflow entry.
2. Compact context card: selected frame, layer/resource counts, project name, refresh action.
3. Four-stage progress strip: read selection, convert structure, review, package.
4. Conversion summary: automatic, recommended-review, and blocked counts.
5. Evidence navigation: images, components, Package/resources, unified checks.
6. Central scrollable evidence panel.
7. Persistent action footer: reject and approve/download.

## Conversion Semantics

- Green `native` and `raster_preserved` items count as automatic conversion and appear as a concise summary.
- Yellow `editable_risk` items show concrete editability impact and server-declared choices.
- Red `blocked` items show the exact source item and required action, and disable approval.
- Color is never the sole signal; every level has a text label and count.

## Evidence Layout

- Image review uses a stable two-column comparison: “Figma 原图” and “FairyGUI 结果”.
- Columns are equal width and use identical aspect-ratio containers with `object-fit: contain`.
- Evidence metadata sits below the pair and does not share the image row.
- Four evidence tabs stay on one line at 520px.
- Long identifiers wrap in a dedicated metadata line rather than stretching columns.

## Demo States

The standalone HTML exposes three switchable scenarios:

1. Ready: automatic conversions only; approval enabled.
2. Review recommended: automatic plus editable-risk items; approval requires acknowledgment.
3. Blocked: at least one red item; approval disabled and corrective guidance visible.

The default demo uses a neutralized village-style complex UI selection only to make the density realistic.

## Visual Direction

- Practical production-tool aesthetic: cool gray canvas, white work surfaces, restrained blue actions.
- Green, amber, and red are reserved for conversion disposition meaning.
- Typography prioritizes Chinese UI legibility; identifiers use a compact monospace face.
- Signature element: the three-state conversion rail acts as both summary and navigation cue.
- Motion is limited to tab/state transitions and respects reduced-motion preferences.

## Acceptance Criteria

- At 520×720, header and footer are visible and do not overlap the central review surface.
- Both comparison images are fully visible side by side with aligned top and bottom edges.
- No horizontal scrolling and no nested vertical scrollbar.
- All four tabs remain on one line.
- Ready, recommended, and blocked states are visually and semantically distinguishable.
- Keyboard focus is visible; tabs and scenario controls are operable by keyboard.
- The HTML is self-contained and can be opened locally without a server.
