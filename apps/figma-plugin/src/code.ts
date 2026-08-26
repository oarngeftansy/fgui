import { isUiToMainMessage, MAX_REVIEW_PREVIEW_BYTES, MAX_SEMANTIC_SCREENSHOT_BYTES } from "./contracts";
import { exportDeclaredAssets } from "./assets";
import { preflightSelection, resourceClipFragments, resourceLookup, serializeSelection, type FigmaSceneNode, type FigmaTransform } from "./selection";

declare const __html__: string;

type PluginRuntime = {
  showUI(html: string, options: { width: number; height: number }): void;
  currentPage?: { selection: readonly FigmaSceneNode[]; children?: readonly FigmaSceneNode[] };
  getNodeByIdAsync?(id: string): Promise<FigmaSceneNode | null>;
  viewport?: { scrollAndZoomIntoView(nodes: readonly FigmaSceneNode[]): void };
  createFrame(): ScreenshotFrameNode;
  createRectangle?(): ReviewRectangleNode;
  createImage?(bytes: Uint8Array): { hash: string };
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

type ScreenshotCloneNode = FigmaSceneNode & {
  x: number;
  y: number;
  relativeTransform: FigmaTransform;
  remove(): void;
};

type ScreenshotFrameNode = ScreenshotExportNode & {
  x: number;
  y: number;
  fills: readonly unknown[] | symbol;
  layoutMode: string;
  clipsContent: boolean;
  resize(width: number, height: number): void;
  appendChild(child: BaseNode): void;
  remove(): void;
};

type ScreenshotBounds = { x: number; y: number; width: number; height: number };

type ReviewCloneNode = FigmaSceneNode & { x: number; y: number; remove(): void };
type ReviewRectangleNode = FigmaSceneNode & { x: number; y: number; fills: readonly unknown[] | symbol; resize(width: number, height: number): void; remove(): void };
type OwnedReviewFrame = ScreenshotFrameNode & { getPluginData(key: string): string; setPluginData(key: string, value: string): void };

const MAX_SCREENSHOT_DIMENSION = 4096;
const MAX_SCREENSHOT_PIXELS = 16_000_000;
const PNG_SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10] as const;

function sameSelection(runtime: PluginRuntime, expected: readonly FigmaSceneNode[]): boolean {
  const current = runtime.currentPage?.selection ?? [];
  if (current.length !== expected.length) return false;
  const expectedMembers = new Set(expected);
  const currentMembers = new Set(current);
  if (expectedMembers.size !== expected.length || currentMembers.size !== current.length) return false;
  return [...expectedMembers].every((node) => currentMembers.has(node));
}

function nodeBounds(node: FigmaSceneNode): ScreenshotBounds | null {
  const bounds = node.absoluteRenderBounds ?? node.absoluteBoundingBox;
  return bounds && [bounds.x, bounds.y, bounds.width, bounds.height].every(Number.isFinite) && bounds.width > 0 && bounds.height > 0
    ? bounds
    : null;
}

function validTransform(value: FigmaTransform | undefined): value is FigmaTransform {
  return Boolean(value
    && value.length === 2
    && value[0].length === 3
    && value[1].length === 3
    && [...value[0], ...value[1]].every(Number.isFinite));
}

function rigidTransform(value: FigmaTransform | undefined): value is FigmaTransform {
  if (!validTransform(value)) return false;
  const [a, c] = value[0];
  const [b, d] = value[1];
  const tolerance = 1e-4;
  const close = (left: number, right: number) => Math.abs(left - right) <= tolerance;
  return close(Math.hypot(a, b), 1)
    && close(Math.hypot(c, d), 1)
    && close(a * c + b * d, 0)
    && close(Math.abs(a * d - b * c), 1);
}

function selectedBounds(nodes: readonly FigmaSceneNode[]): ScreenshotBounds | null {
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const node of nodes) {
    const bounds = nodeBounds(node);
    if (!bounds) return null;
    left = Math.min(left, bounds.x);
    top = Math.min(top, bounds.y);
    right = Math.max(right, bounds.x + bounds.width);
    bottom = Math.max(bottom, bounds.y + bounds.height);
  }
  const result = { x: left, y: top, width: right - left, height: bottom - top };
  return nodes.length && Number.isFinite(result.width) && Number.isFinite(result.height) ? result : null;
}

function rootsOverlap(nodes: readonly FigmaSceneNode[]): boolean {
  const bounds = nodes.map(nodeBounds);
  for (let leftIndex = 0; leftIndex < bounds.length; leftIndex += 1) {
    const left = bounds[leftIndex]!;
    if (!left) return true;
    for (let rightIndex = leftIndex + 1; rightIndex < bounds.length; rightIndex += 1) {
      const right = bounds[rightIndex]!;
      if (!right) return true;
      const horizontal = Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x);
      const vertical = Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y);
      if (horizontal > 0 && vertical > 0) return true;
    }
  }
  return false;
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

async function exportClippedFragment(
  runtime: PluginRuntime,
  source: FigmaSceneNode,
  clip: ScreenshotBounds,
): Promise<Uint8Array> {
  const cloneSource = source as FigmaSceneNode & { clone?: () => ScreenshotCloneNode };
  if (!screenshotBoundsAllowed(clip) || !rigidTransform(source.absoluteTransform) || typeof cloneSource.clone !== "function") throw new Error("unsupported clipped fragment");
  const frame = runtime.createFrame();
  let clone: ScreenshotCloneNode | null = null;
  let attached = false;
  let bytes: Uint8Array | null = null;
  let cleanupFailed = false;
  try {
    frame.name = "Temporary clipped export";
    frame.fills = [];
    frame.layoutMode = "NONE";
    frame.clipsContent = true;
    frame.x = clip.x;
    frame.y = clip.y;
    frame.resize(clip.width, clip.height);
    clone = cloneSource.clone!();
    if (!clone || typeof clone.remove !== "function" || !validTransform(clone.relativeTransform)) throw new Error("unsupported clipped clone");
    clone.visible = true;
    frame.appendChild(clone as unknown as BaseNode);
    attached = true;
    const transform = source.absoluteTransform!;
    clone.relativeTransform = [
      [transform[0][0], transform[0][1], transform[0][2] - clip.x],
      [transform[1][0], transform[1][1], transform[1][2] - clip.y],
    ];
    bytes = await frame.exportAsync({ format: "PNG", constraint: { type: "SCALE", value: 1 } });
    if (pngError(bytes)) throw new Error("invalid clipped PNG");
  } finally {
    let frameRemoved = false;
    try { frame.remove(); frameRemoved = true; } catch { cleanupFailed = true; }
    if (clone && (!attached || !frameRemoved)) try { clone.remove(); } catch { cleanupFailed = true; }
  }
  if (cleanupFailed || !bytes) throw new Error("clipped export cleanup failed");
  return bytes;
}

export function startPlugin(runtime: PluginRuntime): void {
  runtime.showUI(__html__, { width: 640, height: 800 });
  let prepared: SelectionSnapshot | null = null;
  const attempts = new Map<string, SelectionSnapshot>();
  let blockedCode = "selection_export_failed";
  let locatedSelection: { attempt: string; nodeId: string } | null = null;
  const refresh = (type: "selection-preflight" | "selection-changed") => {
    const snapshot = runtime.currentPage ? [...runtime.currentPage.selection] : [];
    const preflight = preflightSelection(snapshot);
    prepared = preflight.manifest ? { manifest: preflight.manifest, lookup: resourceLookup(snapshot, preflight.manifest), roots: snapshot } : null;
    blockedCode = preflight.warnings[0]?.code ?? "selection_export_failed";
    const locateAttempt = type === "selection-changed" && locatedSelection && snapshot.length === 1 && (snapshot[0] as { id?: string } | undefined)?.id === locatedSelection.nodeId ? locatedSelection.attempt : undefined;
    if (type === "selection-changed") locatedSelection = null;
    runtime.ui.postMessage({ type, preflight, ...(locateAttempt ? { locateAttempt } : {}) }, { origin: "*" });
  };
  runtime.ui.onmessage = (message: unknown, _props: OnMessageProperties) => {
    if (!isUiToMainMessage(message)) return;
    if (message.type === "selection-preflight") {
      refresh("selection-preflight");
      return;
    }
    if (message.type === "locate-node") {
      void runtime.getNodeByIdAsync?.(message.nodeId).then((node) => {
        if (!node || !runtime.currentPage) return;
        locatedSelection = { attempt: message.attempt, nodeId: message.nodeId };
        (runtime.currentPage as { selection: FigmaSceneNode[] }).selection = [node];
        runtime.viewport?.scrollAndZoomIntoView([node]);
      });
      return;
    }
    if (message.type === "create-review-area") {
      void (async () => {
        const fail = () => runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "review_area_failed" }, { origin: "*" });
        if (!runtime.currentPage || !runtime.getNodeByIdAsync || !runtime.createRectangle || !runtime.createImage) { fail(); return; }
        const liveBounds = selectedBounds(runtime.currentPage.selection);
        const source = await runtime.getNodeByIdAsync(message.nodeId) as (FigmaSceneNode & { clone?: () => ReviewCloneNode }) | null;
        const sourceBounds = source ? nodeBounds(source) : null;
        if (!liveBounds || !source || !sourceBounds || typeof source.clone !== "function") { fail(); return; }
        if (message.previewBytes.length > MAX_REVIEW_PREVIEW_BYTES || pngError(message.previewBytes)
          || new DataView(message.previewBytes.buffer, message.previewBytes.byteOffset, message.previewBytes.byteLength).getUint32(16) !== message.previewWidth
          || new DataView(message.previewBytes.buffer, message.previewBytes.byteOffset, message.previewBytes.byteLength).getUint32(20) !== message.previewHeight) { fail(); return; }
        const existing = runtime.currentPage.children?.find((node) => {
          const candidate = node as FigmaSceneNode & { getPluginData?: (key: string) => string };
          return candidate.name === "FairyGUI 待审核" && candidate.type === "FRAME" && candidate.getPluginData?.("figma-to-fgui.review-area") === "v1";
        }) as (FigmaSceneNode & { remove?: () => void }) | undefined;
        let frame: ScreenshotFrameNode | null = null;
        try {
          frame = runtime.createFrame();
          frame.name = "FairyGUI 待审核（更新中）";
          const ownedFrame = frame as OwnedReviewFrame;
          if (typeof ownedFrame.setPluginData !== "function") throw new Error("review ownership unavailable");
          ownedFrame.setPluginData("figma-to-fgui.review-area", "v1");
          frame.fills = [];
          frame.layoutMode = "NONE";
          frame.clipsContent = false;
          const padding = 24;
          const gap = 32;
          const targetWidth = sourceBounds.width;
          const targetHeight = sourceBounds.height;
          frame.x = liveBounds.x + liveBounds.width + 160;
          frame.y = liveBounds.y;
          frame.resize(padding * 2 + targetWidth * 2 + gap, padding * 2 + targetHeight);
          const clone = source.clone();
          if (!clone || typeof clone.remove !== "function" || typeof clone.x !== "number" || typeof clone.y !== "number") throw new Error("unsupported review clone");
          frame.appendChild(clone as unknown as BaseNode);
          clone.x = padding;
          clone.y = padding;
          const imageHash = runtime.createImage(message.previewBytes).hash;
          const generated = runtime.createRectangle();
          generated.resize(targetWidth, targetHeight);
          generated.x = padding + targetWidth + gap;
          generated.y = padding;
          generated.fills = [{ type: "IMAGE", imageHash, scaleMode: "FIT" }];
          frame.appendChild(generated as unknown as BaseNode);
          existing?.remove?.();
          frame.name = "FairyGUI 待审核";
          runtime.viewport?.scrollAndZoomIntoView([frame]);
          runtime.ui.postMessage({ type: "review-area-created", attempt: message.attempt }, { origin: "*" });
        } catch {
          try { frame?.remove(); } catch { /* best-effort removal of the new review frame */ }
          fail();
        }
      })();
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
          const fragments = resourceClipFragments(snapshot.manifest);
          for await (const resource of exportDeclaredAssets(snapshot.manifest, snapshot.lookup, async (node, key, format) => {
            const clip = fragments.get(key);
            if (clip) {
              if (format !== "PNG") throw new Error("clipped fragments require PNG");
              return exportClippedFragment(runtime, node, clip);
            }
            if (node.visible === false) {
              const isolatedBounds = nodeBounds(node);
              if (format !== "PNG" || !isolatedBounds) throw new Error("hidden resources require isolated PNG export");
              return exportClippedFragment(runtime, node, isolatedBounds);
            }
            return (node as FigmaSceneNode & { exportAsync(settings: { format: "PNG" | "SVG" }): Promise<Uint8Array> }).exportAsync({ format });
          })) resources.push(resource);
          const mimeTypes = new Map(resources.map((resource) => [resource.key, resource.mime_type]));
          const manifest = {
            ...snapshot.manifest,
            resources: snapshot.manifest.resources.map((resource) => ({
              ...resource,
              mime_type: mimeTypes.get(resource.key) ?? resource.mime_type,
            })),
          };
          runtime.ui.postMessage({ type: "selection-export", attempt: message.attempt, manifest, resources }, { origin: "*" });
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
        if (snapshot.roots.length > 1 && rootsOverlap(snapshot.roots)) {
          runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" });
          return;
        }
        const directNode = snapshot.roots.length === 1 ? snapshot.roots[0] as ScreenshotExportNode : null;
        if (directNode && typeof directNode.exportAsync !== "function") {
          runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" });
          return;
        }
        const isolatedRoots = directNode ? null : snapshot.roots.map((root) => {
          const source = root as FigmaSceneNode & { clone?: () => ScreenshotCloneNode };
          const rootBounds = nodeBounds(root);
          return rootBounds && rigidTransform(root.absoluteTransform) && typeof source.clone === "function"
            ? { source, transform: root.absoluteTransform }
            : null;
        });
        if (isolatedRoots?.some((root) => !root)) {
          runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" });
          return;
        }
        let frame: ScreenshotFrameNode | null = null;
        const clones: ScreenshotCloneNode[] = [];
        const attachedClones = new Set<ScreenshotCloneNode>();
        let screenshotBytes: Uint8Array | null = null;
        let failureCode: "selection_changed" | "selection_export_failed" | "selection_too_large" | null = null;
        try {
          if (!directNode) {
            frame = runtime.createFrame();
            frame.name = "Temporary isolated screenshot";
            frame.fills = [];
            frame.layoutMode = "NONE";
            frame.clipsContent = true;
            frame.x = bounds.x;
            frame.y = bounds.y;
            frame.resize(bounds.width, bounds.height);
            for (const isolated of isolatedRoots!) {
              const { source, transform } = isolated!;
              const clone = source.clone!();
              if (!clone || typeof clone.remove !== "function") throw new Error("unsupported screenshot clone");
              clones.push(clone);
              if (typeof clone.x !== "number" || typeof clone.y !== "number" || !validTransform(clone.relativeTransform)) throw new Error("unsupported screenshot clone");
              frame.appendChild(clone as unknown as BaseNode);
              attachedClones.add(clone);
              clone.relativeTransform = [
                [transform[0][0], transform[0][1], transform[0][2] - bounds.x],
                [transform[1][0], transform[1][1], transform[1][2] - bounds.y],
              ];
            }
          }
          if (!sameSelection(runtime, snapshot.roots)) {
            failureCode = "selection_changed";
          } else {
            const node = directNode ?? frame!;
            const bytes = await node.exportAsync({ format: "PNG", constraint: { type: "SCALE", value: 1 } });
            if (!sameSelection(runtime, snapshot.roots)) {
              failureCode = "selection_changed";
            } else if (!bytes.length || bytes.length > MAX_SEMANTIC_SCREENSHOT_BYTES) {
              failureCode = bytes.length ? "selection_too_large" : "selection_export_failed";
            } else {
              failureCode = pngError(bytes);
              if (!failureCode) screenshotBytes = bytes;
            }
          }
        } catch {
          failureCode = "selection_export_failed";
        }
        let frameRemoved = false;
        let cleanupFailed = false;
        if (frame) {
          try {
            frame.remove();
            frameRemoved = true;
          } catch {
            cleanupFailed = true;
          }
        }
        for (let index = clones.length - 1; index >= 0; index -= 1) {
          const clone = clones[index]!;
          if (frameRemoved && attachedClones.has(clone)) continue;
          try { clone.remove(); } catch { cleanupFailed = true; }
        }
        if (cleanupFailed) failureCode = "selection_export_failed";
        if (failureCode || !screenshotBytes) {
          runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: failureCode ?? "selection_export_failed" }, { origin: "*" });
        } else {
          runtime.ui.postMessage({ type: "semantic-screenshot-export", attempt: message.attempt, mimeType: "image/png", bytes: screenshotBytes }, { origin: "*" });
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
