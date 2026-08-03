import { afterEach, describe, expect, it, vi } from "vitest";
import { startPlugin } from "./code";

function selectedNode(overrides: Record<string, unknown> = {}) {
  return {
    id: "raw:node-id",
    name: "Checkout",
    type: "FRAME",
    visible: true,
    absoluteBoundingBox: { x: 0, y: 0, width: 320, height: 180 },
    children: [],
    ...overrides,
  } as unknown as SceneNode;
}

function runtime(selection: readonly SceneNode[]) {
  const listeners = new Map<string, () => void>();
  const currentPage = { selection };
  return {
    listeners,
    currentPage,
    showUI: vi.fn(),
    on: vi.fn((event: string, listener: () => void) => listeners.set(event, listener)),
    ui: {
      onmessage: undefined as ((message: unknown, props: OnMessageProperties) => void) | undefined,
      postMessage: vi.fn(),
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("Figma selection bridge", () => {
  it("starts pairing-free and reports the current selection", () => {
    vi.stubGlobal("__html__", "<html></html>");
    const figmaRuntime = runtime([selectedNode()]);

    startPlugin(figmaRuntime);

    expect(figmaRuntime.showUI).toHaveBeenCalledOnce();
    expect(figmaRuntime.ui.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "selection-preflight",
        preflight: expect.objectContaining({ sendable: true, nodeCount: 1 }),
      }),
      { origin: "*" },
    );
    expect(figmaRuntime.on).toHaveBeenCalledWith("selectionchange", expect.any(Function));
    expect(JSON.stringify(figmaRuntime.ui.postMessage.mock.calls)).not.toMatch(/pairing|credential/i);
  });

  it("refreshes the preflight when the Figma selection changes", () => {
    vi.stubGlobal("__html__", "<html></html>");
    const figmaRuntime = runtime([selectedNode()]);
    startPlugin(figmaRuntime);
    figmaRuntime.ui.postMessage.mockClear();

    figmaRuntime.currentPage.selection = [selectedNode({ name: "Cart" })];
    figmaRuntime.listeners.get("selectionchange")!();

    expect(figmaRuntime.ui.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "selection-changed",
        preflight: expect.objectContaining({
          sendable: true,
          manifest: expect.objectContaining({ display_name: "Cart" }),
        }),
      }),
      { origin: "*" },
    );
  });

  it("returns a stable empty-selection error when export is requested", async () => {
    vi.stubGlobal("__html__", "<html></html>");
    const figmaRuntime = runtime([]);
    startPlugin(figmaRuntime);

    expect(figmaRuntime.ui.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "selection-preflight",
        preflight: expect.objectContaining({
          sendable: false,
          warnings: [{ code: "selection_empty", message: "请选择要导出的图层" }],
        }),
      }),
      { origin: "*" },
    );

    figmaRuntime.ui.onmessage!({ type: "selection-export", attempt: "empty-attempt" }, { origin: "null" } as OnMessageProperties);
    await Promise.resolve();

    expect(figmaRuntime.ui.postMessage).toHaveBeenCalledWith(
      { type: "selection-error", attempt: "empty-attempt", code: "selection_empty" },
      { origin: "*" },
    );
  });

  it("exports the prepared snapshot when the live selection changes mid-export", async () => {
    vi.stubGlobal("__html__", "<html></html>");
    let finishExport!: (bytes: Uint8Array) => void;
    const exporting = new Promise<Uint8Array>((resolve) => { finishExport = resolve; });
    const figmaRuntime = runtime([
      selectedNode({ name: "Original", type: "VECTOR", exportAsync: () => exporting }),
    ]);
    startPlugin(figmaRuntime);
    figmaRuntime.ui.postMessage.mockClear();

    figmaRuntime.ui.onmessage!({ type: "selection-export", attempt: "snapshot-attempt" }, { origin: "null" } as OnMessageProperties);
    await Promise.resolve();
    figmaRuntime.currentPage.selection = [selectedNode({ name: "Replacement" })];
    figmaRuntime.listeners.get("selectionchange")!();
    finishExport(new Uint8Array([1, 2, 3]));
    await vi.waitFor(() => expect(figmaRuntime.ui.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: "selection-export", attempt: "snapshot-attempt" }),
      { origin: "*" },
    ));

    expect(figmaRuntime.ui.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "selection-export",
        attempt: "snapshot-attempt",
        manifest: expect.objectContaining({ display_name: "Original" }),
        resources: [{ key: "asset-1", mime_type: "image/svg+xml", bytes: new Uint8Array([1, 2, 3]) }],
      }),
      { origin: "*" },
    );
  });

  it("returns a deterministic safe code when a resource export fails", async () => {
    vi.stubGlobal("__html__", "<html></html>");
    const figmaRuntime = runtime([
      selectedNode({
        name: "Broken",
        type: "VECTOR",
        exportAsync: () => Promise.reject(new Error("C:\\private\\credential")),
      }),
    ]);
    startPlugin(figmaRuntime);
    figmaRuntime.ui.postMessage.mockClear();

    figmaRuntime.ui.onmessage!({ type: "selection-export", attempt: "failed-attempt" }, { origin: "null" } as OnMessageProperties);
    await vi.waitFor(() => expect(figmaRuntime.ui.postMessage).toHaveBeenCalledWith(
      { type: "selection-error", attempt: "failed-attempt", code: "selection_export_failed" },
      { origin: "*" },
    ));

    expect(JSON.stringify(figmaRuntime.ui.postMessage.mock.calls)).not.toMatch(/private|credential/i);
  });

  it("exports only the attempt-bound selection as a bounded PNG", async () => {
    vi.stubGlobal("__html__", "<html></html>");
    const exportAsync = vi.fn().mockResolvedValue(new Uint8Array([137, 80, 78, 71]));
    const node = selectedNode({ exportAsync });
    const figmaRuntime = runtime([node]);
    startPlugin(figmaRuntime);

    figmaRuntime.ui.onmessage!({ type: "selection-export", attempt: "a1" }, { origin: "null" } as OnMessageProperties);
    await vi.waitFor(() => expect(figmaRuntime.ui.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: "selection-export", attempt: "a1" }),
      { origin: "*" },
    ));
    exportAsync.mockClear();
    figmaRuntime.ui.postMessage.mockClear();

    figmaRuntime.ui.onmessage!({ type: "semantic-screenshot-export", attempt: "a1" }, { origin: "null" } as OnMessageProperties);

    await vi.waitFor(() => expect(figmaRuntime.ui.postMessage).toHaveBeenCalledWith(
      { type: "semantic-screenshot-export", attempt: "a1", mimeType: "image/png", bytes: new Uint8Array([137, 80, 78, 71]) },
      { origin: "*" },
    ));
    expect(exportAsync).toHaveBeenCalledOnce();
    expect(exportAsync).toHaveBeenCalledWith({ format: "PNG", constraint: { type: "SCALE", value: 1 } });
    expect(JSON.stringify(figmaRuntime.ui.postMessage.mock.calls)).not.toMatch(/children|credential|raw:node/i);
  });

  it("refuses a screenshot when the attempt snapshot is empty or the live selection changed", async () => {
    vi.stubGlobal("__html__", "<html></html>");
    const originalExport = vi.fn().mockResolvedValue(new Uint8Array([1]));
    const original = selectedNode({ exportAsync: originalExport });
    const figmaRuntime = runtime([original]);
    startPlugin(figmaRuntime);
    figmaRuntime.ui.onmessage!({ type: "selection-export", attempt: "a1" }, { origin: "null" } as OnMessageProperties);
    await Promise.resolve();
    figmaRuntime.currentPage.selection = [selectedNode({ name: "Other", exportAsync: vi.fn() })];
    figmaRuntime.listeners.get("selectionchange")!();
    figmaRuntime.ui.postMessage.mockClear();

    figmaRuntime.ui.onmessage!({ type: "semantic-screenshot-export", attempt: "a1" }, { origin: "null" } as OnMessageProperties);
    await vi.waitFor(() => expect(figmaRuntime.ui.postMessage).toHaveBeenCalledWith(
      { type: "selection-error", attempt: "a1", code: "selection_changed" },
      { origin: "*" },
    ));
    expect(originalExport).not.toHaveBeenCalledWith(expect.objectContaining({ format: "PNG", constraint: expect.anything() }));

    const emptyRuntime = runtime([]);
    startPlugin(emptyRuntime);
    emptyRuntime.ui.postMessage.mockClear();
    emptyRuntime.ui.onmessage!({ type: "semantic-screenshot-export", attempt: "missing" }, { origin: "null" } as OnMessageProperties);
    await vi.waitFor(() => expect(emptyRuntime.ui.postMessage).toHaveBeenCalledWith(
      { type: "selection-error", attempt: "missing", code: "selection_empty" },
      { origin: "*" },
    ));
  });

  it("rejects screenshot dimensions and output bytes beyond the semantic limits", async () => {
    vi.stubGlobal("__html__", "<html></html>");
    const oversizedDimensions = runtime([selectedNode({
      absoluteBoundingBox: { x: 0, y: 0, width: 4097, height: 1 },
      exportAsync: vi.fn(),
    })]);
    startPlugin(oversizedDimensions);
    oversizedDimensions.ui.onmessage!({ type: "selection-export", attempt: "dimensions" }, { origin: "null" } as OnMessageProperties);
    await Promise.resolve();
    oversizedDimensions.ui.postMessage.mockClear();
    oversizedDimensions.ui.onmessage!({ type: "semantic-screenshot-export", attempt: "dimensions" }, { origin: "null" } as OnMessageProperties);
    await vi.waitFor(() => expect(oversizedDimensions.ui.postMessage).toHaveBeenCalledWith(
      { type: "selection-error", attempt: "dimensions", code: "selection_too_large" },
      { origin: "*" },
    ));

    const oversizedBytes = runtime([selectedNode({ exportAsync: vi.fn().mockResolvedValue(new Uint8Array(1_024_001)) })]);
    startPlugin(oversizedBytes);
    oversizedBytes.ui.onmessage!({ type: "selection-export", attempt: "bytes" }, { origin: "null" } as OnMessageProperties);
    await vi.waitFor(() => expect(oversizedBytes.ui.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: "selection-export", attempt: "bytes" }),
      { origin: "*" },
    ));
    oversizedBytes.ui.postMessage.mockClear();
    oversizedBytes.ui.onmessage!({ type: "semantic-screenshot-export", attempt: "bytes" }, { origin: "null" } as OnMessageProperties);
    await vi.waitFor(() => expect(oversizedBytes.ui.postMessage).toHaveBeenCalledWith(
      { type: "selection-error", attempt: "bytes", code: "selection_too_large" },
      { origin: "*" },
    ));
  });
});
