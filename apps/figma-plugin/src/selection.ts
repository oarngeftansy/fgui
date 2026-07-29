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

export type FigmaSceneNode = { name: string; type: string; visible?: boolean; absoluteBoundingBox?: { x: number; y: number; width: number; height: number } | null; children?: readonly FigmaSceneNode[]; locked?: boolean; componentProperties?: Record<string, { value?: unknown }>; prototypeStartNode?: unknown };
type SceneLike = FigmaSceneNode;

export class SelectionExportError extends Error {
  constructor(public readonly code: "selection_too_large" | "selection_empty" | "selection_export_failed") {
    super(code === "selection_too_large" ? "选择内容过大" : code === "selection_empty" ? "请选择要导出的图层" : "选择导出失败");
    this.name = "SelectionExportError";
  }
}

function isAssetNode(node: SceneLike): boolean {
  return Array.isArray((node as unknown as { fills?: unknown }).fills) && (node as unknown as { fills: Array<{ type?: unknown }> }).fills.some((fill) => fill.type === "IMAGE");
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
  if (node.locked) properties.locked = true;
  const componentProperties = node.componentProperties as Record<string, { value?: unknown }> | undefined;
  if (componentProperties) {
    properties.component_properties = Object.fromEntries(Object.entries(componentProperties).map(([name, value]) => [name, value.value]));
  }
  return properties;
}

function nodeStyle(node: SceneLike): Record<string, unknown> {
  const text = node as unknown as { fontName?: unknown };
  if (text.fontName && typeof text.fontName === "object" && "family" in text.fontName && "style" in text.fontName) {
    const font = text.fontName as { family?: unknown; style?: unknown };
    if (typeof font.family === "string" && typeof font.style === "string") return { font: { family: font.family, style: font.style } };
  }
  return {};
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
    if (order > MAX_NODES) throw new SelectionExportError("selection_too_large");
    const resourceKeys: string[] = [];
    if (isAssetNode(node)) {
      const key = `asset-${resources.length + 1}`;
      resourceKeys.push(key);
      resources.push({ key, mime_type: node.type === "VECTOR" ? "image/svg+xml" : "image/png", size: 0 });
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
    for (let index = children.length - 1; index >= 0; index -= 1) pending.push({ node: children[index] as SceneLike, destination: serialized.children });
  }
  return { version: 1, display_name: roots[0]?.name ?? "当前选择", top_level_nodes: roots, resources, warnings };
}

export function resourceLookup(nodes: readonly FigmaSceneNode[], manifest: SelectionManifest): ReadonlyMap<string, FigmaSceneNode> {
  const assetNodes: FigmaSceneNode[] = [];
  const pending = nodes.slice().reverse() as FigmaSceneNode[];
  while (pending.length) {
    const node = pending.pop()! as SceneLike;
    if (isAssetNode(node)) assetNodes.push(node);
    const children = node.children ?? [];
    for (let index = children.length - 1; index >= 0; index -= 1) pending.push(children[index]!);
  }
  return new Map(manifest.resources.map((resource, index) => [resource.key, assetNodes[index]! ]));
}

export function preflightSelection(nodes: readonly FigmaSceneNode[]): SelectionPreflight {
  try {
    const manifest = serializeSelection(nodes);
    const estimatedBytes = manifest.resources.reduce((total, resource) => total + Math.min(MAX_RESOURCE_BYTES, Math.max(1, (resourceLookup(nodes, manifest).get(resource.key)?.absoluteBoundingBox?.width ?? 1) * (resourceLookup(nodes, manifest).get(resource.key)?.absoluteBoundingBox?.height ?? 1) * 4)), 0);
    if (estimatedBytes > MAX_SESSION_BYTES) throw new SelectionExportError("selection_too_large");
    return { manifest, nodeCount: manifest.top_level_nodes.reduce((total, node) => total + countNodes(node), 0), assetCount: manifest.resources.length, estimatedBytes, warnings: manifest.warnings, sendable: true };
  } catch (error) {
    const safe = error instanceof SelectionExportError ? error : new SelectionExportError("selection_export_failed");
    return { manifest: null, nodeCount: 0, assetCount: 0, estimatedBytes: 0, warnings: [warning(safe.code, safe.message)], sendable: false };
  }
}

function countNodes(node: SerializedSelectionNode): number { return 1 + node.children.reduce((total, child) => total + countNodes(child), 0); }
