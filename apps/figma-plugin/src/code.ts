import { isUiToMainMessage, MAX_SEMANTIC_SCREENSHOT_BYTES } from "./contracts";
import { exportDeclaredAssets } from "./assets";
import { preflightSelection, resourceLookup, serializeSelection, type FigmaSceneNode } from "./selection";

declare const __html__: string;

type PluginRuntime = {
  showUI(html: string, options: { width: number; height: number }): void;
  currentPage?: { selection: readonly FigmaSceneNode[] };
  createSlice(): ScreenshotSliceNode;
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

type ScreenshotSliceNode = ScreenshotExportNode & {
  x: number;
  y: number;
  resize(width: number, height: number): void;
  remove(): void;
};

type ScreenshotBounds = { x: number; y: number; width: number; height: number };

const MAX_SCREENSHOT_DIMENSION = 4096;
const MAX_SCREENSHOT_PIXELS = 16_000_000;
const PNG_SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10] as const;

function sameSelection(runtime: PluginRuntime, expected: readonly FigmaSceneNode[]): boolean {
  const current = runtime.currentPage?.selection ?? [];
  return current.length === expected.length && current.every((node, index) => node === expected[index]);
}

function selectedBounds(nodes: readonly FigmaSceneNode[]): ScreenshotBounds | null {
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const node of nodes) {
    const bounds = node.absoluteRenderBounds ?? node.absoluteBoundingBox;
    if (!bounds || ![bounds.x, bounds.y, bounds.width, bounds.height].every(Number.isFinite) || bounds.width <= 0 || bounds.height <= 0) return null;
    left = Math.min(left, bounds.x);
    top = Math.min(top, bounds.y);
    right = Math.max(right, bounds.x + bounds.width);
    bottom = Math.max(bottom, bounds.y + bounds.height);
  }
  const result = { x: left, y: top, width: right - left, height: bottom - top };
  return nodes.length && Number.isFinite(result.width) && Number.isFinite(result.height) ? result : null;
}

function screenshotBoundsAllowed(bounds: ScreenshotBounds): boolean {
  return bounds.width > 0
    && bounds.height > 0
    && bounds.width <= MAX_SCREENSHOT_DIMENSION
    && bounds.height <= MAX_SCREENSHOT_DIMENSION
    && bounds.width * bounds.height <= MAX_SCREENSHOT_PIXELS;
}

function pngError(bytes: Uint8Array): "selection_export_failed" | "selection_too_large" | null {
  if (bytes.length < 24 || PNG_SIGNATURE.some((value, index) => bytes[index] !== value)) return "selection_export_failed";
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (view.getUint32(8) !== 13 || bytes[12] !== 73 || bytes[13] !== 72 || bytes[14] !== 68 || bytes[15] !== 82) return "selection_export_failed";
  const width = view.getUint32(16);
  const height = view.getUint32(20);
  if (!width || !height) return "selection_export_failed";
  if (width > MAX_SCREENSHOT_DIMENSION || height > MAX_SCREENSHOT_DIMENSION || width * height > MAX_SCREENSHOT_PIXELS) return "selection_too_large";
  return null;
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
        const bounds = selectedBounds(snapshot.roots);
        if (!bounds) {
          runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" });
          return;
        }
        if (!screenshotBoundsAllowed(bounds)) {
          runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_too_large" }, { origin: "*" });
          return;
        }
        const directNode = snapshot.roots.length === 1 ? snapshot.roots[0] as ScreenshotExportNode : null;
        if (directNode && typeof directNode.exportAsync !== "function") {
          runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" });
          return;
        }
        let slice: ScreenshotSliceNode | null = null;
        try {
          if (!directNode) {
            slice = runtime.createSlice();
            slice.x = bounds.x;
            slice.y = bounds.y;
            slice.resize(bounds.width, bounds.height);
          }
          const node = directNode ?? slice!;
          const bytes = await node.exportAsync({ format: "PNG", constraint: { type: "SCALE", value: 1 } });
          if (!sameSelection(runtime, snapshot.roots)) {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_changed" }, { origin: "*" });
          } else if (!bytes.length || bytes.length > MAX_SEMANTIC_SCREENSHOT_BYTES) {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: bytes.length ? "selection_too_large" : "selection_export_failed" }, { origin: "*" });
          } else {
            const code = pngError(bytes);
            runtime.ui.postMessage(code
              ? { type: "selection-error", attempt: message.attempt, code }
              : { type: "semantic-screenshot-export", attempt: message.attempt, mimeType: "image/png", bytes }, { origin: "*" });
          }
        } catch {
          runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" });
        } finally {
          slice?.remove();
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
