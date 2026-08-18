export type ExportStrategy = "native" | "vector_asset" | "image_asset" | "composite_png" | "skip";
export type RasterReason =
  | "instance_composite"
  | "mask_composite"
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
  maskType?: unknown;
  opacity?: unknown;
  cornerRadius?: unknown;
  topLeftRadius?: unknown;
  topRightRadius?: unknown;
  bottomLeftRadius?: unknown;
  bottomRightRadius?: unknown;
};

export type NativeMaskDescriptor = {
  kind: "rectangle" | "roundedRectangle" | "image";
  maskIndex: number;
  contentIndexes: number[];
  cornerRadii?: [number, number, number, number];
};

const VECTOR_TYPES = new Set(["VECTOR", "BOOLEAN_OPERATION", "STAR", "LINE", "POLYGON", "ELLIPSE"]);
const VISUAL_EFFECT_TYPES = new Set(["DROP_SHADOW", "INNER_SHADOW", "LAYER_BLUR", "BACKGROUND_BLUR"]);

type VisualRecord = { type?: unknown; visible?: unknown };

function visibleRecords(value: unknown): VisualRecord[] {
  return Array.isArray(value)
    ? value.filter((entry): entry is VisualRecord => Boolean(entry) && typeof entry === "object" && (entry as VisualRecord).visible !== false)
    : [];
}

function positiveRadius(value: unknown): boolean {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function radius(value: unknown, fallback: number): number | null {
  if (value === undefined) return fallback;
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

/**
 * Return a project-neutral native mask recipe only for the deliberately small
 * subset whose Figma sibling semantics can be represented without flattening.
 */
export function nativeMaskDescriptor(node: VisualNode): NativeMaskDescriptor | null {
  if (!["GROUP", "FRAME", "COMPONENT"].includes(node.type)) return null;
  const children = node.children ?? [];
  const maskIndexes = children.flatMap((child, index) => child.isMask === true ? [index] : []);
  if (maskIndexes.length !== 1 || maskIndexes[0] !== 0 || children.length < 2) return null;
  const mask = children[0];
  if (mask.type !== "RECTANGLE" || (mask.children?.length ?? 0) > 0) return null;
  if (mask.maskType === "LUMINANCE" || (typeof mask.opacity === "number" && mask.opacity !== 1)) return null;
  if (visibleRecords(mask.effects).length || visibleRecords(mask.strokes).length) return null;
  if (typeof mask.blendMode === "string" && mask.blendMode !== "NORMAL" && mask.blendMode !== "PASS_THROUGH") return null;
  const fills = visibleRecords(mask.fills);
  if (fills.length !== 1) return null;
  const fillType = fills[0]?.type;
  if (typeof fillType === "string" && fillType.startsWith("GRADIENT_")) return null;
  if (fillType === "IMAGE") {
    if (mask.maskType === "VECTOR") return null;
    return { kind: "image", maskIndex: 0, contentIndexes: children.slice(1).map((_child, index) => index + 1) };
  }
  if (fillType !== "SOLID") return null;
  const fill = fills[0] as Record<string, unknown>;
  const color = fill.color;
  if ((typeof fill.opacity === "number" && fill.opacity !== 1)
    || (color && typeof color === "object" && typeof (color as Record<string, unknown>).a === "number" && (color as Record<string, unknown>).a !== 1)) return null;
  const general = typeof mask.cornerRadius === "number" && Number.isFinite(mask.cornerRadius) && mask.cornerRadius >= 0 ? mask.cornerRadius : 0;
  const cornerRadii = [
    radius(mask.topLeftRadius, general),
    radius(mask.topRightRadius, general),
    radius(mask.bottomRightRadius, general),
    radius(mask.bottomLeftRadius, general),
  ];
  if (cornerRadii.some((value) => value === null)) return null;
  const resolvedRadii = cornerRadii as [number, number, number, number];
  const rounded = resolvedRadii.some(positiveRadius);
  return {
    kind: rounded ? "roundedRectangle" : "rectangle",
    maskIndex: 0,
    contentIndexes: children.slice(1).map((_child, index) => index + 1),
    ...(rounded ? { cornerRadii: resolvedRadii } : {}),
  };
}

export function classifyVisualNode(node: VisualNode, _context: { isRoot: boolean }): VisualCapability {
  if (node.type === "VIDEO") return { strategy: "skip", mimeType: null, reasons: [] };

  const fills = visibleRecords(node.fills);
  const strokes = visibleRecords(node.strokes);
  const effects = visibleRecords(node.effects);
  const reasons: RasterReason[] = [];

  if (node.type === "INSTANCE") reasons.push("instance_composite");
  if ((node.children ?? []).some((child) => child.isMask === true) && !nativeMaskDescriptor(node)) reasons.push("mask_composite");
  if ([...fills, ...strokes].some((paint) => typeof paint.type === "string" && paint.type.startsWith("GRADIENT_"))) reasons.push("gradient_paint");
  if (effects.some((effect) => typeof effect.type === "string" && VISUAL_EFFECT_TYPES.has(effect.type))) reasons.push("visual_effect");
  if (typeof node.blendMode === "string" && node.blendMode !== "NORMAL" && node.blendMode !== "PASS_THROUGH") reasons.push("blend_mode");
  if (fills.length > 1 || strokes.length > 1) reasons.push("multiple_paints");

  if (reasons.length) return { strategy: "composite_png", mimeType: "image/png", reasons };
  if (VECTOR_TYPES.has(node.type)) return { strategy: "vector_asset", mimeType: "image/svg+xml", reasons: [] };
  if (fills.some((paint) => paint.type === "IMAGE")) return { strategy: "image_asset", mimeType: "image/png", reasons: [] };
  return { strategy: "native", mimeType: null, reasons: [] };
}
