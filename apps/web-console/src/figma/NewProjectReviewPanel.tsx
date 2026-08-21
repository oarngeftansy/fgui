import { useState } from "react";
import type { NewProjectAdjustmentStrategy, NewProjectReview } from "../../../figma-plugin/src/project-client";

export type WriterPresentationStep = "automatic" | "review" | "confirm";

const strategyLabels: Record<NewProjectAdjustmentStrategy, string> = {
  "preserve-editable": "保留可编辑结构",
  "rasterize-subtree": "栅格化子树",
  "include-contained-definition": "包含完整组件定义",
};

const reasonLabels = {
  gradient_paint: "渐变已按画面保真",
  visual_effect: "复杂阴影或效果已按画面保真",
  blend_mode: "混合模式已按画面保真",
  multiple_paints: "多重填充已按画面保真",
  mask_composite: "遮罩已按画面保真",
  instance_composite: "组件实例已按画面保真",
  visual_style: "视觉样式已按画面保真",
  unrepresentable_transform: "变换无法原生表达",
  rich_text_runs: "富文本包含多段样式",
  component_definition_missing: "缺少可验证的组件定义",
  interaction_unsupported: "交互暂不支持转换",
  resource_missing: "转换所需资源缺失",
} as const;

type ReviewDisposition = NewProjectReview["dispositions"][number];

function impactCopy(item: ReviewDisposition): string {
  const visual = item.visualImpact === "visual_preserved" ? "画面保持一致" : item.visualImpact === "unchanged" ? "原生转换" : "画面可能变化";
  const editing = item.editabilityImpact === "unchanged" ? "仍可编辑" : item.editabilityImpact === "subtree_not_editable" ? "局部不可单独编辑" : "文本样式不再逐段编辑";
  return `${reasonLabels[item.reason]}；${visual}，${editing}。`;
}

function StructuredContext({ generated = false }: { generated?: boolean }) {
  return <div className={`writer-structured-context${generated ? " is-generated" : ""}`} aria-label={generated ? "FairyGUI 结构示意" : "Figma 结构示意"}>
    <div className="writer-context-screen"><span className="writer-context-orbit" /><span className="writer-context-card" /><span className="writer-context-target">{generated ? "转换结果" : "待审核"}</span></div>
  </div>;
}

export function NewProjectReviewPanel({
  review,
  step,
  reviewIndex,
  onReviewIndexChange,
  warningAcknowledged,
  onWarningAcknowledged,
  onLocate,
  onAdjust,
  onCopyReviewArea,
  copyState = "idle",
  previewObjects = {},
  disabled = false,
}: {
  review: NewProjectReview;
  step: WriterPresentationStep;
  reviewIndex: number;
  onReviewIndexChange(index: number): void;
  warningAcknowledged: boolean;
  onWarningAcknowledged(value: boolean): void;
  onLocate(nodeId: string): void;
  onAdjust(checkId: string, strategy: NewProjectAdjustmentStrategy): void;
  onCopyReviewArea(item: ReviewDisposition, generatedPreviewUrl?: string, previewWidth?: number, previewHeight?: number): void;
  copyState?: "idle" | "copying" | "copied" | "failed";
  previewObjects?: Readonly<Record<string, string>>;
  disabled?: boolean;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const automatic = review.dispositions.filter((item) => item.level === "native" || item.level === "raster_preserved");
  const reviewItems = review.dispositions.filter((item) => item.level === "editable_risk" || item.level === "blocked");
  const boundedIndex = Math.max(0, Math.min(reviewItems.length - 1, reviewIndex));
  const current = reviewItems[boundedIndex];
  const evidence = review.imageReviews[boundedIndex] ?? review.imageReviews[0];

  if (step === "automatic") return <section className="writer-step-screen" aria-labelledby="writer-automatic-title">
    <div className="writer-step-heading"><p className="writer-eyebrow">转换完成</p><h2 id="writer-automatic-title">先看已经处理好的内容</h2><p>系统已经完成可确定的转换。下面说明转换方式和后续可编辑程度。</p></div>
    <div className="writer-automatic-list">
      {automatic.map((item) => <article className="writer-automatic-card" key={item.id}>
        <div className="writer-mini-compare"><StructuredContext /><StructuredContext generated /></div>
        <div><span className={`writer-method is-${item.level}`}>{item.level === "native" ? "原生转换" : "视觉保真图片"}</span><h3>{item.sourceName}</h3><p>{impactCopy(item)}</p></div>
      </article>)}
    </div>
    {automatic.length === 0 && <p>没有可自动确认的转换项。</p>}
  </section>;

  if (step === "review" && current) {
    const sourceObject = evidence?.sourcePreviewUrl ? previewObjects[evidence.sourcePreviewUrl] : undefined;
    const generatedObject = evidence ? previewObjects[evidence.generatedAssetUrl] : undefined;
    const matchingChecks = review.checks.filter((check) => check.sourceNodeId === current.sourceNodeId);
    const visibleChecks = matchingChecks.length ? matchingChecks : reviewItems.length === 1 ? review.checks : [];
    return <section className="writer-step-screen" aria-labelledby="writer-review-title">
      <div className="writer-step-heading"><p className="writer-eyebrow">建议审核</p><h2 id="writer-review-title">逐项确认转换结果</h2><p>图中保留可用的来源证据；没有截图时会明确显示结构示意，不冒充真实画面。</p></div>
      <div className="writer-review-nav"><strong>{boundedIndex + 1} / {reviewItems.length}</strong><div><button type="button" disabled={boundedIndex === 0} onClick={() => onReviewIndexChange(boundedIndex - 1)}>上一项</button><button type="button" disabled={boundedIndex === reviewItems.length - 1} onClick={() => onReviewIndexChange(boundedIndex + 1)}>下一项</button></div></div>
      <article className={`writer-illustrated-review is-${current.level}`}>
        <div className="writer-review-title"><div><h3>{current.sourceName}</h3><p>{reasonLabels[current.reason]}</p></div><span className="writer-status-pill">{current.level === "blocked" ? "必须处理" : "建议确认"}</span></div>
        <div className="writer-portrait-compare">
          <div><div className="writer-preview-label"><strong>Figma 原图</strong><span>{sourceObject ? "来源证据" : "结构示意（非截图）"}</span></div><div className="writer-portrait-preview">{sourceObject ? <img src={sourceObject} alt={`${current.sourceName} Figma 原图`} /> : <StructuredContext />}</div></div>
          <div><div className="writer-preview-label"><strong>FairyGUI 结果</strong><span>{generatedObject ? "转换预览" : "结构示意（非截图）"}</span></div><div className="writer-portrait-preview">{generatedObject ? <img src={generatedObject} alt={`${current.sourceName} FairyGUI 结果`} /> : <StructuredContext generated />}</div></div>
        </div>
        <div className="writer-review-reason"><strong>为什么需要确认</strong><p>{impactCopy(current)}</p></div>
        <div className="writer-review-controls"><button type="button" disabled={disabled} onClick={() => onLocate(current.sourceNodeId)}>定位到图层</button>{visibleChecks.flatMap((check) => check.allowedStrategies.map((strategy) => <button type="button" disabled={disabled} key={`${check.id}:${strategy}`} onClick={() => onAdjust(check.id, strategy)}>{strategyLabels[strategy]}</button>))}</div>
      </article>
      {review.warningIds.length > 0 && <label className="writer-ack"><input type="checkbox" checked={warningAcknowledged} disabled={disabled} onChange={(event) => onWarningAcknowledged(event.currentTarget.checked)} /> 我已查看图示和影响，并接受当前转换方案</label>}
      <div className="writer-copy-area"><div><strong>需要在 Figma 中继续讨论？</strong><p>{copyState === "copied" ? "已放到当前画板右侧" : copyState === "copying" ? "正在创建独立审核区…" : copyState === "failed" ? "创建失败，请重试" : "不会修改原画板"}</p></div><button type="button" disabled={disabled || copyState === "copying" || !generatedObject} onClick={() => onCopyReviewArea(current, evidence?.generatedAssetUrl, evidence?.width, evidence?.height)}>复制到 Figma 审核区</button></div>
    </section>;
  }

  return <section className="writer-step-screen" aria-labelledby="writer-confirm-title">
    <div className="writer-step-heading"><p className="writer-eyebrow">确认下载</p><h2 id="writer-confirm-title">工程已经可以交付</h2><p>审核结论与工程闭包都已完成。确认后下载可直接打开的 FairyGUI 工程。</p></div>
    <section className="writer-final-card"><div className="writer-review-heading"><h3>最终检查</h3><span className="writer-method is-native">全部通过</span></div><ul><li>✓ {automatic.length} 项自动转换完成</li><li>✓ {reviewItems.length} 项建议审核已确认</li><li>✓ {reviewItems.filter((item) => item.level === "blocked").length} 项必须处理</li><li>✓ 资源与 XML 闭包{review.packageReview.integrityValid ? "通过" : "未通过"}</li></ul></section>
    <button id="writer-engineering-details" className="secondary-button writer-details-button" type="button" aria-expanded={detailsOpen} onClick={() => setDetailsOpen((value) => !value)}>工程详情</button>
    {detailsOpen && <div className="writer-engineering-panel"><p>FairyGUI {review.packageReview.fairyguiVersion} · {review.packageReview.publishTarget}</p><p>{review.packageReview.componentsAdded} 个组件 · {review.packageReview.resourcesAdded} 个资源</p><p>新增组件：{review.packageReview.componentNames.join("、") || "无"}</p><p>新增资源：{review.packageReview.resourceNames.join("、") || "无"}</p><p>{review.packageReview.resourceClosureValid ? "资源闭包通过" : "资源闭包失败"} · {review.packageReview.integrityValid ? "完整性通过" : "完整性失败"}</p></div>}
  </section>;
}
