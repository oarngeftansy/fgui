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
  it("uses one desktop/browser export path against the isolated FastAPI upload contract", async () => {
    service = await startFastApiService();
    const pairing = await service.fetch("/v1/figma/pairings", { method: "POST" });
    expect(pairing.status).toBe(201);
    const exchange = await service.fetch("/v1/figma/pairings/exchange", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: 1, code: (await pairing.json()).code, device_name: "Plugin harness" }),
    });
    expect(exchange.status).toBe(200);
    const credential = (await exchange.json()).credential as string;
    const fetchImpl = (url: string, init: RequestInit) => service!.fetch(url, init);

    const desktop = createPluginHarness("desktop", [selectedNode()]);
    const browser = createPluginHarness("browser", [selectedNode()]);
    const desktopResult = await desktop.exportAndUpload(credential, "desktop-key", fetchImpl);
    const browserResult = await browser.exportAndUpload(credential, "browser-key", fetchImpl);

    expect(desktopResult.manifest).toEqual(browserResult.manifest);
    expect(desktopResult.resources).toEqual(browserResult.resources);
    expect(desktopResult.view.selection_id).toMatch(/^[0-9a-f]{32}$/);
    expect(desktop.openSelectionTarget()).toBe("_blank");
    expect(browser.openSelectionTarget()).toBe("_self");
    expect((await service.fetch("/v1/figma/selections/uploads", { method: "POST" })).status).toBe(401);
    expect(JSON.stringify(desktopResult.view)).not.toMatch(/credential|private:|asset-1|path/i);
    expect(JSON.stringify(desktopResult.manifest)).not.toContain("private:");
  });
});
