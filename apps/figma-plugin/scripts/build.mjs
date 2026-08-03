import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { buildManifest, normalizeServerOrigin, validatePluginId } from "./build-manifest.mjs";

const origin = normalizeServerOrigin(process.env.FGUI_SERVER_ORIGIN);
const pluginId = validatePluginId(process.env.FIGMA_PLUGIN_ID);
const manifest = buildManifest(origin, pluginId);
const uiTemplate = await readFile(new URL("../src/ui.html", import.meta.url), "utf8");
const distDir = fileURLToPath(new URL("../dist/", import.meta.url));

await mkdir(distDir, { recursive: true });
await writeFile(new URL("../dist/manifest.json", import.meta.url), `${JSON.stringify(manifest, null, 2)}\n`);
const uiBuild = await build({
  entryPoints: [fileURLToPath(new URL("../../web-console/src/figma/plugin-entry.tsx", import.meta.url))],
  outfile: "plugin-ui.js",
  write: false,
  bundle: true,
  format: "iife",
  platform: "browser",
  target: "es2022",
  legalComments: "none",
  define: {
    __FGUI_SERVER_ORIGIN__: JSON.stringify(origin),
    // Task 8 owns deployment-token injection; this keeps the current development bundle executable.
    __FGUI_PLUGIN_ACCESS_TOKEN__: JSON.stringify(""),
  },
});
const uiJavaScript = uiBuild.outputFiles.find((file) => file.path.endsWith(".js"))?.text;
if (!uiJavaScript) throw new Error("plugin UI bundle was not generated");
const uiCss = await readFile(new URL("../../web-console/src/styles.css", import.meta.url), "utf8");
const uiHtml = uiTemplate
  .replace("__PLUGIN_UI_CSS__", uiCss.replace(/<\/style/giu, "<\\/style"))
  .replace("__PLUGIN_UI_JS__", uiJavaScript.replace(/<\/script/giu, "<\\/script"));
await writeFile(new URL("../dist/ui.html", import.meta.url), uiHtml);
await build({
  entryPoints: [fileURLToPath(new URL("../src/code.ts", import.meta.url))],
  outfile: fileURLToPath(new URL("../dist/code.js", import.meta.url)),
  bundle: true,
  format: "iife",
  platform: "browser",
  target: "es2022",
  define: {
    __FGUI_SERVER_ORIGIN__: JSON.stringify(origin),
    __FIGMA_PLUGIN_ID__: JSON.stringify(pluginId),
    __html__: JSON.stringify(uiHtml),
  },
});
