import { describe, expect, it, vi } from "vitest";
import { SelectionUploader } from "./upload";

const manifest = {
  version: 1 as const,
  display_name: "Checkout",
  top_level_nodes: [{ id: "node-1", name: "Checkout", type: "FRAME", bounds: { x: 0, y: 0, width: 1, height: 1 }, children: [], resource_keys: ["asset-1"] }],
  resources: [{ key: "asset-1", mime_type: "image/png" as const, size: 0 }],
  warnings: [],
};

describe("selection upload transaction", () => {
  it("uses the existing idempotent session route order, 64 KiB request bodies, and safe errors", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ version: 1, upload_id: "upload" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ version: 1, state: "manifest_received" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ version: 1, state: "resources_pending" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ version: 1, selection_id: "a".repeat(32), display_name: "Checkout", top_level_summaries: [], preview_urls: [], warnings: [] })));
    const uploader = new SelectionUploader({ credential: "bearer-secret", fetchImpl });
    const progress = vi.fn();

    const result = await uploader.send(manifest, [{ key: "asset-1", mime_type: "image/png", bytes: new Uint8Array(65 * 1024) }], "idempotency-key", progress);

    expect(result.selection_id).toBe("a".repeat(32));
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      "/v1/figma/selections/uploads",
      "/v1/figma/selections/uploads/upload/manifest",
      "/v1/figma/selections/uploads/upload/resources/asset-1",
      "/v1/figma/selections/uploads/upload/commit",
    ]);
    expect(fetchImpl.mock.calls[0]?.[1]).toMatchObject({ headers: { Authorization: "Bearer bearer-secret" } });
    expect(fetchImpl.mock.calls[2]?.[1]?.body).toBeInstanceOf(Uint8Array);
    expect(progress).toHaveBeenLastCalledWith({ completed: 1, total: 1 });
    expect(JSON.stringify(fetchImpl.mock.calls)).not.toContain("raw:");
  });

  it("never exposes server detail, bearer credentials, or opaque IDs in its error", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { code: "selection_too_large", message: "bearer-secret raw:node" } }), { status: 400 }));
    const uploader = new SelectionUploader({ credential: "bearer-secret", fetchImpl });

    await expect(uploader.send(manifest, [], "idempotency-key")).rejects.toThrow("选择内容过大");
    await expect(uploader.send(manifest, [], "idempotency-key")).rejects.not.toThrow(/bearer-secret|raw:node/);
  });

  it("retries only create and never repeats a failed manifest PUT", async () => {
    const fetchImpl = vi.fn()
      .mockRejectedValueOnce(new Error("lost create response"))
      .mockResolvedValueOnce(new Response(JSON.stringify({ version: 1, upload_id: "upload" }), { status: 201 }))
      .mockRejectedValueOnce(new Error("lost manifest response"));
    const uploader = new SelectionUploader({ credential: "secret", fetchImpl });
    await expect(uploader.send(manifest, [{ key: "asset-1", mime_type: "image/png", bytes: new Uint8Array([1]) }], "stable-key")).rejects.toThrow();
    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      "/v1/figma/selections/uploads", "/v1/figma/selections/uploads", "/v1/figma/selections/uploads/upload/manifest",
    ]);
  });
});
