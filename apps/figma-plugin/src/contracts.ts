import type { ExportedResource } from "./assets";
import type { SelectionManifest, SelectionPreflight } from "./selection";

export type MainToUiMessage =
  | { type: "selection-preflight"; preflight: SelectionPreflight }
  | { type: "selection-changed"; preflight: SelectionPreflight }
  | { type: "selection-export"; attempt: string; manifest: SelectionManifest; resources: ExportedResource[] }
  | { type: "selection-error"; attempt: string; code: string };

export type UiToMainMessage =
  | { type: "selection-preflight" }
  | { type: "selection-export"; attempt: string };

export function isUiToMainMessage(value: unknown): value is UiToMainMessage {
  if (!value || typeof value !== "object") return false;
  const message = value as { type?: unknown; attempt?: unknown };
  return message.type === "selection-preflight" || (message.type === "selection-export" && typeof message.attempt === "string");
}
