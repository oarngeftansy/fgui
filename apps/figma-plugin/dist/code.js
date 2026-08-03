"use strict";
(() => {
  // apps/figma-plugin/src/contracts.ts
  var MAX_SEMANTIC_SCREENSHOT_BYTES = 1e3 * 1024;
  function isUiToMainMessage(value) {
    if (!value || typeof value !== "object") return false;
    const message = value;
    return message.type === "selection-preflight" || (message.type === "selection-export" || message.type === "semantic-screenshot-export") && typeof message.attempt === "string" && message.attempt.length > 0;
  }

  // apps/figma-plugin/src/assets.ts
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

  // apps/figma-plugin/src/selection.ts
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

  // apps/figma-plugin/src/code.ts
  var MAX_SCREENSHOT_DIMENSION = 4096;
  var MAX_SCREENSHOT_PIXELS = 16e6;
  var PNG_SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];
  function sameSelection(runtime, expected) {
    const current = runtime.currentPage?.selection ?? [];
    return current.length === expected.length && current.every((node, index) => node === expected[index]);
  }
  function nodeBounds(node) {
    const bounds2 = node.absoluteRenderBounds ?? node.absoluteBoundingBox;
    return bounds2 && [bounds2.x, bounds2.y, bounds2.width, bounds2.height].every(Number.isFinite) && bounds2.width > 0 && bounds2.height > 0 ? bounds2 : null;
  }
  function validTransform(value) {
    return Boolean(value && value.length === 2 && value[0].length === 3 && value[1].length === 3 && [...value[0], ...value[1]].every(Number.isFinite));
  }
  function rigidTransform(value) {
    if (!validTransform(value)) return false;
    const [a, c] = value[0];
    const [b, d] = value[1];
    const tolerance = 1e-4;
    const close = (left, right) => Math.abs(left - right) <= tolerance;
    return close(Math.hypot(a, b), 1) && close(Math.hypot(c, d), 1) && close(a * c + b * d, 0) && close(Math.abs(a * d - b * c), 1);
  }
  function selectedBounds(nodes) {
    let left = Infinity;
    let top = Infinity;
    let right = -Infinity;
    let bottom = -Infinity;
    for (const node of nodes) {
      const bounds2 = nodeBounds(node);
      if (!bounds2) return null;
      left = Math.min(left, bounds2.x);
      top = Math.min(top, bounds2.y);
      right = Math.max(right, bounds2.x + bounds2.width);
      bottom = Math.max(bottom, bounds2.y + bounds2.height);
    }
    const result = { x: left, y: top, width: right - left, height: bottom - top };
    return nodes.length && Number.isFinite(result.width) && Number.isFinite(result.height) ? result : null;
  }
  function rootsOverlap(nodes) {
    const bounds2 = nodes.map(nodeBounds);
    for (let leftIndex = 0; leftIndex < bounds2.length; leftIndex += 1) {
      const left = bounds2[leftIndex];
      if (!left) return true;
      for (let rightIndex = leftIndex + 1; rightIndex < bounds2.length; rightIndex += 1) {
        const right = bounds2[rightIndex];
        if (!right) return true;
        const horizontal = Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x);
        const vertical = Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y);
        if (horizontal > 0 && vertical > 0) return true;
      }
    }
    return false;
  }
  function screenshotBoundsAllowed(bounds2) {
    return bounds2.width > 0 && bounds2.height > 0 && bounds2.width <= MAX_SCREENSHOT_DIMENSION && bounds2.height <= MAX_SCREENSHOT_DIMENSION && bounds2.width * bounds2.height <= MAX_SCREENSHOT_PIXELS;
  }
  function pngError(bytes) {
    if (bytes.length < 24 || PNG_SIGNATURE.some((value, index) => bytes[index] !== value)) return "selection_export_failed";
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    if (view.getUint32(8) !== 13 || bytes[12] !== 73 || bytes[13] !== 72 || bytes[14] !== 68 || bytes[15] !== 82) return "selection_export_failed";
    const width = view.getUint32(16);
    const height = view.getUint32(20);
    if (!width || !height) return "selection_export_failed";
    if (width > MAX_SCREENSHOT_DIMENSION || height > MAX_SCREENSHOT_DIMENSION || width * height > MAX_SCREENSHOT_PIXELS) return "selection_too_large";
    return null;
  }
  function startPlugin(runtime) {
    runtime.showUI(__html__, { width: 360, height: 460 });
    let prepared = null;
    const attempts = /* @__PURE__ */ new Map();
    let blockedCode = "selection_export_failed";
    const refresh = (type) => {
      const snapshot = runtime.currentPage ? [...runtime.currentPage.selection] : [];
      const preflight = preflightSelection(snapshot);
      prepared = preflight.manifest ? { manifest: preflight.manifest, lookup: resourceLookup(snapshot, preflight.manifest), roots: snapshot } : null;
      blockedCode = preflight.warnings[0]?.code ?? "selection_export_failed";
      runtime.ui.postMessage({ type, preflight }, { origin: "*" });
    };
    runtime.ui.onmessage = (message, _props) => {
      if (!isUiToMainMessage(message)) return;
      if (message.type === "selection-preflight") {
        refresh("selection-preflight");
        return;
      }
      if (message.type === "selection-export") {
        const snapshot = prepared;
        if (snapshot) {
          attempts.set(message.attempt, snapshot);
          if (attempts.size > 8) attempts.delete(attempts.keys().next().value);
        }
        void (async () => {
          if (!snapshot) {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: blockedCode }, { origin: "*" });
            return;
          }
          try {
            const resources = [];
            for await (const resource of exportDeclaredAssets(snapshot.manifest, snapshot.lookup)) resources.push(resource);
            runtime.ui.postMessage({ type: "selection-export", attempt: message.attempt, manifest: snapshot.manifest, resources }, { origin: "*" });
          } catch {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" });
          }
        })();
        return;
      }
      if (message.type === "semantic-screenshot-export") {
        const snapshot = attempts.get(message.attempt);
        void (async () => {
          if (!snapshot) {
            const code = (runtime.currentPage?.selection.length ?? 0) === 0 ? "selection_empty" : "selection_changed";
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code }, { origin: "*" });
            return;
          }
          if (!sameSelection(runtime, snapshot.roots)) {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_changed" }, { origin: "*" });
            return;
          }
          const bounds2 = selectedBounds(snapshot.roots);
          if (!bounds2) {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" });
            return;
          }
          if (!screenshotBoundsAllowed(bounds2)) {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_too_large" }, { origin: "*" });
            return;
          }
          if (snapshot.roots.length > 1 && rootsOverlap(snapshot.roots)) {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" });
            return;
          }
          const directNode = snapshot.roots.length === 1 ? snapshot.roots[0] : null;
          if (directNode && typeof directNode.exportAsync !== "function") {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" });
            return;
          }
          const isolatedRoots = directNode ? null : snapshot.roots.map((root) => {
            const source = root;
            const rootBounds = nodeBounds(root);
            return rootBounds && rigidTransform(root.absoluteTransform) && typeof source.clone === "function" ? { source, transform: root.absoluteTransform } : null;
          });
          if (isolatedRoots?.some((root) => !root)) {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: "selection_export_failed" }, { origin: "*" });
            return;
          }
          let frame = null;
          const clones = [];
          const attachedClones = /* @__PURE__ */ new Set();
          let screenshotBytes = null;
          let failureCode = null;
          try {
            if (!directNode) {
              frame = runtime.createFrame();
              frame.name = "Temporary isolated screenshot";
              frame.fills = [];
              frame.layoutMode = "NONE";
              frame.clipsContent = true;
              frame.x = bounds2.x;
              frame.y = bounds2.y;
              frame.resize(bounds2.width, bounds2.height);
              for (const isolated of isolatedRoots) {
                const { source, transform } = isolated;
                const clone = source.clone();
                if (!clone || typeof clone.remove !== "function") throw new Error("unsupported screenshot clone");
                clones.push(clone);
                if (typeof clone.x !== "number" || typeof clone.y !== "number" || !validTransform(clone.relativeTransform)) throw new Error("unsupported screenshot clone");
                frame.appendChild(clone);
                attachedClones.add(clone);
                clone.relativeTransform = [
                  [transform[0][0], transform[0][1], transform[0][2] - bounds2.x],
                  [transform[1][0], transform[1][1], transform[1][2] - bounds2.y]
                ];
              }
            }
            if (!sameSelection(runtime, snapshot.roots)) {
              failureCode = "selection_changed";
            } else {
              const node = directNode ?? frame;
              const bytes = await node.exportAsync({ format: "PNG", constraint: { type: "SCALE", value: 1 } });
              if (!sameSelection(runtime, snapshot.roots)) {
                failureCode = "selection_changed";
              } else if (!bytes.length || bytes.length > MAX_SEMANTIC_SCREENSHOT_BYTES) {
                failureCode = bytes.length ? "selection_too_large" : "selection_export_failed";
              } else {
                failureCode = pngError(bytes);
                if (!failureCode) screenshotBytes = bytes;
              }
            }
          } catch {
            failureCode = "selection_export_failed";
          }
          let frameRemoved = false;
          let cleanupFailed = false;
          if (frame) {
            try {
              frame.remove();
              frameRemoved = true;
            } catch {
              cleanupFailed = true;
            }
          }
          for (let index = clones.length - 1; index >= 0; index -= 1) {
            const clone = clones[index];
            if (frameRemoved && attachedClones.has(clone)) continue;
            try {
              clone.remove();
            } catch {
              cleanupFailed = true;
            }
          }
          if (cleanupFailed) failureCode = "selection_export_failed";
          if (failureCode || !screenshotBytes) {
            runtime.ui.postMessage({ type: "selection-error", attempt: message.attempt, code: failureCode ?? "selection_export_failed" }, { origin: "*" });
          } else {
            runtime.ui.postMessage({ type: "semantic-screenshot-export", attempt: message.attempt, mimeType: "image/png", bytes: screenshotBytes }, { origin: "*" });
          }
        })();
      }
    };
    runtime.on("selectionchange", () => refresh("selection-changed"));
    refresh("selection-preflight");
  }
  if (typeof figma !== "undefined") {
    startPlugin(figma);
  }
})();
