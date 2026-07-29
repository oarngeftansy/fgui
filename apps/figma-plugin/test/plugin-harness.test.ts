import { describe, expect, it } from "vitest";

import { createPluginHarness, type FigmaHarnessNode } from "./plugin-harness";

function selectedNode(): FigmaHarnessNode {
  return {
    id: "private:selection-root",
    name: "Checkout",
    type: "FRAME",
    visible: true,
    absoluteBoundingBox: { x: 0, y: 0, width: 20, height: 10 },
    children: [{
      id: "private:vector",
      name: "Mark",
      type: "VECTOR",
      visible: true,
      absoluteBoundingBox: { x: 0, y: 0, width: 2, height: 2 },
      children: [],
      exportAsync: async () => new Uint8Array([60, 115, 118, 103, 47, 62]),
    }],
  };
}

describe("real plugin selection harness", () => {
  it("uses one desktop/browser export path and the public upload contract", async () => {
    const requests: Array<{ url: string; init: RequestInit }> = [];
    const fetchImpl = async (url: string, init: RequestInit) => {
      requests.push({ url, init });
      if (url === "/v1/figma/selections/uploads") return Response.json({ version: 1, upload_id: "upload-1" }, { status: 201 });
      if (url.endsWith("/commit")) return Response.json({ version: 1, selection_id: "a".repeat(32), display_name: "Checkout", top_level_summaries: [{ name: "Checkout", type: "FRAME" }], preview_urls: [], warnings: [] });
      return Response.json({ version: 1, state: "accepted" });
    };

    const desktop = createPluginHarness("desktop", [selectedNode()]);
    const browser = createPluginHarness("browser", [selectedNode()]);
    const desktopResult = await desktop.exportAndUpload("credential", "desktop-key", fetchImpl);
    const browserResult = await browser.exportAndUpload("credential", "browser-key", fetchImpl);

    expect(desktopResult.manifest).toEqual(browserResult.manifest);
    expect(desktopResult.resources).toEqual(browserResult.resources);
    expect(desktopResult.view.selection_id).toBe("a".repeat(32));
    expect(desktop.openSelectionTarget()).toBe("_blank");
    expect(browser.openSelectionTarget()).toBe("_self");
    expect(requests.map((request) => request.url)).toEqual([
      "/v1/figma/selections/uploads",
      "/v1/figma/selections/uploads/upload-1/manifest",
      "/v1/figma/selections/uploads/upload-1/resources/asset-1",
      "/v1/figma/selections/uploads/upload-1/commit",
      "/v1/figma/selections/uploads",
      "/v1/figma/selections/uploads/upload-1/manifest",
      "/v1/figma/selections/uploads/upload-1/resources/asset-1",
      "/v1/figma/selections/uploads/upload-1/commit",
    ]);
    expect(requests.every((request) => request.init.headers instanceof Headers ? request.init.headers.get("Authorization") === "Bearer credential" : (request.init.headers as Record<string, string>).Authorization === "Bearer credential")).toBe(true);
    expect(JSON.stringify(desktopResult.manifest)).not.toContain("private:");
  });
});
