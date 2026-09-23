import { useEffect, useMemo, useState } from "react";

import type { FixedFontStatus, HifiProjectTree, ProjectView, ProjectWorkflowClient, PsdInspection } from "../../figma-plugin/src/project-client";
import { ProjectWorkflowClient as WorkflowClient } from "../../figma-plugin/src/project-client";
import { HifiTargetPicker, selectedHifiTarget, type HifiTargetSelection } from "./figma/HifiTargetPicker";

export type LocalHifiClientLike = Pick<ProjectWorkflowClient, "fixedFonts" | "uploadProject" | "hifiTargets" | "inspectPsd">;

function errorText(error: unknown): string {
  const code = (error as { code?: string } | null)?.code;
  if (code === "invalid_zip") return "旧 FairyGUI 工程 ZIP 无效。";
  if (code === "invalid_psd") return "PSD 文件无效或无法解析。";
  if (code === "psd_too_large") return "PSD 文件超过本地检查上限。";
  return "本地处理失败，请检查文件后重试。";
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
  const [inspection, setInspection] = useState<PsdInspection>();
  const [projectBusy, setProjectBusy] = useState(false);
  const [psdBusy, setPsdBusy] = useState(false);
  const [error, setError] = useState("");
  const target = useMemo(() => project && tree ? selectedHifiTarget(project, tree, selected) : undefined, [project, selected, tree]);
  const installedFonts = fonts.filter((font) => font.installed).length;
  const ready = Boolean(target && inspection && inspection.blockingIssues.length === 0 && fonts.length > 0 && installedFonts === fonts.length);

  useEffect(() => {
    const controller = new AbortController();
    void client.fixedFonts(controller.signal).then(setFonts).catch((cause) => setError(errorText(cause)));
    return () => controller.abort();
  }, [client]);

  const chooseProject = async (file?: File) => {
    setProject(undefined); setTree(undefined); setSelected(undefined); setError("");
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
    setInspection(undefined); setError("");
    if (!file) return;
    setPsdBusy(true);
    try { setInspection(await client.inspectPsd(file)); }
    catch (cause) { setError(errorText(cause)); }
    finally { setPsdBusy(false); }
  };

  return <main className="local-hifi-app">
    <header className="local-hifi-header"><div><p>本地无损替换工具</p><h1>PSD → FairyGUI</h1></div><span>所有材料仅在本机处理</span></header>
    <ol className="local-hifi-steps" aria-label="工作流"><li className="is-current">1 准备材料</li><li>2 盘点映射</li><li>3 候选审核</li><li>4 Editor 检查与交付</li></ol>
    <div className="local-hifi-grid">
      <section className="local-hifi-card"><div className="local-hifi-card-title"><div><span>01</span><h2>旧 FairyGUI 工程</h2></div>{projectBusy && <small role="status">正在读取…</small>}</div><label className="local-hifi-file">旧 FairyGUI 工程 ZIP<input type="file" accept=".zip,application/zip,application/x-zip-compressed" disabled={projectBusy} onChange={(event) => void chooseProject(event.currentTarget.files?.[0])} /></label>{project && <p className="local-hifi-file-name">{project.displayName}</p>}</section>
      <section className="local-hifi-card"><div className="local-hifi-card-title"><div><span>02</span><h2>HIFI PSD</h2></div>{psdBusy && <small role="status">正在解析…</small>}</div><label className="local-hifi-file">HIFI PSD<input type="file" accept=".psd,image/vnd.adobe.photoshop,image/x-photoshop" disabled={psdBusy} onChange={(event) => void choosePsd(event.currentTarget.files?.[0])} /></label>{inspection && <div className="local-psd-summary"><strong>{inspection.sourceName}</strong><p>{inspection.width} × {inspection.height} · {inspection.depth}-bit {inspection.colorMode}</p><p>{inspection.layerCount} 个图层 · {inspection.textLayerCount} 个文字层 · {inspection.smartObjectCount} 个智能对象</p>{inspection.blockingIssues.length > 0 && <p className="is-blocked">{inspection.blockingIssues.length} 项无损阻断，处理完成前不能进入映射。</p>}</div>}</section>
    </div>
    {tree && project && <HifiTargetPicker project={project} tree={tree} value={selected} disabled={projectBusy || psdBusy} onChange={setSelected} />}
    <section className="local-hifi-card local-font-card"><div className="local-hifi-card-title"><div><span>03</span><h2>固定字体</h2></div><strong className={fonts.length > 0 && installedFonts === fonts.length ? "is-ok" : "is-warn"}>固定字体 {installedFonts} / {fonts.length || 2}</strong></div><p>应用自动检查已登记字体，不需要每次上传。</p><ul>{fonts.map((font) => <li key={font.sha256}><span className={font.installed ? "is-installed" : "is-missing"}>{font.installed ? "✓" : "!"}</span><div><strong>{font.family}</strong><small>{font.postscriptName}</small></div></li>)}</ul></section>
    <details className="local-optional" open><summary>可选补充材料</summary><p>外部切图和效果图均为可选材料</p><div><label>可选 PNG 切图<input type="file" accept=".png,image/png" multiple /></label><label>可选效果图<input type="file" accept=".png,.jpg,.jpeg,image/png,image/jpeg" /></label></div></details>
    {error && <p className="local-hifi-error" role="alert">{error}</p>}
    <footer className="local-hifi-actions"><div><strong>{ready ? "材料检查通过" : "等待材料通过无损检查"}</strong><p>下一步将直接比较 PSD 图层与目标 FGUI 组件，不经过 Figma。</p></div><button type="button" disabled={!ready}>进入盘点与映射</button></footer>
  </main>;
}
