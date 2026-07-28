export type PluginConfig = Readonly<{
  serverOrigin: string;
  pluginId: string;
}>;

export type MainToUiMessage =
  | { type: "credential"; credential: string }
  | { type: "pairing-status"; status: "paired" | "unpaired" | "revoked" }
  | { type: "pairing-error"; code: string };

export type UiToMainMessage =
  | { type: "pairing-credential"; credential: string }
  | { type: "unpair" };

export function isUiToMainMessage(value: unknown): value is UiToMainMessage {
  if (!value || typeof value !== "object") return false;
  const message = value as { type?: unknown; credential?: unknown };
  return message.type === "unpair" || (message.type === "pairing-credential" && typeof message.credential === "string");
}
