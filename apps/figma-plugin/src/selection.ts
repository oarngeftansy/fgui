export type SelectionWarning = { code: string; message: string };
export type SelectionResource = { key: string; mime_type: "image/png" | "image/svg+xml"; size: number };
export type SerializedSelectionNode = {
  id: string;
  name: string;
  type: string;
  bounds: { x: number; y: number; width: number; height: number };
  children: SerializedSelectionNode[];
  rotation?: number;
  visible?: boolean;
  opacity?: number;
  source_order?: number;
  text?: string;
  properties?: Record<string, unknown>;
  style?: Record<string, unknown>;
  resource_keys: string[];
};
export type SelectionManifest = { version: 1; display_name: string; top_level_nodes: SerializedSelectionNode[]; resources: SelectionResource[]; warnings: SelectionWarning[] };
export type SelectionPreflight = { manifest: SelectionManifest | null; nodeCount: number; assetCount: number; estimatedBytes: number; warnings: SelectionWarning[]; sendable: boolean };

const MAX_TOP_LEVEL = 20;
const MAX_NODES = 5000;
const MAX_RESOURCE_BYTES = 25 * 1024 * 1024;
const MAX_SESSION_BYTES = 200 * 1024 * 1024;
const MAX_DEPTH = 32;
const MAX_PROPERTIES = 128;
const MAX_STRING = 64 * 1024;
const MAX_VALUES = 100_000;
const SVG_TYPES = new Set(["VECTOR", "BOOLEAN_OPERATION", "STAR", "LINE", "POLYGON", "ELLIPSE"]);
const STYLE_REFERENCE_KEYS = ["fillStyleId", "strokeStyleId", "effectStyleId", "textStyleId"] as const;

export type FigmaTransform = readonly [readonly [number, number, number], readonly [number, number, number]];
export type FigmaSceneNode = { name: string; type: string; visible?: boolean; absoluteTransform?: FigmaTransform; absoluteRenderBounds?: { x: number; y: number; width: number; height: number } | null; absoluteBoundingBox?: { x: number; y: number; width: number; height: number } | null; children?: readonly FigmaSceneNode[]; locked?: boolean; componentProperties?: Record<string, { value?: unknown }>; prototypeStartNode?: unknown };
type SceneLike = FigmaSceneNode;

export class SelectionExportError extends Error {
  constructor(public readonly code: "selection_too_large" | "selection_empty" | "selection_export_failed") {
    super(code === "selection_too_large" ? "选择内容过大" : code === "selection_empty" ? "请选择要导出的图层" : "选择导出失败");
    this.name = "SelectionExportError";
  }
}

function imageReference(node: SceneLike, localOrder: number): string | null {
  if (node.type === "VIDEO") return null;
  const fills = (node as { fills?: unknown }).fills;
  if (!Array.isArray(fills)) return null;
  const image = fills.find((fill) => fill && typeof fill === "object" && (fill as { type?: unknown }).type === "IMAGE") as { imageHash?: unknown; imageRef?: unknown } | undefined;
  if (!image) return null;
  return typeof image.imageHash === "string" ? `hash:${image.imageHash}` : typeof image.imageRef === "string" ? `ref:${image.imageRef}` : `local:${localOrder}`;
}

function bounds(node: SceneLike) {
  const value = node.absoluteBoundingBox;
  return value ? { x: value.x, y: value.y, width: value.width, height: value.height } : { x: 0, y: 0, width: 0, height: 0 };
}

function sanitizeVisualValue(value: unknown, depth = 0, count = { value: 0 }): unknown {
  count.value += 1;
  if (count.value > MAX_VALUES || depth > MAX_DEPTH) throw new SelectionExportError("selection_too_large");
  if (typeof value === "string") {
    if (value.length > MAX_STRING) throw new SelectionExportError("selection_too_large");
    return value;
  }
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  if (Array.isArray(value)) {
    if (value.length > MAX_PROPERTIES) throw new SelectionExportError("selection_too_large");
    return value.map((nested) => sanitizeVisualValue(nested, depth + 1, count)).filter((nested) => nested !== undefined);
  }
  if (!value || typeof value !== "object") return undefined;
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length > MAX_PROPERTIES) throw new SelectionExportError("selection_too_large");
  const safe: Record<string, unknown> = {};
  for (const [name, nested] of entries) {
    if (name.length > MAX_STRING) throw new SelectionExportError("selection_too_large");
    if (/(?:url|href|src|image(?:hash|ref)?|bytes?|base64|data|(?:node)?id|path|file)/i.test(name)) continue;
    const sanitized = sanitizeVisualValue(nested, depth + 1, count);
    if (sanitized !== undefined) safe[name] = sanitized;
  }
  return safe;
}

function addProperty(target: Record<string, unknown>, name: string, value: unknown): void {
  const sanitized = sanitizeVisualValue(value);
  if (sanitized !== undefined) target[name] = sanitized;
}

function propertyName(name: string): string { return name.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`); }

function nodeProperties(node: SceneLike): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  const layout = node as { layoutMode?: unknown; itemSpacing?: unknown; paddingTop?: unknown; paddingRight?: unknown; paddingBottom?: unknown; paddingLeft?: unknown; constraints?: unknown };
  if (typeof layout.layoutMode === "string" && layout.layoutMode !== "NONE") {
    properties.layout_mode = layout.layoutMode;
    for (const key of ["itemSpacing", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft"] as const) if (typeof layout[key] === "number") properties[propertyName(key)] = layout[key];
  }
  if (layout.constraints && typeof layout.constraints === "object") addProperty(properties, "constraints", layout.constraints);
  const source = node as Record<string, unknown>;
  for (const key of ["primaryAxisAlignItems", "counterAxisAlignItems", "primaryAxisSizingMode", "counterAxisSizingMode", "clipsContent", "cornerRadius", "topLeftRadius", "topRightRadius", "bottomLeftRadius", "bottomRightRadius", "layoutAlign", "layoutGrow", "textAutoResize", "textAlignHorizontal", "textAlignVertical", "fontSize", "lineHeight", "letterSpacing", "variantProperties"] as const) {
    const value = source[key];
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean" || (value && typeof value === "object")) addProperty(properties, propertyName(key), value);
  }
  if (node.locked) properties.locked = true;
  if (node.componentProperties) {
    const entries = Object.entries(node.componentProperties);
    if (entries.length > MAX_PROPERTIES) throw new SelectionExportError("selection_too_large");
    const componentProperties: Record<string, unknown> = {};
    for (const [name, value] of entries) {
      const sanitized = sanitizeVisualValue(value.value);
      if (sanitized !== undefined) componentProperties[name] = sanitized;
    }
    properties.component_properties = componentProperties;
  }
  return properties;
}

function nodeStyle(node: SceneLike, styleReferences: Record<string, string>): Record<string, unknown> {
  const source = node as Record<string, unknown>;
  const style: Record<string, unknown> = {};
  for (const key of ["fills", "strokes", "effects", "relativeTransform", "absoluteTransform"] as const) if (Array.isArray(source[key])) addProperty(style, propertyName(key), source[key]);
  const font = (node as { fontName?: { family?: unknown; style?: unknown } }).fontName;
  if (font && typeof font.family === "string" && typeof font.style === "string") addProperty(style, "font", { family: font.family, style: font.style });
  if (Object.keys(styleReferences).length) style.style_references = styleReferences;
  return style;
}

function warning(code: string, message: string): SelectionWarning { return { code, message }; }

type ResourcePlan = { key: string; mime_type: SelectionResource["mime_type"]; node: FigmaSceneNode };
type NodePlan = { node: SceneLike; order: number; parent: NodePlan | null; resource?: ResourcePlan; styleReferences: Record<string, string> };

// One deterministic DFS owns both declarations and lookup ordering.
function selectionPlan(nodes: readonly FigmaSceneNode[]): { nodes: NodePlan[]; resources: ResourcePlan[] } {
  if (!nodes.length) throw new SelectionExportError("selection_empty");
  if (nodes.length > MAX_TOP_LEVEL) throw new SelectionExportError("selection_too_large");
  const planned: NodePlan[] = [];
  const resources: ResourcePlan[] = [];
  const byReference = new Map<string, ResourcePlan>();
  const styleTokens = new Map<string, string>();
  const pending: Array<{ node: SceneLike; depth: number; parent: NodePlan | null }> = nodes.slice().reverse().map((node) => ({ node: node as SceneLike, depth: 1, parent: null }));
  while (pending.length) {
    const { node, depth, parent } = pending.pop()!;
    const order = planned.length + 1;
    if (order > MAX_NODES || depth > MAX_DEPTH || node.name.length > MAX_STRING || (typeof (node as unknown as { characters?: unknown }).characters === "string" && (node as unknown as { characters: string }).characters.length > MAX_STRING)) throw new SelectionExportError("selection_too_large");
    const vector = SVG_TYPES.has(node.type);
    const mime_type: SelectionResource["mime_type"] = vector ? "image/svg+xml" : "image/png";
    const reference = node.type === "VIDEO" ? null : imageReference(node, order) ?? (vector ? `svg:${order}` : null);
    let resource: ResourcePlan | undefined;
    if (reference) {
      const identity = `${mime_type}:${reference}`;
      resource = byReference.get(identity);
      if (!resource) {
        resource = { key: `asset-${resources.length + 1}`, mime_type, node };
        byReference.set(identity, resource);
        resources.push(resource);
      }
    }
    const styleReferences: Record<string, string> = {};
    for (const key of STYLE_REFERENCE_KEYS) {
      const raw = (node as Record<string, unknown>)[key];
      if (typeof raw !== "string") continue;
      let token = styleTokens.get(raw);
      if (!token) { token = `style-${styleTokens.size + 1}`; styleTokens.set(raw, token); }
      styleReferences[propertyName(key)] = token;
    }
    const current: NodePlan = { node, order, parent, resource, styleReferences };
    planned.push(current);
    const children = node.children ?? [];
    if (pending.length + children.length > MAX_NODES) throw new SelectionExportError("selection_too_large");
    for (let index = children.length - 1; index >= 0; index -= 1) pending.push({ node: children[index] as SceneLike, depth: depth + 1, parent: current });
  }
  return { nodes: planned, resources };
}

export function serializeSelection(nodes: readonly FigmaSceneNode[]): SelectionManifest {
  const plan = selectionPlan(nodes);
  const roots: SerializedSelectionNode[] = [];
  const warnings: SelectionWarning[] = [];
  const serialized = new Map<NodePlan, SerializedSelectionNode>();
  for (const item of plan.nodes) {
    const { node } = item;
    if (!node.visible) warnings.push(warning("node_hidden", "已保留不可见图层"));
    if (node.locked) warnings.push(warning("node_locked", "已保留锁定图层"));
    if (node.type === "VIDEO") warnings.push(warning("unsupported_video", "视频内容不会导出"));
    if (node.prototypeStartNode) warnings.push(warning("unsupported_prototype", "原型连线不会导出"));
    const result: SerializedSelectionNode = {
      id: `node-${item.order}`, name: node.name || "未命名图层", type: node.type, bounds: bounds(node), children: [],
      rotation: typeof (node as unknown as { rotation?: unknown }).rotation === "number" ? (node as unknown as { rotation: number }).rotation : 0,
      visible: node.visible !== false, opacity: typeof (node as unknown as { opacity?: unknown }).opacity === "number" ? (node as unknown as { opacity: number }).opacity : 1,
      source_order: item.order - 1, ...(typeof (node as unknown as { characters?: unknown }).characters === "string" ? { text: (node as unknown as { characters: string }).characters } : {}),
      properties: nodeProperties(node), style: nodeStyle(node, item.styleReferences), resource_keys: item.resource ? [item.resource.key] : [],
    };
    (item.parent ? serialized.get(item.parent)!.children : roots).push(result);
    serialized.set(item, result);
  }
  return { version: 1, display_name: roots[0]?.name ?? "当前选择", top_level_nodes: roots, resources: plan.resources.map(({ key, mime_type }) => ({ key, mime_type, size: 0 })), warnings };
}

export function resourceLookup(nodes: readonly FigmaSceneNode[], manifest: SelectionManifest): ReadonlyMap<string, FigmaSceneNode> {
  const declarations = new Map(selectionPlan(nodes).resources.map((resource) => [resource.key, resource.node]));
  return new Map(manifest.resources.flatMap((resource) => {
    const node = declarations.get(resource.key);
    return node ? [[resource.key, node] as const] : [];
  }));
}

export function preflightSelection(nodes: readonly FigmaSceneNode[]): SelectionPreflight {
  try {
    const manifest = serializeSelection(nodes);
    const lookup = resourceLookup(nodes, manifest);
    const estimates = manifest.resources.map((resource) => Math.max(1, (lookup.get(resource.key)?.absoluteBoundingBox?.width ?? 1) * (lookup.get(resource.key)?.absoluteBoundingBox?.height ?? 1) * 4));
    const estimatedBytes = estimates.reduce((total, size) => total + size, 0);
    if (estimates.some((size) => size > MAX_RESOURCE_BYTES) || estimatedBytes > MAX_SESSION_BYTES) throw new SelectionExportError("selection_too_large");
    return { manifest, nodeCount: selectionPlan(nodes).nodes.length, assetCount: manifest.resources.length, estimatedBytes, warnings: manifest.warnings, sendable: true };
  } catch (error) {
    const safe = error instanceof SelectionExportError ? error : new SelectionExportError("selection_export_failed");
    return { manifest: null, nodeCount: 0, assetCount: 0, estimatedBytes: 0, warnings: [warning(safe.code, safe.message)], sendable: false };
  }
}
