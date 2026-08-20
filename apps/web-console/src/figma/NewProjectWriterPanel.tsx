import { useEffect, useMemo, useRef, useState } from "react";
import type { ExportedResource } from "../../../figma-plugin/src/assets";
import type { MainToUiMessage, UiToMainMessage } from "../../../figma-plugin/src/contracts";
import type { NewProjectAdjustmentStrategy, NewProjectCandidate, NewProjectReview, NewProjectRunResult, ProjectWorkflowClient, WorkflowError } from "../../../figma-plugin/src/project-client";
import type { SelectionManifest, SelectionPreflight } from "../../../figma-plugin/src/selection";
import { NewProjectReviewPanel } from "./NewProjectReviewPanel";

export type WriterClientLike = Pick<ProjectWorkflowClient, "createNewProjectCandidate" | "reviewNewProject" | "adjustNewProject" | "regenerateNewProject" | "approveNewProject" | "rejectNewProject" | "downloadNewProject" | "newProjectPreview">;
export type WriterUiState = "idle" | "exporting" | "running" | "reviewing" | "adjusting" | "regenerating" | "approving" | "rejected" | "failed" | "ready";
type WriterMessage = MainToUiMessage;
type WriterPostMessage = ((message: UiToMainMessage) => void);

const inlineStages: Array<[string, string]> = [["selection", "读取选择"], ["converting", "转换结构"], ["checking", "统一检查"], ["packaging", "打包候选"]];

function safeError(error: unknown): string {
  const code = (error as Partial<WorkflowError> | null)?.code;
  if (code === "aborted") return "操作已取消。";
  if (code === "timeout") return "处理超时，请重试。";
  if (code === "stale_candidate") return "候选工程已失效，请刷新选择后重新生成。";
  if (code === "review_required") return "请完成当前候选的统一检查。";
  return "生成失败，请重试。";
}

function downloadBlob(download: { blob: Blob; downloadName: string }) {
  const url = URL.createObjectURL(download.blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = download.downloadName;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function NewProjectWriterPanel({ client, postToFigma, onOpenUpdate }: { client: WriterClientLike; postToFigma: WriterPostMessage; onOpenUpdate?: () => void }) {
  const [selection, setSelection] = useState<SelectionPreflight | null>(null);
  const [projectName, setProjectName] = useState("");
  const [uiState, setUiState] = useState<WriterUiState>("idle");
  const [serverStage, setServerStage] = useState("selection");
  const [runResult, setRunResult] = useState<NewProjectRunResult>();
  const [candidate, setCandidate] = useState<NewProjectCandidate>();
  const [review, setReview] = useState<NewProjectReview>();
  const [warningAcknowledged, setWarningAcknowledged] = useState(false);
  const [invalidatedGenerations, setInvalidatedGenerations] = useState<number[]>([]);
  const [error, setError] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [selectionNotice, setSelectionNotice] = useState("");
  const [previewObjects, setPreviewObjects] = useState<Record<string, string>>({});
  const attempt = useRef("");
  const pendingName = useRef("");
  const controller = useRef<AbortController | undefined>(undefined);
  const mounted = useRef(true);

  const active = ["exporting", "running", "regenerating", "approving"].includes(uiState);
  const warningsSatisfied = Boolean(review && (review.warningIds.length === 0 || warningAcknowledged));
  const canApprove = Boolean(candidate && review && candidate.status === "awaiting_review" && review.approvable && warningsSatisfied);

  useEffect(() => {
    mounted.current = true;
    postToFigma({ type: "selection-preflight" });
    const receive = (event: MessageEvent<{ pluginMessage?: WriterMessage }>) => {
      const message = event.data?.pluginMessage;
      if (!message) return;
      if (message.type === "selection-preflight" || message.type === "selection-changed") {
        if (message.type === "selection-changed" && !controller.current) {
          setCandidate(undefined);
          setReview(undefined);
          setRunResult(undefined);
          setWarningAcknowledged(false);
          setInvalidatedGenerations([]);
          setError("");
          setUiState("idle");
          setSelectionNotice("当前选择已刷新，旧候选已清除。");
        }
        setSelection(message.preflight);
        return;
      }
      if (message.type !== "selection-export" && message.type !== "selection-error") return;
      if (message.attempt !== attempt.current) return;
      if (message.type === "selection-error") {
        setUiState("failed");
        setError(message.code === "selection_changed" ? "当前选择已变化，请刷新后重试。" : "读取当前选择失败，请重试。");
        return;
      }
      attempt.current = "";
      void runCandidate(message.manifest, message.resources);
    };
    window.addEventListener("message", receive);
    return () => {
      mounted.current = false;
      controller.current?.abort();
      window.removeEventListener("message", receive);
    };
  }, [postToFigma]);

  useEffect(() => {
    if (!review || !candidate || typeof URL.createObjectURL !== "function") { setPreviewObjects({}); return; }
    const previewController = new AbortController();
    const paths = [
      ...review.imageReviews.flatMap((item) => [item.sourcePreviewUrl, item.generatedAssetUrl]),
      ...review.componentReviews.map((item) => item.renderedPreviewUrl),
    ].filter((path): path is string => Boolean(path));
    const created: string[] = [];
    void Promise.all(paths.map(async (path) => {
      try {
        const blob = await client.newProjectPreview(candidate.buildId, path, previewController.signal);
        const objectUrl = URL.createObjectURL(blob);
        created.push(objectUrl);
        return [path, objectUrl] as const;
      } catch { return undefined; }
    })).then((items) => { if (!previewController.signal.aborted) setPreviewObjects(Object.fromEntries(items.filter((item): item is readonly [string, string] => Boolean(item)))); });
    return () => { previewController.abort(); created.forEach((url) => URL.revokeObjectURL(url)); };
  }, [candidate?.buildId, client, review]);

  const runCandidate = async (manifest: SelectionManifest, resources: readonly ExportedResource[]) => {
    const current = new AbortController();
    controller.current?.abort();
    controller.current = current;
    setUiState("running");
    setServerStage("converting");
    try {
      const result = await client.createNewProjectCandidate(manifest, resources, pendingName.current, {
        signal: current.signal,
        onStage: (next) => { if (!current.signal.aborted) setServerStage(next.stage); },
      });
      if (current.signal.aborted || !mounted.current) return;
      setRunResult(result);
      setCandidate(result.candidate);
      if (result.candidate.status === "failed") {
        setError(result.candidate.diagnostics.map((item) => item.message).join("；") || "候选工程未通过生成检查。");
        setUiState("failed");
        return;
      }
      setUiState("reviewing");
      setServerStage("checking");
      const nextReview = await client.reviewNewProject(result.candidate, current.signal);
      if (current.signal.aborted || !mounted.current) return;
      setReview(nextReview);
      setWarningAcknowledged(false);
      setUiState("reviewing");
      setError("");
    } catch (cause) {
      if (!mounted.current) return;
      if (current.signal.aborted) {
        setUiState("idle");
        setError("");
      } else {
        setUiState("failed");
        setError(safeError(cause));
      }
    } finally {
      if (controller.current === current) controller.current = undefined;
    }
  };

  const begin = () => {
    if (!selection?.sendable || !projectName.trim() || active) return;
    setCandidate(undefined);
    setReview(undefined);
    setRunResult(undefined);
    setWarningAcknowledged(false);
    setInvalidatedGenerations([]);
    setError("");
    setSelectionNotice("");
    pendingName.current = projectName.trim();
    attempt.current = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
    setUiState("exporting");
    setServerStage("selection");
    postToFigma({ type: "selection-export", attempt: attempt.current });
  };

  const refreshSelection = () => {
    if (active) return;
    setCandidate(undefined);
    setReview(undefined);
    setRunResult(undefined);
    setWarningAcknowledged(false);
    setInvalidatedGenerations([]);
    setError("");
    setSelectionNotice("当前选择已刷新，旧候选已清除。");
    setUiState("idle");
    postToFigma({ type: "selection-preflight" });
  };

  const cancel = () => {
    attempt.current = "";
    controller.current?.abort();
    controller.current = undefined;
    setUiState("idle");
    setError("");
  };

  const adjust = async (checkId: string, strategy: NewProjectAdjustmentStrategy) => {
    if (!candidate || !review || !runResult) return;
    const current = new AbortController();
    controller.current = current;
    setUiState("adjusting");
    try {
      setCandidate(await client.adjustNewProject(candidate, review, checkId, strategy, current.signal));
    } catch (cause) {
      setError(safeError(cause));
      setUiState("failed");
    } finally { if (controller.current === current) controller.current = undefined; }
  };

  const regenerate = async () => {
    if (!candidate) return;
    const previous = candidate;
    const current = new AbortController();
    controller.current = current;
    setUiState("regenerating");
    setServerStage("packaging");
    try {
      const next = await client.regenerateNewProject(previous, current.signal);
      const nextReview = await client.reviewNewProject(next, current.signal);
      if (current.signal.aborted) return;
      setInvalidatedGenerations((items) => [...items, previous.generation]);
      setCandidate(next);
      setReview(nextReview);
      setWarningAcknowledged(false);
      setUiState("reviewing");
    } catch (cause) { setError(safeError(cause)); setUiState("failed"); }
    finally { if (controller.current === current) controller.current = undefined; }
  };

  const approveAndDownload = async () => {
    if (!candidate || !review || !canApprove) return;
    const current = new AbortController();
    controller.current = current;
    setUiState("approving");
    try {
      const approved = await client.approveNewProject(candidate, review, review.warningIds, current.signal);
      setCandidate(approved);
      downloadBlob(await client.downloadNewProject(approved, current.signal));
      setUiState("ready");
    } catch (cause) { setError(safeError(cause)); setUiState("failed"); }
    finally { if (controller.current === current) controller.current = undefined; }
  };

  const reject = async () => {
    if (!candidate) return;
    const current = new AbortController();
    controller.current = current;
    try { setCandidate(await client.rejectNewProject(candidate, current.signal)); setUiState("rejected"); }
    catch (cause) { setError(safeError(cause)); setUiState("failed"); }
    finally { if (controller.current === current) controller.current = undefined; }
  };

  const redownload = async () => {
    if (!candidate) return;
    try { downloadBlob(await client.downloadNewProject(candidate)); }
    catch (cause) { setError(safeError(cause)); setUiState("failed"); }
  };

  const primary = useMemo(() => {
    if (uiState === "adjusting") return <button className="primary-button" type="button" disabled={candidate?.status !== "adjusting"} onClick={regenerate}>重新生成候选</button>;
    if (uiState === "reviewing") return <button className="primary-button" type="button" disabled={!canApprove} onClick={approveAndDownload}>确认并下载 ZIP</button>;
    if (uiState === "ready") return <button className="primary-button" type="button" onClick={redownload}>再次下载</button>;
    if (uiState === "failed") return <button className="primary-button" type="button" onClick={begin}>重试</button>;
    if (uiState === "rejected") return <button className="primary-button" type="button" onClick={begin}>生成新候选</button>;
    const labels: Partial<Record<WriterUiState, string>> = { exporting: "正在读取选择", running: "正在生成候选", regenerating: "正在重新生成", approving: "正在确认" };
    return <button className="primary-button" type="button" disabled={active || !selection?.sendable || !projectName.trim()} onClick={begin}>{labels[uiState] ?? "生成候选工程"}</button>;
  // callbacks intentionally consume the current candidate/review snapshot.
  }, [active, canApprove, candidate, projectName, review, selection?.sendable, uiState]);

  return <main className="writer-shell" aria-label="新建 FairyGUI 工程 Writer">
    <header className="writer-header"><div><p className="writer-eyebrow">Figma → FairyGUI</p><h1>新建工程</h1></div><div className="writer-overflow"><button type="button" className="icon-button" aria-label="更多操作" aria-expanded={menuOpen} onClick={() => setMenuOpen((value) => !value)}>•••</button>{menuOpen && <div role="menu"><button role="menuitem" type="button" onClick={onOpenUpdate}>更新现有工程</button></div>}</div></header>
    <section className="writer-selection" aria-labelledby="writer-selection-title"><div><h2 id="writer-selection-title">当前选择</h2><p>{selection?.sendable ? `${selection.nodeCount} 个图层 · ${selection.assetCount} 个资源` : "请选择要生成的图层"}</p>{selection?.manifest?.top_level_nodes.slice(0, 2).map((node) => <p className="writer-blueprint" key={node.id}>{node.name} · {node.type}</p>)}</div><button className="secondary-button compact" type="button" disabled={active} onClick={refreshSelection}>刷新选择</button></section>
    {selection?.warnings.map((warning, index) => <p role="alert" className="writer-inline-error" key={`${warning.code}-${index}`}>{warning.message}</p>)}
    {selectionNotice && <p className="writer-inline-note" role="status">{selectionNotice}</p>}
    <section className="writer-setup" aria-label="工程设置"><label>工程名称<input required value={projectName} disabled={active || Boolean(candidate)} onChange={(event) => setProjectName(event.currentTarget.value)} placeholder="例如 InventoryUI" /></label><div className="writer-pills"><span>FairyGUI 6.1.4</span><span>新建独立工程</span></div></section>
    {(active || uiState === "reviewing") && <ol className="writer-stages" aria-label="生成阶段">{inlineStages.map(([id, label]) => <li className={id === serverStage ? "is-current" : ""} key={id}>{label}</li>)}</ol>}
    {invalidatedGenerations.map((generation) => <p className="writer-invalidated" role="status" key={generation}>候选 v{generation} 已失效，不可确认或下载。</p>)}
    {review && candidate && !["idle", "failed", "rejected"].includes(uiState) && <NewProjectReviewPanel review={review} previewObjects={previewObjects} warningAcknowledged={warningAcknowledged} onWarningAcknowledged={setWarningAcknowledged} disabled={active || uiState === "adjusting" && candidate.status !== "adjusting"} onLocate={(nodeId) => postToFigma({ type: "locate-node", nodeId })} onAdjust={adjust} />}
    {uiState === "ready" && candidate?.downloadName && <div className="writer-ready-summary" role="status"><strong>{candidate.downloadName}</strong><p>SHA-256 {candidate.sha256?.slice(0, 12)}… · {candidate.byteSize} bytes</p></div>}
    {uiState === "rejected" && <p className="writer-terminal" role="status">当前候选已拒绝，不会提供下载。</p>}
    {error && <p className="writer-inline-error" role="alert">{error}</p>}
    <footer className="writer-actions">{active && <button className="secondary-button" type="button" onClick={cancel}>取消</button>}{uiState === "reviewing" && <button className="secondary-button" type="button" onClick={reject}>拒绝候选</button>}{primary}</footer>
  </main>;
}
