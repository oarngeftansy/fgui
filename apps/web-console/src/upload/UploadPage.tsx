import { useRef, useState } from "react";
import { createProjectJob, safeReviewMessage, safeUploadMessage, type UploadedProject } from "../api";

export type UploadProject = (file: File, onProgress: (percent: number) => void) => Promise<UploadedProject>;
export type CreateProjectJob = (projectId: string, packageName: string) => Promise<{ job_id: string }>;

type UploadPageProps = {
  uploadProject: UploadProject;
  createJob?: CreateProjectJob;
};

type UploadState = "idle" | "drag-active" | "uploading" | "success" | "error";

const ZIP_ERROR = "请选择 .zip 格式的 FairyGUI 工程文件";

export function UploadPage({ uploadProject, createJob = createProjectJob }: UploadPageProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [file, setFile] = useState<File>();
  const [project, setProject] = useState<UploadedProject>();
  const [packageName, setPackageName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [reviewError, setReviewError] = useState("");

  const submit = async (candidate: File | undefined) => {
    if (!candidate || state === "uploading") return;
    if (!candidate.name.toLowerCase().endsWith(".zip")) {
      setError(ZIP_ERROR);
      setState("error");
      return;
    }

    setFile(candidate);
    setError("");
    setProgress(0);
    setState("uploading");
    try {
      const result = await uploadProject(candidate, setProgress);
      setProject(result);
      setPackageName(result.packages[0]?.name ?? "");
      setState("success");
    } catch (reason) {
      setError(safeUploadMessage(reason));
      setState("error");
    }
  };

  const openPicker = () => inputRef.current?.click();
  const isUploading = state === "uploading";
  const createReview = async () => {
    if (!project || !packageName || isCreating) return;
    setIsCreating(true);
    setReviewError("");
    try {
      const job = await createJob(project.project_id, packageName);
      window.history.pushState({}, "", `/jobs/${encodeURIComponent(job.job_id)}`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    } catch (reason) {
      setReviewError(safeReviewMessage(reason, "暂时无法准备本次更新，请稍后重试"));
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <main className="upload-page" aria-labelledby="page-title">
      <section className="upload-card" aria-describedby="upload-help">
        <p className="eyebrow">Figma 转 FairyGUI</p>
        <h1 id="page-title">上传 FairyGUI 工程</h1>
        <p id="upload-help" className="intro">上传 ZIP 后，我们会识别工程中的包和资源。</p>

        <label className="input-label" htmlFor="project-file">上传 FairyGUI 工程 ZIP</label>
        <input
          ref={inputRef}
          className="visually-hidden"
          id="project-file"
          type="file"
          accept=".zip,application/zip,application/x-zip-compressed"
          tabIndex={-1}
          onChange={(event) => void submit(event.currentTarget.files?.[0])}
        />
        <div
          aria-disabled={isUploading}
          className={`drop-target ${state === "drag-active" ? "is-drag-active" : ""}`}
          onClick={() => !isUploading && openPicker()}
          onDragEnter={(event) => {
            event.preventDefault();
            if (!isUploading) setState("drag-active");
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => !isUploading && setState("idle")}
          onDrop={(event) => {
            event.preventDefault();
            void submit(event.dataTransfer.files[0]);
          }}
          onKeyDown={(event) => {
            if ((event.key === "Enter" || event.key === " ") && !isUploading) {
              event.preventDefault();
              openPicker();
            }
          }}
          role="button"
          tabIndex={0}
        >
          <strong>{isUploading ? "正在上传工程…" : "拖放 ZIP 到这里，或选择文件"}</strong>
          <span>仅支持 FairyGUI 工程 ZIP</span>
        </div>

        {isUploading && (
          <div className="upload-progress" aria-live="polite">
            <progress aria-label="上传进度" max="100" value={progress} />
            <span>{progress}%</span>
          </div>
        )}

        {state === "error" && (
          <div className="message message-error" role="alert">
            <p>{error}</p>
            {file && <button type="button" className="secondary-button" onClick={() => void submit(file)}>重试上传</button>}
          </div>
        )}

        {state === "success" && project && (
          <section className="project-summary" aria-live="polite" aria-labelledby="summary-title">
            <p className="success-label">工程已准备好</p>
            <h2 id="summary-title">{project.display_name}</h2>
            <ul>
              {project.packages.map((item) => <li key={item.name}>{item.name} 包 · {item.resource_count} 个资源</li>)}
            </ul>
            <label className="input-label" htmlFor="project-package">选择需要更新的包</label>
            <select id="project-package" value={packageName} onChange={(event) => setPackageName(event.currentTarget.value)}>
              {project.packages.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
            </select>
            <p className="intro">当前使用示例设计数据生成预览，暂不连接实时 Figma。</p>
            {reviewError && <p className="message message-error" role="alert">{reviewError}</p>}
            <button className="primary-button" data-testid="create-review" disabled={isCreating || !packageName} onClick={() => void createReview()} type="button">
              {isCreating ? "正在准备更新…" : "查看本次更新"}
            </button>
          </section>
        )}
      </section>

      <section className="recent-tasks" aria-labelledby="recent-title">
        <h2 id="recent-title">最近任务</h2>
        {project ? (
          <article className="recent-task">
            <p>刚刚上传</p>
            <strong>已准备好继续下一步</strong>
          </article>
        ) : <p>还没有上传过工程。完成上传后，任务会显示在这里。</p>}
      </section>
    </main>
  );
}
