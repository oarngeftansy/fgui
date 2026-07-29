import { describe, expect, it } from "vitest";
import { SelectionExportError, preflightSelection, serializeSelection } from "./selection";

function node(overrides: Record<string, unknown> = {}) {
  return {
    id: "raw:node-id",
    name: "Checkout",
    type: "FRAME",
    visible: true,
    locked: false,
    opacity: 1,
    absoluteBoundingBox: { x: 10, y: 20, width: 320, height: 180 },
    children: [],
    layoutMode: "HORIZONTAL",
    itemSpacing: 8,
    paddingTop: 12,
    paddingRight: 16,
    paddingBottom: 12,
    paddingLeft: 16,
    constraints: { horizontal: "LEFT", vertical: "TOP" },
    ...overrides,
  } as unknown as SceneNode;
}

describe("current selection serialization", () => {
  it("walks only supplied selected roots in deterministic order and never exposes raw ids", () => {
    const first = node({ id: "secret-root", name: "First", children: [node({ id: "secret-child", name: "Child", type: "TEXT", characters: "Hello", fontName: { family: "Inter", style: "Bold" } })] });
    const second = node({ id: "secret-second", name: "Second", type: "INSTANCE", componentProperties: { State: { value: "Open" } } });

    const manifest = serializeSelection([first, second]);

    expect(manifest.top_level_nodes.map((entry) => entry.id)).toEqual(["node-1", "node-3"]);
    expect(manifest.top_level_nodes[0]?.children[0]).toMatchObject({ id: "node-2", text: "Hello", style: { font: { family: "Inter", style: "Bold" } } });
    expect(manifest.top_level_nodes[0]?.properties).toMatchObject({ layout_mode: "HORIZONTAL", item_spacing: 8, constraints: { horizontal: "LEFT", vertical: "TOP" } });
    expect(manifest.top_level_nodes[1]?.properties).toMatchObject({ component_properties: { State: "Open" } });
    expect(JSON.stringify(manifest)).not.toContain("secret-");
  });

  it("keeps invisible and locked selected nodes while reporting safe unsupported-content warnings", () => {
    const manifest = serializeSelection([
      node({ visible: false, locked: true, type: "VIDEO", name: "Demo" }),
      node({ type: "FRAME", prototypeStartNode: node({ id: "secret-prototype" }) }),
    ]);

    expect(manifest.top_level_nodes[0]).toMatchObject({ visible: false, properties: { locked: true } });
    expect(manifest.warnings.map((warning) => warning.code)).toEqual(expect.arrayContaining(["node_hidden", "node_locked", "unsupported_video", "unsupported_prototype"]));
    expect(JSON.stringify(manifest.warnings)).not.toContain("secret-");
  });

  it("blocks more than twenty selected roots and more than five thousand nodes before export", () => {
    expect(() => serializeSelection(Array.from({ length: 21 }, () => node()))).toThrow(SelectionExportError);
    expect(() => serializeSelection([node({ children: Array.from({ length: 5000 }, () => node()) })])).toThrow(SelectionExportError);
  });

  it("returns a sendable preflight with a bounded asset estimate", () => {
    const preflight = preflightSelection([node({ type: "RECTANGLE", fills: [{ type: "IMAGE" }] })]);

    expect(preflight).toMatchObject({ nodeCount: 1, assetCount: 1, sendable: true });
    expect(preflight.estimatedBytes).toBeGreaterThan(0);
  });

  it("rejects deep trees iteratively and never exports video resources", () => {
    let root = node({ type: "VIDEO", fills: [{ type: "IMAGE", imageHash: "video-bytes" }] });
    let cursor = root as unknown as { children: SceneNode[] };
    for (let index = 0; index < 33; index += 1) { const child = node(); cursor.children = [child]; cursor = child as unknown as { children: SceneNode[] }; }
    expect(() => serializeSelection([root])).toThrow(SelectionExportError);
    const video = serializeSelection([node({ type: "VIDEO", fills: [{ type: "IMAGE", imageHash: "video-bytes" }] })]);
    expect(video.resources).toEqual([]);
  });
});
