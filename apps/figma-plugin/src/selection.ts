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
export type SelectionManifest = {
  version: 1;
  display_name: string;
  top_level_nodes: SerializedSelectionNode[];
  resources: SelectionResource[];
  warnings: SelectionWarning[];
};
export type SelectionPreflight = { manifest: SelectionManifest | null; nodeCount: number; assetCount: number; estimatedBytes: number; warnings: SelectionWarning[]; sendable: boolean };

const MAX_TOP_LEVEL = 20;
const MAX_NODES = 5000;
const MAX_RESOURCE_BYTES = 25 * 1024 * 1024;
const MAX_SESSION_BYTES = 200 * 1024 * 1024;
const MAX_DEPTH = 32;
const MAX_PROPERTIES = 128;
const MAX_STRING = 64 * 1024;

export type FigmaSceneNode = { name: string; type: string; visible?: boolean; absoluteBoundingBox?: { x: number; y: number; width: number; height: number } | null; children?: readonly FigmaSceneNode[]; locked?: boolean; componentProperties?: Record<string, { value?: unknown }>; prototypeStartNode?: unknown };
type SceneLike = FigmaSceneNode;

export class SelectionExportError extends Error {
  constructor(public readonly code: "selection_too_large" | "selection_empty" | "selection_export_failed") {
    super(code === "selection_too_large" ? "选择内容过大" : code === "selection_empty" ? "请选择要导出的图层" : "选择导出失败");
    this.name = "SelectionExportError";
  }
}

function imageReference(node: SceneLike, localOrder?: number): string | null {
  if ((node.type as string) === "VIDEO") return null;
  const fills = (node as unknown as { fills?: unknown }).fills;
  if (!Array.isArray(fills)) return null;
  const image = fills.find((fill) => fill && typeof fill === "object" && (fill as { type?: unknown }).type === "IMAGE") as { imageHash?: unknown; imageRef?: unknown } | undefined;
  if (!image) return null;
  return typeof image.imageHash === "string" ? `hash:${image.imageHash}` : typeof image.imageRef === "string" ? `ref:${image.imageRef}` : localOrder ? `local:${localOrder}` : null;
}

function bounds(node: SceneLike) {
  const value = node.absoluteBoundingBox;
  return value ? { x: value.x, y: value.y, width: value.width, height: value.height } : { x: 0, y: 0, width: 0, height: 0 };
}

function nodeProperties(node: SceneLike): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  const layout = node as unknown as { layoutMode?: unknown; itemSpacing?: unknown; paddingTop?: unknown; paddingRight?: unknown; paddingBottom?: unknown; paddingLeft?: unknown; constraints?: unknown };
  if (typeof layout.layoutMode === "string" && layout.layoutMode !== "NONE") {
    properties.layout_mode = layout.layoutMode;
    for (const key of ["itemSpacing", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft"] as const) if (typeof layout[key] === "number") properties[key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)] = layout[key];
  }
  if (layout.constraints && typeof layout.constraints === "object") properties.constraints = layout.constraints;
  const source = node as unknown as Record<string, unknown>;
  for (const key of ["primaryAxisAlignItems", "counterAxisAlignItems", "primaryAxisSizingMode", "counterAxisSizingMode", "clipsContent", "cornerRadius", "topLeftRadius", "topRightRadius", "bottomLeftRadius", "bottomRightRadius", "layoutAlign", "layoutGrow", "textAutoResize", "textAlignHorizontal", "textAlignVertical", "fontSize", "lineHeight", "letterSpacing", "variantProperties"] as const) {
    const value = source[key];
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean" || (value && typeof value === "object" && JSON.stringify(value).length <= MAX_STRING)) properties[key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)] = value;
  }
  if (node.locked) properties.locked = true;
  const componentProperties = node.componentProperties as Record<string, { value?: unknown }> | undefined;
  if (componentProperties) {
    properties.component_properties = Object.fromEntries(Object.entries(componentProperties).map(([name, value]) => [name, value.value]));
  }
  return properties;
}

function nodeStyle(node: SceneLike): Record<string, unknown> {
  const source = node as unknown as Record<string, unknown>;
  const style: Record<string, unknown> = {};
  for (const key of ["fills", "strokes", "effects"] as const) {
    const value = source[key];
    if (Array.isArray(value)) style[key] = value.map((item) => typeof item === "object" && item ? Object.fromEntries(Object.entries(item as Record<string, unknown>).filter(([name, nested]) => !/imageHash|id|url|bytes|data/i.test(name) && (typeof nested === "string" || typeof nested === "number" || typeof nested === "boolean"))) : item);
  }
  const text = node as unknown as { fontName?: unknown };
  if (text.fontName && typeof text.fontName === "object" && "family" in text.fontName && "style" in text.fontName) {
    const font = text.fontName as { family?: unknown; style?: unknown };
    if (typeof font.family === "string" && typeof font.style === "string") style.font = { family: font.family, style: font.style };
  }
  return style;
}

function warning(code: string, message: string): SelectionWarning { return { code, message }; }

export function serializeSelection(nodes: readonly FigmaSceneNode[]): SelectionManifest {
  if (nodes.length === 0) throw new SelectionExportError("selection_empty");
  if (nodes.length > MAX_TOP_LEVEL) throw new SelectionExportError("selection_too_large");
  const roots: SerializedSelectionNode[] = [];
  const resources: SelectionResource[] = [];
  const warnings: SelectionWarning[] = [];
  let order = 0;
  const pending: Array<{ node: SceneLike; destination: SerializedSelectionNode[] }> = nodes.slice().reverse().map((node) => ({ node: node as SceneLike, destination: roots }));
  while (pending.length) {
    const { node, destination } = pending.pop()!;
    order += 1;
    if (order > MAX_NODES || node.name.length > MAX_STRING || (typeof (node as unknown as { characters?: unknown }).characters === "string" && (node as unknown as { characters: string }).characters.length > MAX_STRING)) throw new SelectionExportError("selection_too_large");
    const resourceKeys: string[] = [];
    const reference = imageReference(node, order);
    if (reference) {
      const existing = resources.findIndex((resource) => (resource as SelectionResource & { reference?: string }).reference === reference);
      const key = existing >= 0 ? resources[existing]!.key : `asset-${resources.length + 1}`;
      resourceKeys.push(key);
      if (existing < 0) resources.push(Object.assign({ key, mime_type: node.type === "VECTOR" ? "image/svg+xml" : "image/png", size: 0 }, { reference }) as SelectionResource);
    }
    if (!node.visible) warnings.push(warning("node_hidden", "已保留不可见图层"));
    if (node.locked) warnings.push(warning("node_locked", "已保留锁定图层"));
    if ((node.type as string) === "VIDEO") warnings.push(warning("unsupported_video", "视频内容不会导出"));
    if (node.prototypeStartNode) warnings.push(warning("unsupported_prototype", "原型连线不会导出"));
    const serialized: SerializedSelectionNode = {
      id: `node-${order}`, name: node.name || "未命名图层", type: node.type, bounds: bounds(node), children: [],
      rotation: typeof (node as unknown as { rotation?: unknown }).rotation === "number" ? (node as unknown as { rotation: number }).rotation : 0, visible: node.visible !== false,
      opacity: typeof (node as unknown as { opacity?: unknown }).opacity === "number" ? (node as unknown as { opacity: number }).opacity : 1, source_order: order - 1,
      ...(typeof (node as unknown as { characters?: unknown }).characters === "string" ? { text: (node as unknown as { characters: string }).characters } : {}),
      properties: nodeProperties(node), style: nodeStyle(node), resource_keys: resourceKeys,
    };
    destination.push(serialized);
    const children = node.children ?? [];
    if (pending.length + children.length > MAX_NODES || pending.length > MAX_DEPTH * MAX_NODES) throw new SelectionExportError("selection_too_large");
    for (let index = children.length - 1; index >= 0; index -= 1) pending.push({ node: children[index] as SceneLike, destination: serialized.children });
  }
  return { version: 1, display_name: roots[0]?.name ?? "当前选择", top_level_nodes: roots, resources: resources.map(({ key, mime_type, size }) => ({ key, mime_type, size })), warnings };
}

export function resourceLookup(nodes: readonly FigmaSceneNode[], manifest: SelectionManifest): ReadonlyMap<string, FigmaSceneNode> {
  const assetNodes: FigmaSceneNode[] = [];
  const pending = nodes.slice().reverse() as FigmaSceneNode[];
  const references = new Set<string>();
  let order = 0;
  while (pending.length) {
    const node = pending.pop()! as SceneLike;
    order += 1;
    const reference = imageReference(node, order);
    if (reference && !references.has(reference)) { references.add(reference); assetNodes.push(node); }
    const children = node.children ?? [];
    for (let index = children.length - 1; index >= 0; index -= 1) pending.push(children[index]!);
  }
  return new Map(manifest.resources.map((resource, index) => [resource.key, assetNodes[index]! ]));
}

export function preflightSelection(nodes: readonly FigmaSceneNode[]): SelectionPreflight {
  try {
    const manifest = serializeSelection(nodes);
    const lookup = resourceLookup(nodes, manifest);
    const estimates = manifest.resources.map((resource) => Math.max(1, (lookup.get(resource.key)?.absoluteBoundingBox?.width ?? 1) * (lookup.get(resource.key)?.absoluteBoundingBox?.height ?? 1) * 4));
    const estimatedBytes = estimates.reduce((total, size) => total + size, 0);
    if (estimates.some((size) => size > MAX_RESOURCE_BYTES) || estimatedBytes > MAX_SESSION_BYTES) throw new SelectionExportError("selection_too_large");
    return { manifest, nodeCount: countNodes(manifest.top_level_nodes), assetCount: manifest.resources.length, estimatedBytes, warnings: manifest.warnings, sendable: true };
  } catch (error) {
    const safe = error instanceof SelectionExportError ? error : new SelectionExportError("selection_export_failed");
    return { manifest: null, nodeCount: 0, assetCount: 0, estimatedBytes: 0, warnings: [warning(safe.code, safe.message)], sendable: false };
  }
}

function countNodes(roots: readonly SerializedSelectionNode[]): number { let count = 0; const pending = [...roots]; while (pending.length) { const node = pending.pop()!; count += 1; if (count > MAX_NODES) throw new SelectionExportError("selection_too_large"); pending.push(...node.children); } return count; }
