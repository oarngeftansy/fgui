import { beforeEach, describe, expect, it, vi } from "vitest";
import { cacheSelectionView, readCachedSelectionView } from "./selectionCache";

const selection = { version: 1 as const, selection_id: "a".repeat(32), display_name: "Checkout", top_level_summaries: [{ name: "Checkout", type: "FRAME" }], preview_urls: [], warnings: [] };

describe("selection popup recovery cache", () => {
  beforeEach(() => localStorage.clear());

  it("stores and loads only the safe committed selection view", () => {
    cacheSelectionView(selection, 1_000);

    const stored = localStorage.getItem(`figma-selection-view:${selection.selection_id}`) ?? "";
    expect(readCachedSelectionView(selection.selection_id)).toEqual(selection);
    expect(stored).not.toMatch(/credential|resource|bytes|path/i);
  });

  it("never throws when browser storage rejects recovery caching", () => {
    const blocked = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("quota", "QuotaExceededError"); });
    expect(() => cacheSelectionView(selection)).not.toThrow();
    blocked.mockRestore();
  });

  it("removes malformed or expired cached values", () => {
    localStorage.setItem(`figma-selection-view:${selection.selection_id}`, "not-json");
    expect(readCachedSelectionView(selection.selection_id)).toBeNull();
    expect(localStorage.getItem(`figma-selection-view:${selection.selection_id}`)).toBeNull();
    localStorage.setItem(`figma-selection-view:${selection.selection_id}`, JSON.stringify({ view: selection, expires_at: 0 }));
    expect(readCachedSelectionView(selection.selection_id)).toBeNull();
    expect(localStorage.getItem(`figma-selection-view:${selection.selection_id}`)).toBeNull();
    localStorage.setItem(`figma-selection-view:${selection.selection_id}`, JSON.stringify({ view: { ...selection, credential: "secret" }, expires_at: Date.now() + 1_000 }));
    expect(readCachedSelectionView(selection.selection_id)).toBeNull();
    expect(localStorage.getItem(`figma-selection-view:${selection.selection_id}`)).toBeNull();
  });
});
