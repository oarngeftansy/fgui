import { describe, expect, it } from "vitest";
import { exportDeclaredAssets } from "./assets";
import { serializeSelection } from "./selection";

function assetNode(type: string, name: string, bytes: Uint8Array, delay = 0) {
  return {
    id: `raw:${name}`,
    name,
    type,
    visible: true,
    locked: false,
    opacity: 1,
    absoluteBoundingBox: { x: 0, y: 0, width: 4, height: 4 },
    fills: [{ type: "IMAGE" }],
    exportAsync: async (settings: { format: string }) => {
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
      return bytes;
    },
  } as unknown as SceneNode;
}

describe("declared asset export", () => {
  it("exports each opaque declared key once using SVG for vectors and PNG for raster nodes", async () => {
    const vector = assetNode("VECTOR", "Mark", new Uint8Array([1]));
    const raster = assetNode("RECTANGLE", "Hero", new Uint8Array([2, 3]));
    const manifest = serializeSelection([vector, raster]);
    const calls: string[] = [];
    for (const selected of [vector, raster]) {
      (selected as unknown as { exportAsync: (settings: { format: string }) => Promise<Uint8Array> }).exportAsync = async (settings) => {
        calls.push(settings.format);
        return new Uint8Array([calls.length]);
      };
    }
    const lookup = new Map(manifest.resources.map((resource, index) => [resource.key, [vector, raster][index]! ]));

    const resources = [];
    for await (const resource of exportDeclaredAssets(manifest, lookup)) resources.push(resource);

    expect(calls).toEqual(["SVG", "PNG"]);
    expect(resources.map((resource) => [resource.key, resource.mime_type, resource.bytes.length])).toEqual([
      ["asset-1", "image/svg+xml", 1],
      ["asset-2", "image/png", 1],
    ]);
  });

  it("limits simultaneous exports to four and reports only a selected display label on failure", async () => {
    let active = 0;
    let maximum = 0;
    const selected = Array.from({ length: 5 }, (_, index) => {
      const result = assetNode("RECTANGLE", `Card ${index + 1}`, new Uint8Array([index]), 5);
      (result as unknown as { exportAsync: () => Promise<Uint8Array> }).exportAsync = async () => {
        active += 1;
        maximum = Math.max(maximum, active);
        await new Promise((resolve) => setTimeout(resolve, 5));
        active -= 1;
        if (index === 4) throw new Error("raw:secret-node");
        return new Uint8Array([index]);
      };
      return result;
    });
    const manifest = serializeSelection(selected);
    const lookup = new Map(manifest.resources.map((resource, index) => [resource.key, selected[index]! ]));

    await expect(async () => {
      for await (const _ of exportDeclaredAssets(manifest, lookup)) { /* drain */ }
    }).rejects.toThrow("Card 5");
    expect(maximum).toBeLessThanOrEqual(4);
  });
});
