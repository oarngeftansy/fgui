import { isUiToMainMessage } from "./contracts";
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

export function startPlugin(runtime: PluginRuntime): void {
  runtime.showUI(__html__, { width: 360, height: 460 });
  let prepared: { manifest: ReturnType<typeof serializeSelection>; lookup: ReadonlyMap<string, FigmaSceneNode> } | null = null;
  let blockedCode = "selection_export_failed";
  const refresh = (type: "selection-preflight" | "selection-changed") => {
    const snapshot = runtime.currentPage ? [...runtime.currentPage.selection] : [];
    const preflight = preflightSelection(snapshot);
    prepared = preflight.manifest ? { manifest: preflight.manifest, lookup: resourceLookup(snapshot, preflight.manifest) } : null;
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
      void (async () => {
        if (!snapshot) { runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: blockedCode }, { origin: "*" }); return; }
        try {
          const resources = [];
          for await (const resource of exportDeclaredAssets(snapshot.manifest, snapshot.lookup)) resources.push(resource);
          runtime.ui.postMessage({ type: "selection-export", attempt: message.attempt, manifest: snapshot.manifest, resources }, { origin: "*" });
        } catch { runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" }); }
      })();
    }
  };
  runtime.on("selectionchange", () => refresh("selection-changed"));
  refresh("selection-preflight");
}

if (typeof figma !== "undefined") {
  startPlugin(figma);
}
