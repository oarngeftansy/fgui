import { useEffect, useRef, useState } from "react";
import {
  approveJob as approveJobRequest,
  getAdvancedDesignerPreview,
  loadReview as loadReviewRequest,
  rejectJob as rejectJobRequest,
  safeReviewMessage,
  type AdvancedDesignerPreview,
  type DesignerChange,
  type JobStatus,
  type ReviewData,
} from "../api";
import { ImageComparison } from "./ImageComparison";

type ReviewPageProps = {
  jobId: string;
  loadReview?: (jobId: string) => Promise<ReviewData>;
  loadAdvancedPreview?: (jobId: string) => Promise<AdvancedDesignerPreview>;
  approveJob?: (jobId: string) => Promise<{ status: string }>;
  rejectJob?: (jobId: string) => Promise<{ status: string }>;
};

type Action = "approve" | "reject" | null;

function useMobileViewOnly() {
  const [mobile, setMobile] = useState(() => window.matchMedia?.("(max-width: 900px)").matches ?? false);
  useEffect(() => {
    const query = window.matchMedia?.("(max-width: 900px)");
    if (!query) return;
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return mobile;
}

function changeName(change: DesignerChange) {
  return change.label.replace(/^(图片|界面|组件|资源)：/, "");
}

function selectedSummary(change: DesignerChange) {
  const name = changeName(change);
  if (change.label.startsWith("图片：")) {
    return <ImageComparison name={name} beforeSrc={change.before_image_url ?? undefined} afterSrc={change.after_image_url ?? undefined} />;
  }
  if (change.label.startsWith("组件：") || change.label.startsWith("界面：")) {
    return <section className="change-summary"><h3>组件更新摘要</h3><p>{name}</p><p>更新后会保持组件与资源的一致性。</p></section>;
  }
  return <section className="change-summary"><h3>资源更新摘要</h3><p>{name}</p><p>这项资源会随完整更新一并处理。</p></section>;
}

export function ReviewPage({
  jobId,
  loadReview = loadReviewRequest,
  loadAdvancedPreview = getAdvancedDesignerPreview,
  approveJob = approveJobRequest,
  rejectJob = rejectJobRequest,
}: ReviewPageProps) {
  const isMobileViewOnly = useMobileViewOnly();
  const [review, setReview] = useState<ReviewData>();
  const [error, setError] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [action, setAction] = useState<Action>(null);
  const [status, setStatus] = useState<JobStatus>();
  const [advanced, setAdvanced] = useState<AdvancedDesignerPreview>();
  const [loadAttempt, setLoadAttempt] = useState(0);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const confirmButtonRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const wasConfirmationOpen = useRef(false);

  useEffect(() => {
    let active = true;
    setError("");
    void loadReview(jobId).then((result) => {
      if (!active) return;
      setReview(result);
      setStatus(result.status);
    }).catch((reason: unknown) => {
      if (active) setError(safeReviewMessage(reason));
    });
    return () => { active = false; };
  }, [jobId, loadAttempt, loadReview]);

  useEffect(() => {
    if (confirmationOpen) cancelButtonRef.current?.focus();
    if (!confirmationOpen && wasConfirmationOpen.current) triggerRef.current?.focus();
    wasConfirmationOpen.current = confirmationOpen;
  }, [confirmationOpen]);

  if (error && !review) return <main className="review-page"><div className="message message-error" role="alert">{error}<button className="secondary-button" onClick={() => setLoadAttempt((attempt) => attempt + 1)} type="button">重试加载</button></div></main>;
  if (!review) return <main className="review-page"><p aria-live="polite">正在准备本次更新…</p></main>;

  const selected = review.preview.changes[selectedIndex];
  const hasErrors = review.preview.checks.some((check) => check.status === "error");
  const isReviewable = status === "ready_for_review";
  const actionsDisabled = action !== null || hasErrors || !isReviewable || isMobileViewOnly;
  const selectChange = (index: number) => setSelectedIndex(index);

  const openAdvanced = async () => {
    if (advanced) {
      setAdvanced(undefined);
      return;
    }
    if (action) return;
    setAction("reject");
    try {
      setAdvanced(await loadAdvancedPreview(jobId));
    } catch (reason) {
      setError(safeReviewMessage(reason));
    } finally {
      setAction(null);
    }
  };

  const submit = async (nextAction: Exclude<Action, null>) => {
    if (action || (nextAction === "approve" && actionsDisabled)) return;
    setAction(nextAction);
    setError("");
    try {
      const result = await (nextAction === "approve" ? approveJob(jobId) : rejectJob(jobId));
      setStatus(result.status as JobStatus);
      setConfirmationOpen(false);
    } catch (reason) {
      setError(safeReviewMessage(reason, "无法完成更新，请稍后重试"));
      setConfirmationOpen(false);
    } finally {
      setAction(null);
    }
  };

  const closeConfirmation = () => setConfirmationOpen(false);

  return (
    <main className="review-page" aria-labelledby="review-title">
      <div aria-hidden={confirmationOpen || undefined} inert={confirmationOpen}>
      <h1 id="review-title" className="visually-hidden">更新审核</h1>
      {error && <div className="message message-error" role="alert">{error}</div>}
      {status === "approved" && <p className="message review-success" role="status">已确认完整更新，正在等待本地助手处理。</p>}
      {status === "rejected" && <p className="message review-success" role="status">已暂不更新本次完整改动。</p>}
      <p className="mobile-review-note">请在桌面浏览器中确认或暂不更新本次完整改动。</p>
      <div className="review-workspace" data-testid="review-workspace">
        <section className="review-panel change-list" aria-labelledby="changes-title">
          <h2 id="changes-title">本次会发生什么</h2>
          <p>{review.preview.summary}</p>
          <ul>
            {review.preview.changes.map((change, index) => (
              <li key={`${change.action}-${change.label}`}>
                <button
                  aria-pressed={selectedIndex === index}
                  className="change-button"
                  onClick={() => selectChange(index)}
                  onKeyDown={(event) => {
                    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
                    event.preventDefault();
                    const next = (index + (event.key === "ArrowDown" ? 1 : -1) + review.preview.changes.length) % review.preview.changes.length;
                    selectChange(next);
                    (event.currentTarget.parentElement?.parentElement?.children[next]?.querySelector("button") as HTMLButtonElement | null)?.focus();
                  }}
                  type="button"
                ><strong>{change.action}</strong><span>{change.label}</span></button>
              </li>
            ))}
          </ul>
        </section>

        <section className="review-panel review-difference" aria-labelledby="difference-title">
          <h2 id="difference-title">查看变化</h2>
          {selected ? selectedSummary(selected) : <p>本次没有可展示的改动。</p>}
        </section>

        <aside className="review-panel review-actions" aria-labelledby="actions-title">
          <h2 id="actions-title">检查与决定</h2>
          <ul className="check-list">
            {review.preview.checks.map((check, index) => <li className={`check-${check.status}`} key={`${check.status}-${index}`}>{check.message}</li>)}
          </ul>
          <p>确认后会创建备份；如本地工程已有新修改，将不会被覆盖。</p>
          {(hasErrors || !isReviewable) && <p className="action-blocked">本次更新暂时不能确认。</p>}
          <div className="review-action-buttons">
            <button className="primary-button" disabled={actionsDisabled} onClick={(event) => { triggerRef.current = event.currentTarget; setConfirmationOpen(true); }} type="button">确认更新到本地工程</button>
            <button className="secondary-button" disabled={actionsDisabled} onClick={() => void submit("reject")} type="button">暂不更新</button>
          </div>
          <button aria-expanded={Boolean(advanced)} className="advanced-button" disabled={action !== null} onClick={() => void openAdvanced()} type="button">{advanced ? "隐藏高级详情" : "查看高级详情"}</button>
          {advanced && <section className="advanced-details" aria-label="高级详情"><h3>高级详情</h3>{advanced.details.files.map((file) => <article key={file.relative_path}><p>{file.relative_path}</p>{file.before_xml && <pre>{file.before_xml}</pre>}{file.after_xml && <pre>{file.after_xml}</pre>}</article>)}</section>}
        </aside>
      </div>
      </div>
      {confirmationOpen && <div aria-labelledby="confirm-title" aria-modal="true" className="confirmation-backdrop" onKeyDown={(event) => {
        if (event.key === "Escape") closeConfirmation();
        if (event.key !== "Tab") return;
        const first = cancelButtonRef.current;
        const last = confirmButtonRef.current;
        if (!first || !last) return;
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }} role="dialog"><section className="confirmation-dialog"><h2 id="confirm-title">确认更新到本地工程</h2><p>这会确认本次完整更新，不能只选择部分改动。</p><div><button className="secondary-button" onClick={closeConfirmation} ref={cancelButtonRef} type="button">取消</button><button className="primary-button" onClick={() => void submit("approve")} ref={confirmButtonRef} type="button">确认更新</button></div></section></div>}
    </main>
  );
}
