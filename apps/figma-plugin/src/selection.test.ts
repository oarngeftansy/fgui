import { describe, expect, it } from "vitest";
import { SelectionExportError, preflightSelection, resourceLookup, serializeSelection } from "./selection";

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

  it("declares ordinary vector-like layers as opaque SVG resources without image fills", () => {
    const vector = node({ type: "VECTOR", id: "raw:vector", fills: [{ type: "SOLID", color: { r: 1, g: 0, b: 0 } }] });
    const boolean = node({ type: "BOOLEAN_OPERATION", id: "raw:boolean", fills: [] });

    const manifest = serializeSelection([vector, boolean]);

    expect(manifest.resources).toEqual([
      { key: "asset-1", mime_type: "image/svg+xml", size: 0 },
      { key: "asset-2", mime_type: "image/svg+xml", size: 0 },
    ]);
    expect(manifest.top_level_nodes.map((entry) => entry.resource_keys)).toEqual([["asset-1"], ["asset-2"]]);
    expect(JSON.stringify(manifest)).not.toContain("raw:");
  });

  it("uses the same deterministic resource plan for declarations and lookup", () => {
    const vector = node({ type: "VECTOR", name: "Mark", fills: [] });
    const raster = node({ type: "RECTANGLE", name: "Hero", fills: [{ type: "IMAGE", imageHash: "private-hash" }] });
    const root = node({ type: "FRAME", children: [vector, raster] });
    const manifest = serializeSelection([root]);

    const lookup = resourceLookup([root], manifest);

    expect([...lookup.entries()]).toEqual([["asset-1", vector], ["asset-2", raster]]);
  });

  it("preserves bounded visual metadata while removing URLs, bytes, hashes, and raw identifiers", () => {
    const manifest = serializeSelection([node({
      fills: [{ type: "GRADIENT_LINEAR", opacity: 0.8, gradientStops: [{ position: 0, color: { r: 1, g: 0, b: 0, a: 1 } }], gradientTransform: [[1, 0, 8], [0, 1, 12]] }],
      effects: [{ type: "DROP_SHADOW", offset: { x: 2, y: 4 }, radius: 6, spread: 1, blendMode: "MULTIPLY", opacity: 0.4, imageHash: "raw-hash", url: "https://private.invalid", filePath: "C:\\private\\design.fig", nested: { relativePath: "..\\secret" } }],
      relativeTransform: [[1, 0, 10], [0, 1, 20]],
      componentProperties: { State: { value: { choice: "Open", rawNodeId: "secret-node", imageBytes: "secret-bytes" } } },
    })]);
    const serialized = manifest.top_level_nodes[0]!;

    expect(serialized.style).toMatchObject({
      fills: [{ type: "GRADIENT_LINEAR", opacity: 0.8, gradientStops: [{ position: 0, color: { r: 1, g: 0, b: 0, a: 1 } }], gradientTransform: [[1, 0, 8], [0, 1, 12]] }],
      effects: [{ type: "DROP_SHADOW", offset: { x: 2, y: 4 }, radius: 6, spread: 1, blendMode: "MULTIPLY", opacity: 0.4 }],
      relative_transform: [[1, 0, 10], [0, 1, 20]],
    });
    expect(serialized.properties).toMatchObject({ component_properties: { State: { choice: "Open" } } });
    expect(JSON.stringify(serialized)).not.toMatch(/secret|raw-hash|private\.invalid|private\\design/i);
  });

  it("maps supported raw style references to shared opaque selection-local tokens", () => {
    const first = node({ fillStyleId: "S:private-fill", strokeStyleId: "S:private-stroke", textStyleId: "S:private-text" });
    const second = node({ fillStyleId: "S:private-fill", effectStyleId: "S:private-effect" });

    const manifest = serializeSelection([first, second]);

    expect(manifest.top_level_nodes.map((entry) => entry.style?.style_references)).toEqual([
      { fill_style_id: "style-1", stroke_style_id: "style-2", text_style_id: "style-3" },
      { fill_style_id: "style-1", effect_style_id: "style-4" },
    ]);
    expect(JSON.stringify(manifest)).not.toContain("private-");
  });

  it("rejects oversized component properties and nested visual metadata", () => {
    expect(() => serializeSelection([node({ componentProperties: Object.fromEntries(Array.from({ length: 129 }, (_, index) => [`P${index}`, { value: index }])) })])).toThrow(SelectionExportError);
    expect(() => serializeSelection([node({ fills: Array.from({ length: 129 }, () => ({ type: "SOLID" })) })])).toThrow(SelectionExportError);
    expect(() => serializeSelection([node({ effects: [{ type: "DROP_SHADOW", offset: { note: "x".repeat(64 * 1024 + 1) } }] })])).toThrow(SelectionExportError);
  });

  it("makes preflight non-sendable when one declared resource exceeds its byte limit", () => {
    const preflight = preflightSelection([
      node({ type: "RECTANGLE", fills: [{ type: "IMAGE", imageHash: "too-large" }], absoluteBoundingBox: { x: 0, y: 0, width: 3000, height: 3000 } }),
    ]);

    expect(preflight).toMatchObject({ manifest: null, sendable: false });
    expect(preflight.warnings.map((item) => item.code)).toContain("selection_too_large");
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
