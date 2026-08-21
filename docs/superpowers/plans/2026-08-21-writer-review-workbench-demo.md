# Writer Review Workbench Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained animated 640×800 portrait HTML demo of the automatic-conversion, illustrated review, and final-download workflow.

**Architecture:** One standalone HTML file owns demo-only markup, CSS illustrations, and a small vanilla-JavaScript state machine; it neither imports production code nor calls Figma or the server. A focused pytest gate uses real local Edge to verify viewport closure, one-scroll layout, large aligned evidence, step and item transitions, acknowledgement, engineering-detail expansion, and the copy-to-Figma review-frame animation.

**Tech Stack:** HTML5, CSS, vanilla JavaScript, pytest, Playwright Core, Microsoft Edge.

## Global Constraints

- The demo viewport is exactly 640×800 CSS pixels and optimized for portrait usage.
- The workflow is three separate screens: `自动转换` → `建议审核` → `确认下载`.
- There is no permanent review directory or four-tab evidence matrix.
- Each review item includes visible contextual Figma and FairyGUI illustrations.
- Each step has at most one vertical scroll surface; there is no nested scrollbar or footer overlap.
- Copying to Figma is an explicit animated demonstration of a separate frame placed to the right of the selected frame.
- Motion respects `prefers-reduced-motion`.
- The file is self-contained and uses no external assets, URLs, or service calls.
- No Project Binding, existing-project behavior, or business-specific conversion rule is added.

---

### Task 1: Portrait step workflow and interaction gate

**Files:**
- Modify: `docs/demos/writer-review-workbench.html`
- Modify: `tests/acceptance/test_writer_review_workbench_demo.py`
- Update: `docs/demos/writer-review-workbench-preview.png`

**Interfaces:**
- Produces: `.plugin-window[data-step]`, three `[data-go-step]` controls, `.step-scroll`, `.comparison-grid`, `.preview-canvas`, `[data-review-nav]`, `#acknowledge`, `#copy-to-figma`, `.figma-canvas-demo`, `#engineering-details`, and `.action-footer`.
- Consumes: only local browser capabilities; no production API, token, Figma mutation, or network access.

- [ ] **Step 1: Replace the acceptance contract and observe RED**

Update the static gate to require `width=640`, the three screen labels, contextual comparison copy, two review records, and the copy-to-Figma control. Update the Edge script to launch at 640×800 and collect root, scroll, footer, preview, step, item, acknowledgement, detail, and animation state.

```python
assert measurement["root"]["width"] == 640
assert measurement["root"]["height"] == 800
assert measurement["scrollCount"] == 1
assert all(item["width"] >= 220 for item in measurement["previews"])
assert states["reviewItemAfterNext"] == "2 / 2"
assert states["copyState"] == "copied"
```

Run: `python -m pytest tests/acceptance/test_writer_review_workbench_demo.py -q`

Expected: FAIL because the existing artifact is 520×720, scenario/tab based, and lacks the new step and copy state.

- [ ] **Step 2: Implement the three-screen portrait shell**

Replace the old scenario dashboard with a fixed shell and exactly one active screen:

```css
.plugin-window {
  width: 640px;
  height: 800px;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
}
.step-screen[hidden] { display: none; }
.step-scroll { min-height: 0; overflow-y: auto; overflow-x: hidden; }
```

Use a single `state` object with `step`, `reviewIndex`, `acknowledged`, `detailsOpen`, and `copyState`. `render()` must update step visibility, header progress, footer actions, and disabled states without creating additional scroll containers.

- [ ] **Step 3: Implement illustrated automatic and review content**

Render the automatic-conversion screen first with illustrated before/after rows and conversion/editability labels. Render review items one at a time with two equal portrait `.preview-canvas` elements, a persistent target outline, surrounding context, reason, impact, server-declared choice, item counter, and previous/next controls.

```javascript
const reviews = [
  { id: "visual-style", title: "视觉样式保真", reason: "复杂视觉已保真合成", impact: "外观保持一致，局部样式不可单独编辑" },
  { id: "instance-boundary", title: "实例边界确认", reason: "嵌套实例转换为可复用结构", impact: "请确认组件拆分边界符合后续维护方式" }
];
```

- [ ] **Step 4: Implement copy-to-Figma and final confirmation interactions**

On `#copy-to-figma`, animate a miniature selected frame and a separate `FairyGUI 待审核` frame appearing to its right, then set `data-copy-state="copied"` and visible confirmation text. Toggle `#engineering-details` from the final screen, and enable download only after the review acknowledgement is complete.

```javascript
copyButton.addEventListener("click", () => {
  state.copyState = "copying";
  render();
  window.setTimeout(() => { state.copyState = "copied"; render(); }, 240);
});
```

- [ ] **Step 5: Run real Edge geometry and interaction verification**

Run: `python -m pytest tests/acceptance/test_writer_review_workbench_demo.py -q`

Expected: PASS. The Edge gate must prove exact 640×800 geometry, one active scroll surface, no horizontal overflow, footer separation, equal preview dimensions/alignment, step transitions, review navigation, acknowledgement, detail expansion, and copied animation state.

- [ ] **Step 6: Regenerate and inspect the preview**

Use the same Playwright/Edge runtime to save `docs/demos/writer-review-workbench-preview.png` after navigating to the first recommended-review item. Inspect it for portrait-image legibility, clear target outlines, hierarchy, clipping, duplicate navigation, nested scrollbars, and footer overlap.

Expected: the evidence pair is the dominant visual area; no review directory or package tab competes with it.

- [ ] **Step 7: Run hygiene and commit**

Run: `python -m pytest tests/acceptance/test_writer_review_workbench_demo.py -q`

Run: `python -m ruff check tests/acceptance/test_writer_review_workbench_demo.py`

Run: `git diff --check`

Expected: all checks pass.

Commit: `feat: demonstrate portrait Writer review flow`

---

## Plan Self-Review

- Spec coverage: portrait viewport, separate workflow steps, illustrated automatic/review items, contextual target, review navigation, explicit Figma review-frame copy, engineering-detail demotion, motion, accessibility, and one-scroll closure are covered by Task 1.
- Placeholder scan: no deferred implementation or ambiguous test step remains.
- Interface consistency: every selector asserted by the browser gate is produced by the implementation task.
