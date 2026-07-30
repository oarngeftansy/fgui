import type { ExportedResource } from "../src/assets";
import { startPlugin } from "../src/code";
import type { FigmaSceneNode, SelectionManifest } from "../src/selection";

export type FigmaHarnessNode = Omit<FigmaSceneNode, "children"> & {
  id?: string;
  children?: readonly FigmaHarnessNode[];
  exportAsync?(settings: { format: "PNG" | "SVG" }): Promise<Uint8Array>;
};

type PluginMessage = { type?: unknown; [key: string]: unknown };

/** A Figma API fake that deliberately exercises the same serializer/exporter/uploader as the plugin. */
export function createPluginHarness(selection: readonly FigmaHarnessNode[]) {
  const exportCurrentSelection = async (): Promise<{ manifest: SelectionManifest; resources: ExportedResource[] }> => {
    const messages: PluginMessage[] = [];
    const runtime = {
      showUI: () => {},
      on: () => {},
      currentPage: { selection },
      ui: {
        onmessage: undefined as ((message: unknown, props: OnMessageProperties) => void) | undefined,
        postMessage: (message: PluginMessage) => { messages.push(message); },
      },
    };
    (globalThis as typeof globalThis & { __html__?: string }).__html__ = "";
    startPlugin(runtime);
    const preflight = await waitForMessage(messages, "selection-preflight") as { preflight: { manifest: SelectionManifest } };
    runtime.ui.onmessage?.({ type: "selection-export", attempt: "harness-attempt" }, { origin: "null" } as OnMessageProperties);
    const exported = await waitForMessage(messages, "selection-export") as {
      manifest: SelectionManifest;
      resources: ExportedResource[];
    };
    if (!preflight.preflight.manifest) throw new Error("expected a sendable Figma selection");
    return { manifest: exported.manifest, resources: exported.resources };
  };

  return {
    exportSelection: exportCurrentSelection,
  };
}

async function waitForMessage(
  messages: PluginMessage[], type: string, matches: (message: PluginMessage) => boolean = () => true,
): Promise<PluginMessage> {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const message = messages.find((candidate) => candidate.type === type && matches(candidate));
    if (message) return message;
    await new Promise((resolve) => setTimeout(resolve, 1));
  }
  throw new Error(`plugin harness did not receive ${type}`);
}
