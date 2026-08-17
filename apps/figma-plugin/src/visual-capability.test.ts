import { describe, expect, it } from "vitest";
import { classifyVisualNode } from "./visual-capability";

function node(overrides: Record<string, unknown> = {}) {
  return { type: "FRAME", children: [], ...overrides };
}

describe("visual capability classification", () => {
  it.each([
    ["plain text", node({ type: "TEXT", fills: [{ type: "SOLID" }] }), false, "native", null, []],
    ["plain container", node(), false, "native", null, []],
    ["vector", node({ type: "VECTOR", fills: [{ type: "SOLID" }] }), false, "vector_asset", "image/svg+xml", []],
    ["image", node({ type: "RECTANGLE", fills: [{ type: "IMAGE" }] }), false, "image_asset", "image/png", []],
    ["instance", node({ type: "INSTANCE" }), false, "composite_png", "image/png", ["instance_composite"]],
    ["mask group", node({ type: "GROUP", children: [node({ isMask: true })] }), false, "composite_png", "image/png", ["mask_composite"]],
    ["internal clip", node({ clipsContent: true }), false, "composite_png", "image/png", ["clip_composite"]],
    ["root clip", node({ clipsContent: true }), true, "native", null, []],
    ["gradient", node({ fills: [{ type: "GRADIENT_LINEAR" }] }), false, "composite_png", "image/png", ["gradient_paint"]],
    ["hidden gradient", node({ fills: [{ type: "GRADIENT_LINEAR", visible: false }] }), false, "native", null, []],
    ["shadow", node({ effects: [{ type: "DROP_SHADOW" }] }), false, "composite_png", "image/png", ["visual_effect"]],
    ["blur", node({ effects: [{ type: "LAYER_BLUR" }] }), false, "composite_png", "image/png", ["visual_effect"]],
    ["hidden effect", node({ effects: [{ type: "DROP_SHADOW", visible: false }] }), false, "native", null, []],
    ["blend", node({ blendMode: "MULTIPLY" }), false, "composite_png", "image/png", ["blend_mode"]],
    ["pass through", node({ blendMode: "PASS_THROUGH" }), false, "native", null, []],
    ["multiple fills", node({ fills: [{ type: "SOLID" }, { type: "SOLID" }] }), false, "composite_png", "image/png", ["multiple_paints"]],
    ["video", node({ type: "VIDEO" }), false, "skip", null, []],
  ])("classifies %s", (_name, input, isRoot, strategy, mimeType, reasons) => {
    expect(classifyVisualNode(input, { isRoot })).toEqual({ strategy, mimeType, reasons });
  });

  it("deduplicates combined reasons in stable priority order", () => {
    expect(classifyVisualNode(node({
      type: "INSTANCE",
      clipsContent: true,
      fills: [{ type: "GRADIENT_LINEAR" }, { type: "SOLID" }],
      effects: [{ type: "INNER_SHADOW" }, { type: "BACKGROUND_BLUR" }],
      blendMode: "SCREEN",
    }), { isRoot: false }).reasons).toEqual([
      "instance_composite",
      "clip_composite",
      "gradient_paint",
      "visual_effect",
      "blend_mode",
      "multiple_paints",
    ]);
  });
});
