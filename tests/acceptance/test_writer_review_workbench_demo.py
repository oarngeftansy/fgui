from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
DEMO = REPO_ROOT / "docs" / "demos" / "writer-review-workbench.html"


def test_writer_review_workbench_demo_is_self_contained() -> None:
    html = DEMO.read_text("utf-8")
    assert "https://" not in html and "http://" not in html
    assert "<link" not in html.lower()
    assert "<img" not in html.lower()
    assert 'data-scenario="ready"' in html
    assert 'data-scenario="recommended"' in html
    assert 'data-scenario="blocked"' in html
    assert 'class="review-scroll"' in html
    assert 'class="comparison-grid"' in html
    assert 'class="action-footer"' in html
    for label in (
        "读取选择",
        "转换结构",
        "统一检查",
        "打包候选",
        "自动转换",
        "建议审核",
        "必须处理",
        "确认并下载 ZIP",
    ):
        assert label in html


def test_writer_review_workbench_demo_fits_real_edge_viewport(tmp_path: Path) -> None:
    node = (
        Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    )
    edge = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
    if not node.is_file() or not edge.is_file():
        pytest.skip("requires the Codex Node runtime and local Microsoft Edge")
    playwright = node.parents[1] / "node_modules/playwright-core"
    screenshot = tmp_path / "workbench.png"
    script = f"""
const {{ chromium }} = require({json.dumps(str(playwright))});
(async () => {{
  const browser = await chromium.launch({{ executablePath: {json.dumps(str(edge))}, headless: true }});
  const page = await browser.newPage({{ viewport: {{ width: 520, height: 720 }}, deviceScaleFactor: 1 }});
  await page.goto({json.dumps(DEMO.resolve().as_uri())});
  await page.screenshot({{ path: {json.dumps(str(screenshot))} }});
  const measurement = await page.evaluate(() => {{
    const box = (selector) => document.querySelector(selector).getBoundingClientRect().toJSON();
    const scrollCount = [...document.querySelectorAll('*')].filter((element) => {{
      const style = getComputedStyle(element);
      return ['auto', 'scroll'].includes(style.overflowY) && element.scrollHeight > element.clientHeight;
    }}).length;
    return {{
      root: box('.plugin-window'),
      review: box('.review-scroll'),
      footer: box('.action-footer'),
      scrollCount,
      documentWidth: document.documentElement.scrollWidth,
      tabs: [...document.querySelectorAll('[role=tab]')].map((element) => element.getBoundingClientRect().toJSON()),
      previews: [...document.querySelectorAll('.preview-canvas')].map((element) => element.getBoundingClientRect().toJSON()),
    }};
  }});
  const states = [];
  for (const scenario of ['ready', 'recommended', 'blocked']) {{
    await page.click(`[data-scenario="${{scenario}}"]`);
    states.push(await page.evaluate((name) => ({{
      name,
      automatic: Number(document.querySelector('#automatic-count').textContent),
      recommended: Number(document.querySelector('#recommended-count').textContent),
      blocked: Number(document.querySelector('#blocked-count').textContent),
      approvalDisabled: document.querySelector('#approve').disabled,
      acknowledgmentVisible: !document.querySelector('#ack-row').classList.contains('hidden'),
    }}), scenario));
  }}
  await browser.close();
  process.stdout.write(JSON.stringify({{ measurement, states }}));
}})().catch((error) => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(
        [str(node), "-e", script], capture_output=True, check=False, text=True
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    measurement = result["measurement"]
    assert measurement["root"]["width"] == 520
    assert measurement["root"]["height"] == 720
    assert measurement["documentWidth"] == 520
    assert measurement["scrollCount"] == 1
    assert measurement["footer"]["top"] >= measurement["review"]["bottom"]
    assert len({round(item["width"], 2) for item in measurement["previews"]}) == 1
    assert len({round(item["top"], 2) for item in measurement["previews"]}) == 1
    assert len({round(item["top"], 2) for item in measurement["tabs"]}) == 1
    assert result["states"] == [
        {
            "name": "ready",
            "automatic": 21,
            "recommended": 0,
            "blocked": 0,
            "approvalDisabled": False,
            "acknowledgmentVisible": False,
        },
        {
            "name": "recommended",
            "automatic": 18,
            "recommended": 3,
            "blocked": 0,
            "approvalDisabled": True,
            "acknowledgmentVisible": True,
        },
        {
            "name": "blocked",
            "automatic": 18,
            "recommended": 2,
            "blocked": 1,
            "approvalDisabled": True,
            "acknowledgmentVisible": False,
        },
    ]
    assert screenshot.is_file() and screenshot.stat().st_size > 10_000
