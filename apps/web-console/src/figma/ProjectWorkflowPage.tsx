import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ExportedResource } from "../../../figma-plugin/src/assets";
import type { ProjectOption, WorkflowResult, WorkflowStage } from "../../../figma-plugin/src/project-client";
import { WorkflowError } from "../../../figma-plugin/src/project-client";
import type { SelectionManifest, SelectionPreflight } from "../../../figma-plugin/src/selection";

export type ProjectWorkflowClientLike = {
  options(signal?: AbortSignal): Promise<ProjectOption[]>;
  runCreate(manifest: SelectionManifest, resources: readonly ExportedResource[], params: { templateId: string; projectName: string }, onStage?: (stage: WorkflowStage) => void, signal?: AbortSignal): Promise<WorkflowResult>;
  runUpdate(manifest: SelectionManifest, resources: readonly ExportedResource[], archive: File, onStage?: (stage: WorkflowStage) => void, signal?: AbortSignal): Promise<WorkflowResult>;
};

type MainMessage =
  | { type: "selection-preflight" | "selection-changed"; preflight: SelectionPreflight }
  | { type: "selection-export"; attempt: string; manifest: SelectionManifest; resources: ExportedResource[] }
  | { type: "selection-error"; attempt: string; code: string };
type UiMessage = { type: "selection-preflight" } | { type: "selection-export"; attempt: string };
type Mode = "create" | "update";
type WorkflowRequest =
  | { mode: "create"; templateId: string; projectName: string }
  | { mode: "update"; archive: File };

const stageLabels: Record<WorkflowStage["stage"], string> = {
  uploading: "上传当前选择",
  parsing: "解析工程",
  converting: "转换",
  checking: "检查",
  packaging: "打包",
  ready: "已完成",
  failed: "生成失败",
};

function postToParent(message: UiMessage) {
  window.parent.postMessage({ pluginMessage: message }, "*");
}

function safeError(error: unknown): string {
  if (error instanceof WorkflowError) return error.message;
  return "生成失败，请重试。";
}

function validArchive(file: File | undefined): boolean {
  return Boolean(file && file.name.toLowerCase().endsWith(".zip") && (!file.type || ["application/zip", "application/x-zip-compressed"].includes(file.type)));
}

function errorForExport(code: string): string {
  if (code === "selection_empty") return "请选择要导出的图层";
  if (code === "selection_too_large") return "当前选择内容过大，请缩小选择范围后重试";
  return "导出当前选择失败，请重试。";
}

export function ProjectWorkflowPage({ client, postToFigma = postToParent }: { client: ProjectWorkflowClientLike; postToFigma?: (message: UiMessage) => void }) {
  const [mode, setMode] = useState<Mode>("create");
  const [selection, setSelection] = useState<SelectionPreflight | null>(null);
  const [projectName, setProjectName] = useState("");
  const [archive, setArchive] = useState<File>();
  const [options, setOptions] = useState<ProjectOption[]>([]);
  const [fairyguiVersion, setFairyguiVersion] = useState("");
  const [targetPlatform, setTargetPlatform] = useState("");
  const [stage, setStage] = useState<WorkflowStage | null>(null);
  const [result, setResult] = useState<WorkflowResult | null>(null);
  const [error, setError] = useState("");
  const [optionsError, setOptionsError] = useState("");
  const [waitingForExport, setWaitingForExport] = useState(false);
  const [workflowRunning, setWorkflowRunning] = useState(false);
  const attempt = useRef("");
  const running = useRef(false);
  const exportRequested = useRef(false);
  const pendingWorkflow = useRef<WorkflowRequest | null>(null);
  const optionsAbort = useRef<AbortController | null>(null);

  const loadOptions = useCallback(() => {
    optionsAbort.current?.abort();
    const controller = new AbortController();
    optionsAbort.current = controller;
    setOptionsError("");
    void client.options(controller.signal).then((next) => {
      if (controller.signal.aborted) return;
      setOptions(next);
      if (next[0]) {
        setFairyguiVersion((value) => value || next[0]!.fairyguiVersion);
        setTargetPlatform((value) => value || next[0]!.targetPlatform);
      }
    }).catch(() => {
      if (!controller.signal.aborted) setOptionsError("无法加载工程选项，请重试。");
    });
  }, [client]);

  useEffect(() => {
    loadOptions();
    postToFigma({ type: "selection-preflight" });
    return () => optionsAbort.current?.abort();
  }, [loadOptions, postToFigma]);

  const matchingOptions = useMemo(
    () => options.filter((option) => option.fairyguiVersion === fairyguiVersion && option.targetPlatform === targetPlatform),
    [fairyguiVersion, options, targetPlatform],
  );
  const selectedOption = matchingOptions[0];
  const versions = [...new Set(options.map((option) => option.fairyguiVersion))];
  const platforms = [...new Set(options.filter((option) => option.fairyguiVersion === fairyguiVersion).map((option) => option.targetPlatform))];
  const controlsLocked = waitingForExport || workflowRunning;
  const readyToGenerate = Boolean(selection?.sendable && !controlsLocked && !exportRequested.current && !running.current && (mode === "create" ? projectName.trim() && selectedOption : validArchive(archive)));

  useEffect(() => {
    const receive = (event: MessageEvent<{ pluginMessage?: MainMessage }>) => {
      const message = event.data?.pluginMessage;
      if (!message) return;
      if (message.type === "selection-preflight" || message.type === "selection-changed") {
        setSelection(message.preflight);
        setError("");
        return;
      }
      if (message.type !== "selection-error" && message.type !== "selection-export") return;
      if (message.attempt !== attempt.current) return;
      if (message.type === "selection-error") {
        running.current = false;
        exportRequested.current = false;
        pendingWorkflow.current = null;
        setWaitingForExport(false);
        setWorkflowRunning(false);
        setStage(null);
        setError(errorForExport(message.code));
        return;
      }
      if (message.type === "selection-export" && !running.current) {
        const request = pendingWorkflow.current;
        if (!request) return;
        pendingWorkflow.current = null;
        exportRequested.current = false;
        running.current = true;
        setWaitingForExport(false);
        setWorkflowRunning(true);
        const onStage = (next: WorkflowStage) => setStage(next);
        const operation = request.mode === "create"
          ? client.runCreate(message.manifest, message.resources, { templateId: request.templateId, projectName: request.projectName }, onStage)
          : client.runUpdate(message.manifest, message.resources, request.archive, onStage);
        void operation.then((next) => {
          setResult(next);
          setStage({ stage: "ready", progress: 100 });
          setError("");
        }).catch((cause: unknown) => {
          setStage(null);
          setError(safeError(cause));
        }).finally(() => {
          running.current = false;
          setWorkflowRunning(false);
        });
      }
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [client]);

  const refreshSelection = () => {
    setError("");
    postToFigma({ type: "selection-preflight" });
  };
  const generate = () => {
    if (!readyToGenerate) return;
    const request: WorkflowRequest | null = mode === "create" && selectedOption
      ? { mode, templateId: selectedOption.templateId, projectName: projectName.trim() }
      : mode === "update" && archive
        ? { mode, archive }
        : null;
    if (!request) return;
    setResult(null);
    setError("");
    setStage({ stage: "uploading", progress: 0 });
    const nextAttempt = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
    attempt.current = nextAttempt;
    exportRequested.current = true;
    pendingWorkflow.current = request;
    setWaitingForExport(true);
    postToFigma({ type: "selection-export", attempt: nextAttempt });
  };
  const chooseVersion = (value: string) => {
    setFairyguiVersion(value);
    const first = options.find((option) => option.fairyguiVersion === value);
    setTargetPlatform(first?.targetPlatform ?? "");
  };
  const download = () => {
    if (!result) return;
    const url = URL.createObjectURL(result.blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = result.downloadName;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return <main className="project-workflow" aria-label="FairyGUI 工程工作流">
    <section className="workflow-step" aria-labelledby="selection-step-title">
      <h1 id="selection-step-title">1. Figma 选择</h1>
      <p>{selection?.sendable ? `已准备当前选择（${selection.nodeCount} 个图层，${selection.assetCount} 个资源）。` : "请选择要生成 FairyGUI 工程的图层。"}</p>
      <button className="secondary-button" type="button" onClick={refreshSelection}>刷新选择</button>
      {selection?.warnings.map((warning, index) => <p className="message message-warning" role="alert" key={`${warning.code}-${index}`}>{warning.message}</p>)}
    </section>

    <section className="workflow-step" aria-labelledby="mode-step-title">
      <h2 id="mode-step-title">2. 新建或更新</h2>
      <fieldset className="workflow-mode"><legend>操作方式</legend>
        <label><input type="radio" name="workflow-mode" checked={mode === "create"} disabled={controlsLocked} onChange={() => setMode("create")} /> 新建工程</label>
        <label><input type="radio" name="workflow-mode" checked={mode === "update"} disabled={controlsLocked} onChange={() => setMode("update")} /> 更新现有工程</label>
      </fieldset>
      {mode === "create" ? <div className="workflow-fields">
        <label>工程名称<input value={projectName} required disabled={controlsLocked} onChange={(event) => setProjectName(event.target.value)} /></label>
        <label>FairyGUI 版本<select value={fairyguiVersion} required disabled={controlsLocked} onChange={(event) => chooseVersion(event.target.value)}><option value="" disabled>请选择版本</option>{versions.map((version) => <option value={version} key={version}>{version}</option>)}</select></label>
        <label>目标平台<select value={targetPlatform} required disabled={controlsLocked} onChange={(event) => setTargetPlatform(event.target.value)}><option value="" disabled>请选择平台</option>{platforms.map((platform) => <option value={platform} key={platform}>{platform}</option>)}</select></label>
      </div> : <div className="workflow-fields">
        <label>现有 FairyGUI 工程 ZIP<input type="file" accept=".zip,application/zip,application/x-zip-compressed" required disabled={controlsLocked} onChange={(event) => {
          const file = event.currentTarget.files?.[0];
          setArchive(file);
          setError(file && !validArchive(file) ? "请选择有效的 FairyGUI 工程 ZIP 文件。" : "");
        }} /></label>
        <p>原始 ZIP 不会被修改；生成结果将作为新的下载文件提供。</p>
      </div>}
    </section>

    <section className="workflow-step" aria-labelledby="running-step-title">
      <h2 id="running-step-title">3. 生成与检查</h2>
      <button className="primary-button" type="button" disabled={!readyToGenerate} onClick={generate}>生成工程</button>
      {(waitingForExport || stage) && <div className="workflow-progress"><progress value={stage?.progress ?? 0} max="100">{stage?.progress ?? 0}%</progress><output role="status">{waitingForExport ? "正在读取当前选择" : `${stageLabels[stage!.stage]} ${stage!.progress}%`}</output></div>}
      {optionsError && <div className="message message-error" role="alert"><p>{optionsError}</p><button className="secondary-button" type="button" onClick={loadOptions}>重试</button></div>}
      {error && <div className="message message-error" role="alert"><p>{error}</p><button className="secondary-button" type="button" onClick={generate}>重试</button></div>}
      {result?.package.diagnostics.map((diagnostic, index) => <p className={`message ${diagnostic.severity === "WARNING" ? "message-warning" : "message-error"}`} role={diagnostic.severity === "ERROR" ? "alert" : undefined} key={`${diagnostic.code}-${index}`}>{diagnostic.message}</p>)}
    </section>

    <section className="workflow-step" aria-labelledby="download-step-title">
      <h2 id="download-step-title">4. 下载工程</h2>
      {result ? <><p>工程已生成，可下载 {result.downloadName}。</p><button className="primary-button" type="button" onClick={download}>下载工程</button></> : <p>完成生成与检查后，可在这里下载新的 FairyGUI 工程。</p>}
    </section>
  </main>;
}
