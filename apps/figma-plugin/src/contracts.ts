import type { ExportedResource } from "./assets";
import type { SelectionManifest, SelectionPreflight } from "./selection";

export type PluginConfig = Readonly<{
  serverOrigin: string;
  pluginId: string;
}>;

export type MainToUiMessage =
  | { type: "credential"; credential: string }
  | { type: "pairing-status"; status: "paired" | "unpaired" | "revoked" }
  | { type: "pairing-error"; code: string }
  | { type: "selection-preflight"; preflight: SelectionPreflight }
  | { type: "selection-export"; attempt: string; manifest: SelectionManifest; resources: ExportedResource[] }
  | { type: "selection-error"; attempt: string; code: string };

export type UiToMainMessage =
  | { type: "pairing-credential"; credential: string }
  | { type: "unpair" }
  | { type: "selection-preflight" }
  | { type: "selection-export"; attempt: string };

export function isUiToMainMessage(value: unknown): value is UiToMainMessage {
  if (!value || typeof value !== "object") return false;
  const message = value as { type?: unknown; credential?: unknown; attempt?: unknown };
  return message.type === "unpair" || message.type === "selection-preflight" || (message.type === "selection-export" && typeof message.attempt === "string") || (message.type === "pairing-credential" && typeof message.credential === "string");
}
