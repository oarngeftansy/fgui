"use strict";
(() => {
  // apps/figma-plugin/src/contracts.ts
  var MAX_SEMANTIC_SCREENSHOT_BYTES = 1e3 * 1024;
  function isUiToMainMessage(value) {
    if (!value || typeof value !== "object") return false;
    const message = value;
    return message.type === "selection-preflight" || (message.type === "selection-export" || message.type === "semantic-screenshot-export") && typeof message.attempt === "string" && message.attempt.length > 0 || message.type === "locate-node" && typeof message.nodeId === "string" && message.nodeId.length > 0 && message.nodeId.length <= 256 && typeof message.attempt === "string" && message.attempt.length > 0 && message.attempt.length <= 128;
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
          if (resource.mime_type !== "image/svg+xml") throw new AssetExportError(node.name || "\u6240\u9009\u56FE\u5C42");
          try {
            results[index] = { key: resource.key, mime_type: "image/png", bytes: await node.exportAsync({ format: "PNG" }) };
          } catch {
            throw new AssetExportError(node.name || "\u6240\u9009\u56FE\u5C42");
          }
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(4, manifest.resources.length) }, worker));
    for (const resource of results) yield resource;
  }

  // apps/figma-plugin/src/visual-capability.ts
  var VECTOR_TYPES = /* @__PURE__ */ new Set(["VECTOR", "BOOLEAN_OPERATION", "STAR", "LINE", "POLYGON", "ELLIPSE"]);
  var VISUAL_EFFECT_TYPES = /* @__PURE__ */ new Set(["DROP_SHADOW", "INNER_SHADOW", "LAYER_BLUR", "BACKGROUND_BLUR"]);
  function visibleRecords(value) {
    return Array.isArray(value) ? value.filter((entry) => Boolean(entry) && typeof entry === "object" && entry.visible !== false) : [];
  }
  function positiveRadius(value) {
    return typeof value === "number" && Number.isFinite(value) && value > 0;
  }
  function radius(value, fallback) {
    if (value === void 0) return fallback;
    return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
  }
  function nativeMaskDescriptor(node) {
    if (!["GROUP", "FRAME", "COMPONENT"].includes(node.type)) return null;
    const children = node.children ?? [];
    const maskIndexes = children.flatMap((child, index) => child.isMask === true ? [index] : []);
    if (maskIndexes.length !== 1 || maskIndexes[0] !== 0 || children.length < 2) return null;
    const mask = children[0];
    if (mask.type !== "RECTANGLE" || (mask.children?.length ?? 0) > 0) return null;
    if (mask.maskType === "LUMINANCE" || typeof mask.opacity === "number" && mask.opacity !== 1) return null;
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
    const fill = fills[0];
    const color = fill.color;
    if (typeof fill.opacity === "number" && fill.opacity !== 1 || color && typeof color === "object" && typeof color.a === "number" && color.a !== 1) return null;
    const general = typeof mask.cornerRadius === "number" && Number.isFinite(mask.cornerRadius) && mask.cornerRadius >= 0 ? mask.cornerRadius : 0;
    const cornerRadii = [
      radius(mask.topLeftRadius, general),
      radius(mask.topRightRadius, general),
      radius(mask.bottomRightRadius, general),
      radius(mask.bottomLeftRadius, general)
    ];
    if (cornerRadii.some((value) => value === null)) return null;
    const resolvedRadii = cornerRadii;
    const rounded = resolvedRadii.some(positiveRadius);
    return {
      kind: rounded ? "roundedRectangle" : "rectangle",
      maskIndex: 0,
      contentIndexes: children.slice(1).map((_child, index) => index + 1),
      ...rounded ? { cornerRadii: resolvedRadii } : {}
    };
  }
  function classifyVisualNode(node, _context) {
    if (node.type === "VIDEO") return { strategy: "skip", mimeType: null, reasons: [] };
    const fills = visibleRecords(node.fills);
    const strokes = visibleRecords(node.strokes);
    const effects = visibleRecords(node.effects);
    const reasons = [];
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

  // apps/figma-plugin/src/nine-slice.ts
  var MARKER = /@9s\(([^)]*)\)/g;
  var VALID_TRAILING = /\s*@9s\((\d+),(\d+),(\d+),(\d+)\)\s*$/;
  function parseNineSliceAnnotation(name, bounds2) {
    const markers = [...name.matchAll(MARKER)];
    if (!name.includes("@9s")) return { displayName: name, insets: null, diagnostic: null };
    const match = VALID_TRAILING.exec(name);
    if (!match || markers.length !== 1) return { displayName: name, insets: null, diagnostic: "nine_slice_invalid" };
    const [left, top, right, bottom] = match.slice(1).map(Number);
    const displayName = name.slice(0, match.index).trimEnd();
    if (left + right >= bounds2.width || top + bottom >= bounds2.height) {
      return { displayName, insets: null, diagnostic: "nine_slice_out_of_bounds" };
    }
    return { displayName, insets: { left, top, right, bottom }, diagnostic: null };
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
  function channel(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return null;
    return Math.round(Math.max(0, Math.min(1, value)) * 255).toString(16).padStart(2, "0");
  }
  function solidRunColor(value) {
    if (!Array.isArray(value) || value.length !== 1) return null;
    const paint = value[0];
    if (!paint || typeof paint !== "object") return null;
    const record = paint;
    if (record.type !== "SOLID" || record.visible === false || !record.color || typeof record.color !== "object") return null;
    const color = record.color;
    const red = channel(color.r);
    const green = channel(color.g);
    const blue = channel(color.b);
    const paintOpacity = typeof record.opacity === "number" ? record.opacity : 1;
    const colorAlpha = typeof color.a === "number" ? color.a : 1;
    const alpha = channel(paintOpacity * colorAlpha);
    return red && green && blue && alpha ? `#${red}${green}${blue}${alpha}` : null;
  }
  function hasNonDefaultTextFeature(value) {
    if (value === null || value === void 0 || value === false || value === 0 || value === "NONE") return false;
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === "object") return Object.values(value).some(hasNonDefaultTextFeature);
    return true;
  }
  function hasDeclaredTextFeature(value) {
    if (Array.isArray(value)) return value.length > 0;
    return Boolean(value) && typeof value === "object" && Object.keys(value).length > 0;
  }
  function textRuns(node) {
    if (node.type !== "TEXT") return null;
    const getter = node.getStyledTextSegments;
    if (typeof getter !== "function") return null;
    let rawSegments;
    try {
      rawSegments = getter.call(node, [
        "fontName",
        "fontSize",
        "fills",
        "textDecoration",
        "textCase",
        "letterSpacing",
        "lineHeight",
        "listOptions",
        "listSpacing",
        "indentation",
        "paragraphIndent",
        "paragraphSpacing",
        "hyperlink",
        "boundVariables",
        "textStyleOverrides",
        "openTypeFeatures"
      ]);
    } catch {
      return [{ content: typeof node.characters === "string" ? node.characters : "", style: {}, unsupportedFeatures: ["styled_text_segments_unavailable"] }];
    }
    if (!Array.isArray(rawSegments) || !rawSegments.length) return null;
    const runs = rawSegments.map((raw) => {
      if (!raw || typeof raw !== "object") return { content: "", style: {}, unsupportedFeatures: ["styled_text_segment_invalid"] };
      const segment = raw;
      const unsupportedFeatures = [];
      const style = {};
      const fontName = segment.fontName;
      if (fontName && typeof fontName === "object") {
        const font = fontName;
        if (typeof font.family === "string" && typeof font.style === "string") style.font = { family: font.family, style: font.style };
        else unsupportedFeatures.push("font_name");
      } else unsupportedFeatures.push("font_name");
      if (typeof segment.fontSize === "number" && Number.isFinite(segment.fontSize) && segment.fontSize > 0) style.fontSize = segment.fontSize;
      else unsupportedFeatures.push("font_size");
      const color = solidRunColor(segment.fills);
      if (color) style.color = color;
      else unsupportedFeatures.push("text_run_fill");
      if (segment.textDecoration !== "NONE") unsupportedFeatures.push("text_decoration");
      if (segment.textCase !== "ORIGINAL") unsupportedFeatures.push("text_case");
      const letterSpacing = segment.letterSpacing;
      if (letterSpacing && typeof letterSpacing === "object" && letterSpacing.value !== 0) unsupportedFeatures.push("letter_spacing");
      const lineHeight = segment.lineHeight;
      if (lineHeight && typeof lineHeight === "object" && lineHeight.unit !== "AUTO") unsupportedFeatures.push("line_height");
      if (hasNonDefaultTextFeature(segment.listOptions)) unsupportedFeatures.push("list_options");
      if (hasNonDefaultTextFeature(segment.listSpacing)) unsupportedFeatures.push("list_spacing");
      if (hasNonDefaultTextFeature(segment.indentation)) unsupportedFeatures.push("indentation");
      if (hasNonDefaultTextFeature(segment.paragraphIndent)) unsupportedFeatures.push("paragraph_indent");
      if (hasNonDefaultTextFeature(segment.paragraphSpacing)) unsupportedFeatures.push("paragraph_spacing");
      if (hasNonDefaultTextFeature(segment.hyperlink)) unsupportedFeatures.push("hyperlink");
      if (hasNonDefaultTextFeature(segment.boundVariables)) unsupportedFeatures.push("bound_variables");
      if (hasNonDefaultTextFeature(segment.textStyleOverrides)) unsupportedFeatures.push("text_style_overrides");
      if (hasDeclaredTextFeature(segment.openTypeFeatures)) unsupportedFeatures.push("open_type_features");
      return {
        content: typeof segment.characters === "string" ? segment.characters : "",
        style,
        unsupportedFeatures
      };
    });
    const content = typeof node.characters === "string" ? node.characters : "";
    if (runs.map((run) => run.content).join("") !== content) return [{ content, style: {}, unsupportedFeatures: ["styled_text_segments_invalid"] }];
    return runs.length > 1 || runs.some((run) => run.unsupportedFeatures.length) ? runs : null;
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
    for (const key of ["primaryAxisAlignItems", "counterAxisAlignItems", "primaryAxisSizingMode", "counterAxisSizingMode", "counterAxisSpacing", "layoutWrap", "minWidth", "maxWidth", "minHeight", "maxHeight", "clipsContent", "cornerRadius", "topLeftRadius", "topRightRadius", "bottomLeftRadius", "bottomRightRadius", "layoutAlign", "layoutGrow", "textAutoResize", "textAlignHorizontal", "textAlignVertical", "fontSize", "lineHeight", "letterSpacing", "strokeWeight", "variantProperties"]) {
      const value = source[key];
      if (typeof value === "string" || typeof value === "number" || typeof value === "boolean" || value && typeof value === "object") addProperty(properties, propertyName(key), value);
    }
    const reactionCount = Array.isArray(node.reactions) ? node.reactions.length : 0;
    if (node.prototypeStartNode || reactionCount) properties.interactions = { present: true, reaction_count: reactionCount, prototype_start: Boolean(node.prototypeStartNode) };
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
    const color = solidRunColor(source.fills);
    if (color) style.color = color;
    const runs = textRuns(node);
    if (runs) style.runs = runs;
    if (Object.keys(styleReferences).length) style.style_references = styleReferences;
    return style;
  }
  function warning(code, message) {
    return { code, message };
  }
  function treeHasPrototypeBehavior(nodes) {
    const pending = [...nodes];
    while (pending.length) {
      const node = pending.pop();
      if (node.prototypeStartNode || Array.isArray(node.reactions) && node.reactions.length) return true;
      pending.push(...(node.children ?? []).map((child) => child));
    }
    return false;
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
      const capability = classifyVisualNode(node, { isRoot: parent === null });
      const nineSlice = parseNineSliceAnnotation(node.name, bounds(node));
      const mime_type = capability.mimeType;
      const reference = capability.strategy === "skip" || capability.strategy === "native" ? null : capability.strategy === "image_asset" ? imageReference(node, order) : `${capability.strategy}:${order}`;
      let resource;
      if (reference && mime_type) {
        const identity = `${mime_type}:${reference}:${order}`;
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
      const current = { node, order, parent, resource, styleReferences, capability, nineSlice };
      planned.push(current);
      const children = capability.strategy === "composite_png" || capability.strategy === "vector_asset" ? [] : node.children ?? [];
      if (pending.length + children.length > MAX_NODES) throw new SelectionExportError("selection_too_large");
      for (let index = children.length - 1; index >= 0; index -= 1) pending.push({ node: children[index], depth: depth + 1, parent: current });
    }
    return { nodes: planned, resources };
  }
  function serializeSelection(nodes) {
    const plan = selectionPlan(nodes);
    const roots = [];
    const warnings = [];
    if (treeHasPrototypeBehavior(nodes)) warnings.push(warning("unsupported_prototype", "\u539F\u578B\u8FDE\u7EBF\u4E0D\u4F1A\u5BFC\u51FA"));
    const serialized = /* @__PURE__ */ new Map();
    const plannedChildren = /* @__PURE__ */ new Map();
    for (const item of plan.nodes) {
      if (item.parent) plannedChildren.set(item.parent, [...plannedChildren.get(item.parent) ?? [], item]);
    }
    for (const item of plan.nodes) {
      const { node } = item;
      if (!node.visible) warnings.push(warning("node_hidden", "\u5DF2\u4FDD\u7559\u4E0D\u53EF\u89C1\u56FE\u5C42"));
      if (node.locked) warnings.push(warning("node_locked", "\u5DF2\u4FDD\u7559\u9501\u5B9A\u56FE\u5C42"));
      if (node.type === "VIDEO") warnings.push(warning("unsupported_video", "\u89C6\u9891\u5185\u5BB9\u4E0D\u4F1A\u5BFC\u51FA"));
      if (item.capability.strategy === "composite_png") warnings.push(warning("visual_rasterized", `\u5DF2\u5C06\u4E0D\u652F\u6301\u7684\u89C6\u89C9\u6548\u679C\u5408\u6210\u4E3A\u56FE\u7247\uFF1A${item.capability.reasons.join(",")}`));
      if (item.nineSlice.diagnostic === "nine_slice_invalid") warnings.push(warning("nine_slice_invalid", "\u4E5D\u5BAB\u683C\u6807\u8BB0\u683C\u5F0F\u65E0\u6548\uFF0C\u5DF2\u6309\u666E\u901A\u56FE\u7247\u5904\u7406"));
      if (item.nineSlice.diagnostic === "nine_slice_out_of_bounds") warnings.push(warning("nine_slice_out_of_bounds", "\u4E5D\u5BAB\u683C\u8FB9\u8DDD\u8D85\u8FC7\u56FE\u5C42\u5C3A\u5BF8\uFF0C\u5DF2\u6309\u666E\u901A\u56FE\u7247\u5904\u7406"));
      const properties = nodeProperties(node);
      properties.export_strategy = item.capability.strategy;
      if (item.capability.reasons.length) properties.raster_reasons = item.capability.reasons;
      if (item.nineSlice.insets) properties.nine_slice_insets = item.nineSlice.insets;
      const style = nodeStyle(node, item.styleReferences);
      const mask = nativeMaskDescriptor(node);
      if (mask) {
        const childPlans = plannedChildren.get(item) ?? [];
        const maskPlan = childPlans[mask.maskIndex];
        const contentPlans = mask.contentIndexes.map((index) => childPlans[index]).filter((child) => Boolean(child));
        if (maskPlan && contentPlans.length === mask.contentIndexes.length) {
          style.mask = {
            kind: mask.kind,
            maskNodeRef: `node-${maskPlan.order}`,
            contentNodeRefs: contentPlans.map((child) => `node-${child.order}`),
            effects: [],
            ...mask.cornerRadii ? { cornerRadii: mask.cornerRadii } : {}
          };
        }
      }
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
        properties,
        style,
        resource_keys: item.resource ? [item.resource.key] : []
      };
      result.name = item.nineSlice.displayName || result.name;
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
    if (current.length !== expected.length) return false;
    const expectedMembers = new Set(expected);
    const currentMembers = new Set(current);
    if (expectedMembers.size !== expected.length || currentMembers.size !== current.length) return false;
    return [...expectedMembers].every((node) => currentMembers.has(node));
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
    runtime.showUI(__html__, { width: 360, height: 680 });
    let prepared = null;
    const attempts = /* @__PURE__ */ new Map();
    let blockedCode = "selection_export_failed";
    let locatedSelection = null;
    const refresh = (type) => {
      const snapshot = runtime.currentPage ? [...runtime.currentPage.selection] : [];
      const preflight = preflightSelection(snapshot);
      prepared = preflight.manifest ? { manifest: preflight.manifest, lookup: resourceLookup(snapshot, preflight.manifest), roots: snapshot } : null;
      blockedCode = preflight.warnings[0]?.code ?? "selection_export_failed";
      const locateAttempt = type === "selection-changed" && locatedSelection && snapshot.length === 1 && snapshot[0]?.id === locatedSelection.nodeId ? locatedSelection.attempt : void 0;
      if (type === "selection-changed") locatedSelection = null;
      runtime.ui.postMessage({ type, preflight, ...locateAttempt ? { locateAttempt } : {} }, { origin: "*" });
    };
    runtime.ui.onmessage = (message, _props) => {
      if (!isUiToMainMessage(message)) return;
      if (message.type === "selection-preflight") {
        refresh("selection-preflight");
        return;
      }
      if (message.type === "locate-node") {
        void runtime.getNodeByIdAsync?.(message.nodeId).then((node) => {
          if (!node || !runtime.currentPage) return;
          locatedSelection = { attempt: message.attempt, nodeId: message.nodeId };
          runtime.currentPage.selection = [node];
          runtime.viewport?.scrollAndZoomIntoView([node]);
        });
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
            const mimeTypes = new Map(resources.map((resource) => [resource.key, resource.mime_type]));
            const manifest = {
              ...snapshot.manifest,
              resources: snapshot.manifest.resources.map((resource) => ({
                ...resource,
                mime_type: mimeTypes.get(resource.key) ?? resource.mime_type
              }))
            };
            runtime.ui.postMessage({ type: "selection-export", attempt: message.attempt, manifest, resources }, { origin: "*" });
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
