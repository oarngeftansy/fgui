export type ExportStrategy = "native" | "vector_asset" | "image_asset" | "composite_png" | "skip";
export type RasterReason =
  | "instance_composite"
  | "mask_composite"
  | "clip_composite"
  | "gradient_paint"
  | "visual_effect"
  | "blend_mode"
  | "multiple_paints";

export type VisualCapability = {
  strategy: ExportStrategy;
  mimeType: "image/png" | "image/svg+xml" | null;
  reasons: RasterReason[];
};

export type VisualNode = {
  type: string;
  clipsContent?: boolean;
  blendMode?: unknown;
  fills?: unknown;
  strokes?: unknown;
  effects?: unknown;
  children?: readonly VisualNode[];
  isMask?: boolean;
};

const VECTOR_TYPES = new Set(["VECTOR", "BOOLEAN_OPERATION", "STAR", "LINE", "POLYGON", "ELLIPSE"]);
const VISUAL_EFFECT_TYPES = new Set(["DROP_SHADOW", "INNER_SHADOW", "LAYER_BLUR", "BACKGROUND_BLUR"]);

type VisualRecord = { type?: unknown; visible?: unknown };

function visibleRecords(value: unknown): VisualRecord[] {
  return Array.isArray(value)
    ? value.filter((entry): entry is VisualRecord => Boolean(entry) && typeof entry === "object" && (entry as VisualRecord).visible !== false)
    : [];
}

export function classifyVisualNode(node: VisualNode, context: { isRoot: boolean }): VisualCapability {
  if (node.type === "VIDEO") return { strategy: "skip", mimeType: null, reasons: [] };

  const fills = visibleRecords(node.fills);
  const strokes = visibleRecords(node.strokes);
  const effects = visibleRecords(node.effects);
  const reasons: RasterReason[] = [];

  if (node.type === "INSTANCE") reasons.push("instance_composite");
  if (node.type === "GROUP" && (node.children ?? []).some((child) => child.isMask === true)) reasons.push("mask_composite");
  if (!context.isRoot && node.clipsContent === true) reasons.push("clip_composite");
  if ([...fills, ...strokes].some((paint) => typeof paint.type === "string" && paint.type.startsWith("GRADIENT_"))) reasons.push("gradient_paint");
  if (effects.some((effect) => typeof effect.type === "string" && VISUAL_EFFECT_TYPES.has(effect.type))) reasons.push("visual_effect");
  if (typeof node.blendMode === "string" && node.blendMode !== "NORMAL" && node.blendMode !== "PASS_THROUGH") reasons.push("blend_mode");
  if (fills.length > 1 || strokes.length > 1) reasons.push("multiple_paints");

  if (reasons.length) return { strategy: "composite_png", mimeType: "image/png", reasons };
  if (VECTOR_TYPES.has(node.type)) return { strategy: "vector_asset", mimeType: "image/svg+xml", reasons: [] };
  if (fills.some((paint) => paint.type === "IMAGE")) return { strategy: "image_asset", mimeType: "image/png", reasons: [] };
  return { strategy: "native", mimeType: null, reasons: [] };
}
