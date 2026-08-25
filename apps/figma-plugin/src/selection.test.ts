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

  it("preserves only safe blocking markers for reactions and complex auto layout", () => {
    const manifest = serializeSelection([node({
      prototypeStartNode: node({ id: "secret-prototype" }),
      reactions: [{ trigger: { type: "ON_CLICK" }, action: { destinationId: "secret-target" } }],
      layoutWrap: "WRAP",
      counterAxisSpacing: 12,
      minWidth: 80,
      maxWidth: 480,
    })]);

    expect(manifest.top_level_nodes[0]?.properties).toMatchObject({
      interactions: { present: true, reaction_count: 1, prototype_start: true },
      layout_wrap: "WRAP",
      counter_axis_spacing: 12,
      min_width: 80,
      max_width: 480,
    });
    expect(manifest.warnings.map((warning) => warning.code)).toContain("unsupported_prototype");
    expect(JSON.stringify(manifest)).not.toContain("secret-");
  });

  it("serializes safe mixed text runs and marks unsupported run styling", () => {
    let requestedFields: readonly string[] = [];
    const text = node({
      type: "TEXT",
      characters: "Hello world",
      getStyledTextSegments: (fields: readonly string[]) => {
        requestedFields = fields;
        return [
        {
          characters: "Hello",
          start: 0,
          end: 5,
          fontName: { family: "Inter", style: "Bold" },
          fontSize: 20,
          fills: [{ type: "SOLID", color: { r: 1, g: 0, b: 0 }, opacity: 1 }],
          textDecoration: "NONE",
          textCase: "ORIGINAL",
          letterSpacing: { unit: "PIXELS", value: 0 },
          lineHeight: { unit: "AUTO" },
        },
        {
          characters: " world",
          start: 5,
          end: 11,
          fontName: { family: "Inter", style: "Regular" },
          fontSize: 18,
          fills: [{ type: "SOLID", color: { r: 0, g: 0, b: 1 } }],
          textDecoration: "UNDERLINE",
          textCase: "ORIGINAL",
          letterSpacing: { unit: "PIXELS", value: 0 },
          lineHeight: { unit: "AUTO" },
          hyperlink: { type: "URL", value: "https://private.invalid" },
          listOptions: { type: "UNORDERED" },
          paragraphSpacing: 8,
          openTypeFeatures: { LIGA: true },
        },
      ];
      },
    });

    const manifest = serializeSelection([text]);

    expect(manifest.top_level_nodes[0]?.style?.runs).toEqual([
      {
        content: "Hello",
        style: { color: "#ff0000ff", font: { family: "Inter", style: "Bold" }, fontSize: 20 },
        unsupportedFeatures: [],
      },
      {
        content: " world",
        style: { color: "#0000ffff", font: { family: "Inter", style: "Regular" }, fontSize: 18 },
        unsupportedFeatures: ["text_decoration", "list_options", "paragraph_spacing", "hyperlink", "open_type_features"],
      },
    ]);
    expect(requestedFields).toEqual(expect.arrayContaining(["listOptions", "paragraphSpacing", "hyperlink", "openTypeFeatures"]));
    expect(JSON.stringify(manifest)).not.toContain("private.invalid");
  });

  it("preserves a single solid text color and blocks declared OpenType overrides", () => {
    const text = node({
      type: "TEXT",
      characters: "Red label",
      fills: [{ type: "SOLID", color: { r: 1, g: 0, b: 0 }, opacity: 1 }],
      fontName: { family: "Inter", style: "Regular" },
      getStyledTextSegments: () => [{
        characters: "Red label",
        fontName: { family: "Inter", style: "Regular" },
        fontSize: 18,
        fills: [{ type: "SOLID", color: { r: 1, g: 0, b: 0 }, opacity: 1 }],
        textDecoration: "NONE",
        textCase: "ORIGINAL",
        letterSpacing: { unit: "PIXELS", value: 0 },
        lineHeight: { unit: "AUTO" },
        openTypeFeatures: { LIGA: false },
      }],
    });

    const manifest = serializeSelection([text]);

    expect(manifest.top_level_nodes[0]?.style).toMatchObject({
      color: "#ff0000ff",
      runs: [{ content: "Red label", unsupportedFeatures: ["open_type_features"] }],
    });
  });

  it("keeps one uniformly styled text run with fixed line height editable", () => {
    const text = node({
      type: "TEXT",
      characters: "5/5",
      fontSize: 44,
      lineHeight: { unit: "PIXELS", value: 40 },
      fills: [{ type: "SOLID", color: { r: 0.2, g: 0.56, b: 0.05 } }],
      getStyledTextSegments: () => [{
        characters: "5/5",
        fontName: { family: "CoreSans", style: "Regular" },
        fontSize: 44,
        fills: [{ type: "SOLID", color: { r: 0.2, g: 0.56, b: 0.05 } }],
        textDecoration: "NONE",
        textCase: "ORIGINAL",
        letterSpacing: { unit: "PERCENT", value: 0 },
        lineHeight: { unit: "PIXELS", value: 40 },
      }],
    });

    const manifest = serializeSelection([text]);

    expect(manifest.resources).toEqual([]);
    expect(manifest.top_level_nodes[0]).toMatchObject({
      text: "5/5",
      properties: { export_strategy: "native", font_size: 44, line_height: { unit: "PIXELS", value: 40 } },
    });
    expect(manifest.top_level_nodes[0]?.style?.runs).toBeUndefined();
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

  it("returns stable designer-readable empty and unsupported-content warnings", () => {
    expect(preflightSelection([])).toMatchObject({
      sendable: false,
      warnings: [{ code: "selection_empty", message: "请选择要导出的图层" }],
    });
    expect(preflightSelection([node({ type: "VIDEO", name: "Demo" })])).toMatchObject({
      sendable: true,
      warnings: [{ code: "unsupported_video", message: "视频内容不会导出" }],
    });
  });

  it("declares ordinary vector-like layers as opaque PNG resources without image fills", () => {
    const vector = node({ type: "VECTOR", id: "raw:vector", fills: [{ type: "SOLID", color: { r: 1, g: 0, b: 0 } }] });
    const boolean = node({ type: "BOOLEAN_OPERATION", id: "raw:boolean", fills: [] });

    const manifest = serializeSelection([vector, boolean]);

    expect(manifest.resources).toEqual([
      { key: "asset-1", mime_type: "image/png", size: 0 },
      { key: "asset-2", mime_type: "image/png", size: 0 },
    ]);
    expect(manifest.top_level_nodes.map((entry) => entry.resource_keys)).toEqual([["asset-1"], ["asset-2"]]);
    expect(JSON.stringify(manifest)).not.toContain("raw:");
  });

  it("preserves children of image-filled containers so conversion can block lossy flattening", () => {
    const frame = node({
      type: "FRAME",
      fills: [{ type: "IMAGE", imageHash: "private-image" }],
      children: [node({ type: "TEXT", characters: "Editable child" })],
    });

    const manifest = serializeSelection([frame]);

    expect(manifest.top_level_nodes[0]).toMatchObject({
      resource_keys: ["asset-1"],
      properties: { export_strategy: "image_asset" },
    });
    expect(manifest.top_level_nodes[0]?.children).toHaveLength(1);
    expect(manifest.top_level_nodes[0]?.children[0]?.text).toBe("Editable child");
  });

  it("preserves readable instance children instead of flattening text into a PNG", () => {
    const child = node({ type: "TEXT", name: "Internal label", characters: "Build Level" });
    const instance = node({ type: "INSTANCE", name: "Village node", children: [child] });

    const manifest = serializeSelection([instance]);

    expect(manifest.resources).toEqual([]);
    expect(manifest.top_level_nodes[0]).toMatchObject({
      properties: { export_strategy: "native" },
      resource_keys: [],
      children: [{ name: "Internal label", text: "Build Level", properties: { export_strategy: "native" } }],
    });
  });

  it("exports groups containing a Figma mask as one opaque PNG", () => {
    const mask = node({ type: "ELLIPSE", name: "Mask", isMask: true });
    const artwork = node({ type: "RECTANGLE", name: "Artwork", fills: [{ type: "IMAGE", imageHash: "private" }] });
    const group = node({ type: "GROUP", name: "Masked portrait", children: [mask, artwork] });

    const manifest = serializeSelection([group]);

    expect(manifest.resources).toEqual([{ key: "asset-1", mime_type: "image/png", size: 0 }]);
    expect(manifest.top_level_nodes[0]?.resource_keys).toEqual(["asset-1"]);
  });

  it("preserves the selected clipping root and rasterizes only its unsupported nested clip", () => {
    const clipped = node({
      type: "FRAME",
      name: "Reward viewport",
      clipsContent: true,
      children: [node({ type: "RECTANGLE", name: "Overflowing slot" })],
    });
    const frame = node({ type: "FRAME", name: "Panel", clipsContent: true, children: [clipped] });

    const manifest = serializeSelection([frame]);

    expect(manifest.resources).toEqual([{ key: "asset-1", mime_type: "image/png", size: 0 }]);
    expect(manifest.top_level_nodes[0]).toMatchObject({
      resource_keys: [],
      properties: { clips_content: true, export_strategy: "native" },
      children: [{
        resource_keys: ["asset-1"],
        properties: { clips_content: true, export_strategy: "composite_png", raster_reasons: ["mask_composite"] },
        children: [],
      }],
    });
  });

  it("rasterizes only the smallest child with unsupported visual semantics", () => {
    const gradient = node({ type: "RECTANGLE", name: "Gradient card", fills: [{ type: "GRADIENT_LINEAR" }] });
    const label = node({ type: "TEXT", name: "Editable label", characters: "Village" });
    const root = node({ type: "FRAME", name: "Panel", children: [gradient, label] });

    const manifest = serializeSelection([root]);

    expect(manifest.resources).toEqual([{ key: "asset-1", mime_type: "image/png", size: 0 }]);
    expect(manifest.top_level_nodes[0]?.properties).toMatchObject({ export_strategy: "native" });
    expect(manifest.top_level_nodes[0]?.children).toHaveLength(2);
    expect(manifest.top_level_nodes[0]?.children[0]).toMatchObject({
      resource_keys: ["asset-1"],
      properties: { export_strategy: "composite_png", raster_reasons: ["gradient_paint"] },
    });
    expect(manifest.top_level_nodes[0]?.children[1]).toMatchObject({
      resource_keys: [],
      properties: { export_strategy: "native" },
    });
    expect(resourceLookup([root], manifest).get("asset-1")).toBe(gradient);
    expect(manifest.warnings).toContainEqual({
      code: "visual_rasterized",
      message: "已自动保真处理为图片：gradient_paint",
    });
  });

  it("does not collapse a selected frame when Figma reports empty style ids", () => {
    const label = node({ type: "TEXT", name: "Editable label", characters: "Village" });
    const root = node({
      name: "Village upgrade",
      fillStyleId: "",
      strokeStyleId: "",
      effectStyleId: "",
      fills: [],
      strokes: [],
      effects: [],
      children: [label],
    });

    const manifest = serializeSelection([root]);

    expect(manifest.resources).toEqual([]);
    expect(manifest.top_level_nodes[0]).toMatchObject({
      properties: { export_strategy: "native" },
    });
    expect(manifest.top_level_nodes[0]?.style?.style_references).toBeUndefined();
    expect(manifest.top_level_nodes[0]?.children).toHaveLength(1);
    expect(manifest.warnings).not.toContainEqual(expect.objectContaining({ code: "visual_rasterized" }));
  });

  it("records combined raster reasons deterministically and prunes the composite subtree", () => {
    const composite = node({
      type: "FRAME",
      clipsContent: true,
      fills: [{ type: "GRADIENT_LINEAR" }, { type: "SOLID" }],
      effects: [{ type: "DROP_SHADOW" }],
      blendMode: "MULTIPLY",
      children: [node({ type: "TEXT", characters: "Must not duplicate" })],
    });
    const manifest = serializeSelection([node({ children: [composite] })]);

    expect(manifest.top_level_nodes[0]?.children[0]).toMatchObject({
      children: [],
      properties: {
        export_strategy: "composite_png",
        raster_reasons: ["mask_composite", "gradient_paint", "visual_effect", "blend_mode", "multiple_paints"],
      },
    });
  });

  it("exports vector PNG without generic raster warnings and keeps complex text editable", () => {
    const styled = node({ type: "RECTANGLE", name: "Styled card", fills: [{ type: "SOLID", color: { r: 1, g: 0, b: 0 } }] });
    const transformed = node({ type: "BOOLEAN_OPERATION", name: "Scaled mark", relativeTransform: [[2, 0, 10], [0, 2, 20]] });
    const richText = node({
      type: "TEXT",
      name: "Mixed label",
      characters: "AB",
      getStyledTextSegments: () => [
        { characters: "A", fontName: { family: "Inter", style: "Regular" }, fontSize: 12, fills: [{ type: "SOLID", color: { r: 1, g: 1, b: 1 } }], textDecoration: "NONE", textCase: "ORIGINAL" },
        { characters: "B", fontName: { family: "Inter", style: "Bold" }, fontSize: 14, fills: [{ type: "SOLID", color: { r: 1, g: 1, b: 1 } }], textDecoration: "NONE", textCase: "ORIGINAL" },
      ],
    });

    const manifest = serializeSelection([node({ name: "Root", children: [styled, transformed, richText] })]);

    expect(manifest.resources).toEqual([
      { key: "asset-1", mime_type: "image/png", size: 0 },
    ]);
    expect(manifest.top_level_nodes[0]?.children.map((item) => item.properties?.raster_reasons)).toEqual([
      undefined,
      undefined,
      ["rich_text_runs"],
    ]);
  });

  it("reports prototype behavior inside a pruned composite subtree", () => {
    const interactive = node({
      type: "TEXT",
      characters: "Interactive",
      reactions: [{ trigger: { type: "ON_CLICK" }, action: { destinationId: "private-target" } }],
    });
    const composite = node({
      type: "FRAME",
      fills: [{ type: "GRADIENT_LINEAR" }],
      children: [interactive],
    });

    const manifest = serializeSelection([composite]);

    expect(manifest.top_level_nodes[0]?.children).toEqual([]);
    expect(manifest.warnings).toContainEqual({
      code: "unsupported_prototype",
      message: "原型连线不会导出",
    });
    expect(JSON.stringify(manifest)).not.toContain("private-target");
  });

  it("preserves a root rectangle mask as editable native structure", () => {
    const mask = node({
      type: "RECTANGLE",
      name: "Mask",
      isMask: true,
      fills: [{ type: "SOLID", color: { r: 1, g: 1, b: 1 } }],
    });
    const content = node({ type: "TEXT", name: "Editable", characters: "Label" });
    const group = node({ type: "GROUP", name: "Masked group", children: [mask, content] });

    const manifest = serializeSelection([group]);

    expect(manifest.resources).toEqual([]);
    expect(manifest.top_level_nodes[0]).toMatchObject({
      id: "node-1",
      properties: { export_strategy: "native" },
      resource_keys: [],
      style: { mask: { kind: "rectangle", maskNodeRef: "node-2", contentNodeRefs: ["node-3"] } },
      children: [expect.objectContaining({ name: "Mask" }), expect.objectContaining({ name: "Editable" })],
    });
    expect(manifest.warnings).not.toContainEqual(expect.objectContaining({ code: "visual_rasterized" }));
  });

  it("rasterizes a nested native mask group because FairyGUI only encodes root clips", () => {
    const mask = node({ type: "RECTANGLE", name: "Mask", isMask: true, fills: [{ type: "SOLID" }] });
    const content = node({ type: "TEXT", name: "Editable", characters: "Label" });
    const maskedGroup = node({ type: "GROUP", name: "Nested mask", children: [mask, content] });
    const root = node({ type: "FRAME", name: "Screen", children: [maskedGroup] });

    const manifest = serializeSelection([root]);

    expect(manifest.resources).toEqual([{ key: "asset-1", mime_type: "image/png", size: 0 }]);
    expect(manifest.top_level_nodes[0]?.children).toEqual([
      expect.objectContaining({
        name: "Nested mask",
        children: [],
        resource_keys: ["asset-1"],
        properties: expect.objectContaining({
          export_strategy: "composite_png",
          raster_reasons: ["mask_composite"],
        }),
      }),
    ]);
    expect(manifest.warnings).toContainEqual({
      code: "visual_rasterized",
      message: "已自动保真处理为图片：mask_composite",
    });
  });

  it("serializes valid nine-slice insets and removes the technical name marker", () => {
    const image = node({ type: "RECTANGLE", name: "Primary Button @9s(20,10,20,10)", fills: [{ type: "IMAGE" }] });
    const manifest = serializeSelection([image]);

    expect(manifest.top_level_nodes[0]).toMatchObject({
      name: "Primary Button",
      properties: { nine_slice_insets: { left: 20, top: 10, right: 20, bottom: 10 } },
    });
    expect(manifest.warnings).toEqual([]);
  });

  it("reports and ignores an invalid nine-slice marker without leaking node data", () => {
    const manifest = serializeSelection([node({ name: "Panel @9s(200,1,200,1)" })]);

    expect(manifest.top_level_nodes[0]?.properties?.nine_slice_insets).toBeUndefined();
    expect(manifest.warnings).toContainEqual({ code: "nine_slice_out_of_bounds", message: "九宫格边距超过图层尺寸，已按普通图片处理" });
  });

  it("uses the same deterministic resource plan for declarations and lookup", () => {
    const vector = node({ type: "VECTOR", name: "Mark", fills: [] });
    const raster = node({ type: "RECTANGLE", name: "Hero", fills: [{ type: "IMAGE", imageHash: "private-hash" }] });
    const root = node({ type: "FRAME", children: [vector, raster] });
    const manifest = serializeSelection([root]);

    const lookup = resourceLookup([root], manifest);

    expect([...lookup.entries()]).toEqual([["asset-1", vector], ["asset-2", raster]]);
  });

  it("does not deduplicate node render exports solely by shared image hash", () => {
    const first = node({ type: "RECTANGLE", name: "First crop", fills: [{ type: "IMAGE", imageHash: "shared" }] });
    const second = node({ type: "RECTANGLE", name: "Second crop", fills: [{ type: "IMAGE", imageHash: "shared" }] });

    const manifest = serializeSelection([first, second]);
    const lookup = resourceLookup([first, second], manifest);

    expect(manifest.resources.map((item) => item.key)).toEqual(["asset-1", "asset-2"]);
    expect(manifest.top_level_nodes.map((item) => item.resource_keys)).toEqual([["asset-1"], ["asset-2"]]);
    expect([...lookup.values()]).toEqual([first, second]);
  });

  it("treats every exported resource as an atomic subtree boundary", () => {
    const child = node({ type: "RECTANGLE", fills: [{ type: "IMAGE", imageHash: "child" }] });
    const boolean = node({ type: "BOOLEAN_OPERATION", fills: [], children: [child] });

    const manifest = serializeSelection([boolean]);

    expect(manifest.resources).toEqual([{ key: "asset-1", mime_type: "image/png", size: 0 }]);
    expect(manifest.top_level_nodes[0]?.children).toEqual([]);
  });

  it("bakes vector rotation into its PNG bounds without rotating the FairyGUI image twice", () => {
    const vector = node({
      type: "VECTOR",
      name: "Rotated mark",
      fills: [],
      rotation: 37,
      absoluteBoundingBox: { x: 145, y: 260, width: 81, height: 64 },
    });
    const group = node({
      type: "GROUP",
      name: "Translated group",
      absoluteBoundingBox: { x: 100, y: 200, width: 200, height: 180 },
      children: [vector],
    });

    const manifest = serializeSelection([group]);

    expect(manifest.top_level_nodes[0]?.children[0]).toMatchObject({
      bounds: { x: 145, y: 260, width: 81, height: 64 },
      rotation: 0,
      properties: { export_strategy: "vector_asset" },
      resource_keys: ["asset-1"],
    });
  });

  it("preserves bounded visual metadata while removing URLs, bytes, hashes, and raw identifiers", () => {
    const manifest = serializeSelection([node({
      fills: [{ type: "GRADIENT_LINEAR", opacity: 0.8, gradientStops: [{ position: 0, color: { r: 1, g: 0, b: 0, a: 1 } }], gradientTransform: [[1, 0, 8], [0, 1, 12]] }],
      effects: [{ type: "DROP_SHADOW", offset: { x: 2, y: 4 }, radius: 6, spread: 1, blendMode: "MULTIPLY", opacity: 0.4, imageHash: "raw-hash", url: "https://private.invalid", filePath: "C:\\private\\design.fig", nested: { relativePath: "..\\secret" } }],
      relativeTransform: [[1, 0, 10], [0, 1, 20]], strokeWeight: 3,
      componentProperties: { State: { value: { choice: "Open", rawNodeId: "secret-node", imageBytes: "secret-bytes" } } },
    })]);
    const serialized = manifest.top_level_nodes[0]!;

    expect(serialized.style).toMatchObject({
      fills: [{ type: "GRADIENT_LINEAR", opacity: 0.8, gradientStops: [{ position: 0, color: { r: 1, g: 0, b: 0, a: 1 } }], gradientTransform: [[1, 0, 8], [0, 1, 12]] }],
      effects: [{ type: "DROP_SHADOW", offset: { x: 2, y: 4 }, radius: 6, spread: 1, blendMode: "MULTIPLY", opacity: 0.4 }],
      relative_transform: [[1, 0, 10], [0, 1, 20]],
    });
    expect(serialized.properties).toMatchObject({ stroke_weight: 3, component_properties: { State: { choice: "Open" } } });
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
