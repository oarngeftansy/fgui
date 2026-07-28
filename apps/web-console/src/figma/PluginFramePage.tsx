import { FormEvent, useEffect, useRef, useState } from "react";

type PluginMessage =
  | { type: "pairing-credential"; credential: string }
  | { type: "unpair" };

type PostToFigma = (message: { pluginId: string; pluginMessage: PluginMessage }, targetOrigin: string) => void;
type PairingStatus = "ready" | "loading" | "paired" | "revoked" | "error";

type PluginFramePageProps = {
  pluginId?: string;
  exchange?: (code: string, deviceName: string) => Promise<{ credential: string }>;
  postToFigma?: PostToFigma;
  status?: "revoked";
};

const FIGMA_ORIGIN = "https://www.figma.com";

function safeMessage(error: unknown): string {
  const code = error && typeof error === "object" ? (error as { detail?: { code?: unknown } }).detail?.code : undefined;
  if (code === "pairing_code_expired") return "配对码已过期，请获取新的配对码";
  if (code === "pairing_rate_limited") return "尝试次数过多，请稍后再试";
  if (code === "plugin_credential_revoked") return "此插件配对已撤销，请重新配对";
  return "配对未完成，请检查配对码后重试";
}

async function exchangePairing(code: string, deviceName: string): Promise<{ credential: string }> {
  const response = await fetch("/v1/figma/pairings/exchange", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ version: 1, code, device_name: deviceName }),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw payload;
  const credential = payload && typeof payload === "object" ? (payload as { credential?: unknown }).credential : undefined;
  if (typeof credential !== "string" || credential.length === 0) throw null;
  return { credential };
}

function configuredPluginId(value: string | undefined): string {
  const queryValue = new URLSearchParams(window.location.search).get("pluginId");
  const pluginId = value ?? queryValue;
  return pluginId && /^\d+$/.test(pluginId) ? pluginId : "";
}

export function PluginFramePage({ pluginId: explicitPluginId, exchange = exchangePairing, postToFigma, status }: PluginFramePageProps) {
  const pluginId = configuredPluginId(explicitPluginId);
  const [code, setCode] = useState("");
  const [state, setState] = useState<PairingStatus>(status ?? "ready");
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setState(status ?? "ready"), [status]);
  useEffect(() => {
    const receive = (event: MessageEvent<{ pluginMessage?: { type?: string; status?: string; code?: string } }>) => {
      if (event.origin !== FIGMA_ORIGIN) return;
      const message = event.data?.pluginMessage;
      if (message?.type === "pairing-status") setState(message.status === "paired" ? "paired" : "ready");
      if (message?.type === "pairing-error") {
        setError(safeMessage({ detail: { code: message.code } }));
        setState(message.code === "plugin_credential_revoked" ? "revoked" : "error");
      }
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, []);

  const post = postToFigma ?? ((message, targetOrigin) => window.parent.postMessage(message, targetOrigin));
  const unpair = () => {
    post({ pluginId, pluginMessage: { type: "unpair" } }, FIGMA_ORIGIN);
    setCode("");
    setError("");
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
      setState("paired");
    } catch (caught) {
      setError(safeMessage(caught));
      setState("error");
    }
  };

  if (state === "paired") {
    return (
      <main className="plugin-frame" aria-labelledby="plugin-frame-title">
        <p className="eyebrow">Figma 转 FairyGUI</p>
        <h1 id="plugin-frame-title">已完成配对</h1>
        <p className="plugin-copy" aria-live="polite">现在可以返回插件继续操作。</p>
        <button className="secondary-button" type="button" onClick={unpair}>
          取消配对
        </button>
      </main>
    );
  }

  if (state === "revoked") {
    return (
      <main className="plugin-frame" aria-labelledby="plugin-frame-title">
        <p className="eyebrow">Figma 转 FairyGUI</p>
        <h1 id="plugin-frame-title">连接 Figma 插件</h1>
        <p className="plugin-copy" role="alert">此插件配对已撤销，请重新配对</p>
        <button className="primary-button" type="button" onClick={() => setState("ready")}>重新配对</button>
      </main>
    );
  }

  return (
    <main className="plugin-frame" aria-labelledby="plugin-frame-title">
      <p className="eyebrow">Figma 转 FairyGUI</p>
      <h1 id="plugin-frame-title">连接 Figma 插件</h1>
      <p className="plugin-copy">在 Web Console 中获取六位配对码，然后回到这里完成连接。</p>
      <form className="plugin-pairing-form" onSubmit={submit}>
        <label htmlFor="pairing-code">配对码</label>
        <input
          ref={inputRef}
          id="pairing-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          onChange={(event) => setCode(event.target.value)}
          disabled={state === "loading"}
          aria-describedby={error ? "pairing-error" : undefined}
        />
        {error && <p id="pairing-error" className="message message-error" role="alert">{error}</p>}
        <button className="primary-button" type="submit" disabled={state === "loading"}>
          {state === "loading" ? "正在配对…" : state === "error" ? "重试配对" : "完成配对"}
        </button>
      </form>
    </main>
  );
}
