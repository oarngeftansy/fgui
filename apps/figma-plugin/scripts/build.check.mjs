import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const packageRoot = fileURLToPath(new URL("../", import.meta.url));
const build = (outputDir) => new Promise((resolve, reject) => execFile(process.execPath, ["scripts/build.mjs"], {
  cwd: packageRoot,
  env: { ...process.env, FGUI_SERVER_ORIGIN: "https://fgui.corp.example", FIGMA_PLUGIN_ID: "123456789", FGUI_PLUGIN_DIST_DIR: outputDir },
}, (error, stdout, stderr) => error ? reject(new Error(stderr || stdout)) : resolve()));
const artifactNames = ["manifest.json", "ui.html", "code.js"];
const checkedInDist = fileURLToPath(new URL("../dist/", import.meta.url));
const readArtifacts = (directory) => Promise.all(artifactNames.map((name) => readFile(join(directory, name))));

test("build sources wire the workflow entry into a non-empty plugin UI", async () => {
  const [script, check, template, entry] = await Promise.all([
    readFile(new URL("./build.mjs", import.meta.url), "utf8"),
    readFile(new URL("./build.check.mjs", import.meta.url), "utf8"),
    readFile(new URL("../src/ui.html", import.meta.url), "utf8"),
    readFile(new URL("../../web-console/src/figma/plugin-entry.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(script, /plugin-entry\.tsx/);
  assert.match(script, /styles\.css/);
  assert.match(script, /__PLUGIN_UI_JS__/);
  assert.match(script, /FGUI_PLUGIN_DIST_DIR/);
  assert.match(check, /mkdtemp/);
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
  const checkedIn = await readArtifacts(checkedInDist);
  const buildDirs = [];
  try {
    const firstDir = await mkdtemp(join(tmpdir(), "figma-plugin-build-"));
    buildDirs.push(firstDir);
    const secondDir = await mkdtemp(join(tmpdir(), "figma-plugin-build-"));
    buildDirs.push(secondDir);
    await build(firstDir);
    const first = await readArtifacts(firstDir);
    for (const [index, name] of artifactNames.entries()) assert.deepEqual(first[index], checkedIn[index], `${name} is stale`);

    await build(secondDir);
    const second = await readArtifacts(secondDir);
    for (const [index, name] of artifactNames.entries()) assert.deepEqual(second[index], first[index], `${name} is not deterministic`);

    const [source, generated] = await Promise.all([
      readFile(new URL("../src/code.ts", import.meta.url), "utf8"),
      readFile(join(firstDir, "code.js"), "utf8"),
    ]);
    for (const contract of ["selection-preflight", "selection-export", "selection-error"]) {
      assert.match(source, new RegExp(contract));
      assert.match(generated, new RegExp(contract));
    }
  } finally {
    await Promise.all(buildDirs.map((directory) => rm(directory, { recursive: true, force: true })));
  }
});
