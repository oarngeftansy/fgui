# Writer Review Workbench Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained 520×720 interactive HTML demo of the complete Writer review workflow and verify its layout in a real Edge viewport.

**Architecture:** One standalone HTML file owns demo-only markup, CSS, and state switching; it does not import production code or call a service. A focused acceptance test verifies closure and semantic content, then uses the installed Playwright Core and Microsoft Edge to measure the fixed viewport, scrolling surfaces, tab alignment, image comparison geometry, and footer non-overlap.

**Tech Stack:** HTML5, CSS, vanilla JavaScript, pytest, Playwright Core, Microsoft Edge.

## Global Constraints

- The demo viewport is exactly 520×720 CSS pixels.
- Header, context summary, workflow stage strip, and footer remain visible.
- Exactly one central review-content scroll surface; no nested vertical scrollbar.
- Comparison images are equal-width, aligned, and use `object-fit: contain`.
- The four evidence tabs remain on one line.
- Ready, recommended-review, and blocked scenarios are switchable.
- The file is self-contained and opens locally without a server or external assets.
- No Project Binding, existing-project behavior, or business-specific conversion rule is added.

---

### Task 1: Interactive workbench demo and real-browser layout gate

**Files:**
- Create: `docs/demos/writer-review-workbench.html`
- Create: `tests/acceptance/test_writer_review_workbench_demo.py`

**Interfaces:**
- Produces: a local HTML artifact with scenario buttons carrying `data-scenario`, one `.review-scroll` surface, one `.comparison-grid`, and one `.action-footer`.
- Consumes: only local browser capabilities; no production API, token, or network access.

- [ ] **Step 1: Write the failing static closure test**

Create a test which expects the demo file to exist, contain no external URL/script/style/image references, expose all three scenario IDs, and include the complete workflow labels.

```python
def test_writer_review_workbench_demo_is_self_contained() -> None:
    html = DEMO.read_text("utf-8")
    assert "https://" not in html and "http://" not in html
    assert 'data-scenario="ready"' in html
    assert 'data-scenario="recommended"' in html
    assert 'data-scenario="blocked"' in html
    for label in ("读取选择", "转换结构", "统一检查", "打包候选", "确认并下载 ZIP"):
        assert label in html
```

- [ ] **Step 2: Run the closure test and observe RED**

Run: `python -m pytest tests/acceptance/test_writer_review_workbench_demo.py -q`

Expected: FAIL because `docs/demos/writer-review-workbench.html` does not exist.

- [ ] **Step 3: Implement the self-contained interactive HTML**

Build a fixed `.plugin-window` at 520×720 with CSS grid rows:

```css
.plugin-window {
  width: 520px;
  height: 720px;
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr) auto;
  overflow: hidden;
}
.review-scroll { min-height: 0; overflow-y: auto; overflow-x: hidden; }
.comparison-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.action-footer { position: static; }
```

Use inline SVG/data-free CSS shapes for the two visual previews. JavaScript must switch the count rail, issue rows, acknowledgment state, and approval button for `ready`, `recommended`, and `blocked` without changing the overall geometry.

- [ ] **Step 4: Add the real Edge geometry test**

Launch Edge headlessly at 520×720 and assert literal geometry:

```python
assert measurement["root"]["width"] == 520
assert measurement["root"]["height"] == 720
assert measurement["scrollCount"] == 1
assert measurement["footer"]["top"] >= measurement["review"]["bottom"]
assert len({round(item["width"], 2) for item in measurement["images"]}) == 1
assert len({round(item["top"], 2) for item in measurement["tabs"]}) == 1
```

- [ ] **Step 5: Run acceptance and inspect a screenshot**

Run the focused pytest and save a real-browser screenshot to `docs/demos/writer-review-workbench-preview.png`. Inspect it for clipped copy, tab wrapping, image misalignment, footer overlap, and horizontal overflow.

Expected: tests pass; screenshot shows a readable full-width workbench with aligned evidence.

- [ ] **Step 6: Run repository hygiene and commit**

Run: `python -m pytest tests/acceptance/test_writer_review_workbench_demo.py -q`

Run: `git diff --check`

Expected: all pass and no whitespace errors.

Commit: `feat: demonstrate Writer review workbench`

---

## Plan Self-Review

- Spec coverage: fixed viewport, one scrolling surface, evidence alignment, one-line tabs, three states, accessibility, and self-contained delivery are all covered by Task 1.
- Placeholder scan: no deferred implementation or ambiguous test step remains.
- Interface consistency: HTML selectors used by the browser gate are defined in the implementation step.
