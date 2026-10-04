import { useEffect, useMemo, useState, type CSSProperties } from "react";
import type {
  HifiMappingAction,
  HifiMappingDraft,
  HifiMappingItem,
  PsdLayer,
} from "../../../figma-plugin/src/project-client";

type PreviewBounds = [number, number, number, number];
type CanvasSize = { width: number; height: number };
type MappingUnit = {
  id: string;
  label: string;
  bounds?: PreviewBounds;
  members: HifiMappingItem[];
};

function unionBounds(list: PreviewBounds[]): PreviewBounds | undefined {
  if (!list.length) return undefined;
  const left = Math.min(...list.map((bounds) => bounds[0]));
  const top = Math.min(...list.map((bounds) => bounds[1]));
  const right = Math.max(...list.map((bounds) => bounds[0] + bounds[2]));
  const bottom = Math.max(...list.map((bounds) => bounds[1] + bounds[3]));
  return [left, top, right - left, bottom - top];
}

function memberBounds(
  members: HifiMappingItem[],
  side: "old" | "figma",
): PreviewBounds | undefined {
  return unionBounds(
    members
      .map((item) => (side === "old" ? item.oldBounds : item.figmaBounds))
      .filter((bounds): bounds is PreviewBounds => Boolean(bounds)),
  );
}

function buildOldUnits(items: HifiMappingItem[]): MappingUnit[] {
  const units: MappingUnit[] = items
    .filter((item) => item.oldObjectType === "component" && item.oldObjectId)
    .map((component) => ({
      id: `unit:${component.itemId}`,
      label: component.oldName ?? component.itemId,
      members: [component],
    }));
  const pageMembers: HifiMappingItem[] = [];
  for (const item of items) {
    if (!item.oldObjectId) {
      pageMembers.push(item);
      continue;
    }
    const segments = item.oldObjectId.split(":").filter(Boolean);
    let owner: MappingUnit | undefined;
    for (let cut = segments.length - 1; cut >= 1; cut -= 1) {
      const prefix = segments.slice(0, cut).join(":");
      owner = units.find((unit) => unit.members[0]?.oldObjectId === prefix);
      if (owner) break;
    }
    if (owner) owner.members.push(item);
    else if (item.oldObjectType !== "component") pageMembers.push(item);
  }
  if (pageMembers.length)
    units.push({ id: "unit:page", label: "页面直接对象", members: pageMembers });
  for (const unit of units) unit.bounds = memberBounds(unit.members, "old");
  return units;
}

function buildPsdUnits(
  items: HifiMappingItem[],
  psdLayers: PsdLayer[] | undefined,
  canvasSize: CanvasSize | undefined,
): MappingUnit[] {
  const layerById = new Map((psdLayers ?? []).map((layer) => [layer.id, layer]));
  const groupKeyOf = (layerId: string): string => {
    let cursor = layerById.get(layerId);
    while (cursor && cursor.kind !== "group" && cursor.parentId)
      cursor = layerById.get(cursor.parentId);
    return cursor && cursor.kind === "group" ? cursor.id : layerId;
  };
  const grouped = new Map<string, HifiMappingItem[]>();
  for (const item of items) {
    let key: string | undefined;
    if (item.ownedGroupId) key = item.ownedGroupId;
    else if (item.figmaNodeId)
      key = psdLayers ? groupKeyOf(item.figmaNodeId) : item.figmaNodeId;
    else if (item.candidates[0]?.startsWith("psd-layer:"))
      key = item.candidates[0];
    if (!key) continue;
    const members = grouped.get(key);
    if (members) members.push(item);
    else grouped.set(key, [item]);
  }
  const units: MappingUnit[] = [];
  for (const [key, members] of grouped) {
    const layer = layerById.get(key);
    let bounds = memberBounds(members, "figma");
    if (!bounds && layer && canvasSize)
      bounds = [
        layer.bounds[0] / canvasSize.width,
        layer.bounds[1] / canvasSize.height,
        (layer.bounds[2] - layer.bounds[0]) / canvasSize.width,
        (layer.bounds[3] - layer.bounds[1]) / canvasSize.height,
      ];
    units.push({
      id: `psd-unit:${key}`,
      label: layer?.name ?? key.split(":").pop() ?? key,
      bounds,
      members,
    });
  }
  return units;
}

function focusViewport(bounds: PreviewBounds): PreviewBounds {
  const size = Math.min(1, Math.max(0.24, bounds[2] * 3.2, bounds[3] * 3.2));
  const centerX = bounds[0] + bounds[2] / 2;
  const centerY = bounds[1] + bounds[3] / 2;
  return [
    Math.max(0, Math.min(1 - size, centerX - size / 2)),
    Math.max(0, Math.min(1 - size, centerY - size / 2)),
    size,
    size,
  ];
}

function intersects(bounds: PreviewBounds, viewport: PreviewBounds): boolean {
  return (
    bounds[0] < viewport[0] + viewport[2] &&
    bounds[0] + bounds[2] > viewport[0] &&
    bounds[1] < viewport[1] + viewport[3] &&
    bounds[1] + bounds[3] > viewport[1]
  );
}

function MappingCanvas({
  side,
  items,
  units,
  unitView,
  currentId,
  onSelect,
  onSelectUnit,
  previewBounds,
  psdPreviewUrl,
  oldPreviewUrl,
  canvasSize,
  focused,
}: {
  side: "old" | "figma";
  items: HifiMappingItem[];
  units: MappingUnit[];
  unitView: boolean;
  currentId?: string;
  onSelect(itemId: string): void;
  onSelectUnit(unit: MappingUnit): void;
  previewBounds?: PreviewBounds;
  psdPreviewUrl?: string;
  oldPreviewUrl?: string;
  canvasSize?: CanvasSize;
  focused: boolean;
}) {
  const current = items.find((item) => item.itemId === currentId);
  const currentUnit = units.find((unit) =>
    unit.members.some((member) => member.itemId === currentId),
  );
  const itemBounds =
    current && (side === "old" ? current.oldBounds : current.figmaBounds);
  const currentBounds = unitView ? currentUnit?.bounds : itemBounds;
  const missingCurrent = current && !currentBounds;
  const sideName = side === "old" ? "旧 FGUI" : "HIFI";
  const viewport: PreviewBounds =
    focused && currentBounds ? focusViewport(currentBounds) : [0, 0, 1, 1];
  const nearby = currentBounds
    ? items
          .filter((item) => item.itemId !== currentId)
          .map((item) => ({
            item,
            bounds: side === "old" ? item.oldBounds : item.figmaBounds,
          }))
          .filter(
            (
              entry,
            ): entry is { item: HifiMappingItem; bounds: PreviewBounds } =>
              Boolean(entry.bounds && intersects(entry.bounds, viewport)),
          )
          .sort((left, right) => {
            const centerX = currentBounds[0] + currentBounds[2] / 2;
            const centerY = currentBounds[1] + currentBounds[3] / 2;
            const leftDistance =
              Math.abs(left.bounds[0] + left.bounds[2] / 2 - centerX) +
              Math.abs(left.bounds[1] + left.bounds[3] / 2 - centerY);
            const rightDistance =
              Math.abs(right.bounds[0] + right.bounds[2] / 2 - centerX) +
              Math.abs(right.bounds[1] + right.bounds[3] / 2 - centerY);
            return leftDistance - rightDistance;
          })
          .slice(0, 12)
          .map((entry) => entry.item)
      : [];
  const previewItems = focused ? (current ? [...nearby, current] : []) : items;
  return (
    <div
      className="hifi-canvas-wrap"
      style={
        canvasSize
          ? ({
              "--canvas-ratio": canvasSize.width / canvasSize.height,
            } as CSSProperties)
          : undefined
      }
    >
      <div
        className="hifi-canvas"
        aria-label={`${sideName} 结构`}
        style={
          canvasSize
            ? { aspectRatio: `${canvasSize.width} / ${canvasSize.height}` }
            : undefined
        }
      >
        {side === "figma" && psdPreviewUrl && (
          <img
            className="hifi-canvas-psd"
            src={psdPreviewUrl}
            alt="HIFI PSD 实际画面"
            style={{
              left: `${(-viewport[0] / viewport[2]) * 100}%`,
              top: `${(-viewport[1] / viewport[3]) * 100}%`,
              width: `${100 / viewport[2]}%`,
              height: `${100 / viewport[3]}%`,
            }}
          />
        )}
        {side === "old" && oldPreviewUrl && currentBounds && (
          <img
            className="hifi-canvas-psd"
            src={oldPreviewUrl}
            alt="旧 FGUI 对象资源图"
            style={{
              left: `${((currentBounds[0] - viewport[0]) / viewport[2]) * 100}%`,
              top: `${((currentBounds[1] - viewport[1]) / viewport[3]) * 100}%`,
              width: `${(currentBounds[2] / viewport[2]) * 100}%`,
              height: `${(currentBounds[3] / viewport[3]) * 100}%`,
            }}
          />
        )}
        {unitView &&
          units.map((unit) => {
            if (!unit.bounds) return null;
            const left = ((unit.bounds[0] - viewport[0]) / viewport[2]) * 100;
            const top = ((unit.bounds[1] - viewport[1]) / viewport[3]) * 100;
            const width = (unit.bounds[2] / viewport[2]) * 100;
            const height = (unit.bounds[3] / viewport[3]) * 100;
            return (
              <button
                type="button"
                aria-label={`${sideName} · ${unit.label}`}
                className={`hifi-canvas-unit ${unit.id === currentUnit?.id ? "is-active" : ""}`}
                style={{
                  left: `${left}%`,
                  top: `${top}%`,
                  width: `${Math.max(width, 4)}%`,
                  height: `${Math.max(height, 4)}%`,
                }}
                onClick={() => onSelectUnit(unit)}
                key={`${side}-${unit.id}`}
              />
            );
          })}
        {!unitView &&
          previewItems.map((item) => {
            const bounds = side === "old" ? item.oldBounds : item.figmaBounds;
            if (!bounds) return null;
            const name = side === "old" ? item.oldName : item.figmaName;
            const left = ((bounds[0] - viewport[0]) / viewport[2]) * 100;
            const top = ((bounds[1] - viewport[1]) / viewport[3]) * 100;
            const width = (bounds[2] / viewport[2]) * 100;
            const height = (bounds[3] / viewport[3]) * 100;
            return (
              <button
                type="button"
                aria-label={`${sideName} · ${name ?? item.itemId}`}
                className={`hifi-canvas-object ${item.itemId === currentId ? "is-active" : ""}`}
                style={{
                  left: `${left}%`,
                  top: `${top}%`,
                  width: `${Math.max(width, 4)}%`,
                  height: `${Math.max(height, 4)}%`,
                }}
                onClick={() => onSelect(item.itemId)}
                key={`${side}-${item.itemId}`}
              />
            );
          })}
        {previewBounds && (
          <div
            className="hifi-canvas-preview"
            style={{
              left: `${((previewBounds[0] - viewport[0]) / viewport[2]) * 100}%`,
              top: `${((previewBounds[1] - viewport[1]) / viewport[3]) * 100}%`,
              width: `${(previewBounds[2] / viewport[2]) * 100}%`,
              height: `${(previewBounds[3] / viewport[3]) * 100}%`,
            }}
          />
        )}
        {missingCurrent && (
          <div
            className="hifi-canvas-empty is-active"
            data-testid={`${side === "old" ? "fgui" : "hifi"}-focus`}
          >
            此侧无对应对象
          </div>
        )}
        {current && !missingCurrent && (
          <div
            className="hifi-focus-label"
            data-testid={`${side === "old" ? "fgui" : "hifi"}-focus`}
            aria-label={`${sideName} · ${side === "old" ? current.oldName : current.figmaName}`}
          />
        )}
      </div>
      <div className="hifi-canvas-caption">
        <strong>
          {(unitView
            ? currentUnit?.label
            : current &&
                (side === "old" ? current.oldName : current.figmaName)) ||
            "无对应对象"}
        </strong>
        <small>
          {unitView
            ? `${currentUnit?.members.length ?? 0} 条映射记录`
            : side === "old" && current?.oldObjectType
              ? `旧对象类型：${current.oldObjectType}${oldPreviewUrl ? " · 原资源图" : " · 暂无渲染预览"}`
              : side === "figma" && psdPreviewUrl
                ? "PSD 合成图中的实际位置"
                : "未提供画面预览，当前显示对象边界"}
        </small>
      </div>
    </div>
  );
}

const STATUS_LABELS: Record<HifiMappingItem["status"], string> = {
  matched: "已对应",
  suggested: "建议对应",
  uncertain: "待判断",
  fgui_only: "仅旧工程",
  hifi_added: "PSD 未对应",
  blocked: "PSD 容器待对应",
  structural: "非绘制结构已保留",
  out_of_scope: "范围外（跨包共享组件）",
  occluded: "已遮挡（上层不透明全幅图层）",
};

export function HifiMappingPanel({
  mapping,
  currentItemId,
  busy,
  onCurrentChange,
  onDecision,
  onLocate,
  psdPreviewUrl,
  oldPreviewUrl,
  psdLayers,
  allowVisualAddition = true,
  allowKeepOld = true,
}: {
  mapping: HifiMappingDraft;
  currentItemId?: string;
  busy: boolean;
  onCurrentChange(itemId: string): void;
  onDecision(
    item: HifiMappingItem,
    action: HifiMappingAction,
    figmaNodeId?: string,
  ): void;
  onLocate?(nodeId: string): void;
  psdPreviewUrl?: string;
  oldPreviewUrl?: string;
  psdLayers?: PsdLayer[];
  allowVisualAddition?: boolean;
  allowKeepOld?: boolean;
}) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [oldChoices, setOldChoices] = useState<Record<string, string>>({});
  const [picked, setPicked] = useState<string>();
  const [scope, setScope] = useState<"pending" | "all">("pending");
  const [focused, setFocused] = useState(false);
  const [unitView, setUnitView] = useState(true);
  const oldUnits = useMemo(() => buildOldUnits(mapping.items), [mapping.items]);
  const psdUnits = useMemo(
    () => buildPsdUnits(mapping.items, psdLayers, mapping.sourceCanvasSize),
    [mapping.items, psdLayers, mapping.sourceCanvasSize],
  );
  const selectUnit = (unit: MappingUnit) => {
    const representative =
      unit.members.find((member) => !member.action) ?? unit.members[0];
    if (representative) selectItem(representative.itemId);
  };
  const pendingItems = mapping.items.filter((item) => !item.action);
  const auditParts: Array<[string, number]> = [
    [
      "非绘制结构已保留",
      mapping.items.filter(
        (item) => item.action === "preserve_structure" && !item.outOfScope,
      ).length,
    ],
    ["范围外", mapping.items.filter((item) => item.outOfScope).length],
    ["已遮挡", mapping.items.filter((item) => item.occluded).length],
    [
      "多层视觉包",
      mapping.items.filter(
        (item) => item.ownedSourceIds && item.ownedSourceIds.length > 0,
      ).length,
    ],
    [
      "默认页不可见",
      mapping.items.filter((item) => item.defaultVisible === false).length,
    ],
  ];
  const auditSummary = auditParts
    .filter(([, count]) => count > 0)
    .map(([label, count]) => `${label} ${count}`)
    .join(" · ");
  const activeScope =
    scope === "pending" && pendingItems.length ? "pending" : "all";
  const visibleItems =
    activeScope === "pending" ? pendingItems : mapping.items;
  const selectItem = (itemId: string) => {
    if (!visibleItems.some((item) => item.itemId === itemId)) setScope("all");
    onCurrentChange(itemId);
  };
  const currentIndex = Math.max(
    0,
    visibleItems.findIndex((item) => item.itemId === currentItemId),
  );
  const current = visibleItems[currentIndex];
  useEffect(() => {
    if (current && current.itemId !== currentItemId)
      onCurrentChange(current.itemId);
  }, [current?.itemId, currentItemId, onCurrentChange]);
  const figmaNames = useMemo(
    () =>
      new Map(
        mapping.items
          .filter((item) => item.figmaNodeId)
          .map((item) => [
            item.figmaNodeId!,
            item.figmaName ?? item.figmaNodeId!,
          ]),
      ),
    [mapping.items],
  );
  if (!current) return <p>当前工程没有可映射对象。</p>;
  const selectedCandidate =
    choices[current.itemId] ?? current.figmaNodeId ?? current.candidates[0];
  const distanceToCurrent = (item: HifiMappingItem): number => {
    const target = current.figmaBounds ?? current.oldBounds;
    const source = item.oldBounds;
    if (!target || !source) return Number.MAX_SAFE_INTEGER;
    return (
      Math.abs(source[0] + source[2] / 2 - (target[0] + target[2] / 2)) +
      Math.abs(source[1] + source[3] / 2 - (target[1] + target[3] / 2))
    );
  };
  const availableOldItems = mapping.items
    .filter(
      (item) => item.oldObjectId && (!item.action || item.action === "keep_old"),
    )
    .sort((left, right) => distanceToCurrent(left) - distanceToCurrent(right))
    .slice(0, 20);
  const selectedOldItem =
    availableOldItems.find(
      (item) => item.itemId === oldChoices[current.itemId],
    ) ?? availableOldItems[0];
  const hasOld = Boolean(current.oldObjectId);
  const hasFigma = Boolean(current.figmaNodeId);
  const hasOwnedVisual = Boolean(
    current.ownedSourceIds && current.ownedSourceIds.length > 0,
  );
  const canPickLayer =
    hasOld && !hasOwnedVisual && current.candidates.length > 0;
  const canPickOld = !hasOld && hasFigma && availableOldItems.length > 0;
  const pickerOpen = picked === current.itemId;
  const candidatePreviewBounds =
    pickerOpen && canPickLayer && selectedCandidate
      ? mapping.items.find((item) => item.figmaNodeId === selectedCandidate)
          ?.figmaBounds ??
        (() => {
          const layer = psdLayers?.find(
            (entry) => entry.id === selectedCandidate,
          );
          if (!layer || !mapping.sourceCanvasSize) return undefined;
          return [
            layer.bounds[0] / mapping.sourceCanvasSize.width,
            layer.bounds[1] / mapping.sourceCanvasSize.height,
            (layer.bounds[2] - layer.bounds[0]) / mapping.sourceCanvasSize.width,
            (layer.bounds[3] - layer.bounds[1]) / mapping.sourceCanvasSize.height,
          ] as PreviewBounds;
        })()
      : undefined;
  const oldPreviewBounds =
    pickerOpen && canPickOld && selectedOldItem
      ? selectedOldItem.oldBounds
      : undefined;
  const candidateLabel = (nodeId: string): string => {
    const layer = psdLayers?.find((entry) => entry.id === nodeId);
    if (layer) return `${layer.name}（${layer.kind}）`;
    return figmaNames.get(nodeId) ?? nodeId.split(":").pop() ?? nodeId;
  };
  const canConfirm = hasOld && hasFigma && current.status !== "blocked";
  const unmappedOld = current.status === "fgui_only" && hasOld && !hasFigma;
  const canSkipBlocked =
    current.status === "blocked" && (!hasOld || allowKeepOld);
  const noWayOut =
    current.status === "blocked" &&
    hasOld &&
    !allowKeepOld &&
    current.candidates.length === 0;
  return (
    <>
      <section className="hifi-mapping-heading">
        <div>
          <h2>组件对齐工作台</h2>
          <p>
            右侧显示 PSD 实际画面；先建立旧对象与 PSD
            内容的一对一对应，再判断真正新增的内容。
          </p>
        </div>
      </section>
      {auditSummary && (
        <p className="local-hifi-note">审计摘要：{auditSummary}</p>
      )}
      <div
        className="hifi-mapping-filter"
        role="group"
        aria-label="映射项目范围"
      >
          <button
            type="button"
            className={activeScope === "pending" ? "is-active" : ""}
            aria-pressed={activeScope === "pending"}
            disabled={!pendingItems.length}
            onClick={() => setScope("pending")}
          >
            待确认 {pendingItems.length}
          </button>
          <button
            type="button"
            className={activeScope === "all" ? "is-active" : ""}
            aria-pressed={activeScope === "all"}
            onClick={() => setScope("all")}
          >
            全部 {mapping.items.length}
          </button>
      </div>
      <div className="hifi-alignment-layout">
        <section className="hifi-structure" aria-label="结构视图">
          <h3>结构视图</h3>
          <div
            className="hifi-mapping-filter"
            role="group"
            aria-label="预览范围"
          >
            <button
              type="button"
              className={!focused ? "is-active" : ""}
              aria-pressed={!focused}
              onClick={() => setFocused(false)}
            >
              完整页面
            </button>
            <button
              type="button"
              className={focused ? "is-active" : ""}
              aria-pressed={focused}
              onClick={() => setFocused(true)}
            >
              聚焦当前对象
            </button>
          </div>
          <div
            className="hifi-mapping-filter"
            role="group"
            aria-label="结构视图单位"
          >
            <button
              type="button"
              className={unitView ? "is-active" : ""}
              aria-pressed={unitView}
              onClick={() => setUnitView(true)}
            >
              组件/组单位
            </button>
            <button
              type="button"
              className={unitView ? "" : "is-active"}
              aria-pressed={!unitView}
              onClick={() => setUnitView(false)}
            >
              叶子诊断
            </button>
          </div>
          <div className="hifi-structure-labels">
            <span>旧 FGUI · 对象结构</span>
            <span>HIFI · PSD 实际画面</span>
          </div>
          <div className="hifi-canvas-pair">
            <MappingCanvas
              side="old"
              items={mapping.items}
              units={oldUnits}
              unitView={unitView}
              currentId={current.itemId}
              onSelect={selectItem}
              onSelectUnit={selectUnit}
              previewBounds={oldPreviewBounds}
              oldPreviewUrl={oldPreviewUrl}
              canvasSize={mapping.oldCanvasSize}
              focused={focused}
            />
            <MappingCanvas
              side="figma"
              items={mapping.items}
              units={psdUnits}
              unitView={unitView}
              currentId={current.itemId}
              onSelect={selectItem}
              onSelectUnit={selectUnit}
              previewBounds={candidatePreviewBounds}
              psdPreviewUrl={psdPreviewUrl}
              canvasSize={mapping.sourceCanvasSize}
              focused={focused}
            />
          </div>
        </section>
        <aside className="hifi-object-inspector" aria-label="对象映射与处理">
          <div className="hifi-item-nav">
            <button
              type="button"
              disabled={currentIndex === 0}
              onClick={() =>
                onCurrentChange(visibleItems[currentIndex - 1].itemId)
              }
            >
              上一项
            </button>
            <strong>
              {currentIndex + 1} / {visibleItems.length}
            </strong>
            <button
              type="button"
              disabled={currentIndex === visibleItems.length - 1}
              onClick={() =>
                onCurrentChange(visibleItems[currentIndex + 1].itemId)
              }
            >
              下一项
            </button>
          </div>
          <ol className="hifi-mapping-list">
            {visibleItems.map((item) => (
              <li key={item.itemId}>
                <button
                  type="button"
                  className={item.itemId === current.itemId ? "is-active" : ""}
                  aria-pressed={item.itemId === current.itemId}
                  onClick={() => onCurrentChange(item.itemId)}
                >
                  <span>{item.oldName ?? "待找旧对象"}</span>
                  <span>→</span>
                  <span>
                    {item.figmaName ??
                      (item.action === "preserve_structure"
                        ? "非绘制结构已保留"
                        : item.action === "keep_old"
                          ? "保留旧对象"
                          : "尚未找到对应")}
                  </span>
                  <small>
                    {STATUS_LABELS[item.status]}
                    {item.oldObjectId
                      ? ` · 匹配分 ${Math.round(item.score * 100)}/100`
                      : ""}
                  </small>
                </button>
              </li>
            ))}
          </ol>
          <section className="hifi-current-card">
            <div>
              <strong>{current.oldName ?? "HIFI 新增视觉"}</strong>
              <span> → </span>
              <strong>
                {current.figmaName ??
                  (current.action === "keep_old"
                    ? "旧对象保留"
                    : "尚未找到对应")}
              </strong>
            </div>
            {current.ownedSourceIds && current.ownedSourceIds.length > 0 && (
              <p className="writer-inline-note">
                该旧对象将承载 {current.ownedSourceIds.length} 个 PSD
                视觉叶图层的合成资源；{current.retainedSourceIds?.length ?? 0}{" "}
                个文字叶图层仍由原文字对象承载。
              </p>
            )}
            {current.defaultVisible === false && (
              <p className="writer-inline-note">
                此对象在控制器默认页不可见；保留原有状态逻辑，并单独验收非默认页的新视觉。
              </p>
            )}
            {hasOwnedVisual && current.candidates.length > 0 && (
              <p className="writer-inline-note">
                该对象承载多层 PSD 视觉包；换层须重新生成视觉包，界面不能直接换层。可确认当前对应，或列为例外人工处理。
              </p>
            )}
            {current.status === "blocked" && (
              <p className="writer-inline-note">
                {current.preserveRuntimeText
                  ? "已按实例传入的文字精确找到 PSD 图层，但共享组件各实例的布局不同，须生成实例视觉变体并验证后才能写入。"
                  : "该节点是容器、组件实例或其他非静态叶子，当前不会自动写入 FGUI。"}
              </p>
            )}
            {current.action !== "preserve_structure" && (
              <div className="hifi-decision-actions">
                <p className="hifi-decision-prompt">处理方式</p>
                <div
                  className="hifi-decision-choices"
                  role="group"
                  aria-label="处理方式"
                >
                  {canConfirm && (
                    <button
                      className="primary-button compact"
                      type="button"
                      disabled={busy}
                      onClick={() => onDecision(current, "accept")}
                    >
                      确认对应
                    </button>
                  )}
                  {(canPickLayer || canPickOld) && (
                    <button
                      className="secondary-button compact"
                      type="button"
                      aria-pressed={pickerOpen}
                      disabled={busy}
                      onClick={() =>
                        setPicked(pickerOpen ? undefined : current.itemId)
                      }
                    >
                      {pickerOpen ? "收起" : "更换图层"}
                    </button>
                  )}
                  {unmappedOld && (
                    <p className="writer-inline-note">
                      PSD 没有画这个旧对象。列为例外会保留对象与程序逻辑，
                      并隐藏其默认视觉，使画面与设计稿一致。
                    </p>
                  )}
                  {current.status === "hifi_added" &&
                    allowVisualAddition &&
                    current.action !== "add_visual" && (
                      <button
                        className="secondary-button compact"
                        type="button"
                        disabled={busy}
                        onClick={() => onDecision(current, "add_visual")}
                      >
                        标记为新增视觉
                      </button>
                    )}
                  {current.status === "hifi_added" && !allowVisualAddition && (
                    <p className="writer-inline-note">
                      PSD
                      替换须先找到旧对象；独立新增需要明确归属，当前不能直接新增。
                    </p>
                  )}
                  {current.status === "hifi_added" &&
                    current.action !== "exception" && (
                      <button
                        className="secondary-button compact"
                        type="button"
                        disabled={busy}
                        onClick={() => onDecision(current, "exception")}
                      >
                        暂不处理
                      </button>
                    )}
                  {canSkipBlocked && current.action !== "exception" && (
                    <button
                      className="primary-button compact"
                      type="button"
                      disabled={busy}
                      onClick={() => onDecision(current, "exception")}
                    >
                      列为例外（人工处理）
                    </button>
                  )}
                  {unmappedOld && current.action !== "exception" && (
                    <button
                      className="primary-button compact"
                      type="button"
                      disabled={busy}
                      onClick={() => onDecision(current, "exception")}
                    >
                      隐藏旧视觉
                    </button>
                  )}
                  {allowKeepOld && hasOld && current.action !== "keep_old" && (
                    <button
                      className="secondary-button compact"
                      type="button"
                      disabled={busy}
                      onClick={() => onDecision(current, "keep_old")}
                    >
                      保留旧对象
                    </button>
                  )}
                  {noWayOut && (
                    <p className="writer-inline-note">
                      该项挂着旧对象且没有可对应的 PSD 候选；需要调整归属规则并重新映射后才能继续。若有候选，请通过“更换图层”提供对应证据。
                    </p>
                  )}
                </div>
                {pickerOpen && canPickLayer && (
                  <label className="hifi-candidate-select">
                    换成哪个图层
                    <select
                      aria-label="换成哪个图层"
                      value={selectedCandidate}
                      disabled={busy}
                      onChange={(event) =>
                        setChoices({
                          ...choices,
                          [current.itemId]: event.currentTarget.value,
                        })
                      }
                    >
                      {current.candidates.map((nodeId) => (
                        <option value={nodeId} key={nodeId}>
                          {candidateLabel(nodeId)}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {pickerOpen && canPickLayer && selectedCandidate && (
                  <button
                    className="primary-button compact"
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      onDecision(current, "retarget", selectedCandidate)
                    }
                  >
                    确认更换
                  </button>
                )}
                {pickerOpen && canPickOld && selectedOldItem && (
                  <label className="hifi-candidate-select">
                    对应的旧 FGUI 对象
                    <select
                      aria-label="对应的旧 FGUI 对象"
                      value={selectedOldItem.itemId}
                      disabled={busy}
                      onChange={(event) =>
                        setOldChoices({
                          ...oldChoices,
                          [current.itemId]: event.currentTarget.value,
                        })
                      }
                    >
                      {availableOldItems.map((item) => (
                        <option value={item.itemId} key={item.itemId}>
                          {item.oldName}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {pickerOpen && canPickOld && selectedOldItem && (
                  <button
                    className="primary-button compact"
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      onDecision(
                        selectedOldItem,
                        "retarget",
                        current.figmaNodeId,
                      )
                    }
                  >
                    建立对应
                  </button>
                )}
                {current.figmaNodeId && onLocate && (
                  <button
                    className="secondary-button compact"
                    type="button"
                    onClick={() => onLocate(current.figmaNodeId!)}
                  >
                    定位到来源图层
                  </button>
                )}
                {current.action &&
                  current.candidates.length > 0 &&
                  current.figmaNodeId !== current.candidates[0] &&
                  !(
                    current.ownedSourceIds && current.ownedSourceIds.length > 0
                  ) && (
                    <button
                      className="secondary-button compact"
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        onDecision(current, "retarget", current.candidates[0])
                      }
                    >
                      恢复自动建议
                    </button>
                  )}
              </div>
            )}
          </section>
        </aside>
      </div>
    </>
  );
}
