import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useNewProjectReviewPreviews } from "./useNewProjectReviewPreviews";

const candidate = { buildId: "a".repeat(32) };
const review = {
  imageReviews: [{ sourcePreviewUrl: "/source", generatedAssetUrl: "/generated" }],
  componentReviews: [{ renderedPreviewUrl: "/component" }],
};

afterEach(() => vi.unstubAllGlobals());

describe("useNewProjectReviewPreviews", () => {
  it("owns loaded blobs and releases every object URL on teardown", async () => {
    const revokeObjectURL = vi.fn();
    let nextUrl = 0;
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => `blob:${++nextUrl}`), revokeObjectURL });
    const blob = new Blob(["png"], { type: "image/png" });
    const client = { newProjectPreview: vi.fn().mockResolvedValue(blob) };

    const { result, unmount } = renderHook(() => useNewProjectReviewPreviews(client, candidate, review));
    await waitFor(() => expect(result.current.previewState).toBe("ready"));

    expect(client.newProjectPreview).toHaveBeenCalledTimes(3);
    expect(result.current.previewObjects).toEqual({ "/source": "blob:1", "/generated": "blob:2", "/component": "blob:3" });
    expect(result.current.previewBlobs["/generated"]).toBe(blob);

    unmount();
    expect(revokeObjectURL.mock.calls.flat()).toEqual(["blob:1", "blob:2", "blob:3"]);
  });

  it("fails closed when any required preview cannot load", async () => {
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:loaded"), revokeObjectURL: vi.fn() });
    const client = { newProjectPreview: vi.fn(async (_buildId: string, path: string) => {
      if (path === "/generated") throw new Error("missing");
      return new Blob(["png"], { type: "image/png" });
    }) };

    const { result } = renderHook(() => useNewProjectReviewPreviews(client, candidate, review));
    await waitFor(() => expect(result.current.previewState).toBe("failed"));

    expect(result.current.previewObjects).not.toHaveProperty("/generated");
  });
});
