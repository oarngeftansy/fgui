import type { MainToUiMessage, PluginConfig, UiToMainMessage } from "./contracts";

const CREDENTIAL_KEY = "figma-to-fairygui-plugin-credential";

type ClientStorage = {
  getAsync(key: string): Promise<unknown>;
  setAsync(key: string, value: string): Promise<void>;
  deleteAsync(key: string): Promise<void>;
};

type PairingResponse = {
  ok: boolean;
  json(): Promise<unknown>;
};

type PairingFetch = (url: string, init: RequestInit) => Promise<PairingResponse>;
type PostToHosted = (message: MainToUiMessage, targetOrigin: string) => void;

export class PairingValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PairingValidationError";
  }
}

export class PairingRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PairingRequestError";
  }
}

export function validatePairingCode(value: string): string {
  const code = value.trim();
  if (!/^\d{6}$/.test(code)) {
    throw new PairingValidationError("请输入六位数字配对码");
  }
  return code;
}

export function safePairingMessage(code: unknown): string {
  if (code === "pairing_code_expired") return "配对码已过期，请获取新的配对码";
  if (code === "pairing_rate_limited") return "尝试次数过多，请稍后再试";
  if (code === "plugin_credential_revoked") return "此插件配对已撤销，请重新配对";
  return "配对未完成，请检查配对码后重试";
}

export class PairingClient {
  constructor(private readonly fetchImpl: PairingFetch = fetch) {}

  async exchange(code: string, deviceName: string): Promise<{ credential: string; deviceId: string }> {
    const response = await this.fetchImpl("/v1/figma/pairings/exchange", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: 1, code: validatePairingCode(code), device_name: deviceName }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const code = payload && typeof payload === "object" ? (payload as { detail?: { code?: unknown } }).detail?.code : undefined;
      throw new PairingRequestError(safePairingMessage(code));
    }
    const result = payload as { version?: unknown; credential?: unknown; device?: { device_id?: unknown } };
    if (result.version !== 1 || typeof result.credential !== "string" || typeof result.device?.device_id !== "string") {
      throw new PairingRequestError(safePairingMessage(undefined));
    }
    return { credential: result.credential, deviceId: result.device.device_id };
  }
}

export class CredentialStore {
  constructor(private readonly storage: ClientStorage) {}

  async load(): Promise<string | null> {
    const value = await this.storage.getAsync(CREDENTIAL_KEY);
    return typeof value === "string" && value.length > 0 ? value : null;
  }

  save(credential: string): Promise<void> {
    return this.storage.setAsync(CREDENTIAL_KEY, credential);
  }

  clear(): Promise<void> {
    return this.storage.deleteAsync(CREDENTIAL_KEY);
  }
}

export function createMainPairingController(config: PluginConfig, store: CredentialStore, post: PostToHosted) {
  const send = (message: MainToUiMessage) => post(message, config.serverOrigin);
  return {
    async restore(): Promise<void> {
      const credential = await store.load();
      if (credential) {
        send({ type: "credential", credential });
      } else {
        send({ type: "pairing-status", status: "unpaired" });
      }
    },
    async handle(message: UiToMainMessage): Promise<void> {
      if (message.type === "pairing-credential") {
        await store.save(message.credential);
        send({ type: "pairing-status", status: "paired" });
        return;
      }
      await store.clear();
      send({ type: "pairing-status", status: "unpaired" });
    },
  };
}
