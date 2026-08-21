import type { ExportedResource } from "./assets";
import type { SelectionManifest, SelectionPreflight } from "./selection";

export const MAX_SEMANTIC_SCREENSHOT_BYTES = 1000 * 1024;

export type MainToUiMessage =
  | { type: "selection-preflight"; preflight: SelectionPreflight }
  | { type: "selection-changed"; preflight: SelectionPreflight; locateAttempt?: string }
  | { type: "selection-export"; attempt: string; manifest: SelectionManifest; resources: ExportedResource[] }
  | { type: "semantic-screenshot-export"; attempt: string; mimeType: "image/png"; bytes: Uint8Array }
  | { type: "selection-error"; attempt: string; code: string };

export type UiToMainMessage =
  | { type: "selection-preflight" }
  | { type: "selection-export"; attempt: string }
  | { type: "semantic-screenshot-export"; attempt: string }
  | { type: "locate-node"; nodeId: string; attempt: string };

export function isUiToMainMessage(value: unknown): value is UiToMainMessage {
  if (!value || typeof value !== "object") return false;
  const message = value as { type?: unknown; attempt?: unknown; nodeId?: unknown };
  return message.type === "selection-preflight" || (
    (message.type === "selection-export" || message.type === "semantic-screenshot-export")
    && typeof message.attempt === "string"
    && message.attempt.length > 0
  ) || (message.type === "locate-node" && typeof message.nodeId === "string" && message.nodeId.length > 0 && message.nodeId.length <= 256 && typeof message.attempt === "string" && message.attempt.length > 0 && message.attempt.length <= 128);
}
