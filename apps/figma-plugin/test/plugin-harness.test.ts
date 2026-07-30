import { afterEach, describe, expect, it } from "vitest";

import { startFastApiService, type FastApiService } from "./fastapi-service";
import { createPluginHarness, type FigmaHarnessNode } from "./plugin-harness";

let service: FastApiService | undefined;

afterEach(async () => {
  await service?.stop();
  service = undefined;
});

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
  it("uses the direct-token export path against the isolated FastAPI upload contract", async () => {
    service = await startFastApiService();
    const fetchImpl = (url: string, init: RequestInit) => service!.fetch(url, init);

    const plugin = createPluginHarness([selectedNode()]);
    const result = await plugin.exportAndUpload(service.baseUrl, service.pluginToken, "selection-key", fetchImpl);

    expect(result.resources).toHaveLength(1);
    expect(result.view.selection_id).toMatch(/^[0-9a-f]{32}$/);
    expect((await service.fetch("/v1/figma/selections/uploads", { method: "POST" })).status).toBe(401);
    expect(JSON.stringify(result.view)).not.toMatch(/token|private:|asset-1|path/i);
    expect(JSON.stringify(result.manifest)).not.toContain("private:");
  });
});
