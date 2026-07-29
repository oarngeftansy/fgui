"use strict";
(() => {
  // src/contracts.ts
  function isUiToMainMessage(value) {
    if (!value || typeof value !== "object") return false;
    const message = value;
    return message.type === "unpair" || message.type === "selection-preflight" || message.type === "selection-export" && typeof message.attempt === "string" || message.type === "pairing-credential" && typeof message.credential === "string";
  }

  // src/pairing.ts
  var CREDENTIAL_KEY = "figma-to-fairygui-plugin-credential";
  var CredentialStore = class {
    constructor(storage) {
      this.storage = storage;
    }
    async load() {
      const value = await this.storage.getAsync(CREDENTIAL_KEY);
      return typeof value === "string" && value.length > 0 ? value : null;
    }
    save(credential) {
      return this.storage.setAsync(CREDENTIAL_KEY, credential);
    }
    clear() {
      return this.storage.deleteAsync(CREDENTIAL_KEY);
    }
  };
  function createMainPairingController(config, store, post) {
    const send = (message) => post(message, config.serverOrigin);
    return {
      async restore() {
        const credential = await store.load();
        if (credential) {
          send({ type: "credential", credential });
        } else {
          send({ type: "pairing-status", status: "unpaired" });
        }
      },
      async handle(message) {
        if (message.type === "pairing-credential") {
          await store.save(message.credential);
          send({ type: "pairing-status", status: "paired" });
          return;
        }
        await store.clear();
        send({ type: "pairing-status", status: "unpaired" });
      }
    };
  }

  // src/assets.ts
  var AssetExportError = class extends Error {
    constructor(label) {
      super(`\u65E0\u6CD5\u5BFC\u51FA\u56FE\u5C42\uFF1A${label}`);
      this.name = "AssetExportError";
    }
  };
  async function* exportDeclaredAssets(manifest, lookup) {
    const results = new Array(manifest.resources.length);
    let cursor = 0;
    const worker = async () => {
      while (cursor < manifest.resources.length) {
        const index = cursor++;
        const resource = manifest.resources[index];
        const node = lookup.get(resource.key);
        if (!node) throw new AssetExportError("\u6240\u9009\u56FE\u5C42");
        try {
          const format = resource.mime_type === "image/svg+xml" ? "SVG" : "PNG";
          results[index] = { key: resource.key, mime_type: resource.mime_type, bytes: await node.exportAsync({ format }) };
        } catch {
          throw new AssetExportError(node.name || "\u6240\u9009\u56FE\u5C42");
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(4, manifest.resources.length) }, worker));
    for (const resource of results) yield resource;
  }

  // src/selection.ts
  var MAX_TOP_LEVEL = 20;
  var MAX_NODES = 5e3;
  var MAX_RESOURCE_BYTES = 25 * 1024 * 1024;
  var MAX_SESSION_BYTES = 200 * 1024 * 1024;
  var MAX_DEPTH = 32;
  var MAX_PROPERTIES = 128;
  var MAX_STRING = 64 * 1024;
  var MAX_VALUES = 1e5;
  var SVG_TYPES = /* @__PURE__ */ new Set(["VECTOR", "BOOLEAN_OPERATION", "STAR", "LINE", "POLYGON", "ELLIPSE"]);
  var STYLE_REFERENCE_KEYS = ["fillStyleId", "strokeStyleId", "effectStyleId", "textStyleId"];
  var SelectionExportError = class extends Error {
    constructor(code) {
      super(code === "selection_too_large" ? "\u9009\u62E9\u5185\u5BB9\u8FC7\u5927" : code === "selection_empty" ? "\u8BF7\u9009\u62E9\u8981\u5BFC\u51FA\u7684\u56FE\u5C42" : "\u9009\u62E9\u5BFC\u51FA\u5931\u8D25");
      this.code = code;
      this.name = "SelectionExportError";
    }
  };
  function imageReference(node, localOrder) {
    if (node.type === "VIDEO") return null;
    const fills = node.fills;
    if (!Array.isArray(fills)) return null;
    const image = fills.find((fill) => fill && typeof fill === "object" && fill.type === "IMAGE");
    if (!image) return null;
    return typeof image.imageHash === "string" ? `hash:${image.imageHash}` : typeof image.imageRef === "string" ? `ref:${image.imageRef}` : `local:${localOrder}`;
  }
  function bounds(node) {
    const value = node.absoluteBoundingBox;
    return value ? { x: value.x, y: value.y, width: value.width, height: value.height } : { x: 0, y: 0, width: 0, height: 0 };
  }
  function sanitizeVisualValue(value, depth = 0, count = { value: 0 }) {
    count.value += 1;
    if (count.value > MAX_VALUES || depth > MAX_DEPTH) throw new SelectionExportError("selection_too_large");
    if (typeof value === "string") {
      if (value.length > MAX_STRING) throw new SelectionExportError("selection_too_large");
      return value;
    }
    if (value === null || typeof value === "boolean") return value;
    if (typeof value === "number") return Number.isFinite(value) ? value : void 0;
    if (Array.isArray(value)) {
      if (value.length > MAX_PROPERTIES) throw new SelectionExportError("selection_too_large");
      return value.map((nested) => sanitizeVisualValue(nested, depth + 1, count)).filter((nested) => nested !== void 0);
    }
    if (!value || typeof value !== "object") return void 0;
    const entries = Object.entries(value);
    if (entries.length > MAX_PROPERTIES) throw new SelectionExportError("selection_too_large");
    const safe = {};
    for (const [name, nested] of entries) {
      if (name.length > MAX_STRING) throw new SelectionExportError("selection_too_large");
      if (/(?:url|href|src|image(?:hash|ref)?|bytes?|base64|data|(?:node)?id|path|file)/i.test(name)) continue;
      const sanitized = sanitizeVisualValue(nested, depth + 1, count);
      if (sanitized !== void 0) safe[name] = sanitized;
    }
    return safe;
  }
  function addProperty(target, name, value) {
    const sanitized = sanitizeVisualValue(value);
    if (sanitized !== void 0) target[name] = sanitized;
  }
  function propertyName(name) {
    return name.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
  }
  function nodeProperties(node) {
    const properties = {};
    const layout = node;
    if (typeof layout.layoutMode === "string" && layout.layoutMode !== "NONE") {
      properties.layout_mode = layout.layoutMode;
      for (const key of ["itemSpacing", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft"]) if (typeof layout[key] === "number") properties[propertyName(key)] = layout[key];
    }
    if (layout.constraints && typeof layout.constraints === "object") addProperty(properties, "constraints", layout.constraints);
    const source = node;
    for (const key of ["primaryAxisAlignItems", "counterAxisAlignItems", "primaryAxisSizingMode", "counterAxisSizingMode", "clipsContent", "cornerRadius", "topLeftRadius", "topRightRadius", "bottomLeftRadius", "bottomRightRadius", "layoutAlign", "layoutGrow", "textAutoResize", "textAlignHorizontal", "textAlignVertical", "fontSize", "lineHeight", "letterSpacing", "variantProperties"]) {
      const value = source[key];
      if (typeof value === "string" || typeof value === "number" || typeof value === "boolean" || value && typeof value === "object") addProperty(properties, propertyName(key), value);
    }
    if (node.locked) properties.locked = true;
    if (node.componentProperties) {
      const entries = Object.entries(node.componentProperties);
      if (entries.length > MAX_PROPERTIES) throw new SelectionExportError("selection_too_large");
      const componentProperties = {};
      for (const [name, value] of entries) {
        const sanitized = sanitizeVisualValue(value.value);
        if (sanitized !== void 0) componentProperties[name] = sanitized;
      }
      properties.component_properties = componentProperties;
    }
    return properties;
  }
  function nodeStyle(node, styleReferences) {
    const source = node;
    const style = {};
    for (const key of ["fills", "strokes", "effects", "relativeTransform", "absoluteTransform"]) if (Array.isArray(source[key])) addProperty(style, propertyName(key), source[key]);
    const font = node.fontName;
    if (font && typeof font.family === "string" && typeof font.style === "string") addProperty(style, "font", { family: font.family, style: font.style });
    if (Object.keys(styleReferences).length) style.style_references = styleReferences;
    return style;
  }
  function warning(code, message) {
    return { code, message };
  }
  function selectionPlan(nodes) {
    if (!nodes.length) throw new SelectionExportError("selection_empty");
    if (nodes.length > MAX_TOP_LEVEL) throw new SelectionExportError("selection_too_large");
    const planned = [];
    const resources = [];
    const byReference = /* @__PURE__ */ new Map();
    const styleTokens = /* @__PURE__ */ new Map();
    const pending = nodes.slice().reverse().map((node) => ({ node, depth: 1, parent: null }));
    while (pending.length) {
      const { node, depth, parent } = pending.pop();
      const order = planned.length + 1;
      if (order > MAX_NODES || depth > MAX_DEPTH || node.name.length > MAX_STRING || typeof node.characters === "string" && node.characters.length > MAX_STRING) throw new SelectionExportError("selection_too_large");
      const vector = SVG_TYPES.has(node.type);
      const mime_type = vector ? "image/svg+xml" : "image/png";
      const reference = node.type === "VIDEO" ? null : imageReference(node, order) ?? (vector ? `svg:${order}` : null);
      let resource;
      if (reference) {
        const identity = `${mime_type}:${reference}`;
        resource = byReference.get(identity);
        if (!resource) {
          resource = { key: `asset-${resources.length + 1}`, mime_type, node };
          byReference.set(identity, resource);
          resources.push(resource);
        }
      }
      const styleReferences = {};
      for (const key of STYLE_REFERENCE_KEYS) {
        const raw = node[key];
        if (typeof raw !== "string") continue;
        let token = styleTokens.get(raw);
        if (!token) {
          token = `style-${styleTokens.size + 1}`;
          styleTokens.set(raw, token);
        }
        styleReferences[propertyName(key)] = token;
      }
      const current = { node, order, parent, resource, styleReferences };
      planned.push(current);
      const children = node.children ?? [];
      if (pending.length + children.length > MAX_NODES) throw new SelectionExportError("selection_too_large");
      for (let index = children.length - 1; index >= 0; index -= 1) pending.push({ node: children[index], depth: depth + 1, parent: current });
    }
    return { nodes: planned, resources };
  }
  function serializeSelection(nodes) {
    const plan = selectionPlan(nodes);
    const roots = [];
    const warnings = [];
    const serialized = /* @__PURE__ */ new Map();
    for (const item of plan.nodes) {
      const { node } = item;
      if (!node.visible) warnings.push(warning("node_hidden", "\u5DF2\u4FDD\u7559\u4E0D\u53EF\u89C1\u56FE\u5C42"));
      if (node.locked) warnings.push(warning("node_locked", "\u5DF2\u4FDD\u7559\u9501\u5B9A\u56FE\u5C42"));
      if (node.type === "VIDEO") warnings.push(warning("unsupported_video", "\u89C6\u9891\u5185\u5BB9\u4E0D\u4F1A\u5BFC\u51FA"));
      if (node.prototypeStartNode) warnings.push(warning("unsupported_prototype", "\u539F\u578B\u8FDE\u7EBF\u4E0D\u4F1A\u5BFC\u51FA"));
      const result = {
        id: `node-${item.order}`,
        name: node.name || "\u672A\u547D\u540D\u56FE\u5C42",
        type: node.type,
        bounds: bounds(node),
        children: [],
        rotation: typeof node.rotation === "number" ? node.rotation : 0,
        visible: node.visible !== false,
        opacity: typeof node.opacity === "number" ? node.opacity : 1,
        source_order: item.order - 1,
        ...typeof node.characters === "string" ? { text: node.characters } : {},
        properties: nodeProperties(node),
        style: nodeStyle(node, item.styleReferences),
        resource_keys: item.resource ? [item.resource.key] : []
      };
      (item.parent ? serialized.get(item.parent).children : roots).push(result);
      serialized.set(item, result);
    }
    return { version: 1, display_name: roots[0]?.name ?? "\u5F53\u524D\u9009\u62E9", top_level_nodes: roots, resources: plan.resources.map(({ key, mime_type }) => ({ key, mime_type, size: 0 })), warnings };
  }
  function resourceLookup(nodes, manifest) {
    const declarations = new Map(selectionPlan(nodes).resources.map((resource) => [resource.key, resource.node]));
    return new Map(manifest.resources.flatMap((resource) => {
      const node = declarations.get(resource.key);
      return node ? [[resource.key, node]] : [];
    }));
  }
  function preflightSelection(nodes) {
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

  // src/code.ts
  function startPlugin(config, runtime) {
    runtime.showUI('<!doctype html>\n<html lang="zh-CN">\n  <head>\n    <meta charset="utf-8" />\n    <meta name="viewport" content="width=device-width, initial-scale=1" />\n    <title>Figma \u8F6C FairyGUI</title>\n  </head>\n  <body>\n    <script>location.replace("https://fgui.corp.example/figma-plugin?pluginId=123456789");<\/script>\n  </body>\n</html>\n', { width: 360, height: 460 });
    const controller = createMainPairingController(config, new CredentialStore(runtime.clientStorage), (message, origin) => {
      runtime.ui.postMessage(message, { origin });
    });
    let prepared = null;
    runtime.ui.onmessage = (message, props) => {
      if (props.origin !== config.serverOrigin) return;
      if (!isUiToMainMessage(message)) return;
      if (message.type === "selection-preflight") {
        const snapshot = runtime.currentPage ? [...runtime.currentPage.selection] : [];
        const preflight = preflightSelection(snapshot);
        prepared = preflight.manifest ? { manifest: preflight.manifest, lookup: resourceLookup(snapshot, preflight.manifest) } : null;
        runtime.ui.postMessage({ type: "selection-preflight", preflight }, { origin: config.serverOrigin });
        return;
      }
      if (message.type === "selection-export") {
        void (async () => {
          if (!prepared) {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: config.serverOrigin });
            return;
          }
          try {
            const resources = [];
            for await (const resource of exportDeclaredAssets(prepared.manifest, prepared.lookup)) resources.push(resource);
            runtime.ui.postMessage({ type: "selection-export", attempt: message.attempt, manifest: prepared.manifest, resources }, { origin: config.serverOrigin });
          } catch {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: config.serverOrigin });
          }
        })();
        return;
      }
      void controller.handle(message);
    };
    void controller.restore();
  }
  if (typeof figma !== "undefined") {
    startPlugin({ serverOrigin: "https://fgui.corp.example", pluginId: "123456789" }, figma);
  }
})();
