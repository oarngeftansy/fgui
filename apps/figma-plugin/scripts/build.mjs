import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { buildManifest, normalizeServerOrigin, validatePluginId } from "./build-manifest.mjs";

const origin = normalizeServerOrigin(process.env.FGUI_SERVER_ORIGIN);
const pluginId = validatePluginId(process.env.FIGMA_PLUGIN_ID);
const manifest = buildManifest(origin, pluginId);
const uiTemplate = await readFile(new URL("../src/ui.html", import.meta.url), "utf8");
const frameUrl = new URL("/figma-plugin", `${origin}/`);
frameUrl.searchParams.set("pluginId", pluginId);
const distDir = fileURLToPath(new URL("../dist/", import.meta.url));

await mkdir(distDir, { recursive: true });
await writeFile(new URL("../dist/manifest.json", import.meta.url), `${JSON.stringify(manifest, null, 2)}\n`);
await writeFile(
  new URL("../dist/ui.html", import.meta.url),
  uiTemplate.replace("__PLUGIN_FRAME_URL__", JSON.stringify(frameUrl.toString())),
);
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
    __html__: JSON.stringify(await readFile(new URL("../dist/ui.html", import.meta.url), "utf8")),
  },
});
