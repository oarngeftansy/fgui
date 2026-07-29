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
