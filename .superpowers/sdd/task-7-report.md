# Task 7 Report: Designer Review Workspace

## Delivered

- Added `/jobs/{jobId}` routing and a three-column designer review workspace: understandable changes, selected visual/component/resource summary, and checks with whole-update decisions.
- Added typed review API calls for normal preview, opt-in advanced preview, approval, rejection, and the safe job-status read required to gate reviewability. Server response details are never rendered as error copy.
- Added image comparison markup with Chinese alternative text and fixed intrinsic dimensions; no image, hash, ID, path, XML, resource ID, rule evidence, or changeset data appears before the user opens “高级详情”.
- Added confirmation before whole-update approval, cancellation, duplicate-submit protection, safe success/failure feedback, idempotent rejection UI, keyboard change selection, mobile view-only gating, visible focus styling, and reduced-motion handling.

## RED → GREEN Evidence

1. RED: `pnpm --dir apps/web-console test -- --run src/review/ReviewPage.test.tsx` failed because `ReviewPage` did not exist (`Failed to resolve import "./ReviewPage"`).
2. GREEN: the implemented page made the initial interaction suite pass; a later approval-failure test exposed that the page replaced the workspace with an error alert. The error is now inline so retry remains available.
3. RED: the advanced-detail collapse test failed because technical details remained visible after “隐藏高级详情”.
4. GREEN: collapsing now removes only the opt-in technical disclosure without a second API request.
5. RED: the mobile review test showed rejection could still submit at a narrow viewport.
6. GREEN: media-query state now disables both decision controls in addition to CSS stacking/hiding. Final suite: 24/24 tests across 3 test files.

## State, Accessibility, Responsive, and Disclosure Audits

- States covered: loading; normal, warning, and error checks; selection; approval confirm/cancel/success/failure/retry; rejection; advanced disclosure/collapse; and loading failure.
- Semantic headings, real buttons/lists, 44px-or-larger interactive targets, visible focus rings, keyboard ArrowUp/ArrowDown change selection, accessible confirmation dialog, Chinese image alternatives, and `prefers-reduced-motion` support are present.
- Desktop uses `.review-workspace` with three grid columns. At `max-width: 900px`, content stacks and runtime media-query state makes approval/rejection inoperable with desktop-direction copy.
- Normal rendering uses only designer labels, summary, and plain-language checks. Advanced API content is fetched only after disclosure and is visually separated. No local server error detail is trusted.

## Verification

Successful on 2026-07-28:

```powershell
$env:CI='true'
pnpm --dir apps/web-console test -- --run
# 24/24 passed

pnpm --dir apps/web-console build
# tsc -b && vite build passed

Push-Location apps/web-console
& '.\node_modules\.bin\tsc.cmd' --noEmit
Pop-Location
# passed

git diff --check
# passed
```

`pnpm --dir apps/web-console exec tsc --noEmit` could not resolve `tsc` in this worktree (`'tsc' is not recognized`), despite the package-local executable existing. The direct local TypeScript command and the production build's `tsc -b` both passed, so this is a pnpm `exec` PATH issue rather than a type error.

Browser QA used the project-installed Playwright against a temporary local Vite server with mocked safe API responses: it checked the 1440px three-column grid, image dimensions, confirmation success flow, and the 375px stacked, disabled-action review view. The temporary server was stopped afterwards.

## Deep User Audit

**Real job:** decide whether a complete FairyGUI update is safe to hand to the local assistant without understanding implementation artifacts.

The immediate workflow is clear: one selected change at a time, plain-language checks, explicit backup/local-change protection, and one confirmation for the whole update. A remaining larger product bet is serving real before/after image URLs from the preview API; this slice preserves the comparison layout and accessible labels but has no asset identifier in the approved preview response to load the actual thumbnails.

## Commit

`6b45f9d` — `feat: add designer review workspace`
