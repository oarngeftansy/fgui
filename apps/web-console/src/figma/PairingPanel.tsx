import { useCallback, useEffect, useState } from "react";
import {
  cancelConsolePairing,
  createConsolePairing,
  getConsolePairingStatus,
  getCurrentConsoleSelection,
  listFigmaDevices,
  revokeFigmaDevice,
  safeFigmaConsoleMessage,
  type ConsolePairing,
  type ConsolePairingStatus,
  type FigmaDevice,
  type FigmaSelectionView,
} from "../api";

type PairingPanelProps = {
  onSelection: (selection: FigmaSelectionView, session: string) => void;
  createPairing?: () => Promise<ConsolePairing>;
  getStatus?: (session: string) => Promise<ConsolePairingStatus>;
  getSelection?: (session: string) => Promise<FigmaSelectionView | null>;
  listDevices?: () => Promise<FigmaDevice[]>;
  revokeDevice?: (deviceId: string) => Promise<FigmaDevice>;
  cancelPairing?: (session: string) => Promise<null>;
};

function secondsUntil(expiresAt: string, now: number): string {
  const seconds = Math.max(0, Math.ceil((new Date(expiresAt).getTime() - now) / 1_000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function PairingPanel({
  onSelection,
  createPairing = createConsolePairing,
  getStatus = getConsolePairingStatus,
  getSelection = getCurrentConsoleSelection,
  listDevices = listFigmaDevices,
  revokeDevice = revokeFigmaDevice,
  cancelPairing = cancelConsolePairing,
}: PairingPanelProps) {
  const [pairing, setPairing] = useState<ConsolePairing | null>(null);
  const [devices, setDevices] = useState<FigmaDevice[]>([]);
  const [status, setStatus] = useState<ConsolePairingStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());

  const refreshDevices = useCallback(async () => {
    try {
      setDevices(await listDevices());
    } catch {
      setError("无法加载已配对设备，请稍后重试");
    }
  }, [listDevices]);

  const begin = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const next = await createPairing();
      setPairing(next);
      setStatus({ version: 1, state: "waiting_for_device", expires_at: next.expires_at });
      void refreshDevices();
    } catch (reason) {
      setError(safeFigmaConsoleMessage(reason));
    } finally {
      setBusy(false);
    }
  }, [createPairing, refreshDevices]);

  useEffect(() => { void begin(); }, [begin]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!pairing || error) return;
    let active = true;
    let poll: number | undefined;
    const check = async () => {
      if (status?.state !== "paired" && Date.now() >= new Date(pairing.expires_at).getTime()) {
        setError("配对码已过期，请重新生成");
        return;
      }
      try {
        const nextStatus = await getStatus(pairing.console_credential);
        if (!active) return;
        setStatus(nextStatus);
        if (nextStatus.state === "paired") {
          const selection = await getSelection(pairing.console_credential);
          if (!active) return;
          if (selection) {
            onSelection(selection, pairing.console_credential);
            return;
          }
        }
        poll = window.setTimeout(() => void check(), 2_000);
      } catch (reason) {
        if (active) setError(safeFigmaConsoleMessage(reason));
      }
    };
    void check();
    return () => {
      active = false;
      if (poll) window.clearTimeout(poll);
    };
  }, [pairing, status?.state, error, getSelection, getStatus, onSelection]);

  const regenerate = async () => {
    if (!pairing || busy) return;
    setBusy(true);
    try {
      await cancelPairing(pairing.console_credential);
      setPairing(null);
      await begin();
    } catch (reason) {
      setError(safeFigmaConsoleMessage(reason));
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!pairing || busy) return;
    setBusy(true);
    try {
      await cancelPairing(pairing.console_credential);
      setPairing(null);
      setStatus(null);
    } catch (reason) {
      setError(safeFigmaConsoleMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (deviceId: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await revokeDevice(deviceId);
      await refreshDevices();
    } catch (reason) {
      setError(safeFigmaConsoleMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return <section className="workflow-panel pairing-panel" aria-labelledby="pairing-title">
    <p className="eyebrow">步骤 1 / 5</p><h2 id="pairing-title">连接 Figma 插件</h2>
    <p className="intro">在 Figma 插件中输入此一次性配对码。配对完成后，请发送当前选择。</p>
    {pairing ? <>
      <output className="pairing-code" aria-label="六位配对码">{pairing.code}</output>
      <p className="pairing-expiry" aria-live="polite">配对码剩余 {secondsUntil(pairing.expires_at, now)}</p>
      <p role="status" aria-live="polite">{status?.state === "paired" ? "已连接 Figma，正在等待选择" : "等待 Figma 插件完成配对"}</p>
      <div className="button-row"><button className="secondary-button" type="button" disabled={busy} onClick={() => void regenerate()}>重新生成配对码</button><button className="advanced-button" type="button" disabled={busy} onClick={() => void cancel()}>取消配对</button></div>
    </> : <p className="message">尚未创建配对码</p>}
    {error && <p className="message message-error" role="alert">{error}</p>}
    <section className="device-list" aria-labelledby="devices-title"><h3 id="devices-title">已配对设备</h3>
      {devices.length ? <ul>{devices.map((device) => <li key={device.device_id}><span>{device.device_name}</span><button className="secondary-button" type="button" disabled={busy} onClick={() => void revoke(device.device_id)} aria-label={`撤销 ${device.device_name}`}>撤销</button></li>)}</ul> : <p>尚无已配对设备。</p>}
    </section>
  </section>;
}
