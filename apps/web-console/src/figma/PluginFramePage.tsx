import { FormEvent, useEffect, useRef, useState } from "react";
import { PairingClient, PairingRequestError, safePairingMessage } from "../../../figma-plugin/src/pairing";
import { SelectionUploader, type SelectionView, safeUploadMessage } from "../../../figma-plugin/src/upload";
import type { ExportedResource } from "../../../figma-plugin/src/assets";
import type { SelectionManifest, SelectionPreflight } from "../../../figma-plugin/src/selection";

type PluginMessage =
  | { type: "pairing-credential"; credential: string }
  | { type: "unpair" }
  | { type: "selection-preflight" }
  | { type: "selection-export" };
type PostToFigma = (message: { pluginId: string; pluginMessage: PluginMessage }, targetOrigin: string) => void;
type UploadProgress = { completed: number; total: number };
type PluginFramePageProps = {
  pluginId?: string;
  exchange?: (code: string, deviceName: string) => Promise<{ credential: string }>;
  postToFigma?: PostToFigma;
  status?: "revoked";
  upload?: (
    manifest: SelectionManifest,
    resources: ExportedResource[],
    credential: string,
    idempotencyKey: string,
    onProgress: (progress: UploadProgress) => void,
  ) => Promise<SelectionView>;
};

const FIGMA_ORIGIN = "https://www.figma.com";

function safeMessage(error: unknown): string {
  if (error instanceof PairingRequestError) return error.message;
  const code = error && typeof error === "object" ? (error as { detail?: { code?: unknown } }).detail?.code : undefined;
  return safePairingMessage(code);
}

async function exchangePairing(code: string, deviceName: string): Promise<{ credential: string }> {
  const paired = await new PairingClient().exchange(code, deviceName);
  return { credential: paired.credential };
}

function configuredPluginId(value: string | undefined): string {
  const pluginId = value ?? new URLSearchParams(window.location.search).get("pluginId");
  return pluginId && /^\d+$/.test(pluginId) ? pluginId : "";
}

function defaultUpload(
  manifest: SelectionManifest,
  resources: ExportedResource[],
  credential: string,
  idempotencyKey: string,
  onProgress: (progress: UploadProgress) => void,
) {
  return new SelectionUploader({ credential }).send(manifest, resources, idempotencyKey, onProgress);
}

export function PluginFramePage({
  pluginId: explicitPluginId,
  exchange = exchangePairing,
  postToFigma,
  status,
  upload = defaultUpload,
}: PluginFramePageProps) {
  const pluginId = configuredPluginId(explicitPluginId);
  const [code, setCode] = useState("");
  const [state, setState] = useState<"ready" | "loading" | "paired" | "revoked" | "error">(status ?? "ready");
  const [error, setError] = useState("");
  const [preflight, setPreflight] = useState<SelectionPreflight | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [view, setView] = useState<SelectionView | null>(null);
  const [copyStatus, setCopyStatus] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const credential = useRef("");
  const idempotencyKey = useRef("");
  const selectionSignature = useRef("");
  const activePreflight = useRef<SelectionPreflight | null>(null);

  useEffect(() => setState(status ?? "ready"), [status]);
  const post = postToFigma ?? ((message, targetOrigin) => window.parent.postMessage(message, targetOrigin));

  useEffect(() => {
    const receive = (event: MessageEvent<{
      pluginId?: string;
      pluginMessage?: {
        type?: string;
        status?: string;
        code?: string;
        credential?: string;
        preflight?: SelectionPreflight;
        manifest?: SelectionManifest;
        resources?: ExportedResource[];
      };
    }>) => {
      if (event.origin !== FIGMA_ORIGIN || event.source !== window.parent || event.data?.pluginId !== pluginId) return;
      const message = event.data?.pluginMessage;
      if (message?.type === "credential" && typeof message.credential === "string") {
        credential.current = message.credential;
        setState("paired");
      }
      if (message?.type === "pairing-status") {
        setState(message.status === "paired" ? "paired" : message.status === "revoked" ? "revoked" : "ready");
      }
      if (message?.type === "pairing-error") {
        setError(safeMessage({ detail: { code: message.code } }));
        setState(message.code === "plugin_credential_revoked" ? "revoked" : "error");
      }
      if (message?.type === "selection-preflight" && message.preflight) {
        const signature = JSON.stringify(message.preflight.manifest);
        if (signature !== selectionSignature.current) {
          selectionSignature.current = signature;
          idempotencyKey.current = crypto.randomUUID();
          setView(null);
        }
        activePreflight.current = message.preflight;
        setPreflight(message.preflight);
        setProgress(null);
        setCopyStatus("");
      }
      if (message?.type === "selection-error") {
        setError(safeUploadMessage(message.code));
        setUploading(false);
      }
      if (
        message?.type === "selection-export"
        && message.manifest
        && Array.isArray(message.resources)
        && credential.current
        && idempotencyKey.current
        && activePreflight.current
      ) {
        setUploading(true);
        setProgress({ completed: 0, total: message.resources.length });
        void upload(
          message.manifest,
          message.resources,
          credential.current,
          idempotencyKey.current,
          setProgress,
        ).then((result) => {
          setView(result);
          setUploading(false);
          setError("");
          try {
            window.open(`/figma/selections/${result.selection_id}`, "_blank", "noopener");
          } catch {
            // Popup failure is not an upload failure; the fallback link stays visible.
          }
        }).catch(() => {
          setError(safeUploadMessage(undefined));
          setUploading(false);
        });
      }
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [pluginId, upload]);

  const clearSelectionAttempt = () => {
    activePreflight.current = null;
    selectionSignature.current = "";
    idempotencyKey.current = "";
    setPreflight(null);
    setProgress(null);
    setUploading(false);
    setView(null);
    setCopyStatus("");
  };

  const unpair = () => {
    post({ pluginId, pluginMessage: { type: "unpair" } }, FIGMA_ORIGIN);
    credential.current = "";
    setCode("");
    setError("");
    clearSelectionAttempt();
    setState("ready");
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (state === "loading") return;
    if (!/^\d{6}$/.test(code.trim())) {
      setError("请输入六位数字配对码");
      setState("error");
      inputRef.current?.focus();
      return;
    }
    if (!pluginId) {
      setError("插件配置无效，请联系管理员");
      setState("error");
      return;
    }
    setError("");
    setState("loading");
    try {
      const paired = await exchange(code.trim(), "Figma plugin");
      post({ pluginId, pluginMessage: { type: "pairing-credential", credential: paired.credential } }, FIGMA_ORIGIN);
      credential.current = paired.credential;
      setState("paired");
    } catch (caught) {
      setError(safeMessage(caught));
      setState("error");
    }
  };

  const copyTaskLink = async () => {
    if (!view) return;
    const url = `${window.location.origin}/figma/selections/${view.selection_id}`;
    try {
      if (!navigator.clipboard) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(url);
      setCopyStatus("链接已复制");
    } catch {
      setCopyStatus("复制失败，请点击“打开任务”后从浏览器地址栏复制链接");
    }
  };

  if (state === "revoked") {
    return <main className="plugin-frame" aria-labelledby="plugin-frame-title"><p className="eyebrow">Figma 转 FairyGUI</p><h1 id="plugin-frame-title">连接 Figma 插件</h1><p className="plugin-copy" role="alert">此插件配对已撤销，请重新配对</p><button className="primary-button" type="button" onClick={() => setState("ready")}>重新配对</button></main>;
  }

  if (state === "paired") {
    return <main className="plugin-frame" aria-labelledby="plugin-frame-title">
      <p className="eyebrow">Figma 转 FairyGUI</p><h1 id="plugin-frame-title">已完成配对</h1>
      <p className="plugin-copy" aria-live="polite">现在可以导出当前选择。</p>
      {!preflight && <button className="primary-button" type="button" onClick={() => post({ pluginId, pluginMessage: { type: "selection-preflight" } }, FIGMA_ORIGIN)}>准备导出当前选择</button>}
      {preflight && <section className="project-summary" aria-live="polite">
        <p>{preflight.manifest?.display_name}</p><p>{preflight.nodeCount} 个图层，预计 {preflight.assetCount} 个资源。</p>
        {preflight.warnings.map((item) => <p key={item.code}>{item.message}</p>)}
        <button className="primary-button" type="button" disabled={!preflight.sendable || uploading} onClick={() => {
          if (preflight.sendable && !uploading) {
            setUploading(true); setProgress(null); setError("");
            post({ pluginId, pluginMessage: { type: "selection-export" } }, FIGMA_ORIGIN);
          }
        }}>{uploading ? "正在发送…" : "发送当前选择"}</button>
        {progress && <div role="status" aria-live="polite">
          <progress aria-label="上传进度" value={progress.completed} max={Math.max(1, progress.total)} aria-valuenow={progress.completed} aria-valuemin={0} aria-valuemax={progress.total} />
          <span>{progress.completed} / {progress.total}</span>
        </div>}
      </section>}
      {error && <p className="message message-error" role="alert">{error}</p>}
      {view && <section className="project-summary" aria-live="polite">
        <p>已创建任务。</p>
        <a href={`/figma/selections/${view.selection_id}`} target="_blank" rel="noopener">打开任务</a>
        <button className="secondary-button" type="button" onClick={() => void copyTaskLink()}>复制链接</button>
        {copyStatus && <p className={copyStatus.startsWith("复制失败") ? "message message-error" : "message"} role={copyStatus.startsWith("复制失败") ? "alert" : "status"}>{copyStatus}</p>}
      </section>}
      <button className="secondary-button" type="button" onClick={unpair}>取消配对</button>
    </main>;
  }

  return <main className="plugin-frame" aria-labelledby="plugin-frame-title">
    <p className="eyebrow">Figma 转 FairyGUI</p><h1 id="plugin-frame-title">连接 Figma 插件</h1>
    <p className="plugin-copy">在 Web Console 中获取六位配对码，然后回到这里完成连接。</p>
    <form className="plugin-pairing-form" onSubmit={submit}>
      <label htmlFor="pairing-code">配对码</label>
      <input ref={inputRef} id="pairing-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(event) => setCode(event.target.value)} disabled={state === "loading"} aria-describedby={error ? "pairing-error" : undefined} />
      {error && <p id="pairing-error" className="message message-error" role="alert">{error}</p>}
      <button className="primary-button" type="submit" disabled={state === "loading"}>{state === "loading" ? "正在配对…" : state === "error" ? "重试配对" : "完成配对"}</button>
    </form>
  </main>;
}
