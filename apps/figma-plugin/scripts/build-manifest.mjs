import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const templatePath = fileURLToPath(new URL("../manifest.template.json", import.meta.url));

export function normalizeServerOrigin(value) {
  if (typeof value !== "string" || value.includes("*") || value.includes(",")) {
    throw new Error("FGUI_SERVER_ORIGIN must be one HTTPS origin");
  }
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("FGUI_SERVER_ORIGIN must be one HTTPS origin");
  }
  if (
    parsed.protocol !== "https:" ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error("FGUI_SERVER_ORIGIN must be one HTTPS origin");
  }
  return parsed.origin;
}

export function validatePluginId(value) {
  if (typeof value !== "string" || !/^\d+$/.test(value)) {
    throw new Error("FIGMA_PLUGIN_ID must be an explicit numeric plugin ID");
  }
  return value;
}

export function buildManifest(serverOrigin, pluginId) {
  const origin = normalizeServerOrigin(serverOrigin);
  const id = validatePluginId(pluginId);
  const template = JSON.parse(readFileSync(templatePath, "utf8"));
  return {
    ...template,
    id,
    networkAccess: { allowedDomains: [origin] },
  };
}
