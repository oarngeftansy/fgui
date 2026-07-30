import { afterEach, describe, expect, it } from "vitest";

import { ProjectWorkflowClient } from "../src/project-client";
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
  it("creates and updates downloadable projects through the real FastAPI contract", async () => {
    service = await startFastApiService();
    const fetchImpl = (url: string, init: RequestInit) => service!.fetch(url, init);
    const plugin = createPluginHarness([selectedNode()]);
    const selection = await plugin.exportSelection();
    const client = new ProjectWorkflowClient({ serverOrigin: service.baseUrl, pluginToken: service.pluginToken, fetchImpl, wait: (ms) => new Promise((resolve) => setTimeout(resolve, Math.min(ms, 10))) });

    await expect(client.options()).resolves.toEqual([expect.objectContaining({ templateId: "fgui-2024-web" })]);
    const created = await client.runCreate(selection.manifest, selection.resources, { templateId: "fgui-2024-web", projectName: "Quiz" });
    expect(created.downloadName).toMatch(/^Quiz-Figma新建-\d{8}-\d{4}\.zip$/);
    expect(created.blob.size).toBeGreaterThan(0);

    const archive = new File([service.projectArchive], "Existing.zip", { type: "application/zip" });
    const before = new Uint8Array(await archive.arrayBuffer());
    const updated = await client.runUpdate(selection.manifest, selection.resources, archive);
    expect(updated.downloadName).toMatch(/^Existing-Figma更新-\d{8}-\d{4}\.zip$/);
    expect(updated.blob.size).toBeGreaterThan(0);
    expect(new Uint8Array(await archive.arrayBuffer())).toEqual(before);

    expect((await service.fetch("/v1/figma/selections/uploads", { method: "POST" })).status).toBe(401);
    expect(JSON.stringify([created.selection, updated.selection])).not.toMatch(/token|private:|asset-1|path/i);
    expect(JSON.stringify(selection.manifest)).not.toContain("private:");
  });
});
