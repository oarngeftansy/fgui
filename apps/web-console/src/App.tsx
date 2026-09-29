import { useEffect, useMemo, useState } from "react";

import type { FixedFontStatus, HifiEditorVerification, HifiExportMode, HifiMappingAction, HifiMappingDraft, HifiMappingItem, HifiProjectTree, HifiReplacement, HifiReplacementReview, HifiTargetRef, ProjectView, ProjectWorkflowClient, PsdSource } from "../../figma-plugin/src/project-client";
import { PROJECT_ARCHIVE_ACCEPT, ProjectWorkflowClient as WorkflowClient } from "../../figma-plugin/src/project-client";
import { HifiMappingPanel } from "./figma/HifiMappingPanel";
import { HifiReplacementReviewActions, HifiReplacementReviewPanel, type HifiEditorCheckState } from "./figma/HifiReplacementReviewPanel";
import { HifiTargetPicker, selectedHifiTarget, type HifiTargetSelection } from "./figma/HifiTargetPicker";

export type LocalHifiClientLike = Pick<ProjectWorkflowClient, "resumePsdHifiReplacement" | "fixedFonts" | "uploadProject" | "hifiTargets" | "uploadPsd" | "psdComposite" | "projectAssetThumbnail" | "createPsdHifiReplacement" | "createPsdHifiReplacementBatch" | "hifiMapping" | "decideHifiMapping" | "buildHifiReplacement" | "reviewHifiReplacement" | "verifyHifiReplacementInEditor" | "hifiEditorScreenshot" | "approveHifiReplacement" | "rejectHifiReplacement" | "downloadHifiReplacement">;

type Stage = "prepare" | "sessions" | "mapping" | "review" | "delivered";
const EMPTY_CHECKS: HifiEditorCheckState = { layout: false, references: false, interactions: false };

function downloadBlob(download: { blob: Blob; downloadName: string }) {
  const url = URL.createObjectURL(download.blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = download.downloadName;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

function errorText(error: unknown): string {
  const code = (error as { code?: string } | null)?.code;
  if (code === "invalid_zip") return "旧 FairyGUI 工程压缩包无效。";
  if (code === "hifi_review_budget_exceeded") return "超过最多 5 个对象的人工判断上限，需先完善自动映射。";
  if (code === "hifi_in_place_raster_unsupported") return "该旧对象无法原位承载位图，已阻止生成覆盖层。";
  if (code === "hifi_nested_visual_mapping_required") return "组件内部视觉和状态尚未对应，不能生成候选。";
  if (code === "hifi_shared_scope_violation") return "共享组件会影响未选中的页面，已阻止写入。";
  if (code === "hifi_shared_instance_conflict") return "共享组件的不同实例要求不同视觉，不能写成同一份资源。";
  if (code === "hifi_nested_geometry_unverified") return "嵌套对象的缩放或旋转坐标尚未验证，不能写入。";
  if (code === "hifi_instance_override_conflict") return "替换与既有按钮标题或图标实例参数冲突，已阻止写入。";
  if (code === "hifi_type_conversion_not_authorized") return "该对象没有原位改类型许可，已阻止转换。";
  if (code === "psd_stroke_only_raster_unsupported") return "当前渲染器会错误填满此描边图层，已阻止导出；需要修复并验证图层渲染。";
  if (code === "invalid_psd") return "PSD 文件无效或无法解析。";
  if (code === "psd_too_large") return "PSD 文件超过本地检查上限。";
  if (code === "psd_lossless_blocked") return "PSD 仍有未证明等价的视觉属性，当前不能生成候选工程。";
  if (code === "psd_source_unavailable") return "本机保存的 PSD 来源已损坏或丢失，请重新导入。";
  return "本地处理失败，请检查文件后重试。";
}

const PSD_BLOCKER_LABELS: Record<string, string> = {
  color_mode_not_rgb: "颜色模式不是 RGB，无法按当前链路证明颜色一致",
  unsupported_bit_depth: "PSD 位深不受支持",
  smart_objects_require_equivalence_check: "智能对象需要展开或通过像素等价检查",
  adjustment_layers_require_equivalence_check: "调整图层需要合成结果等价检查",
  layer_effects_require_equivalence_check: "图层效果需要转换并验证描边、阴影与叠加效果",
  pixel_layers_require_equivalence_check: "像素图层需要无降质导出与透明度检查",
  shape_styles_require_equivalence_check: "形状图层的填充、描边与蒙版需要等价检查",
  text_styles_require_equivalence_check: "文字样式需要验证字体资源、字号、颜色、行距与效果",
};

function blockerLabel(code: string): string {
  return PSD_BLOCKER_LABELS[code] ?? code;
}

async function bootstrapLocalClient(): Promise<LocalHifiClientLike> {
  const response = await fetch("/v1/local/bootstrap", { credentials: "same-origin", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error("local bootstrap unavailable");
  const payload = await response.json() as { version?: unknown; access_token?: unknown };
  if (payload.version !== 1 || typeof payload.access_token !== "string" || payload.access_token.length < 32) throw new Error("invalid local bootstrap");
  return new WorkflowClient({ serverOrigin: window.location.origin, pluginToken: payload.access_token });
}

export function App({ client }: { client?: LocalHifiClientLike } = {}) {
  const [resolved, setResolved] = useState<LocalHifiClientLike | undefined>(client);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (client) { setResolved(client); return; }
    let active = true;
    void bootstrapLocalClient().then((value) => { if (active) setResolved(value); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [client]);
  if (failed) return <main className="local-hifi-startup"><h1>PSD → FairyGUI</h1><p>本地服务没有启用独立应用模式，请重新运行启动脚本。</p></main>;
  if (!resolved) return <main className="local-hifi-startup"><h1>PSD → FairyGUI</h1><p>正在连接本地服务…</p></main>;
  return <LocalHifiApp client={resolved} />;
}

function LocalHifiApp({ client }: { client: LocalHifiClientLike }) {
  const [fonts, setFonts] = useState<FixedFontStatus[]>([]);
  const [project, setProject] = useState<ProjectView>();
  const [tree, setTree] = useState<HifiProjectTree>();
  const [selectedList, setSelectedList] = useState<HifiTargetSelection[]>([]);
  const [sessions, setSessions] = useState<HifiReplacement[]>([]);
  const [exportMode, setExportMode] = useState<HifiExportMode>("package");
  const [psdSource, setPsdSource] = useState<PsdSource>();
  const [compositeUrl, setCompositeUrl] = useState<string>();
  const [oldPreviewUrl, setOldPreviewUrl] = useState<string>();
  const [stage, setStage] = useState<Stage>("prepare");
  const [replacement, setReplacement] = useState<HifiReplacement>();
  const [mapping, setMapping] = useState<HifiMappingDraft>();
  const [review, setReview] = useState<HifiReplacementReview>();
  const [editorVerification, setEditorVerification] = useState<HifiEditorVerification>();
  const [editorScreenshotUrl, setEditorScreenshotUrl] = useState<string>();
  const [checks, setChecks] = useState<HifiEditorCheckState>(EMPTY_CHECKS);
  const [currentItemId, setCurrentItemId] = useState<string>();
  const [projectBusy, setProjectBusy] = useState(false);
  const [psdBusy, setPsdBusy] = useState(false);
  const [projectError, setProjectError] = useState("");
  const [error, setError] = useState("");
  const [restoreNote, setRestoreNote] = useState("");
  const [allowExtendedReview, setAllowExtendedReview] = useState(false);
  const targets = useMemo(() => project && tree
    ? selectedList.map((item) => selectedHifiTarget(project, tree, item)).filter((item): item is HifiTargetRef => Boolean(item))
    : [], [project, selectedList, tree]);
  const target = targets[0];
  const installedFonts = fonts.filter((font) => font.installed).length;
  const inspection = psdSource?.inspection;
  const visibleTextLayers = psdSource?.layers.filter((layer) => layer.kind.toLowerCase() === "type" && layer.effectiveVisible) ?? [];
  const styledVisibleTextLayers = visibleTextLayers.filter((layer) => layer.textStyle && layer.textStyle.runs.length > 0);
  const resolvedVisibleFontRuns = styledVisibleTextLayers.flatMap((layer) => layer.textStyle?.runs ?? []).filter((run) => run.fontName).length;
  const visibleFontRuns = styledVisibleTextLayers.flatMap((layer) => layer.textStyle?.runs ?? []).length;
  const ready = Boolean(targets.length > 0 && psdSource && fonts.length > 0 && installedFonts === fonts.length);
  const toggleTarget = (selection: HifiTargetSelection) => {
    const matches = (item: HifiTargetSelection) => item[0] === selection[0] && item[1] === selection[1] && item[2] === selection[2];
    setSelectedList((current) => current.some(matches) ? current.filter((item) => !matches(item)) : [...current, selection]);
  };

  useEffect(() => {
    let active = true;
    let saved: string | null = null;
    try { saved = window.location.hash.match(/^#session=([0-9a-f]{32})$/)?.[1] ?? localStorage.getItem("hifi-last-session"); } catch { /* Storage may be disabled. */ }
    if (!saved || !/^[0-9a-f]{32}$/.test(saved)) return;
    setPsdBusy(true);
    void client.resumePsdHifiReplacement(saved).then(async (restored) => {
      if (!active) return;
      setProject(restored.project); setTree(restored.tree); setPsdSource(restored.source);
      const pi = restored.tree.packages.findIndex((p) => p.packageId === restored.replacement.target.packageId);
      const di = restored.tree.packages[pi]?.directories.findIndex((d) => d.path === restored.replacement.target.directory) ?? -1;
      const ci = restored.tree.packages[pi]?.directories[di]?.components.findIndex((c) => c.resourceId === restored.replacement.target.componentId) ?? -1;
      if (pi >= 0 && di >= 0 && ci >= 0) setSelectedList([[pi, di, ci]]);
      setChecks(EMPTY_CHECKS);
      if (restored.stale) {
        setStage("prepare");
        setRestoreNote("上次会话的安全规则已过期，材料已就位但没有可用映射。重新盘点需要重新解析 PSD，耗时较长；确认后再点“进入盘点与映射”。");
      } else {
        setReplacement(restored.replacement); setMapping(restored.mapping);
        setCurrentItemId(restored.mapping.items.find((item) => !item.action)?.itemId ?? restored.mapping.items[0]?.itemId);
        setStage("mapping");
        setRestoreNote("已恢复本机会话，材料无需重新上传。审核勾选需重新确认。");
      }
      const composite = await client.psdComposite(restored.source.sourceId);
      if (active && typeof URL.createObjectURL === "function") setCompositeUrl(URL.createObjectURL(composite));
    }).catch((cause) => { if (active) setError(`无法恢复上次会话：${errorText(cause)}可重新选择材料。`); })
      .finally(() => { if (active) setPsdBusy(false); });
    return () => { active = false; };
  }, [client]);
  useEffect(() => {
    if (replacement) {
      window.history.replaceState(null, "", `#session=${replacement.sessionId}`);
      try { localStorage.setItem("hifi-last-session", replacement.sessionId); } catch { /* Storage may be disabled. */ }
    }
  }, [replacement]);

  useEffect(() => {
    const controller = new AbortController();
    void client.fixedFonts(controller.signal).then(setFonts).catch((cause) => setError(errorText(cause)));
    return () => controller.abort();
  }, [client]);
  useEffect(() => () => {
    if (compositeUrl) URL.revokeObjectURL(compositeUrl);
  }, [compositeUrl]);
  useEffect(() => {
    const current = mapping?.items.find((item) => item.itemId === currentItemId);
    if (!project || current?.oldObjectType !== "image" || !current.oldResourceId) { setOldPreviewUrl(undefined); return; }
    setOldPreviewUrl(undefined);
    const controller = new AbortController();
    let objectUrl: string | undefined;
    void client.projectAssetThumbnail(project.projectId, current.oldResourceId, controller.signal).then((blob) => {
      if (!controller.signal.aborted) { objectUrl = URL.createObjectURL(blob); setOldPreviewUrl(objectUrl); }
    }).catch(() => setOldPreviewUrl(undefined));
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [client, project, mapping, currentItemId]);
  useEffect(() => () => {
    if (editorScreenshotUrl) URL.revokeObjectURL(editorScreenshotUrl);
  }, [editorScreenshotUrl]);

  const chooseProject = async (file?: File) => {
    setProject(undefined); setTree(undefined); setSelectedList([]); setSessions([]); setReplacement(undefined); setMapping(undefined); setReview(undefined); setEditorVerification(undefined); setEditorScreenshotUrl(undefined); setChecks(EMPTY_CHECKS); setStage("prepare"); setProjectError("");
    if (!file) return;
    setProjectBusy(true);
    try {
      const uploaded = await client.uploadProject(file);
      const targets = await client.hifiTargets(uploaded.projectId);
      setProject(uploaded); setTree(targets);
    } catch (cause) { setProjectError(`${errorText(cause)}请检查文件并重新选择。`); }
    finally { setProjectBusy(false); }
  };

  const choosePsd = async (file?: File) => {
    setPsdSource(undefined); setCompositeUrl(undefined); setReplacement(undefined); setMapping(undefined); setReview(undefined); setEditorVerification(undefined); setEditorScreenshotUrl(undefined); setChecks(EMPTY_CHECKS); setStage("prepare"); setError(""); setRestoreNote("");
    window.history.replaceState(null, "", window.location.pathname);
    try { localStorage.removeItem("hifi-last-session"); } catch { /* Storage may be disabled. */ }
    if (!file) return;
    setPsdBusy(true);
    try {
      const uploaded = await client.uploadPsd(file);
      setPsdSource(uploaded);
      const composite = await client.psdComposite(uploaded.sourceId);
      if (typeof URL.createObjectURL === "function") setCompositeUrl(URL.createObjectURL(composite));
    }
    catch (cause) { setError(errorText(cause)); }
    finally { setPsdBusy(false); }
  };

  const enterSession = (session: HifiReplacement, draft: HifiMappingDraft) => {
    setReplacement(session); setMapping(draft);
    setCurrentItemId(draft.items.find((item) => !item.action)?.itemId ?? draft.items[0]?.itemId);
    setStage("mapping");
  };

  const startMapping = async () => {
    if (!project || !targets.length || !psdSource || projectBusy || psdBusy) return;
    setPsdBusy(true); setError("");
    try {
      if (targets.length === 1) {
        const started = await client.createPsdHifiReplacement(psdSource.sourceId, project, targets[0]);
        enterSession(started.replacement, started.mapping);
      } else {
        setSessions(await client.createPsdHifiReplacementBatch(psdSource.sourceId, targets));
        setStage("sessions");
      }
    } catch (cause) { setError(errorText(cause)); }
    finally { setPsdBusy(false); }
  };

  const openSession = async (session: HifiReplacement) => {
    setPsdBusy(true); setError("");
    try { enterSession(session, await client.hifiMapping(session.sessionId)); }
    catch (cause) { setError(errorText(cause)); }
    finally { setPsdBusy(false); }
  };

  const decide = async (item: HifiMappingItem, action: HifiMappingAction, nodeId?: string) => {
    if (!replacement || !mapping || psdBusy) return;
    setPsdBusy(true); setError("");
    try {
      const next = await client.decideHifiMapping(replacement.sessionId, mapping.mappingRevision, item.itemId, action, nodeId);
      const nextMapping = await client.hifiMapping(next.sessionId);
      setReplacement(next); setMapping(nextMapping);
      setCurrentItemId(nextMapping.items.find((entry) => !entry.action)?.itemId ?? item.itemId);
    } catch (cause) { setError(errorText(cause)); }
    finally { setPsdBusy(false); }
  };

  const decideBatch = async (kind: "suggested" | "hifi_added" | "blocked" | "fgui_only") => {
    if (!replacement || !mapping || psdBusy) return;
    setPsdBusy(true); setError("");
    try {
      let nextReplacement = replacement;
      let nextMapping = mapping;
      const itemIds = mapping.items.filter((item) => item.action === undefined && item.status === kind).map((item) => item.itemId);
      for (const itemId of itemIds) {
        const item = nextMapping.items.find((entry) => entry.itemId === itemId);
        if (!item || item.action !== undefined) continue;
        const action: HifiMappingAction = kind === "suggested" ? "accept" : kind === "hifi_added" ? "add_visual" : "exception";  // blocked / fgui_only -> exception
        nextReplacement = await client.decideHifiMapping(nextReplacement.sessionId, nextMapping.mappingRevision, item.itemId, action);
        nextMapping = await client.hifiMapping(nextReplacement.sessionId);
      }
      setReplacement(nextReplacement); setMapping(nextMapping);
      setCurrentItemId(nextMapping.items.find((entry) => !entry.action)?.itemId ?? nextMapping.items[0]?.itemId);
    } catch (cause) { setError(errorText(cause)); }
    finally { setPsdBusy(false); }
  };

  const build = async () => {
    if (!replacement || !mapping || mapping.unresolvedCount || psdBusy) return;
    setPsdBusy(true); setError("");
    try {
      const built = await client.buildHifiReplacement(replacement.sessionId, mapping.mappingRevision);
      const nextReview = await client.reviewHifiReplacement(replacement.sessionId);
      setReplacement(built); setReview(nextReview); setEditorVerification(undefined); setEditorScreenshotUrl(undefined); setChecks(EMPTY_CHECKS); setStage("review");
    } catch (cause) { setError(errorText(cause)); }
    finally { setPsdBusy(false); }
  };

  const download = async (candidate: boolean) => {
    if (!replacement) return;
    try { downloadBlob(await client.downloadHifiReplacement(replacement.sessionId, candidate)); }
    catch (cause) { setError(errorText(cause)); }
  };

  const verifyEditor = async () => {
    if (!replacement || psdBusy) return;
    setPsdBusy(true); setError("");
    try {
      const verification = await client.verifyHifiReplacementInEditor(replacement.sessionId);
      setEditorVerification(verification);
      if (verification.screenshotUrl) {
        const screenshot = await client.hifiEditorScreenshot(replacement.sessionId);
        setEditorScreenshotUrl(URL.createObjectURL(screenshot));
      }
    } catch (cause) { setError(errorText(cause)); }
    finally { setPsdBusy(false); }
  };

  const approve = async () => {
    if (!replacement || !(review?.approvable || editorVerification?.approvable) || !review?.candidateSha256 || psdBusy) return;
    setPsdBusy(true); setError("");
    try {
      const approved = await client.approveHifiReplacement(replacement.sessionId, review.candidateSha256, exportMode);
      if (exportMode === "package") {
        downloadBlob(await client.downloadHifiReplacement(approved.sessionId, false));
      }
      setReplacement(approved); setStage("delivered");
    } catch (cause) { setError(errorText(cause)); }
    finally { setPsdBusy(false); }
  };

  const reject = async (reason: string) => {
    if (!replacement || psdBusy) return;
    setPsdBusy(true); setError("");
    try {
      await client.rejectHifiReplacement(replacement.sessionId, reason);
      setStage("mapping"); setReview(undefined); setEditorVerification(undefined); setEditorScreenshotUrl(undefined); setChecks(EMPTY_CHECKS);
    } catch (cause) { setError(errorText(cause)); }
    finally { setPsdBusy(false); }
  };

  return <main className="local-hifi-app">
    <header className="local-hifi-header"><div><p>本地视觉替换 · 验证版</p><h1>PSD → FairyGUI</h1></div><span>所有材料仅在本机处理</span></header>
    <ol className="local-hifi-steps" aria-label="工作流"><li className={stage === "prepare" ? "is-current" : "is-done"}>1 准备材料</li><li className={stage === "mapping" || stage === "sessions" ? "is-current" : ["review", "delivered"].includes(stage) ? "is-done" : ""}>2 盘点映射</li><li className={stage === "review" ? "is-current" : stage === "delivered" ? "is-done" : ""}>3 候选审核</li><li className={stage === "delivered" ? "is-current" : ""}>4 Editor 检查与交付</li></ol>
    {stage === "prepare" && <><div className="local-hifi-grid">
      <section className="local-hifi-card"><div className="local-hifi-card-title"><div><span>01</span><h2>旧 FairyGUI 工程</h2></div>{projectBusy && <small role="status">正在读取…</small>}</div><label className="local-hifi-file">旧 FairyGUI 工程压缩包<input type="file" accept={PROJECT_ARCHIVE_ACCEPT} disabled={projectBusy} onChange={(event) => void chooseProject(event.currentTarget.files?.[0])} /></label>{project && <p className="local-hifi-file-name">{project.displayName}</p>}{projectError && <p className="local-hifi-error" role="alert">{projectError}</p>}</section>
      <section className="local-hifi-card"><div className="local-hifi-card-title"><div><span>02</span><h2>HIFI PSD</h2></div>{psdBusy && <small role="status">正在解析并保存…</small>}</div><label className="local-hifi-file">HIFI PSD<input type="file" accept=".psd,image/vnd.adobe.photoshop,image/x-photoshop" disabled={psdBusy} onChange={(event) => void choosePsd(event.currentTarget.files?.[0])} /></label>{inspection && <div className="local-psd-summary"><strong>{inspection.sourceName}</strong><p>{inspection.width} × {inspection.height} · {inspection.depth}-bit {inspection.colorMode}</p><p>{inspection.layerCount} 个图层 · {inspection.textLayerCount} 个文字层 · {inspection.smartObjectCount} 个智能对象</p><p>PSD 已保存在本机，后续映射不会重复上传。</p>{visibleTextLayers.length > 0 && <p className="local-text-evidence">可见文字样式 {styledVisibleTextLayers.length} / {visibleTextLayers.length} 层 · 字体名称 {resolvedVisibleFontRuns} / {visibleFontRuns} 个运行已解析</p>}{compositeUrl && <figure className="local-psd-composite"><img src={compositeUrl} alt="PSD 合成基准图" /><figcaption>PSD 内嵌合成基准</figcaption></figure>}{inspection.blockingIssues.length > 0 && <details className="local-lossless-audit" open><summary>{inspection.blockingIssues.length} 项无损阻断；可以先做映射</summary><p>以下证据会在候选审核与 Editor 检查阶段逐项验证。</p><ul>{inspection.blockingIssues.map((code) => <li key={code}>{blockerLabel(code)}</li>)}</ul></details>}</div>}</section>
    </div>
    {tree && project && <HifiTargetPicker project={project} tree={tree} values={selectedList} disabled={projectBusy || psdBusy} onToggle={toggleTarget} />}
    <section className="local-hifi-card local-font-card"><div className="local-hifi-card-title"><div><span>03</span><h2>固定字体</h2></div><strong className={fonts.length > 0 && installedFonts === fonts.length ? "is-ok" : "is-warn"}>固定字体 {installedFonts} / {fonts.length || 2}</strong></div><p>应用自动检查已登记字体，不需要每次上传。</p><ul>{fonts.map((font) => <li key={font.sha256}><span className={font.installed ? "is-installed" : "is-missing"}>{font.installed ? "✓" : "!"}</span><div><strong>{font.family}</strong><small>{font.postscriptName}</small></div></li>)}</ul></section>
    <details className="local-optional" open><summary>可选补充材料</summary><p>外部切图和效果图均为可选材料</p><div><label>可选 PNG 切图<input type="file" accept=".png,image/png" multiple /></label><label>可选效果图<input type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" /></label></div></details>
    </>}
    {restoreNote && <p role="status">{restoreNote}</p>}
    {stage === "mapping" && mapping && <section className="local-mapping-workspace">{mapping.unresolvedCount > 5 && !allowExtendedReview && <button type="button" className="secondary-button" onClick={() => setAllowExtendedReview(true)}>展开全部待审核记录</button>}<div className="local-mapping-batch" aria-label="批量映射操作"><div><strong>批量处理建议项</strong><p>以下为算法建议，仍需核对具体对象后确认。</p></div><div className="local-hifi-action-buttons"><button type="button" className="secondary-button" disabled={psdBusy || mapping.unresolvedCount > 5 && !allowExtendedReview || !mapping.items.some((item) => item.action === undefined && item.status === "suggested")} onClick={() => void decideBatch("suggested")}>接受建议对应 {mapping.items.filter((item) => item.action === undefined && item.status === "suggested").length}</button><button type="button" className="secondary-button" disabled={psdBusy || mapping.unresolvedCount > 5 && !allowExtendedReview || !mapping.items.some((item) => item.action === undefined && item.status === "fgui_only")} onClick={() => void decideBatch("fgui_only")}>未绘制对象列为例外 {mapping.items.filter((item) => item.action === undefined && item.status === "fgui_only").length}</button></div></div><HifiMappingPanel mapping={mapping} currentItemId={currentItemId} busy={psdBusy} onCurrentChange={setCurrentItemId} onDecision={(item, action, nodeId) => void decide(item, action, nodeId)} psdPreviewUrl={compositeUrl} oldPreviewUrl={oldPreviewUrl} allowVisualAddition={false} allowKeepOld={false} reviewLimit={allowExtendedReview ? Infinity : 5} />{inspection && inspection.blockingIssues.length > 0 && <p className="local-hifi-error" role="status">{inspection.blockingIssues.length} 项无损证据将在候选审核与 Editor 检查中验证。</p>}</section>}
    {stage === "sessions" && <section className="local-hifi-card"><div className="local-hifi-card-title"><div><span>02</span><h2>批量会话</h2></div><strong>{sessions.length} 个目标</strong></div><p>PSD 只解析一次，每个目标一个独立会话；逐个完成映射、审核与交付。</p><ul className="hifi-session-list">{sessions.map((session) => <li key={session.sessionId}><button type="button" className="secondary-button" disabled={psdBusy} onClick={() => void openSession(session)}>{session.target.packageName} / {session.target.directory} / {session.target.componentName}</button><small>{session.unresolvedCount} 项待确认 · {session.status}</small></li>)}</ul></section>}
    {stage === "review" && review && <section className="local-review-workspace"><section className="local-hifi-card local-export-card"><div className="local-hifi-card-title"><div><span>04</span><h2>交付方式</h2></div><strong>{exportMode === "overwrite" ? "覆盖旧工程" : "导出新版"}</strong></div><label><input type="radio" name="hifi-export-mode" checked={exportMode === "package"} disabled={psdBusy} onChange={() => setExportMode("package")} /> 导出新版工程 ZIP，旧工程保持不变</label><label><input type="radio" name="hifi-export-mode" checked={exportMode === "overwrite"} disabled={psdBusy} onChange={() => setExportMode("overwrite")} /> 覆盖本机旧工程，历史版本仍可回退</label><p className="writer-inline-note">两种方式写入的内容完全相同，且都必须与已审核候选的哈希逐字节一致；覆盖不会跳过任何校验。</p></section><HifiReplacementReviewPanel review={review} checks={checks} busy={psdBusy} verification={editorVerification} editorScreenshotUrl={editorScreenshotUrl} onChecksChange={setChecks} onDownloadCandidate={() => void download(true)} onVerifyEditor={() => void verifyEditor()} onReject={(reason) => void reject(reason)} /></section>}
    {stage === "delivered" && <section className="hifi-delivered" role="status"><strong>{exportMode === "overwrite" ? "已覆盖本机旧工程" : "已交付 HIFI 替换工程"}</strong><p>{exportMode === "overwrite" ? "本机旧工程已更新为审核通过的内容，写入字节与候选哈希一致；此前的工程版本仍保留在本机记录中。" : "正式 ZIP 已下载，内容与审核候选哈希一致。"}</p>{sessions.length > 1 && <p>批量进度：可回到“批量会话”继续下一个目标。</p>}</section>}
    {error && <p className="local-hifi-error" role="alert">{error}</p>}
    <footer className="local-hifi-actions">
      {stage === "prepare" && <><div><strong>{ready ? "材料已就绪" : "等待必需材料"}</strong><p>{projectBusy ? "正在读取旧 FairyGUI 工程…" : projectError ? "请重新选择旧 FairyGUI 工程压缩包" : !project ? "请先导入旧 FairyGUI 工程压缩包" : !targets.length ? "请展开工程目录并勾选一个或多个根组件" : !psdSource ? "请导入 HIFI PSD" : targets.length > 1 ? `将为 ${targets.length} 个根组件分别建立替换会话，PSD 只解析一次。` : "下一步将直接比较 PSD 图层与目标 FGUI 组件，不经过 Figma。"}</p></div><button type="button" disabled={!ready || projectBusy || psdBusy} onClick={() => void startMapping()}>{targets.length > 1 ? `为 ${targets.length} 个目标建立会话` : "进入盘点与映射"}</button></>}
      {stage === "sessions" && <><div><strong>{sessions.length} 个会话待处理</strong><p>逐个进入映射与交付；PSD 材料已复用，不会重复解析。</p></div><button type="button" className="secondary-button" disabled={psdBusy} onClick={() => setStage("prepare")}>返回材料页</button></>}
      {stage === "mapping" && <><div><strong>{mapping?.unresolvedCount ?? 0} 项待确认</strong><p>{(mapping?.unresolvedCount ?? 0) > 5 ? `还有 ${mapping?.unresolvedCount} 条记录；可展开逐项审核，候选仍须全部安全归属后生成。` : inspection?.blockingIssues.length ? `${inspection.blockingIssues.length} 项无损证据将在候选审核中继续验证` : "映射和无损证据已就绪"}</p></div><div className="local-hifi-action-buttons"><button type="button" className="secondary-button" disabled={psdBusy} onClick={() => setStage("prepare")}>返回材料页</button><button type="button" disabled={Boolean(mapping?.unresolvedCount) || psdBusy} onClick={() => void build()}>{psdBusy ? "正在生成…" : "生成审核候选"}</button></div></>}
      {stage === "review" && review && <HifiReplacementReviewActions review={review} checks={checks} verification={editorVerification} busy={psdBusy} onReturn={() => { setStage("mapping"); setChecks(EMPTY_CHECKS); }} onApprove={() => void approve()} />}
      {stage === "delivered" && <>{sessions.length > 1 && <button type="button" className="secondary-button" disabled={psdBusy} onClick={() => setStage("sessions")}>回到批量会话</button>}{exportMode === "package" && <button type="button" onClick={() => void download(false)}>再次下载正式 ZIP</button>}</>}
    </footer>
  </main>;
}
