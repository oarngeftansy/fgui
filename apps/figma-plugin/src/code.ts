import type { PluginConfig } from "./contracts";
import { isUiToMainMessage } from "./contracts";
import { CredentialStore, createMainPairingController } from "./pairing";

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
  runtime.ui.onmessage = (message: unknown, props: OnMessageProperties) => {
    if (props.origin !== config.serverOrigin) return;
    if (isUiToMainMessage(message)) void controller.handle(message);
  };
  void controller.restore();
}

if (typeof figma !== "undefined") {
  startPlugin({ serverOrigin: __FGUI_SERVER_ORIGIN__, pluginId: __FIGMA_PLUGIN_ID__ }, figma);
}
