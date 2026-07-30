import type { FigmaSelectionView } from "../api";

const PREFIX = "figma-selection-view:";
const MAX_TTL = 15 * 60 * 1000;
const keyFor = (selectionId: string) => `${PREFIX}${selectionId}`;

function safeView(value: unknown, selectionId?: string): FigmaSelectionView | null {
  if (!value || typeof value !== "object") return null;
  const view = value as Record<string, unknown>;
  if (Object.keys(view).some((key) => !["version", "selection_id", "display_name", "top_level_summaries", "preview_urls", "warnings"].includes(key))) return null;
  if (view.version !== 1 || typeof view.selection_id !== "string" || !/^[0-9a-f]{32}$/.test(view.selection_id) || (selectionId && view.selection_id !== selectionId) || typeof view.display_name !== "string" || view.display_name.length > 500 || !Array.isArray(view.top_level_summaries) || !Array.isArray(view.preview_urls) || !Array.isArray(view.warnings)) return null;
  if (view.top_level_summaries.some((item) => !item || typeof item !== "object" || Object.keys(item).some((key) => key !== "name" && key !== "type") || typeof (item as { name?: unknown }).name !== "string" || typeof (item as { type?: unknown }).type !== "string") || view.preview_urls.some((url) => typeof url !== "string") || view.warnings.some((warning) => !warning || typeof warning !== "object" || Object.keys(warning).some((key) => key !== "code" && key !== "message") || typeof (warning as { code?: unknown }).code !== "string" || typeof (warning as { message?: unknown }).message !== "string")) return null;
  return view as unknown as FigmaSelectionView;
}

export function cacheSelectionView(view: FigmaSelectionView, ttl = MAX_TTL): void {
  const safe = safeView(view);
  if (!safe) return;
  try {
    localStorage.setItem(keyFor(safe.selection_id), JSON.stringify({ view: safe, expires_at: Date.now() + Math.min(MAX_TTL, Math.max(1, ttl)) }));
  } catch { /* recovery caching must never change a committed upload into a failure */ }
}

export function readCachedSelectionView(selectionId: string): FigmaSelectionView | null {
  const key = keyFor(selectionId);
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? "") as { view?: unknown; expires_at?: unknown };
    const safe = typeof value.expires_at === "number" && value.expires_at > Date.now() ? safeView(value.view, selectionId) : null;
    if (safe) return safe;
  } catch { /* malformed values use the same recovery path */ }
  try { localStorage.removeItem(key); } catch { /* disabled storage uses the missing-cache recovery path */ }
  return null;
}
