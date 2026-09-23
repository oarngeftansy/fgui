import { useEffect, useMemo, useState } from "react";

import type { FixedFontStatus, HifiMappingAction, HifiMappingDraft, HifiMappingItem, HifiProjectTree, HifiReplacement, HifiReplacementReview, ProjectView, ProjectWorkflowClient, PsdSource } from "../../figma-plugin/src/project-client";
import { ProjectWorkflowClient as WorkflowClient } from "../../figma-plugin/src/project-client";
import { HifiMappingPanel } from "./figma/HifiMappingPanel";
import { HifiReplacementReviewActions, HifiReplacementReviewPanel, type HifiEditorCheckState } from "./figma/HifiReplacementReviewPanel";
import { HifiTargetPicker, selectedHifiTarget, type HifiTargetSelection } from "./figma/HifiTargetPicker";

export type LocalHifiClientLike = Pick<ProjectWorkflowClient, "fixedFonts" | "uploadProject" | "hifiTargets" | "uploadPsd" | "psdComposite" | "createPsdHifiReplacement" | "hifiMapping" | "decideHifiMapping" | "buildHifiReplacement" | "reviewHifiReplacement" | "approveHifiReplacement" | "rejectHifiReplacement" | "downloadHifiReplacement">;

type Stage = "prepare" | "mapping" | "review" | "delivered";
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
  if (code === "invalid_zip") return "旧 FairyGUI 工程 ZIP 无效。";
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
  const [selected, setSelected] = useState<HifiTargetSelection>();
  const [psdSource, setPsdSource] = useState<PsdSource>();
  const [compositeUrl, setCompositeUrl] = useState<string>();
  const [stage, setStage] = useState<Stage>("prepare");
  const [replacement, setReplacement] = useState<HifiReplacement>();
  const [mapping, setMapping] = useState<HifiMappingDraft>();
  const [review, setReview] = useState<HifiReplacementReview>();
  const [checks, setChecks] = useState<HifiEditorCheckState>(EMPTY_CHECKS);
  const [currentItemId, setCurrentItemId] = useState<string>();
  const [projectBusy, setProjectBusy] = useState(false);
  const [psdBusy, setPsdBusy] = useState(false);
  const [error, setError] = useState("");
  const target = useMemo(() => project && tree ? selectedHifiTarget(project, tree, selected) : undefined, [project, selected, tree]);
  const installedFonts = fonts.filter((font) => font.installed).length;
  const inspection = psdSource?.inspection;
  const visibleTextLayers = psdSource?.layers.filter((layer) => layer.kind.toLowerCase() === "type" && layer.effectiveVisible) ?? [];
  const styledVisibleTextLayers = visibleTextLayers.filter((layer) => layer.textStyle && layer.textStyle.runs.length > 0);
  const resolvedVisibleFontRuns = styledVisibleTextLayers.flatMap((layer) => layer.textStyle?.runs ?? []).filter((run) => run.fontName).length;
  const visibleFontRuns = styledVisibleTextLayers.flatMap((layer) => layer.textStyle?.runs ?? []).length;
  const ready = Boolean(target && psdSource && fonts.length > 0 && installedFonts === fonts.length);

  useEffect(() => {
    const controller = new AbortController();
    void client.fixedFonts(controller.signal).then(setFonts).catch((cause) => setError(errorText(cause)));
    return () => controller.abort();
  }, [client]);
  useEffect(() => () => {
    if (compositeUrl) URL.revokeObjectURL(compositeUrl);
  }, [compositeUrl]);

  const chooseProject = async (file?: File) => {
    setProject(undefined); setTree(undefined); setSelected(undefined); setReplacement(undefined); setMapping(undefined); setReview(undefined); setChecks(EMPTY_CHECKS); setStage("prepare"); setError("");
    if (!file) return;
    setProjectBusy(true);
    try {
      const uploaded = await client.uploadProject(file);
      const targets = await client.hifiTargets(uploaded.projectId);
      setProject(uploaded); setTree(targets);
    } catch (cause) { setError(errorText(cause)); }
    finally { setProjectBusy(false); }
  };

  const choosePsd = async (file?: File) => {
    setPsdSource(undefined); setCompositeUrl(undefined); setReplacement(undefined); setMapping(undefined); setReview(undefined); setChecks(EMPTY_CHECKS); setStage("prepare"); setError("");
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

  const startMapping = async () => {
    if (!project || !target || !psdSource || projectBusy || psdBusy) return;
    setPsdBusy(true); setError("");
    try {
      const started = await client.createPsdHifiReplacement(psdSource.sourceId, project, target);
      setReplacement(started.replacement); setMapping(started.mapping);
      setCurrentItemId(started.mapping.items.find((item) => !item.action)?.itemId ?? started.mapping.items[0]?.itemId);
      setStage("mapping");
    } catch (cause) { setError(errorText(cause)); }
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

  const build = async () => {
    if (!replacement || !mapping || mapping.unresolvedCount || inspection?.blockingIssues.length || psdBusy) return;
    setPsdBusy(true); setError("");
    try {
      const built = await client.buildHifiReplacement(replacement.sessionId, mapping.mappingRevision);
      const nextReview = await client.reviewHifiReplacement(replacement.sessionId);
      setReplacement(built); setReview(nextReview); setChecks(EMPTY_CHECKS); setStage("review");
    } catch (cause) { setError(errorText(cause)); }
    finally { setPsdBusy(false); }
  };

  const download = async (candidate: boolean) => {
    if (!replacement) return;
    try { downloadBlob(await client.downloadHifiReplacement(replacement.sessionId, candidate)); }
    catch (cause) { setError(errorText(cause)); }
  };

  const approve = async () => {
    if (!replacement || !review?.approvable || !review.candidateSha256 || psdBusy) return;
    setPsdBusy(true); setError("");
    try {
      const approved = await client.approveHifiReplacement(replacement.sessionId, review.candidateSha256);
      const artifact = await client.downloadHifiReplacement(approved.sessionId, false);
      downloadBlob(artifact); setReplacement(approved); setStage("delivered");
    } catch (cause) { setError(errorText(cause)); }
    finally { setPsdBusy(false); }
  };

  const reject = async (reason: string) => {
    if (!replacement || psdBusy) return;
    setPsdBusy(true); setError("");
    try {
      await client.rejectHifiReplacement(replacement.sessionId, reason);
      setStage("mapping"); setReview(undefined); setChecks(EMPTY_CHECKS);
    } catch (cause) { setError(errorText(cause)); }
    finally { setPsdBusy(false); }
  };

  return <main className="local-hifi-app">
    <header className="local-hifi-header"><div><p>本地无损替换工具</p><h1>PSD → FairyGUI</h1></div><span>所有材料仅在本机处理</span></header>
    <ol className="local-hifi-steps" aria-label="工作流"><li className={stage === "prepare" ? "is-current" : "is-done"}>1 准备材料</li><li className={stage === "mapping" ? "is-current" : ["review", "delivered"].includes(stage) ? "is-done" : ""}>2 盘点映射</li><li className={stage === "review" ? "is-current" : stage === "delivered" ? "is-done" : ""}>3 候选审核</li><li className={stage === "delivered" ? "is-current" : ""}>4 Editor 检查与交付</li></ol>
    {stage === "prepare" && <><div className="local-hifi-grid">
      <section className="local-hifi-card"><div className="local-hifi-card-title"><div><span>01</span><h2>旧 FairyGUI 工程</h2></div>{projectBusy && <small role="status">正在读取…</small>}</div><label className="local-hifi-file">旧 FairyGUI 工程 ZIP<input type="file" accept=".zip,application/zip,application/x-zip-compressed" disabled={projectBusy} onChange={(event) => void chooseProject(event.currentTarget.files?.[0])} /></label>{project && <p className="local-hifi-file-name">{project.displayName}</p>}</section>
      <section className="local-hifi-card"><div className="local-hifi-card-title"><div><span>02</span><h2>HIFI PSD</h2></div>{psdBusy && <small role="status">正在解析并保存…</small>}</div><label className="local-hifi-file">HIFI PSD<input type="file" accept=".psd,image/vnd.adobe.photoshop,image/x-photoshop" disabled={psdBusy} onChange={(event) => void choosePsd(event.currentTarget.files?.[0])} /></label>{inspection && <div className="local-psd-summary"><strong>{inspection.sourceName}</strong><p>{inspection.width} × {inspection.height} · {inspection.depth}-bit {inspection.colorMode}</p><p>{inspection.layerCount} 个图层 · {inspection.textLayerCount} 个文字层 · {inspection.smartObjectCount} 个智能对象</p><p>PSD 已保存在本机，后续映射不会重复上传。</p>{visibleTextLayers.length > 0 && <p className="local-text-evidence">可见文字样式 {styledVisibleTextLayers.length} / {visibleTextLayers.length} 层 · 字体名称 {resolvedVisibleFontRuns} / {visibleFontRuns} 个运行已解析</p>}{compositeUrl && <figure className="local-psd-composite"><img src={compositeUrl} alt="PSD 合成基准图" /><figcaption>PSD 内嵌合成基准</figcaption></figure>}{inspection.blockingIssues.length > 0 && <details className="local-lossless-audit" open><summary>{inspection.blockingIssues.length} 项无损阻断；可以先做映射</summary><p>以下证据未通过前，候选工程和交付会保持锁定。</p><ul>{inspection.blockingIssues.map((code) => <li key={code}>{blockerLabel(code)}</li>)}</ul></details>}</div>}</section>
    </div>
    {tree && project && <HifiTargetPicker project={project} tree={tree} value={selected} disabled={projectBusy || psdBusy} onChange={setSelected} />}
    <section className="local-hifi-card local-font-card"><div className="local-hifi-card-title"><div><span>03</span><h2>固定字体</h2></div><strong className={fonts.length > 0 && installedFonts === fonts.length ? "is-ok" : "is-warn"}>固定字体 {installedFonts} / {fonts.length || 2}</strong></div><p>应用自动检查已登记字体，不需要每次上传。</p><ul>{fonts.map((font) => <li key={font.sha256}><span className={font.installed ? "is-installed" : "is-missing"}>{font.installed ? "✓" : "!"}</span><div><strong>{font.family}</strong><small>{font.postscriptName}</small></div></li>)}</ul></section>
    <details className="local-optional" open><summary>可选补充材料</summary><p>外部切图和效果图均为可选材料</p><div><label>可选 PNG 切图<input type="file" accept=".png,image/png" multiple /></label><label>可选效果图<input type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" /></label></div></details>
    </>}
    {stage === "mapping" && mapping && <section className="local-mapping-workspace"><HifiMappingPanel mapping={mapping} currentItemId={currentItemId} busy={psdBusy} onCurrentChange={setCurrentItemId} onDecision={(item, action, nodeId) => void decide(item, action, nodeId)} />{inspection && inspection.blockingIssues.length > 0 && <p className="local-hifi-error" role="status">当前可完成组件映射；{inspection.blockingIssues.length} 项无损阻断仍会阻止候选工程和交付。</p>}</section>}
    {stage === "review" && review && <section className="local-review-workspace"><HifiReplacementReviewPanel review={review} checks={checks} busy={psdBusy} onChecksChange={setChecks} onDownloadCandidate={() => void download(true)} onReject={(reason) => void reject(reason)} /></section>}
    {stage === "delivered" && <section className="hifi-delivered" role="status"><strong>已交付 HIFI 替换工程</strong><p>正式 ZIP 已下载，内容与审核候选哈希一致。</p></section>}
    {error && <p className="local-hifi-error" role="alert">{error}</p>}
    <footer className="local-hifi-actions">
      {stage === "prepare" && <><div><strong>{ready ? "材料已就绪" : "等待必需材料"}</strong><p>下一步将直接比较 PSD 图层与目标 FGUI 组件，不经过 Figma。</p></div><button type="button" disabled={!ready || psdBusy} onClick={() => void startMapping()}>进入盘点与映射</button></>}
      {stage === "mapping" && <><div><strong>{mapping?.unresolvedCount ?? 0} 项待确认</strong><p>{inspection?.blockingIssues.length ? `${inspection.blockingIssues.length} 项无损证据尚未通过` : "映射和无损证据已就绪"}</p></div><div className="local-hifi-action-buttons"><button type="button" className="secondary-button" disabled={psdBusy} onClick={() => setStage("prepare")}>返回材料页</button><button type="button" disabled={Boolean(mapping?.unresolvedCount) || Boolean(inspection?.blockingIssues.length) || psdBusy} onClick={() => void build()}>{psdBusy ? "正在生成…" : "生成候选工程"}</button></div></>}
      {stage === "review" && review && <HifiReplacementReviewActions review={review} checks={checks} busy={psdBusy} onReturn={() => { setStage("mapping"); setChecks(EMPTY_CHECKS); }} onApprove={() => void approve()} />}
      {stage === "delivered" && <button type="button" onClick={() => void download(false)}>再次下载正式 ZIP</button>}
    </footer>
  </main>;
}
