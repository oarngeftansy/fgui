import { createHash } from "node:crypto";
import { inflateRawSync } from "node:zlib";
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
    absoluteBoundingBox: { x: 0, y: 0, width: 600, height: 300 },
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
  it("creates and updates checked downloads through the plugin public HTTP contract", async () => {
    service = await startFastApiService();
    const requests: string[] = [];
    const fetchImpl = (url: string, init: RequestInit) => {
      requests.push(new URL(url).pathname);
      return service!.fetch(url, init);
    };
    const plugin = createPluginHarness([selectedNode()]);
    const selection = await plugin.exportSelection();
    const client = new ProjectWorkflowClient({ serverOrigin: service.baseUrl, pluginToken: service.pluginToken, fetchImpl, wait: (ms) => new Promise((resolve) => setTimeout(resolve, Math.min(ms, 10))) });
    const templateHash = await service.templateSha256();

    await expect(client.options()).resolves.toEqual([expect.objectContaining({ templateId: "fgui-2024-web" })]);
    const created = await client.runCreate(selection.manifest, selection.resources, { templateId: "fgui-2024-web", projectName: "Quiz" });
    expect(created.downloadName).toMatch(/^Quiz-Figma新建-\d{8}-\d{4}\.zip$/);
    const createdArchive = await openZip(created.blob);
    expect(createdArchive.get(`${created.project.packages[0]!.name}/package.xml`)).toContain("<package");
    expect([...createdArchive.keys()].filter((name) => name.endsWith(".xml"))).toHaveLength(2);
    expect([...createdArchive.keys()].some((name) => /\/assets\/.+\.(?:png|svg)$/i.test(name))).toBe(true);

    const archive = new File([service.projectArchive], "Existing.zip", { type: "application/zip" });
    const archiveHash = sha256(await archive.arrayBuffer());
    const updated = await client.runUpdate(selection.manifest, selection.resources, archive);
    expect(updated.downloadName).toMatch(/^Existing-Figma更新-\d{8}-\d{4}\.zip$/);
    expect(updated.downloadName).not.toBe(created.downloadName);
    const updatedArchive = await openZip(updated.blob);
    expect(updatedArchive.get(`${updated.project.packages[0]!.name}/package.xml`)).toContain("<package");
    expect([...updatedArchive.keys()].filter((name) => name.endsWith(".xml"))).toHaveLength(2);
    expect([...updatedArchive.keys()].some((name) => /\/assets\/.+\.(?:png|svg)$/i.test(name))).toBe(true);
    expect(sha256(await archive.arrayBuffer())).toBe(archiveHash);
    expect(await service.templateSha256()).toBe(templateHash);
    expect(requests.some((path) => path.startsWith("/v1/agents/"))).toBe(false);

    expect((await service.fetch("/v1/figma/selections/uploads", { method: "POST" })).status).toBe(401);
    expect(JSON.stringify([created.selection, updated.selection])).not.toMatch(/token|private:|asset-1|path/i);
    expect(JSON.stringify(selection.manifest)).not.toContain("private:");
  });
});

function sha256(bytes: ArrayBuffer): string {
  return createHash("sha256").update(new Uint8Array(bytes)).digest("hex");
}

async function openZip(blob: Blob): Promise<Map<string, string>> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const entries = new Map<string, string>();
  const end = findEndOfCentralDirectory(view);
  const count = view.getUint16(end + 10, true);
  let cursor = view.getUint32(end + 16, true);
  for (let index = 0; index < count; index += 1) {
    expect(view.getUint32(cursor, true)).toBe(0x02014b50);
    const compression = view.getUint16(cursor + 10, true);
    let compressedSize = view.getUint32(cursor + 20, true);
    const nameLength = view.getUint16(cursor + 28, true);
    const extraLength = view.getUint16(cursor + 30, true);
    const commentLength = view.getUint16(cursor + 32, true);
    let localOffset = view.getUint32(cursor + 42, true);
    const extraStart = cursor + 46 + nameLength;
    if (compressedSize === 0xffffffff || localOffset === 0xffffffff) {
      const zip64 = zip64Values(view, extraStart, extraLength);
      if (compressedSize === 0xffffffff) compressedSize = zip64.compressedSize;
      if (localOffset === 0xffffffff) localOffset = zip64.localOffset;
    }
    const name = new TextDecoder().decode(bytes.slice(cursor + 46, cursor + 46 + nameLength));
    expect(view.getUint32(localOffset, true)).toBe(0x04034b50);
    const localNameLength = view.getUint16(localOffset + 26, true);
    const localExtraLength = view.getUint16(localOffset + 28, true);
    const dataStart = localOffset + 30 + localNameLength + localExtraLength;
    const compressed = bytes.slice(dataStart, dataStart + compressedSize);
    const content = compression === 0 ? compressed : compression === 8 ? inflateRawSync(compressed) : undefined;
    expect(content, `unsupported ZIP compression for ${name}`).toBeDefined();
    entries.set(name, new TextDecoder().decode(content!));
    cursor += 46 + nameLength + extraLength + commentLength;
  }
  expect(entries.size).toBeGreaterThan(0);
  return entries;
}

function findEndOfCentralDirectory(view: DataView): number {
  for (let offset = view.byteLength - 22; offset >= Math.max(0, view.byteLength - 65_557); offset -= 1) {
    if (view.getUint32(offset, true) === 0x06054b50) return offset;
  }
  throw new Error("ZIP end of central directory was not found");
}

function zip64Values(view: DataView, start: number, length: number): { compressedSize: number; localOffset: number } {
  let cursor = start;
  const end = start + length;
  while (cursor + 4 <= end) {
    const id = view.getUint16(cursor, true);
    const size = view.getUint16(cursor + 2, true);
    if (id === 0x0001) {
      let value = cursor + 4;
      value += 8; // uncompressed size is always present before the fields this reader needs.
      const compressedSize = Number(view.getBigUint64(value, true));
      value += 8;
      const localOffset = Number(view.getBigUint64(value, true));
      return { compressedSize, localOffset };
    }
    cursor += 4 + size;
  }
  throw new Error("ZIP64 central directory data was not found");
}
