import { useState } from "react";
import type { HifiReplacementReview } from "../../../figma-plugin/src/project-client";

export type HifiEditorCheckState = { layout: boolean; references: boolean; interactions: boolean };

const KIND_LABELS = { changed: "修改", added: "新增", kept: "保留", exception: "例外" } as const;

export function HifiReplacementReviewPanel({ review, checks, busy, onChecksChange, onDownloadCandidate, onReject }: {
  review: HifiReplacementReview;
  checks: HifiEditorCheckState;
  busy: boolean;
  onChecksChange(checks: HifiEditorCheckState): void;
  onDownloadCandidate(): void;
  onReject(reason: string): void;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  return <>
    <section className="hifi-review-card">
      <h2>候选差异审核</h2>
      <p className={review.protectedChecksPassed ? "hifi-check-ok" : "writer-inline-error"}>{review.protectedChecksPassed ? "✓ Controller、Gear、Transition、Relation 和组件引用均保持原样" : "程序行为保护检查未通过"}</p>
      {review.candidateSha256 && <p className="hifi-candidate-hash"><strong>候选 SHA-256</strong><code>{review.candidateSha256}</code></p>}
      <h3>对象差异</h3>
      {review.objectDiffs.map((item) => <div className={`hifi-diff-row is-${item.kind}`} key={item.itemId}><strong>{KIND_LABELS[item.kind]}</strong><span>{item.oldName ?? "新增对象"} → {item.figmaName ?? "无对应 HIFI 对象"}</span><small>{item.summary}</small></div>)}
      <h3>文件差异</h3>
      {review.changedFiles.map((file) => <div className="hifi-diff-row" key={file.relativePath}><strong>{file.operation === "replace" ? "修改" : "新增"}</strong><span>{file.relativePath}</span><small>{file.summary}</small></div>)}
      {review.warnings.map((warning) => <p className="writer-inline-note" key={warning}>{warning}</p>)}
    </section>
    <section className="hifi-editor-check">
      <h2>FairyGUI Editor 检查</h2>
      <p>下载此哈希对应的候选工程，在 FairyGUI 6.1.4 中打开、保存并重开目标组件。</p>
      <button className="secondary-button" type="button" disabled={busy} onClick={onDownloadCandidate}>下载候选 ZIP</button>
      <label><input type="checkbox" checked={checks.layout} onChange={(event) => onChecksChange({ ...checks, layout: event.currentTarget.checked })} /> 布局与图层顺序正确</label>
      <label><input type="checkbox" checked={checks.references} onChange={(event) => onChecksChange({ ...checks, references: event.currentTarget.checked })} /> 图片与共享组件引用正常</label>
      <label><input type="checkbox" checked={checks.interactions} onChange={(event) => onChecksChange({ ...checks, interactions: event.currentTarget.checked })} /> Controller、Gear、Transition 正常</label>
    </section>
    {rejecting && <section className="hifi-reject-card"><label>退回原因<textarea aria-label="退回原因" value={reason} maxLength={500} onChange={(event) => setReason(event.currentTarget.value)} /></label><button type="button" className="secondary-button" disabled={!reason.trim() || busy} onClick={() => onReject(reason.trim())}>确认退回</button></section>}
    <button className="secondary-button" type="button" disabled={busy} onClick={() => setRejecting(!rejecting)}>退回候选</button>
  </>;
}

export function HifiReplacementReviewActions({ review, checks, busy, onReturn, onApprove }: {
  review: HifiReplacementReview;
  checks: HifiEditorCheckState;
  busy: boolean;
  onReturn(): void;
  onApprove(): void;
}) {
  const allChecked = checks.layout && checks.references && checks.interactions;
  const canApprove = review.approvable && review.protectedChecksPassed && allChecked && !busy;
  return <>
    <button className="secondary-button" type="button" disabled={busy} onClick={onReturn}>返回对齐修改</button>
    <button className="primary-button" type="button" disabled={!canApprove} onClick={onApprove}>{busy ? "正在交付…" : "确认并交付 ZIP"}</button>
  </>;
}
