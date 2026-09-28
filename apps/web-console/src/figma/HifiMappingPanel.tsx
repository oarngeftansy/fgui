import { useMemo, useState } from "react";
import type { HifiMappingAction, HifiMappingDraft, HifiMappingItem } from "../../../figma-plugin/src/project-client";

type PreviewBounds = [number, number, number, number];
type CanvasSize = { width: number; height: number };

function focusViewport(bounds: PreviewBounds, canvasSize?: CanvasSize): PreviewBounds {
  const aspect = canvasSize ? canvasSize.width / canvasSize.height / (750 / 420) : 1;
  const width = Math.min(1, Math.max(.24, bounds[2] * 3.2, bounds[3] * 3.2 / aspect));
  const height = Math.min(1, canvasSize ? width * aspect : Math.max(.24, bounds[3] * 3.2));
  const centerX = bounds[0] + bounds[2] / 2;
  const centerY = bounds[1] + bounds[3] / 2;
  return [Math.max(0, Math.min(1 - width, centerX - width / 2)), Math.max(0, Math.min(1 - height, centerY - height / 2)), width, height];
}

function intersects(bounds: PreviewBounds, viewport: PreviewBounds): boolean {
  return bounds[0] < viewport[0] + viewport[2] && bounds[0] + bounds[2] > viewport[0] && bounds[1] < viewport[1] + viewport[3] && bounds[1] + bounds[3] > viewport[1];
}

function MappingCanvas({ side, items, currentId, onSelect, psdPreviewUrl, oldPreviewUrl, canvasSize }: { side: "old" | "figma"; items: HifiMappingItem[]; currentId?: string; onSelect(itemId: string): void; psdPreviewUrl?: string; oldPreviewUrl?: string; canvasSize?: CanvasSize }) {
  const current = items.find((item) => item.itemId === currentId);
  const currentBounds = current && (side === "old" ? current.oldBounds : current.figmaBounds);
  const missingCurrent = current && !currentBounds;
  const sideName = side === "old" ? "旧 FGUI" : "HIFI";
  const viewport = currentBounds ? focusViewport(currentBounds, canvasSize) : undefined;
  const nearby = viewport && currentBounds ? items
    .filter((item) => item.itemId !== currentId)
    .map((item) => ({ item, bounds: side === "old" ? item.oldBounds : item.figmaBounds }))
    .filter((entry): entry is { item: HifiMappingItem; bounds: PreviewBounds } => Boolean(entry.bounds && intersects(entry.bounds, viewport)))
    .sort((left, right) => {
      const centerX = currentBounds[0] + currentBounds[2] / 2;
      const centerY = currentBounds[1] + currentBounds[3] / 2;
      const leftDistance = Math.abs(left.bounds[0] + left.bounds[2] / 2 - centerX) + Math.abs(left.bounds[1] + left.bounds[3] / 2 - centerY);
      const rightDistance = Math.abs(right.bounds[0] + right.bounds[2] / 2 - centerX) + Math.abs(right.bounds[1] + right.bounds[3] / 2 - centerY);
      return leftDistance - rightDistance;
    })
    .slice(0, 12)
    .map((entry) => entry.item) : [];
  const previewItems = current ? [...nearby, current] : [];
  return <div className="hifi-canvas-wrap">
    <div className="hifi-canvas" aria-label={`${sideName} 结构`}>
    {side === "figma" && psdPreviewUrl && viewport && <img className="hifi-canvas-psd" src={psdPreviewUrl} alt="HIFI PSD 实际画面" style={{ left: `${-viewport[0] / viewport[2] * 100}%`, top: `${-viewport[1] / viewport[3] * 100}%`, width: `${100 / viewport[2]}%`, height: `${100 / viewport[3]}%` }} />}
    {side === "old" && oldPreviewUrl && viewport && currentBounds && <img className="hifi-canvas-psd" src={oldPreviewUrl} alt="旧 FGUI 对象资源图" style={{ left: `${(currentBounds[0] - viewport[0]) / viewport[2] * 100}%`, top: `${(currentBounds[1] - viewport[1]) / viewport[3] * 100}%`, width: `${currentBounds[2] / viewport[2] * 100}%`, height: `${currentBounds[3] / viewport[3] * 100}%` }} />}
    {viewport && previewItems.map((item) => {
      const bounds = side === "old" ? item.oldBounds : item.figmaBounds;
      if (!bounds) return null;
      const name = side === "old" ? item.oldName : item.figmaName;
      const left = (bounds[0] - viewport[0]) / viewport[2] * 100;
      const top = (bounds[1] - viewport[1]) / viewport[3] * 100;
      const width = bounds[2] / viewport[2] * 100;
      const height = bounds[3] / viewport[3] * 100;
      return <button
        type="button"
        aria-label={`${sideName} · ${name ?? item.itemId}`}
        className={`hifi-canvas-object ${item.itemId === currentId ? "is-active" : ""}`}
        style={{ left: `${left}%`, top: `${top}%`, width: `${Math.max(width, 4)}%`, height: `${Math.max(height, 4)}%` }}
        onClick={() => onSelect(item.itemId)}
        key={`${side}-${item.itemId}`}
      />;
    })}
    {missingCurrent && <div className="hifi-canvas-empty is-active" data-testid={`${side === "old" ? "fgui" : "hifi"}-focus`}>此侧无对应对象</div>}
    {current && !missingCurrent && <div className="hifi-focus-label" data-testid={`${side === "old" ? "fgui" : "hifi"}-focus`} aria-label={`${sideName} · ${side === "old" ? current.oldName : current.figmaName}`} />}
    </div>
    <div className="hifi-canvas-caption"><strong>{current && (side === "old" ? current.oldName : current.figmaName) || "无对应对象"}</strong><small>{side === "old" && current?.oldObjectType ? `旧对象类型：${current.oldObjectType}${oldPreviewUrl ? " · 原资源图" : " · 暂无渲染预览"}` : side === "figma" && psdPreviewUrl ? "PSD 合成图中的实际位置" : "无画面预览"}</small></div>
  </div>;
}

const STATUS_LABELS: Record<HifiMappingItem["status"], string> = {
  matched: "已对应",
  suggested: "建议对应",
  uncertain: "待判断",
  fgui_only: "仅旧工程",
  hifi_added: "PSD 未对应",
  blocked: "PSD 容器待对应",
};

export function HifiMappingPanel({ mapping, currentItemId, busy, onCurrentChange, onDecision, onLocate, psdPreviewUrl, oldPreviewUrl, canvasSize, allowVisualAddition = true, reviewLimit = Infinity }: {
  mapping: HifiMappingDraft;
  currentItemId?: string;
  busy: boolean;
  onCurrentChange(itemId: string): void;
  onDecision(item: HifiMappingItem, action: HifiMappingAction, figmaNodeId?: string): void;
  onLocate?(nodeId: string): void;
  psdPreviewUrl?: string;
  oldPreviewUrl?: string;
  canvasSize?: CanvasSize;
  allowVisualAddition?: boolean;
  reviewLimit?: number;
}) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [oldChoices, setOldChoices] = useState<Record<string, string>>({});
  const [scope, setScope] = useState<"pending" | "all">("pending");
  const pendingItems = mapping.items.filter((item) => !item.action);
  const overBudget = pendingItems.length > reviewLimit;
  const activeScope = scope === "pending" && pendingItems.length ? "pending" : "all";
  const visibleItems = overBudget ? pendingItems.slice(0, reviewLimit) : activeScope === "pending" ? pendingItems : mapping.items;
  const currentIndex = Math.max(0, visibleItems.findIndex((item) => item.itemId === currentItemId));
  const current = visibleItems[currentIndex];
  const figmaNames = useMemo(() => new Map(mapping.items.filter((item) => item.figmaNodeId).map((item) => [item.figmaNodeId!, item.figmaName ?? item.figmaNodeId!])), [mapping.items]);
  if (!current) return <p>当前工程没有可映射对象。</p>;
  const selectedCandidate = choices[current.itemId] ?? current.figmaNodeId ?? current.candidates[0];
  const availableOldItems = mapping.items.filter((item) => item.oldObjectId && (!item.action || item.action === "keep_old"));
  const selectedOldItem = availableOldItems.find((item) => item.itemId === oldChoices[current.itemId]) ?? availableOldItems[0];
  const applyCandidate = () => {
    if (!selectedCandidate) return;
    const unchangedSuggestion = selectedCandidate === current.figmaNodeId && current.status !== "uncertain";
    onDecision(current, unchangedSuggestion ? "accept" : "retarget", unchangedSuggestion ? undefined : selectedCandidate);
  };
  return <>
    <section className="hifi-mapping-heading"><div><h2>组件对齐工作台</h2><p>右侧显示 PSD 实际画面；先建立旧对象与 PSD 内容的一对一对应，再判断真正新增的内容。</p></div><strong>{mapping.unresolvedCount} 项待处理</strong></section>
    {overBudget && <p className="local-hifi-error" role="status">当前有 {pendingItems.length} 个对象无法自动判定，超过最多 {reviewLimit} 个对象的人工判断上限。下方只展示前 {reviewLimit} 个诊断示例，暂不能逐项批准或生成候选；需要先提高自动映射的可靠性。</p>}
    {!overBudget && <div className="hifi-mapping-filter" role="group" aria-label="映射项目范围"><button type="button" className={activeScope === "pending" ? "is-active" : ""} aria-pressed={activeScope === "pending"} disabled={!pendingItems.length} onClick={() => setScope("pending")}>待确认 {pendingItems.length}</button><button type="button" className={activeScope === "all" ? "is-active" : ""} aria-pressed={activeScope === "all"} onClick={() => setScope("all")}>全部 {mapping.items.length}</button></div>}
    <section className="hifi-structure" aria-label="结构视图">
      <h3>结构视图</h3>
      <div className="hifi-structure-labels"><span>旧 FGUI · 对象结构</span><span>HIFI · PSD 实际画面</span></div>
      <div className="hifi-canvas-pair"><MappingCanvas side="old" items={mapping.items} currentId={current.itemId} onSelect={onCurrentChange} oldPreviewUrl={oldPreviewUrl} canvasSize={canvasSize} /><MappingCanvas side="figma" items={mapping.items} currentId={current.itemId} onSelect={onCurrentChange} psdPreviewUrl={psdPreviewUrl} canvasSize={canvasSize} /></div>
    </section>
    <div className="hifi-item-nav"><button type="button" disabled={currentIndex === 0} onClick={() => onCurrentChange(visibleItems[currentIndex - 1].itemId)}>上一项</button><strong>{currentIndex + 1} / {visibleItems.length}</strong><button type="button" disabled={currentIndex === visibleItems.length - 1} onClick={() => onCurrentChange(visibleItems[currentIndex + 1].itemId)}>下一项</button></div>
    <ol className="hifi-mapping-list">{visibleItems.map((item) => <li key={item.itemId}><button type="button" className={item.itemId === current.itemId ? "is-active" : ""} onClick={() => onCurrentChange(item.itemId)}><span>{item.oldName ?? "待找旧对象"}</span><span>→</span><span>{item.figmaName ?? "保留旧对象"}</span><small>{STATUS_LABELS[item.status]}{item.oldObjectId ? ` · ${Math.round(item.score * 100)}%` : ""}</small></button></li>)}</ol>
    <section className="hifi-current-card">
      <div><strong>{current.oldName ?? "HIFI 新增视觉"}</strong><span> → </span><strong>{current.figmaName ?? "旧对象保留"}</strong></div>
      {current.status === "blocked" && <p className="writer-inline-note">该节点是容器、组件实例或其他非静态叶子，首版不会自动写入 FGUI。</p>}
      {!overBudget && <div className="hifi-decision-actions">
        {current.oldObjectId && current.candidates.length > 0 && <label className="hifi-candidate-select">HIFI 对应组件<select aria-label="HIFI 对应组件" value={selectedCandidate} disabled={busy} onChange={(event) => setChoices({ ...choices, [current.itemId]: event.currentTarget.value })}>{current.candidates.map((nodeId) => <option value={nodeId} key={nodeId}>{figmaNames.get(nodeId) ?? nodeId}</option>)}</select></label>}
        {current.oldObjectId && selectedCandidate && <button className="primary-button compact" type="button" disabled={busy} onClick={applyCandidate}>应用对应</button>}
        {current.oldObjectId && current.action !== "keep_old" && <button className="secondary-button compact" type="button" disabled={busy} onClick={() => onDecision(current, "keep_old")}>保留旧对象</button>}
        {!current.oldObjectId && current.figmaNodeId && selectedOldItem && <label className="hifi-candidate-select">对应的旧 FGUI 对象<select aria-label="对应的旧 FGUI 对象" value={selectedOldItem.itemId} disabled={busy} onChange={(event) => setOldChoices({ ...oldChoices, [current.itemId]: event.currentTarget.value })}>{availableOldItems.map((item) => <option value={item.itemId} key={item.itemId}>{item.oldName}</option>)}</select></label>}
        {!current.oldObjectId && current.figmaNodeId && selectedOldItem && <button className="primary-button compact" type="button" disabled={busy} onClick={() => onDecision(selectedOldItem, "retarget", current.figmaNodeId)}>建立一对一对应</button>}
        {current.status === "hifi_added" && !allowVisualAddition && <p className="writer-inline-note">PSD 替换须先找到旧对象；独立新增需要明确归属，当前不能直接新增。</p>}
        {current.status === "hifi_added" && allowVisualAddition && current.action !== "add_visual" && <details className="hifi-new-visual-option"><summary>确实没有旧对象？</summary><button className="secondary-button compact" type="button" disabled={busy} onClick={() => onDecision(current, "add_visual")}>确认为独立新增视觉</button></details>}
        {current.status === "hifi_added" && current.action !== "exception" && <button className="secondary-button compact" type="button" disabled={busy} onClick={() => onDecision(current, "exception")}>暂不处理</button>}
        {current.status === "blocked" && current.action !== "exception" && <button className="primary-button compact" type="button" disabled={busy} onClick={() => onDecision(current, "exception")}>列为例外并保留人工处理</button>}
        {current.figmaNodeId && onLocate && <button className="secondary-button compact" type="button" onClick={() => onLocate(current.figmaNodeId!)}>定位到来源图层</button>}
      </div>}
    </section>
  </>;
}
