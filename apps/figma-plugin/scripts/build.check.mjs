import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const packageRoot = fileURLToPath(new URL("../", import.meta.url));
const build = () => new Promise((resolve, reject) => execFile(process.execPath, ["scripts/build.mjs"], {
  cwd: packageRoot,
  env: { ...process.env, FGUI_SERVER_ORIGIN: "https://fgui.corp.example", FIGMA_PLUGIN_ID: "123456789" },
}, (error, stdout, stderr) => error ? reject(new Error(stderr || stdout)) : resolve()));
const hash = async (name) => createHash("sha256").update(await readFile(new URL(`../dist/${name}`, import.meta.url))).digest("hex");

test("build sources wire the workflow entry into a non-empty plugin UI", async () => {
  const [script, template, entry] = await Promise.all([
    readFile(new URL("./build.mjs", import.meta.url), "utf8"),
    readFile(new URL("../src/ui.html", import.meta.url), "utf8"),
    readFile(new URL("../../web-console/src/figma/plugin-entry.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(script, /plugin-entry\.tsx/);
  assert.match(script, /styles\.css/);
  assert.match(script, /__PLUGIN_UI_JS__/);
  assert.match(template, /__PLUGIN_UI_CSS__/);
  assert.match(template, /__PLUGIN_UI_JS__/);
  assert.match(entry, /ProjectWorkflowPage/);
  assert.doesNotMatch(template, /location\.replace/);
});

test("checked-in plugin UI artifact contains the bundled workflow", async () => {
  const generatedUi = await readFile(new URL("../dist/ui.html", import.meta.url), "utf8");
  assert.match(generatedUi, /project-workflow/);
  assert.match(generatedUi, /selection-preflight/);
  assert.doesNotMatch(generatedUi, /<style>__PLUGIN_UI_CSS__<\/style>/);
  assert.doesNotMatch(generatedUi, /<script>__PLUGIN_UI_JS__<\/script>/);
});

test("build regenerates fresh deterministic artifacts from the current plugin sources", async () => {
  await build();
  const first = await Promise.all(["manifest.json", "ui.html", "code.js"].map(hash));
  await build();
  const second = await Promise.all(["manifest.json", "ui.html", "code.js"].map(hash));
  assert.deepEqual(second, first);
  const [source, generated] = await Promise.all([
    readFile(new URL("../src/code.ts", import.meta.url), "utf8"),
    readFile(new URL("../dist/code.js", import.meta.url), "utf8"),
  ]);
  for (const contract of ["selection-preflight", "selection-export", "selection-error"]) {
    assert.match(source, new RegExp(contract));
    assert.match(generated, new RegExp(contract));
  }
});
