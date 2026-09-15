import { useEffect, useMemo, useRef, useState } from "react";
import type { ExportedResource } from "../../../figma-plugin/src/assets";
import type {
  HifiMappingAction,
  HifiMappingDraft,
  HifiMappingItem,
  HifiProjectTree,
  HifiReplacement,
  HifiReplacementReview,
  HifiTargetRef,
  ProjectView,
  ProjectWorkflowClient,
} from "../../../figma-plugin/src/project-client";
import type { MainToUiMessage, UiToMainMessage } from "../../../figma-plugin/src/contracts";
import type { SelectionManifest, SelectionPreflight } from "../../../figma-plugin/src/selection";


export type HifiClientLike = Pick<
  ProjectWorkflowClient,
  "uploadProject" | "hifiTargets" | "createHifiReplacement" | "hifiMapping" |
  "decideHifiMapping" | "buildHifiReplacement" | "reviewHifiReplacement" |
  "approveHifiReplacement" | "rejectHifiReplacement" | "downloadHifiReplacement"
>;

type Stage = "prepare" | "mapping" | "review" | "delivered";

function downloadBlob(download: { blob: Blob; downloadName: string }) {
  const url = URL.createObjectURL(download.blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = download.downloadName;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

function errorMessage(error: unknown): string {
  const code = (error as { code?: string } | null)?.code;
  if (code === "invalid_zip") return "工程 ZIP 无效或无法解析。";
  if (code === "selection_invalid") return "当前 Figma 选择无法上传，请刷新后重试。";
  if (code === "conversion_conflict" || code === "stale_candidate") return "工程、映射或候选已变化，请重新检查。";
  if (code === "unauthorized") return "插件没有访问本地服务的权限。";
  return "HIFI 替换操作失败，请重试。";
}

function targetReason(reason?: string): string {
  const labels: Record<string, string> = {
    unsupported_fairygui_version: "仅支持 FairyGUI 6.1.4",
    component_unavailable: "组件文件不可读",
    invalid_component_root: "不是有效根组件",
    no_selectable_components: "没有可选组件",
  };
  return reason ? labels[reason] ?? "不可选择" : "不可选择";
}

function targetRef(project: ProjectView, tree: HifiProjectTree, packageIndex: number, directoryIndex: number, componentIndex: number): HifiTargetRef | undefined {
  const packageItem = tree.packages[packageIndex];
  const directory = packageItem?.directories[directoryIndex];
  const component = directory?.components[componentIndex];
  if (!packageItem || !directory || !component?.selectable) return undefined;
  return {
    version: 1,
    projectId: project.projectId,
    projectFingerprint: tree.projectFingerprint,
    packageId: packageItem.packageId,
    packageName: packageItem.name,
    directory: directory.path,
    componentId: component.resourceId,
    componentName: component.name,
    componentRelativePath: component.relativePath,
  };
}

function MappingCanvas({ side, items, currentId, onSelect }: { side: "old" | "figma"; items: HifiMappingItem[]; currentId?: string; onSelect(itemId: string): void }) {
  const current = items.find((item) => item.itemId === currentId);
  const missingCurrent = current && !(side === "old" ? current.oldBounds : current.figmaBounds);
  return <div className="hifi-canvas" aria-label={side === "old" ? "旧 FGUI 结构" : "HIFI 结构"}>
    {items.map((item) => {
      const bounds = side === "old" ? item.oldBounds : item.figmaBounds;
      if (!bounds) return null;
      return <button
        type="button"
        aria-label={side === "old" ? item.oldName ?? item.itemId : item.figmaName ?? item.itemId}
        className={`hifi-canvas-object ${item.itemId === currentId ? "is-active" : ""}`}
        style={{ left: `${bounds[0] * 100}%`, top: `${bounds[1] * 100}%`, width: `${Math.max(bounds[2] * 100, 3)}%`, height: `${Math.max(bounds[3] * 100, 3)}%` }}
        onClick={() => onSelect(item.itemId)}
        key={`${side}-${item.itemId}`}
      ><span>{side === "old" ? item.oldName : item.figmaName}</span></button>;
    })}
    {missingCurrent && <div className="hifi-canvas-empty is-active">此侧无对应对象</div>}
  </div>;
}

export function HifiReplacementPanel({ client, postToFigma, onOpenNew }: { client: HifiClientLike; postToFigma(message: UiToMainMessage): void; onOpenNew(): void }) {
  const [selection, setSelection] = useState<SelectionPreflight | null>(null);
  const [archive, setArchive] = useState<File>();
  const [project, setProject] = useState<ProjectView>();
  const [tree, setTree] = useState<HifiProjectTree>();
  const [selected, setSelected] = useState<[number, number, number]>();
  const [stage, setStage] = useState<Stage>("prepare");
  const [mapping, setMapping] = useState<HifiMappingDraft>();
  const [replacement, setReplacement] = useState<HifiReplacement>();
  const [review, setReview] = useState<HifiReplacementReview>();
  const [currentItemId, setCurrentItemId] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [checks, setChecks] = useState({ layout: false, references: false, interactions: false });
  const [candidateChoices, setCandidateChoices] = useState<Record<string, string>>({});
  const attempt = useRef("");
  const pendingTarget = useRef<HifiTargetRef | undefined>(undefined);
  const mounted = useRef(true);

  const target = useMemo(
    () => project && tree && selected ? targetRef(project, tree, ...selected) : undefined,
    [project, selected, tree],
  );
  const current = mapping?.items.find((item) => item.itemId === currentItemId) ?? mapping?.items[0];
  const allChecked = checks.layout && checks.references && checks.interactions;
  const singleRoot = selection?.manifest?.top_level_nodes.length === 1;
  const candidateLabel = (nodeId: string) => mapping?.items.find((item) => item.figmaNodeId === nodeId)?.figmaName ?? nodeId;
  const statusLabel: Record<HifiMappingItem["status"], string> = {
    matched: "已对应",
    suggested: "建议对应",
    uncertain: "待判断",
    fgui_only: "仅旧工程",
    hifi_added: "HIFI 新增",
  };

  useEffect(() => {
    mounted.current = true;
    postToFigma({ type: "selection-preflight" });
    const receive = (event: MessageEvent<{ pluginMessage?: MainToUiMessage }>) => {
      const message = event.data?.pluginMessage;
      if (!message) return;
      if (message.type === "selection-preflight" || message.type === "selection-changed") {
        setSelection(message.preflight);
        if (message.type === "selection-changed" && stage !== "prepare") {
          setStage("prepare");
          setReplacement(undefined);
          setMapping(undefined);
          setReview(undefined);
          setError("Figma 选择已变化，旧映射和候选已失效；请重新开始对齐。");
        }
        return;
      }
      if (message.type !== "selection-export" && message.type !== "selection-error") return;
      if (message.attempt !== attempt.current) return;
      if (message.type === "selection-error") {
        setBusy(false);
        setError("读取当前 Figma 选择失败，请重试。");
        return;
      }
      const activeTarget = pendingTarget.current;
      if (!project || !activeTarget) return;
      void client.createHifiReplacement(message.manifest, message.resources, project, activeTarget)
        .then((result) => {
          if (!mounted.current) return;
          setReplacement(result.replacement);
          setMapping(result.mapping);
          setCurrentItemId(result.mapping.items[0]?.itemId);
          setStage("mapping");
          setError("");
        })
        .catch((cause) => mounted.current && setError(errorMessage(cause)))
        .finally(() => mounted.current && setBusy(false));
    };
    window.addEventListener("message", receive);
    return () => { mounted.current = false; window.removeEventListener("message", receive); };
  }, [client, postToFigma, project, stage]);

  const chooseArchive = async (file: File | undefined) => {
    setArchive(file);
    setProject(undefined);
    setTree(undefined);
    setSelected(undefined);
    setError("");
    if (!file) return;
    setBusy(true);
    try {
      const uploaded = await client.uploadProject(file);
      const targets = await client.hifiTargets(uploaded.projectId);
      if (!mounted.current) return;
      setProject(uploaded);
      setTree(targets);
    } catch (cause) {
      if (mounted.current) setError(errorMessage(cause));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const start = () => {
    if (!target || !selection?.sendable || busy) return;
    pendingTarget.current = target;
    attempt.current = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
    setBusy(true);
    setError("");
    postToFigma({ type: "selection-export", attempt: attempt.current });
  };

  const decide = async (item: HifiMappingItem, action: HifiMappingAction, figmaNodeId?: string) => {
    if (!replacement || !mapping || busy) return;
    setBusy(true);
    try {
      const next = await client.decideHifiMapping(replacement.sessionId, mapping.mappingRevision, item.itemId, action, figmaNodeId);
      const nextMapping = await client.hifiMapping(next.sessionId);
      setReplacement(next);
      setMapping(nextMapping);
      const nextUnresolved = nextMapping.items.find((entry) => !entry.action);
      setCurrentItemId(nextUnresolved?.itemId ?? item.itemId);
      setError("");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  };

  const build = async () => {
    if (!replacement || !mapping || mapping.unresolvedCount || busy) return;
    setBusy(true);
    try {
      const built = await client.buildHifiReplacement(replacement.sessionId, mapping.mappingRevision);
      const nextReview = await client.reviewHifiReplacement(replacement.sessionId);
      setReplacement(built);
      setReview(nextReview);
      setStage("review");
      setError("");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  };

  const downloadCandidate = async () => {
    if (!replacement) return;
    try { downloadBlob(await client.downloadHifiReplacement(replacement.sessionId, true)); }
    catch (cause) { setError(errorMessage(cause)); }
  };

  const approve = async () => {
    if (!replacement || !allChecked || busy) return;
    setBusy(true);
    try {
      const approved = await client.approveHifiReplacement(replacement.sessionId);
      downloadBlob(await client.downloadHifiReplacement(approved.sessionId, false));
      setReplacement(approved);
      setStage("delivered");
      setError("");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  };

  return <main className="writer-shell hifi-shell" aria-label="HIFI 替换">
    <header className="writer-header">
      <div><p className="writer-eyebrow">Figma → FairyGUI</p><h1>HIFI 替换</h1></div>
      <nav className="writer-mode-tabs" aria-label="产品功能"><button type="button" onClick={onOpenNew}>新建工程</button><button type="button" className="is-active" aria-current="page">HIFI 替换</button></nav>
    </header>
    <ol className="writer-presentation-rail hifi-rail" aria-label="替换流程">
      <li className={stage === "prepare" ? "is-current" : "is-done"}>1 准备材料</li>
      <li className={stage === "mapping" ? "is-current" : ["review", "delivered"].includes(stage) ? "is-done" : ""}>2 对齐组件</li>
      <li className={["review", "delivered"].includes(stage) ? "is-current" : ""}>3 审核交付</li>
    </ol>
    <div className="writer-step-scroll">
      {stage === "prepare" && <>
        <section className="writer-selection"><div><h2>当前 HIFI 选择</h2><strong>{selection?.manifest?.display_name ?? "未选择"}</strong><p>{selection?.sendable ? `${selection.nodeCount} 个图层 · ${selection.assetCount} 个资源` : "请在 Figma 中选择 HIFI 根节点"}</p></div><button className="secondary-button compact" type="button" onClick={() => postToFigma({ type: "selection-preflight" })}>刷新选择</button></section>
        {selection?.sendable && !singleRoot && <p className="writer-inline-error" role="alert">HIFI 替换一次只能选择一个根节点。</p>}
        <section className="writer-setup hifi-project-source"><label>旧 FairyGUI 工程 ZIP<input type="file" accept=".zip,application/zip,application/x-zip-compressed" disabled={busy} onChange={(event) => void chooseArchive(event.currentTarget.files?.[0])} /></label>{archive && <p>{archive.name}</p>}{busy && !tree && <p role="status">正在读取工程目录…</p>}</section>
        {tree && <section className="hifi-target-tree" aria-labelledby="hifi-target-title"><div className="hifi-section-heading"><div><h2 id="hifi-target-title">FGUI 修改位置</h2><p>先选择目录，再选择该目录中的根组件。</p></div><span>需确认</span></div>
          {tree.packages.map((packageItem, packageIndex) => <div className="hifi-package" key={packageItem.packageId}><strong>▾ {packageItem.name}</strong>{packageItem.directories.map((directory, directoryIndex) => <div key={directory.path}>
            <button className={`hifi-tree-row hifi-directory ${selected?.[0] === packageIndex && selected[1] === directoryIndex ? "is-selected" : ""}`} type="button" disabled={!directory.selectable} onClick={() => setSelected([packageIndex, directoryIndex, -1])}><span>▾ {directory.path}</span><small>{directory.selectable ? "目录" : targetReason(directory.reason)}</small></button>
            {directory.components.map((component, componentIndex) => <button className={`hifi-tree-row hifi-component ${selected?.[0] === packageIndex && selected[1] === directoryIndex && selected[2] === componentIndex ? "is-selected" : ""}`} type="button" disabled={!component.selectable} onClick={() => setSelected([packageIndex, directoryIndex, componentIndex])} key={component.resourceId}><span>◆ {component.name}</span><small>{component.selectable ? "根组件" : targetReason(component.reason)}</small></button>)}
          </div>)}</div>)}
          {target && <dl className="hifi-target-summary"><div><dt>目标目录</dt><dd>{target.packageName} / {target.directory}</dd></div><div><dt>根组件</dt><dd>{target.componentName}</dd></div></dl>}
        </section>}
      </>}
      {stage === "mapping" && mapping && <>
        <section className="hifi-mapping-heading"><div><h2>组件对齐工作台</h2><p>点击列表或视图中的对象，左右两侧会同时高亮当前组件。</p></div><strong>{mapping.unresolvedCount} 项待确认</strong></section>
        <section className="hifi-structure" aria-label="结构视图"><h3>结构视图</h3><div className="hifi-structure-labels"><span>旧 FGUI</span><span>HIFI</span></div><div className="hifi-canvas-pair"><MappingCanvas side="old" items={mapping.items} currentId={current?.itemId} onSelect={setCurrentItemId} /><MappingCanvas side="figma" items={mapping.items} currentId={current?.itemId} onSelect={setCurrentItemId} /></div></section>
        <ol className="hifi-mapping-list">{mapping.items.map((item) => <li key={item.itemId}><button type="button" className={item.itemId === current?.itemId ? "is-active" : ""} onClick={() => setCurrentItemId(item.itemId)}><span>{item.oldName ?? "＋ 新增"}</span><span>→</span><span>{item.figmaName ?? "保留旧对象"}</span><small>{statusLabel[item.status]} · {Math.round(item.score * 100)}%</small></button></li>)}</ol>
        {current && <section className="hifi-current-card"><div><strong>{current.oldName ?? "HIFI 新增视觉"}</strong><span> → </span><strong>{current.figmaName ?? "旧对象保留"}</strong></div><div className="hifi-decision-actions">
          {!current.action && current.candidates.length > 0 && <label className="hifi-candidate-select">HIFI 对应组件<select aria-label="HIFI 对应组件" value={candidateChoices[current.itemId] ?? current.figmaNodeId ?? current.candidates[0]} onChange={(event) => setCandidateChoices({ ...candidateChoices, [current.itemId]: event.currentTarget.value })}>{current.candidates.map((nodeId) => <option value={nodeId} key={nodeId}>{candidateLabel(nodeId)}</option>)}</select></label>}
          {!current.action && current.figmaNodeId && <button className="primary-button compact" type="button" disabled={busy} onClick={() => { const chosen = candidateChoices[current.itemId] ?? current.figmaNodeId!; void decide(current, chosen === current.figmaNodeId && current.status !== "uncertain" ? "accept" : "retarget", chosen === current.figmaNodeId && current.status !== "uncertain" ? undefined : chosen); }}>确认对应</button>}
          {!current.action && current.oldObjectId && <button className="secondary-button compact" type="button" disabled={busy} onClick={() => void decide(current, "keep_old")}>保留旧对象</button>}
          {current.status === "matched" && <button className="secondary-button compact" type="button" disabled={busy} onClick={() => void decide(current, "keep_old")}>改为保留旧对象</button>}
          {current.status === "hifi_added" && current.action === "add_visual" && <button className="secondary-button compact" type="button" disabled={busy} onClick={() => void decide(current, "exception")}>忽略这个新增项</button>}
        </div></section>}
      </>}
      {stage === "review" && review && <>
        <section className="hifi-review-card"><h2>候选差异审核</h2><p className={review.protectedChecksPassed ? "hifi-check-ok" : "writer-inline-error"}>{review.protectedChecksPassed ? "✓ 原组件身份、层级和行为引用未变化" : "保护检查未通过"}</p>{review.changedFiles.map((file) => <div className="hifi-diff-row" key={file.relativePath}><strong>{file.operation === "replace" ? "修改" : "新增"}</strong><span>{file.relativePath}</span><small>{file.summary}</small></div>)}{review.warnings.map((warning) => <p className="writer-inline-note" key={warning}>{warning}</p>)}</section>
        <section className="hifi-editor-check"><h2>FairyGUI Editor 检查</h2><p>先下载候选工程，在 Editor 中打开目标组件，再完成三项确认。</p><button className="secondary-button" type="button" onClick={() => void downloadCandidate()}>下载候选 ZIP</button>
          <label><input type="checkbox" checked={checks.layout} onChange={(event) => setChecks({ ...checks, layout: event.currentTarget.checked })} /> 布局与图层顺序正确</label>
          <label><input type="checkbox" checked={checks.references} onChange={(event) => setChecks({ ...checks, references: event.currentTarget.checked })} /> 图片与共享组件引用正常</label>
          <label><input type="checkbox" checked={checks.interactions} onChange={(event) => setChecks({ ...checks, interactions: event.currentTarget.checked })} /> Controller、Gear、Transition 正常</label>
        </section>
      </>}
      {stage === "delivered" && <section className="hifi-delivered" role="status"><strong>已交付 HIFI 替换工程</strong><p>正式 ZIP 已下载。原工程未被覆盖。</p></section>}
      {error && <p className="writer-inline-error" role="alert">{error}</p>}
    </div>
    <footer className="writer-actions">
      {stage === "prepare" && <button className="primary-button" type="button" disabled={!target || !selection?.sendable || !singleRoot || busy} onClick={start}>{busy ? "正在准备…" : "开始盘点与映射"}</button>}
      {stage === "mapping" && <><button className="secondary-button" type="button" disabled={busy} onClick={() => { setStage("prepare"); setReplacement(undefined); setMapping(undefined); }}>返回目标选择</button><button className="primary-button" type="button" disabled={Boolean(mapping?.unresolvedCount) || busy} onClick={() => void build()}>{busy ? "正在生成候选…" : "生成候选工程"}</button></>}
      {stage === "review" && <><button className="secondary-button" type="button" disabled={busy} onClick={() => { setStage("mapping"); setChecks({ layout: false, references: false, interactions: false }); }}>返回对齐修改</button><button className="primary-button" type="button" disabled={!allChecked || busy} onClick={() => void approve()}>{busy ? "正在交付…" : "确认并交付 ZIP"}</button></>}
      {stage === "delivered" && replacement && <button className="primary-button" type="button" onClick={() => void client.downloadHifiReplacement(replacement.sessionId, false).then(downloadBlob).catch((cause) => setError(errorMessage(cause)))}>再次下载</button>}
    </footer>
  </main>;
}
