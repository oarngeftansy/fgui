import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const packageRoot = fileURLToPath(new URL("../", import.meta.url));
const repositoryRoot = fileURLToPath(new URL("../../../", import.meta.url));
const packageScript = join(repositoryRoot, "packaging", "figma-plugin", "build-package.ps1");
const releaseToken = "not-a-secret-public-test-placeholder-000000";
const childTimeoutMs = 30_000;
const runChild = (step, file, args, options = {}) => {
  const result = spawnSync(file, args, {
  ...options,
  timeout: childTimeoutMs,
  windowsHide: true,
  encoding: "utf8",
  });
  if (!result.error && result.status === 0) return Promise.resolve(result.stdout);
  const message = result.error?.message ?? `exited with ${result.status ?? result.signal ?? "unknown status"}`;
  const timedOut = result.error?.code === "ETIMEDOUT" || /timed out/i.test(message);
  const detail = result.stderr || result.stdout || message;
  return Promise.reject(new Error(`${step} ${timedOut ? `timed out after ${childTimeoutMs}ms` : "failed"}: ${detail}`));
};
const build = (outputDir, token = releaseToken) => runChild("plugin build", process.execPath, ["scripts/build.mjs"], {
  cwd: packageRoot,
  env: {
    ...process.env,
    FGUI_SERVER_ORIGIN: "https://fgui.corp.example",
    FIGMA_PLUGIN_ID: "123456789",
    FGUI_PLUGIN_ACCESS_TOKEN: token,
    FGUI_PLUGIN_DIST_DIR: outputDir,
  },
});
const artifactNames = ["manifest.json", "ui.html", "code.js"];
const readArtifacts = (directory) => Promise.all(artifactNames.map((name) => readFile(join(directory, name))));
const packagePlugin = (pluginDistDir, outputDir) => runChild("PowerShell package build", "powershell", [
  "-NoProfile",
  "-NonInteractive",
  "-ExecutionPolicy",
  "Bypass",
  "-File",
  packageScript,
  "-PluginDistDir",
  pluginDistDir,
  "-OutputDir",
  outputDir,
]);
const zipEntries = (archivePath) => runChild("PowerShell ZIP inspection", "powershell", [
  "-NoProfile",
  "-NonInteractive",
  "-ExecutionPolicy",
  "Bypass",
  "-Command",
  "Add-Type -AssemblyName System.IO.Compression.FileSystem; $archive = [System.IO.Compression.ZipFile]::OpenRead($env:FGUI_PLUGIN_ZIP_FOR_TEST); try { @($archive.Entries | ForEach-Object { [pscustomobject]@{ fullName = $_.FullName; zipTimestampUtc = $_.LastWriteTime.DateTime.ToString('yyyy-MM-ddTHH:mm:ss') + 'Z' } }) | ConvertTo-Json -Compress } finally { $archive.Dispose() }",
], { env: { ...process.env, FGUI_PLUGIN_ZIP_FOR_TEST: archivePath } }).then((stdout) => JSON.parse(stdout));
const sha256 = (content) => createHash("sha256").update(content).digest("hex");

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

test("generated plugin sources contain no retired pairing or Agent workflow", async () => {
  const [script, entry, styles] = await Promise.all([
    readFile(new URL("./build.mjs", import.meta.url), "utf8"),
    readFile(new URL("../../web-console/src/figma/plugin-entry.tsx", import.meta.url), "utf8"),
    readFile(new URL("../../web-console/src/styles.css", import.meta.url), "utf8"),
  ]);
  for (const source of [script, entry, styles]) {
    assert.doesNotMatch(source, /pairing|Web Console|clientStorage|\/v1\/agents\//i);
  }
});

test("build rejects an empty deployment access token", async () => {
  const outputDir = await mkdtemp(join(tmpdir(), "figma-plugin-token-"));
  try {
    await assert.rejects(build(outputDir, ""), /FGUI_PLUGIN_ACCESS_TOKEN/);
  } finally {
    await rm(outputDir, { recursive: true, force: true });
  }
});

test("checked-in plugin distribution matches a fresh plugin-only build", async () => {
  const outputDir = await mkdtemp(join(tmpdir(), "figma-plugin-dist-check-"));
  try {
    await build(outputDir);
    const [freshArtifacts, checkedInArtifacts] = await Promise.all([
      readArtifacts(outputDir),
      readArtifacts(join(packageRoot, "dist")),
    ]);
    for (const [index, artifactName] of artifactNames.entries()) {
      assert.deepEqual(
        checkedInArtifacts[index],
        freshArtifacts[index],
        `apps/figma-plugin/dist/${artifactName} must be regenerated before packaging`,
      );
    }
    for (const bundle of [checkedInArtifacts[1], checkedInArtifacts[2]]) {
      assert.doesNotMatch(bundle.toString("utf8"), /\/v1\/figma\/pairings|\/v1\/agents\/|Web Console|pairing|clientStorage/i);
    }
  } finally {
    await rm(outputDir, { recursive: true, force: true });
  }
});

test("production build and package contain only the install workflow", async () => {
  const buildDirs = [];
  const packageDirs = [];
  try {
    const firstDir = await mkdtemp(join(tmpdir(), "figma-plugin-build-"));
    buildDirs.push(firstDir);
    const secondDir = await mkdtemp(join(tmpdir(), "figma-plugin-build-"));
    buildDirs.push(secondDir);
    await build(firstDir);
    const first = await readArtifacts(firstDir);
    await build(secondDir);
    const second = await readArtifacts(secondDir);
    for (const [index, name] of artifactNames.entries()) assert.deepEqual(second[index], first[index], `${name} is not deterministic`);

    const [manifest, ui, code, readme, deployment, checklist, packageSource] = await Promise.all([
      readFile(join(firstDir, "manifest.json"), "utf8"),
      readFile(join(firstDir, "ui.html"), "utf8"),
      readFile(join(firstDir, "code.js"), "utf8"),
      readFile(join(repositoryRoot, "packaging", "figma-plugin", "README.md"), "utf8"),
      readFile(join(repositoryRoot, "docs", "deployment", "internal-https.md"), "utf8"),
      readFile(join(repositoryRoot, "docs", "acceptance", "figma-plugin-checklist.md"), "utf8"),
      readFile(packageScript, "utf8"),
    ]);
    assert.deepEqual(JSON.parse(manifest).networkAccess.allowedDomains, ["https://fgui.corp.example"]);
    assert.match(ui, new RegExp(releaseToken));
    assert.doesNotMatch(code, new RegExp(releaseToken));
    assert.doesNotMatch(manifest, new RegExp(releaseToken));
    for (const bundle of [ui, code]) {
      assert.doesNotMatch(bundle, /import\s*\(/);
      assert.doesNotMatch(bundle, /\/v1\/figma\/pairings(?:\/exchange)?/i);
      assert.doesNotMatch(bundle, /Web Console/i);
      assert.doesNotMatch(bundle, /(?:\.development\.js|ReactDOM\.render is no longer supported)/);
    }
    for (const secretFreeFile of [readme, deployment, checklist]) assert.doesNotMatch(secretFreeFile, new RegExp(releaseToken));
    assert.match(packageSource, /ZipArchive/);
    assert.doesNotMatch(packageSource, /Compress-Archive/);

    const firstPackageDir = await mkdtemp(join(tmpdir(), "figma-plugin-package-"));
    packageDirs.push(firstPackageDir);
    const secondPackageDir = await mkdtemp(join(tmpdir(), "figma-plugin-package-"));
    packageDirs.push(secondPackageDir);
    await packagePlugin(firstDir, firstPackageDir);
    await packagePlugin(secondDir, secondPackageDir);
    const firstArchive = join(firstPackageDir, "Figma-to-FairyGUI-plugin.zip");
    const secondArchive = join(secondPackageDir, "Figma-to-FairyGUI-plugin.zip");
    assert.deepEqual(await readFile(firstArchive), await readFile(secondArchive), "delivery ZIP is not deterministic");
    assert.deepEqual(await zipEntries(firstArchive), [
      { fullName: "INSTALL.md", zipTimestampUtc: "2000-01-01T00:00:00Z" },
      { fullName: "code.js", zipTimestampUtc: "2000-01-01T00:00:00Z" },
      { fullName: "manifest.json", zipTimestampUtc: "2000-01-01T00:00:00Z" },
      { fullName: "ui.html", zipTimestampUtc: "2000-01-01T00:00:00Z" },
    ]);
    const archive = await readFile(firstArchive);
    const checksum = await readFile(join(firstPackageDir, "checksums.sha256"), "utf8");
    const checksumMatch = /^([a-f0-9]{64}) \*Figma-to-FairyGUI-plugin\.zip\r?\n$/.exec(checksum);
    assert.ok(checksumMatch, "checksums.sha256 has an unexpected format");
    assert.equal(checksumMatch[1], sha256(archive));
  } finally {
    await Promise.all(buildDirs.map((directory) => rm(directory, { recursive: true, force: true })));
    await Promise.all(packageDirs.map((directory) => rm(directory, { recursive: true, force: true })));
  }
});
