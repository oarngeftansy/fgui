import { useRef, useState } from "react";
import { createSelectionProjectJob, safeFigmaConsoleMessage, safeReviewMessage, safeUploadMessage, type FigmaSelectionView, type UploadedProject } from "../api";
import { PairingPanel } from "../figma/PairingPanel";
import { SelectionSummary } from "../figma/SelectionSummary";

export type UploadProject = (file: File, onProgress: (percent: number) => void) => Promise<UploadedProject>;
export type CreateProjectJob = (session: string, selectionId: string, projectId: string, packageName: string) => Promise<{ job_id: string }>;

type UploadPageProps = {
  uploadProject: UploadProject;
  createJob?: CreateProjectJob;
  initialSelection?: FigmaSelectionView;
  initialSession?: string;
};

type UploadState = "idle" | "drag-active" | "uploading" | "success" | "error";
const ZIP_ERROR = "请选择 .zip 格式的 FairyGUI 工程文件";

export function UploadPage({ uploadProject, createJob = createSelectionProjectJob, initialSelection, initialSession = "" }: UploadPageProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [file, setFile] = useState<File>();
  const [project, setProject] = useState<UploadedProject>();
  const [packageName, setPackageName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [selection, setSelection] = useState<FigmaSelectionView | undefined>(initialSelection);
  const [session, setSession] = useState(initialSession);

  const submit = async (candidate: File | undefined) => {
    if (!candidate || state === "uploading" || !selection) return;
    if (!candidate.name.toLowerCase().endsWith(".zip")) { setError(ZIP_ERROR); setState("error"); return; }
    setFile(candidate); setError(""); setProgress(0); setState("uploading");
    try {
      const result = await uploadProject(candidate, setProgress);
      setProject(result); setPackageName(result.packages[0]?.name ?? ""); setState("success");
    } catch (reason) { setError(safeUploadMessage(reason)); setState("error"); }
  };

  const createReview = async () => {
    if (!project || !packageName || !selection || !session || isCreating) return;
    setIsCreating(true); setReviewError("");
    try {
      const job = await createJob(session, selection.selection_id, project.project_id, packageName);
      window.history.pushState({}, "", `/jobs/${encodeURIComponent(job.job_id)}`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    } catch (reason) { setReviewError(safeReviewMessage(reason, safeFigmaConsoleMessage(reason))); }
    finally { setIsCreating(false); }
  };

  const isUploading = state === "uploading";
  return <main className="upload-page" aria-labelledby="page-title">
    <section className="upload-card" aria-describedby="upload-help">
      <p className="eyebrow">Figma 转 FairyGUI</p><h1 id="page-title">准备本次更新</h1>
      <p id="upload-help" className="intro">按顺序连接 Figma、确认当前选择、上传 FairyGUI 工程并进入审阅。</p>
      {!selection ? <PairingPanel onSelection={(next, nextSession) => { setSelection(next); setSession(nextSession); setError(""); }} /> : <>
        <SelectionSummary selection={selection} session={session} />
        <section className="workflow-panel upload-step" aria-labelledby="zip-title">
          <p className="eyebrow">步骤 3 / 5</p><h2 id="zip-title">上传 FairyGUI 工程</h2>
          <label className="input-label" htmlFor="project-file">上传 FairyGUI 工程 ZIP</label>
          <input ref={inputRef} className="visually-hidden" id="project-file" type="file" accept=".zip,application/zip,application/x-zip-compressed" tabIndex={-1} onChange={(event) => void submit(event.currentTarget.files?.[0])} />
          <div aria-disabled={isUploading} className={`drop-target ${state === "drag-active" ? "is-drag-active" : ""}`} onClick={() => !isUploading && inputRef.current?.click()} onDragEnter={(event) => { event.preventDefault(); if (!isUploading) setState("drag-active"); }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => !isUploading && setState("idle")} onDrop={(event) => { event.preventDefault(); void submit(event.dataTransfer.files[0]); }} onKeyDown={(event) => { if ((event.key === "Enter" || event.key === " ") && !isUploading) { event.preventDefault(); inputRef.current?.click(); } }} role="button" tabIndex={0}>
            <strong>{isUploading ? "正在上传工程…" : "拖放 ZIP 到这里，或选择文件"}</strong><span>仅支持 FairyGUI 工程 ZIP</span>
          </div>
          {isUploading && <div className="upload-progress" aria-live="polite"><progress aria-label="上传进度" max="100" value={progress} /><span>{progress}%</span></div>}
          {state === "error" && <div className="message message-error" role="alert"><p>{error}</p>{file && <button type="button" className="secondary-button" onClick={() => void submit(file)}>重试上传</button>}</div>}
        </section>
        {state === "success" && project && <section className="workflow-panel project-summary" aria-live="polite" aria-labelledby="summary-title">
          <p className="eyebrow">步骤 4 / 5</p><h2 id="summary-title">{project.display_name}</h2><ul>{project.packages.map((item) => <li key={item.name}>{item.name} 包 · {item.resource_count} 个资源</li>)}</ul>
          <label className="input-label" htmlFor="project-package">选择需要更新的包</label><select id="project-package" value={packageName} onChange={(event) => setPackageName(event.currentTarget.value)}>{project.packages.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select>
          {reviewError && <p className="message message-error" role="alert">{reviewError}</p>}
          <button className="primary-button" data-testid="create-review" disabled={isCreating || !packageName} onClick={() => void createReview()} type="button">{isCreating ? "正在准备更新…" : "步骤 5：查看本次更新"}</button>
        </section>}
      </>}
    </section>
    <section className="recent-tasks" aria-labelledby="recent-title"><h2 id="recent-title">当前进度</h2>{selection ? <p role="status">{project ? "工程已上传，可继续进入审阅。" : "已收到 Figma 选择，等待上传 FairyGUI 工程。"}</p> : <p>等待完成 Figma 配对并发送当前选择。</p>}</section>
  </main>;
}
