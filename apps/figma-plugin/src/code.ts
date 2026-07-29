import type { PluginConfig } from "./contracts";
import { isUiToMainMessage } from "./contracts";
import { CredentialStore, createMainPairingController } from "./pairing";
import { exportDeclaredAssets } from "./assets";
import { preflightSelection, resourceLookup, serializeSelection, type FigmaSceneNode } from "./selection";

declare const __FGUI_SERVER_ORIGIN__: string;
declare const __FIGMA_PLUGIN_ID__: string;
declare const __html__: string;

type PluginRuntime = {
  clientStorage: {
    getAsync(key: string): Promise<unknown>;
    setAsync(key: string, value: string): Promise<void>;
    deleteAsync(key: string): Promise<void>;
  };
  showUI(html: string, options: { width: number; height: number }): void;
  currentPage?: { selection: readonly FigmaSceneNode[] };
  ui: {
    onmessage?: (message: unknown, props: { origin: string }) => void;
    postMessage(message: unknown, options: { origin: string }): void;
  };
};

export function startPlugin(config: PluginConfig, runtime: PluginRuntime): void {
  runtime.showUI(__html__, { width: 360, height: 460 });
  const controller = createMainPairingController(config, new CredentialStore(runtime.clientStorage), (message, origin) => {
    runtime.ui.postMessage(message, { origin });
  });
  let prepared: { manifest: ReturnType<typeof serializeSelection>; lookup: ReadonlyMap<string, FigmaSceneNode> } | null = null;
  runtime.ui.onmessage = (message: unknown, props: OnMessageProperties) => {
    if (props.origin !== config.serverOrigin) return;
    if (!isUiToMainMessage(message)) return;
    if (message.type === "selection-preflight") {
      const snapshot = runtime.currentPage ? [...runtime.currentPage.selection] : [];
      const preflight = preflightSelection(snapshot);
      prepared = preflight.manifest ? { manifest: preflight.manifest, lookup: resourceLookup(snapshot, preflight.manifest) } : null;
      runtime.ui.postMessage({ type: "selection-preflight", preflight }, { origin: config.serverOrigin });
      return;
    }
    if (message.type === "selection-export") {
      void (async () => {
        if (!prepared) { runtime.ui.postMessage({ type: "selection-error", code: "selection_export_failed" }, { origin: config.serverOrigin }); return; }
        try {
          const resources = [];
          for await (const resource of exportDeclaredAssets(prepared.manifest, prepared.lookup)) resources.push(resource);
          runtime.ui.postMessage({ type: "selection-export", manifest: prepared.manifest, resources }, { origin: config.serverOrigin });
        } catch { runtime.ui.postMessage({ type: "selection-error", code: "selection_export_failed" }, { origin: config.serverOrigin }); }
      })();
      return;
    }
    void controller.handle(message);
  };
  void controller.restore();
}

if (typeof figma !== "undefined") {
  startPlugin({ serverOrigin: __FGUI_SERVER_ORIGIN__, pluginId: __FIGMA_PLUGIN_ID__ }, figma);
}
