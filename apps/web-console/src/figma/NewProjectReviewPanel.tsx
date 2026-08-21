import { useRef, useState } from "react";
import type { NewProjectAdjustmentStrategy, NewProjectReview } from "../../../figma-plugin/src/project-client";

const strategyLabels: Record<NewProjectAdjustmentStrategy, string> = {
  "preserve-editable": "保留可编辑结构",
  "rasterize-subtree": "栅格化子树",
  "include-contained-definition": "包含完整组件定义",
};

type ReviewTab = "images" | "components" | "package" | "checks";

export function NewProjectReviewPanel({
  review,
  warningAcknowledged,
  onWarningAcknowledged,
  onLocate,
  onAdjust,
  previewObjects = {},
  disabled = false,
}: {
  review: NewProjectReview;
  warningAcknowledged: boolean;
  onWarningAcknowledged(value: boolean): void;
  onLocate(nodeId: string): void;
  onAdjust(checkId: string, strategy: NewProjectAdjustmentStrategy): void;
  previewObjects?: Readonly<Record<string, string>>;
  disabled?: boolean;
}) {
  const [tab, setTab] = useState<ReviewTab>("images");
  const [expanded, setExpanded] = useState<string>();
  const tabs: Array<[ReviewTab, string]> = [["images", "图片"], ["components", "组件 / 界面"], ["package", "Package / 资源"], ["checks", "统一检查"]];
  const tabRefs = useRef<Partial<Record<ReviewTab, HTMLButtonElement>>>({});
  const selectAdjacent = (current: ReviewTab, direction: number) => {
    const index = tabs.findIndex(([id]) => id === current);
    const next = tabs[(index + direction + tabs.length) % tabs.length]![0];
    setTab(next);
    tabRefs.current[next]?.focus();
  };
  return <section className="writer-review" aria-labelledby="writer-review-title">
    <div className="writer-review-heading"><h2 id="writer-review-title">候选 v{review.generation}</h2><span className="writer-status-pill">待统一确认</span></div>
    <div className="writer-tabs" role="tablist" aria-label="候选检查类型">
      {tabs.map(([id, label]) => <button id={`writer-tab-${id}`} aria-controls={`writer-panel-${id}`} key={id} ref={(element) => { tabRefs.current[id] = element ?? undefined; }} role="tab" tabIndex={tab === id ? 0 : -1} aria-selected={tab === id} className={tab === id ? "is-active" : ""} type="button" onKeyDown={(event) => { if (event.key === "ArrowRight") { event.preventDefault(); selectAdjacent(id, 1); } else if (event.key === "ArrowLeft") { event.preventDefault(); selectAdjacent(id, -1); } }} onClick={() => setTab(id)}>{label}</button>)}
    </div>
    <div id={`writer-panel-${tab}`} aria-labelledby={`writer-tab-${tab}`} className="writer-tab-panel" role="tabpanel">
      {tab === "images" && <div className="writer-review-list">{review.imageReviews.length ? review.imageReviews.map((item) => <article className="writer-evidence-card" key={item.resourceId}><div><strong>{item.label}</strong><span className="evidence-label">source image</span></div>{item.sourcePreviewUrl && previewObjects[item.sourcePreviewUrl] && <img src={previewObjects[item.sourcePreviewUrl]} alt={`${item.label} source image`} />}<div className="writer-generated-evidence"><span className="evidence-label">generated asset</span>{previewObjects[item.generatedAssetUrl] && <img src={previewObjects[item.generatedAssetUrl]} alt={`${item.label} generated asset`} />}</div><p>{item.width} × {item.height}{item.nineSlice ? " · 九宫格" : ""}</p><p>裁剪 {item.cropBoundsMatch ? "通过" : "失败"} · 透明度 {item.transparencyPreserved ? "通过" : "失败"}</p></article>) : <p>候选工程不包含图片资源。</p>}</div>}
      {tab === "components" && <div className="writer-review-list">{review.componentReviews.map((item) => <article className="writer-evidence-card" key={item.componentId}><div><strong>{item.label}</strong><span className="evidence-label">{item.evidenceKind === "rendered" ? "rendered" : "structured summary"}</span></div>{item.renderedPreviewUrl && previewObjects[item.renderedPreviewUrl] && <img src={previewObjects[item.renderedPreviewUrl]} alt={`${item.label} rendered`} />}<p>{item.objectCount} 个对象 · {item.textCount} 个文本 · {item.resourceRefs} 个资源引用</p><p>层级 {item.hierarchyValid ? "通过" : "失败"} · 几何 {item.geometryValid ? "通过" : "失败"} · 文本 {item.textValid ? "通过" : "失败"}</p></article>)}</div>}
      {tab === "package" && <article className="writer-package-card"><strong>{review.packageReview.packageName}</strong><p>FairyGUI {review.packageReview.fairyguiVersion} · {review.packageReview.publishTarget === "unity" ? "Unity" : review.packageReview.publishTarget}</p><p>{review.packageReview.componentsAdded} 个组件 · {review.packageReview.resourcesAdded} 个资源</p><p>{review.packageReview.resourceClosureValid ? "资源闭包检查通过" : "资源闭包检查未通过"} · {review.packageReview.integrityValid ? "完整性通过" : "完整性失败"}</p><p>{review.packageReview.namingConflicts.length ? `命名冲突：${review.packageReview.namingConflicts.join("、")}` : "无命名冲突"}</p></article>}
      {tab === "checks" && <div className="writer-review-list">
        {review.checks.length ? review.checks.map((check) => <article className={`writer-check severity-${check.severity.toLowerCase()}`} key={check.id}>
          <div className="writer-check-title"><strong>{check.severity === "WARNING" ? "警告" : check.severity === "ERROR" ? "阻断" : "提示"}</strong><span>{check.id}</span></div>
          <div className="writer-check-actions">
            {check.sourceNodeId && <button type="button" disabled={disabled} onClick={() => onLocate(check.sourceNodeId!)}>定位到图层</button>}
            <button type="button" aria-expanded={expanded === check.id} onClick={() => setExpanded((value) => value === check.id ? undefined : check.id)}>查看原因</button>
          </div>
          {expanded === check.id && <p>{check.message}</p>}
          {check.allowedStrategies.length > 0 && <div className="writer-strategies" aria-label="安全调整策略">{check.allowedStrategies.map((strategy) => <button type="button" disabled={disabled} key={strategy} onClick={() => onAdjust(check.id, strategy)}>{strategyLabels[strategy]}</button>)}</div>}
        </article>) : <p>统一检查未发现问题。</p>}
        {review.warningIds.length > 0 && <label className="writer-ack"><input type="checkbox" checked={warningAcknowledged} disabled={disabled} onChange={(event) => onWarningAcknowledged(event.currentTarget.checked)} /> 已阅读并确认全部警告</label>}
      </div>}
    </div>
  </section>;
}
