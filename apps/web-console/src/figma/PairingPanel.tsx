import { useCallback, useEffect, useRef, useState } from "react";
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
  listDevices?: (session: string) => Promise<FigmaDevice[]>;
  revokeDevice?: (session: string, deviceId: string) => Promise<FigmaDevice>;
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
  const generation = useRef(0);
  const session = useRef("");

  const invalidatePairing = useCallback(() => {
    generation.current += 1;
    session.current = "";
    setPairing(null);
    setDevices([]);
    setStatus(null);
    setError("");
  }, []);

  const refreshDevices = useCallback(async (credential: string, expectedGeneration: number) => {
    try {
      const nextDevices = await listDevices(credential);
      if (generation.current === expectedGeneration && session.current === credential) setDevices(nextDevices);
    } catch {
      if (generation.current !== expectedGeneration || session.current !== credential) return;
      setError("无法加载已配对设备，请稍后重试");
    }
  }, [listDevices]);

  const begin = useCallback(async () => {
    invalidatePairing();
    const expectedGeneration = generation.current;
    setBusy(true);
    try {
      const next = await createPairing();
      if (generation.current !== expectedGeneration) return;
      session.current = next.console_credential;
      setPairing(next);
      setStatus({ version: 1, state: "waiting_for_device", expires_at: next.expires_at });
      void refreshDevices(next.console_credential, expectedGeneration);
    } catch (reason) {
      if (generation.current !== expectedGeneration) return;
      setError(safeFigmaConsoleMessage(reason));
    } finally {
      if (generation.current === expectedGeneration) setBusy(false);
    }
  }, [createPairing, invalidatePairing, refreshDevices]);

  useEffect(() => { void begin(); }, [begin]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!pairing || error) return;
    let active = true;
    let poll: number | undefined;
    const expectedGeneration = generation.current;
    const credential = pairing.console_credential;
    const isCurrent = () => active && generation.current === expectedGeneration && session.current === credential;
    const check = async () => {
      if (status?.state !== "paired" && Date.now() >= new Date(pairing.expires_at).getTime()) {
        if (!isCurrent()) return;
        setError("配对码已过期，请重新生成");
        return;
      }
      try {
        const nextStatus = await getStatus(credential);
        if (!isCurrent()) return;
        setStatus(nextStatus);
        if (nextStatus.state === "paired") {
          void refreshDevices(credential, expectedGeneration);
          const selection = await getSelection(credential);
          if (!isCurrent()) return;
          if (selection) {
            onSelection(selection, credential);
            return;
          }
        }
        if (isCurrent()) poll = window.setTimeout(() => void check(), 2_000);
      } catch (reason) {
        if (isCurrent()) setError(safeFigmaConsoleMessage(reason));
      }
    };
    void check();
    return () => {
      active = false;
      if (poll) window.clearTimeout(poll);
    };
  }, [pairing, status?.state, error, getSelection, getStatus, onSelection, refreshDevices]);

  const regenerate = async () => {
    if (!pairing || busy) return;
    const expectedGeneration = generation.current;
    const credential = pairing.console_credential;
    setBusy(true);
    try {
      await cancelPairing(credential);
      if (generation.current !== expectedGeneration || session.current !== credential) return;
      invalidatePairing();
      await begin();
    } catch (reason) {
      if (generation.current !== expectedGeneration || session.current !== credential) return;
      setError(safeFigmaConsoleMessage(reason));
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!pairing || busy) return;
    const expectedGeneration = generation.current;
    const credential = pairing.console_credential;
    setBusy(true);
    try {
      await cancelPairing(credential);
      if (generation.current !== expectedGeneration || session.current !== credential) return;
      invalidatePairing();
      setBusy(false);
    } catch (reason) {
      if (generation.current !== expectedGeneration || session.current !== credential) return;
      setError(safeFigmaConsoleMessage(reason));
    } finally {
      if (generation.current === expectedGeneration && session.current === credential) setBusy(false);
    }
  };

  const revoke = async (deviceId: string) => {
    if (!pairing || busy) return;
    const expectedGeneration = generation.current;
    const credential = pairing.console_credential;
    setBusy(true);
    try {
      await revokeDevice(credential, deviceId);
      if (generation.current !== expectedGeneration || session.current !== credential) return;
      invalidatePairing();
      setBusy(false);
    } catch (reason) {
      if (generation.current !== expectedGeneration || session.current !== credential) return;
      setError(safeFigmaConsoleMessage(reason));
    } finally {
      if (generation.current === expectedGeneration && session.current === credential) setBusy(false);
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
    </> : <><p className="message">尚未创建配对码</p><button className="primary-button" type="button" disabled={busy} onClick={() => void begin()}>开始配对</button></>}
    {error && <p className="message message-error" role="alert">{error}</p>}
    <section className="device-list" aria-labelledby="devices-title"><h3 id="devices-title">已配对设备</h3>
      {devices.length ? <ul>{devices.map((device) => <li key={device.device_id}><span>{device.device_name}</span><button className="secondary-button" type="button" disabled={busy} onClick={() => void revoke(device.device_id)} aria-label={`撤销 ${device.device_name}`}>撤销</button></li>)}</ul> : <p>尚无已配对设备。</p>}
    </section>
  </section>;
}
