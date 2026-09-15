import { useMemo, useState } from "react";
import type { HifiMappingAction, HifiMappingDraft, HifiMappingItem } from "../../../figma-plugin/src/project-client";

function MappingCanvas({ side, items, currentId, onSelect }: { side: "old" | "figma"; items: HifiMappingItem[]; currentId?: string; onSelect(itemId: string): void }) {
  const current = items.find((item) => item.itemId === currentId);
  const missingCurrent = current && !(side === "old" ? current.oldBounds : current.figmaBounds);
  const sideName = side === "old" ? "旧 FGUI" : "HIFI";
  return <div className="hifi-canvas" aria-label={`${sideName} 结构`}>
    {items.map((item) => {
      const bounds = side === "old" ? item.oldBounds : item.figmaBounds;
      if (!bounds) return null;
      const name = side === "old" ? item.oldName : item.figmaName;
      return <button
        type="button"
        aria-label={`${sideName} · ${name ?? item.itemId}`}
        className={`hifi-canvas-object ${item.itemId === currentId ? "is-active" : ""}`}
        style={{ left: `${bounds[0] * 100}%`, top: `${bounds[1] * 100}%`, width: `${Math.max(bounds[2] * 100, 3)}%`, height: `${Math.max(bounds[3] * 100, 3)}%` }}
        onClick={() => onSelect(item.itemId)}
        key={`${side}-${item.itemId}`}
      ><span>{name}</span></button>;
    })}
    {missingCurrent && <div className="hifi-canvas-empty is-active" data-testid={`${side === "old" ? "fgui" : "hifi"}-focus`}>此侧无对应对象</div>}
    {current && !missingCurrent && <div className="hifi-focus-label" data-testid={`${side === "old" ? "fgui" : "hifi"}-focus`} aria-label={`${sideName} · ${side === "old" ? current.oldName : current.figmaName}`} />}
  </div>;
}

const STATUS_LABELS: Record<HifiMappingItem["status"], string> = {
  matched: "已对应",
  suggested: "建议对应",
  uncertain: "待判断",
  fgui_only: "仅旧工程",
  hifi_added: "HIFI 新增",
  blocked: "受限项",
};

export function HifiMappingPanel({ mapping, currentItemId, busy, onCurrentChange, onDecision, onLocate }: {
  mapping: HifiMappingDraft;
  currentItemId?: string;
  busy: boolean;
  onCurrentChange(itemId: string): void;
  onDecision(item: HifiMappingItem, action: HifiMappingAction, figmaNodeId?: string): void;
  onLocate(nodeId: string): void;
}) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  const currentIndex = Math.max(0, mapping.items.findIndex((item) => item.itemId === currentItemId));
  const current = mapping.items[currentIndex];
  const figmaNames = useMemo(() => new Map(mapping.items.filter((item) => item.figmaNodeId).map((item) => [item.figmaNodeId!, item.figmaName ?? item.figmaNodeId!])), [mapping.items]);
  if (!current) return <p>当前工程没有可映射对象。</p>;
  const selectedCandidate = choices[current.itemId] ?? current.figmaNodeId ?? current.candidates[0];
  const applyCandidate = () => {
    if (!selectedCandidate) return;
    const unchangedSuggestion = selectedCandidate === current.figmaNodeId && current.status !== "uncertain";
    onDecision(current, unchangedSuggestion ? "accept" : "retarget", unchangedSuggestion ? undefined : selectedCandidate);
  };
  return <>
    <section className="hifi-mapping-heading"><div><h2>组件对齐工作台</h2><p>点击列表或视图中的对象，左右两侧同时高亮当前组件。</p></div><strong>{mapping.unresolvedCount} 项待确认</strong></section>
    <section className="hifi-structure" aria-label="结构视图">
      <h3>结构视图</h3>
      <div className="hifi-structure-labels"><span>旧 FGUI</span><span>HIFI</span></div>
      <div className="hifi-canvas-pair"><MappingCanvas side="old" items={mapping.items} currentId={current.itemId} onSelect={onCurrentChange} /><MappingCanvas side="figma" items={mapping.items} currentId={current.itemId} onSelect={onCurrentChange} /></div>
    </section>
    <div className="hifi-item-nav"><button type="button" disabled={currentIndex === 0} onClick={() => onCurrentChange(mapping.items[currentIndex - 1].itemId)}>上一项</button><strong>{currentIndex + 1} / {mapping.items.length}</strong><button type="button" disabled={currentIndex === mapping.items.length - 1} onClick={() => onCurrentChange(mapping.items[currentIndex + 1].itemId)}>下一项</button></div>
    <ol className="hifi-mapping-list">{mapping.items.map((item) => <li key={item.itemId}><button type="button" className={item.itemId === current.itemId ? "is-active" : ""} onClick={() => onCurrentChange(item.itemId)}><span>{item.oldName ?? "＋ 新增"}</span><span>→</span><span>{item.figmaName ?? "保留旧对象"}</span><small>{STATUS_LABELS[item.status]} · {Math.round(item.score * 100)}%</small></button></li>)}</ol>
    <section className="hifi-current-card">
      <div><strong>{current.oldName ?? "HIFI 新增视觉"}</strong><span> → </span><strong>{current.figmaName ?? "旧对象保留"}</strong></div>
      {current.status === "blocked" && <p className="writer-inline-note">该节点是容器、组件实例或其他非静态叶子，首版不会自动写入 FGUI。</p>}
      <div className="hifi-decision-actions">
        {current.oldObjectId && current.candidates.length > 0 && <label className="hifi-candidate-select">HIFI 对应组件<select aria-label="HIFI 对应组件" value={selectedCandidate} disabled={busy} onChange={(event) => setChoices({ ...choices, [current.itemId]: event.currentTarget.value })}>{current.candidates.map((nodeId) => <option value={nodeId} key={nodeId}>{figmaNames.get(nodeId) ?? nodeId}</option>)}</select></label>}
        {current.oldObjectId && selectedCandidate && <button className="primary-button compact" type="button" disabled={busy} onClick={applyCandidate}>应用对应</button>}
        {current.oldObjectId && current.action !== "keep_old" && <button className="secondary-button compact" type="button" disabled={busy} onClick={() => onDecision(current, "keep_old")}>保留旧对象</button>}
        {current.status === "hifi_added" && current.action !== "add_visual" && <button className="primary-button compact" type="button" disabled={busy} onClick={() => onDecision(current, "add_visual")}>允许新增视觉节点</button>}
        {current.status === "hifi_added" && current.action !== "exception" && <button className="secondary-button compact" type="button" disabled={busy} onClick={() => onDecision(current, "exception")}>列为例外</button>}
        {current.status === "blocked" && current.action !== "exception" && <button className="primary-button compact" type="button" disabled={busy} onClick={() => onDecision(current, "exception")}>列为例外并保留人工处理</button>}
        {current.figmaNodeId && <button className="secondary-button compact" type="button" onClick={() => onLocate(current.figmaNodeId!)}>定位到 Figma 图层</button>}
      </div>
    </section>
  </>;
}
