import { isUiToMainMessage, MAX_SEMANTIC_SCREENSHOT_BYTES } from "./contracts";
import { exportDeclaredAssets } from "./assets";
import { preflightSelection, resourceLookup, serializeSelection, type FigmaSceneNode } from "./selection";

declare const __html__: string;

type PluginRuntime = {
  showUI(html: string, options: { width: number; height: number }): void;
  currentPage?: { selection: readonly FigmaSceneNode[] };
  on(event: "selectionchange", callback: () => void): void;
  ui: {
    onmessage?: (message: unknown, props: OnMessageProperties) => void;
    postMessage(message: unknown, options: { origin: string }): void;
  };
};

type SelectionSnapshot = {
  manifest: ReturnType<typeof serializeSelection>;
  lookup: ReadonlyMap<string, FigmaSceneNode>;
  roots: readonly FigmaSceneNode[];
};

type ScreenshotExportNode = FigmaSceneNode & {
  exportAsync(settings: { format: "PNG"; constraint: { type: "SCALE"; value: 1 } }): Promise<Uint8Array>;
};

const MAX_SCREENSHOT_DIMENSION = 4096;
const MAX_SCREENSHOT_PIXELS = 4096 * 4096;

function sameSelection(runtime: PluginRuntime, expected: readonly FigmaSceneNode[]): boolean {
  const current = runtime.currentPage?.selection ?? [];
  return current.length === expected.length && current.every((node, index) => node === expected[index]);
}

function screenshotBoundsAllowed(node: FigmaSceneNode): boolean {
  const bounds = node.absoluteBoundingBox;
  return Boolean(
    bounds
    && Number.isFinite(bounds.width)
    && Number.isFinite(bounds.height)
    && bounds.width > 0
    && bounds.height > 0
    && bounds.width <= MAX_SCREENSHOT_DIMENSION
    && bounds.height <= MAX_SCREENSHOT_DIMENSION
    && bounds.width * bounds.height <= MAX_SCREENSHOT_PIXELS
  );
}

export function startPlugin(runtime: PluginRuntime): void {
  runtime.showUI(__html__, { width: 360, height: 460 });
  let prepared: SelectionSnapshot | null = null;
  const attempts = new Map<string, SelectionSnapshot>();
  let blockedCode = "selection_export_failed";
  const refresh = (type: "selection-preflight" | "selection-changed") => {
    const snapshot = runtime.currentPage ? [...runtime.currentPage.selection] : [];
    const preflight = preflightSelection(snapshot);
    prepared = preflight.manifest ? { manifest: preflight.manifest, lookup: resourceLookup(snapshot, preflight.manifest), roots: snapshot } : null;
    blockedCode = preflight.warnings[0]?.code ?? "selection_export_failed";
    runtime.ui.postMessage({ type, preflight }, { origin: "*" });
  };
  runtime.ui.onmessage = (message: unknown, _props: OnMessageProperties) => {
    if (!isUiToMainMessage(message)) return;
    if (message.type === "selection-preflight") {
      refresh("selection-preflight");
      return;
    }
    if (message.type === "selection-export") {
      const snapshot = prepared;
      if (snapshot) {
        attempts.set(message.attempt, snapshot);
        if (attempts.size > 8) attempts.delete(attempts.keys().next().value!);
      }
      void (async () => {
        if (!snapshot) { runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: blockedCode }, { origin: "*" }); return; }
        try {
          const resources = [];
          for await (const resource of exportDeclaredAssets(snapshot.manifest, snapshot.lookup)) resources.push(resource);
          runtime.ui.postMessage({ type: "selection-export", attempt: message.attempt, manifest: snapshot.manifest, resources }, { origin: "*" });
        } catch { runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" }); }
      })();
      return;
    }
    if (message.type === "semantic-screenshot-export") {
      const snapshot = attempts.get(message.attempt);
      void (async () => {
        if (!snapshot) {
          const code = (runtime.currentPage?.selection.length ?? 0) === 0 ? "selection_empty" : "selection_changed";
          runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code }, { origin: "*" });
          return;
        }
        if (!sameSelection(runtime, snapshot.roots)) {
          runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_changed" }, { origin: "*" });
          return;
        }
        if (snapshot.roots.length !== 1 || !screenshotBoundsAllowed(snapshot.roots[0]!)) {
          runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_too_large" }, { origin: "*" });
          return;
        }
        const node = snapshot.roots[0] as ScreenshotExportNode;
        if (typeof node.exportAsync !== "function") {
          runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" });
          return;
        }
        try {
          const bytes = await node.exportAsync({ format: "PNG", constraint: { type: "SCALE", value: 1 } });
          if (!sameSelection(runtime, snapshot.roots)) {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_changed" }, { origin: "*" });
          } else if (!bytes.length || bytes.length > MAX_SEMANTIC_SCREENSHOT_BYTES) {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: bytes.length ? "selection_too_large" : "selection_export_failed" }, { origin: "*" });
          } else {
            runtime.ui.postMessage({ type: "semantic-screenshot-export", attempt: message.attempt, mimeType: "image/png", bytes }, { origin: "*" });
          }
        } catch {
          runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" });
        }
      })();
    }
  };
  runtime.on("selectionchange", () => refresh("selection-changed"));
  refresh("selection-preflight");
}

if (typeof figma !== "undefined") {
  startPlugin(figma);
}
