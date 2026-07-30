import { describe, expect, it, vi } from "vitest";
import { ProjectWorkflowClient, WorkflowError } from "./project-client";
import type { SelectionManifest } from "./selection";

const manifest: SelectionManifest = {
  version: 1,
  display_name: "Checkout",
  top_level_nodes: [{ id: "node-1", name: "Checkout", type: "FRAME", bounds: { x: 0, y: 0, width: 1, height: 1 }, children: [], resource_keys: ["asset-1"] }],
  resources: [{ key: "asset-1", mime_type: "image/png", size: 1 }],
  warnings: [],
};
const resources = [{ key: "asset-1", mime_type: "image/png" as const, bytes: new Uint8Array([1]) }];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const project = (name = "Quiz") => ({ version: 1, project_id: "project-1", display_name: name, packages: [{ name: "Quiz", resource_count: 1 }] });
const selection = { version: 1, selection_id: "a".repeat(32), display_name: "Checkout", top_level_summaries: [], preview_urls: [], warnings: [] };
const job = { version: 1, job_id: "job-1", project_id: "project-1", status: "ready_for_review" };
const packageView = (status: string, download_name: string | null = null) => ({ version: 1, job_id: "job-1", status, stage: status, progress: status === "ready" ? 100 : 90, download_name, sha256: status === "ready" ? "b".repeat(64) : null, diagnostics: [] });

function successfulFetch(mode: "create" | "update") {
  return vi.fn(async (url: string, init: RequestInit) => {
    const path = new URL(url).pathname;
    if (path === "/v1/projects/from-template") return json(project(), 201);
    if (path === "/v1/projects/uploads") return json(project("GameUI.zip"), 201);
    if (path === "/v1/figma/selections/uploads") return json({ version: 1, upload_id: "upload-1" }, 201);
    if (path.endsWith("/manifest") || path.includes("/resources/")) return json({ version: 1, state: "received" });
    if (path.endsWith("/commit")) return json(selection);
    if (path.endsWith("/jobs")) return json(job);
    if (path.endsWith("/package") && init.method === "POST") return json(packageView("checking"), 202);
    if (path.endsWith("/package")) return json(packageView("ready", `${mode === "create" ? "Quiz-Figma新建" : "GameUI-Figma更新"}-20260730-1530.zip`));
    if (path.endsWith("/download")) return new Response(new Blob(["zip"]), { headers: { "Content-Type": "application/zip", "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(mode === "create" ? "Quiz-Figma新建-20260730-1530.zip" : "GameUI-Figma更新-20260730-1530.zip")}` } });
    throw new Error(`unexpected ${init.method} ${path}`);
  });
}

describe("ProjectWorkflowClient", () => {
  it("runs create mode without uploading a ZIP and authenticates absolute requests", async () => {
    const fetchImpl = successfulFetch("create");
    const stages = vi.fn();
    const client = new ProjectWorkflowClient({ serverOrigin: "https://fgui.test/some/path", pluginToken: "plugin-token", fetchImpl, wait: async () => {} });

    const result = await client.runCreate(manifest, resources, { projectName: "Quiz", templateId: "fgui-2024-web" }, stages);

    const calls = fetchImpl.mock.calls as unknown as Array<[string, RequestInit]>;
    expect(calls.map(([url]) => new URL(url).pathname)).not.toContain("/v1/projects/uploads");
    expect(calls.every(([url, init]) => url.startsWith("https://fgui.test/") && new Headers(init.headers).get("X-Figma-Plugin-Token") === "plugin-token")).toBe(true);
    expect(JSON.parse(String(calls.find(([url]) => new URL(url).pathname === "/v1/projects/from-template")?.[1].body))).toEqual({ version: 1, template_id: "fgui-2024-web", project_name: "Quiz" });
    expect(JSON.parse(String(calls.find(([url]) => new URL(url).pathname.endsWith("/jobs"))?.[1].body))).toEqual({ version: 1, selection_id: "a".repeat(32), project_id: "project-1", package_name: "Quiz" });
    expect(JSON.parse(String(calls.find(([url, init]) => new URL(url).pathname.endsWith("/package") && init.method === "POST")?.[1].body))).toEqual({ version: 1, mode: "create", project_name: "Quiz" });
    expect(new Headers(calls.find(([url]) => new URL(url).pathname.endsWith("/manifest"))?.[1].headers).get("Content-Type")).toBe("application/json");
    expect(new Headers(calls.find(([url]) => new URL(url).pathname.includes("/resources/"))?.[1].headers).get("Content-Type")).toBe("image/png");
    expect(result.downloadName).toBe("Quiz-Figma新建-20260730-1530.zip");
    expect(result.blob).toBeInstanceOf(Blob);
    expect(stages).toHaveBeenCalledWith(expect.objectContaining({ stage: "ready", progress: 100 }));
  });

  it("runs update mode with the original ZIP in FormData", async () => {
    const fetchImpl = successfulFetch("update");
    const client = new ProjectWorkflowClient({ serverOrigin: "https://fgui.test", pluginToken: "plugin-token", fetchImpl, wait: async () => {} });
    const archive = new File(["project"], "My Game.zip", { type: "application/zip" });

    const result = await client.runUpdate(manifest, resources, archive);

    const calls = fetchImpl.mock.calls as unknown as Array<[string, RequestInit]>;
    const upload = calls.find(([url]) => new URL(url).pathname === "/v1/projects/uploads")!;
    expect(upload[1].body).toBeInstanceOf(FormData);
    expect((upload[1].body as FormData).get("project")).toBe(archive);
    expect(new Headers(upload[1].headers).has("Content-Type")).toBe(false);
    expect(calls.map(([url]) => new URL(url).pathname)).not.toContain("/v1/projects/from-template");
    expect(JSON.parse(String(calls.find(([url, init]) => new URL(url).pathname.endsWith("/package") && init.method === "POST")?.[1].body)).project_name).toBe("My-Game");
    expect(result.downloadName).toBe("GameUI-Figma更新-20260730-1530.zip");
  });

  it("loads and validates configured template options", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(json({ version: 1, options: [{ template_id: "fgui-2024-web", fairygui_version: "2024.2", target_platform: "web", display_name: "Web" }] }));
    const client = new ProjectWorkflowClient({ serverOrigin: "https://fgui.test", pluginToken: "token", fetchImpl });
    await expect(client.options()).resolves.toEqual([{ templateId: "fgui-2024-web", fairyguiVersion: "2024.2", targetPlatform: "web", displayName: "Web" }]);
    expect(fetchImpl).toHaveBeenCalledWith("https://fgui.test/v1/figma/project-options", expect.objectContaining({ method: "GET" }));
  });

  it("times out package polling and can abort an injected wait", async () => {
    const fetchImpl = vi.fn(async () => json(packageView("packaging")));
    const client = new ProjectWorkflowClient({ serverOrigin: "https://fgui.test", pluginToken: "token", fetchImpl, wait: async () => {} });
    await expect(client.waitForPackage("job-1", { timeoutMs: 0 })).rejects.toMatchObject({ code: "timeout" });

    const controller = new AbortController();
    const waiting = new ProjectWorkflowClient({
      serverOrigin: "https://fgui.test",
      pluginToken: "token",
      fetchImpl,
      wait: (_ms, signal) => new Promise((_resolve, reject) => signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true })),
    }).waitForPackage("job-1", { signal: controller.signal });
    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalled());
    controller.abort();
    await expect(waiting).rejects.toMatchObject({ code: "aborted" });
  });

  it("retries safe reads once but never repeats project or ZIP creation", async () => {
    const optionsFetch = vi.fn().mockRejectedValueOnce(new TypeError("offline")).mockResolvedValueOnce(json({ version: 1, options: [] }));
    await new ProjectWorkflowClient({ serverOrigin: "https://fgui.test", pluginToken: "token", fetchImpl: optionsFetch }).options();
    expect(optionsFetch).toHaveBeenCalledTimes(2);

    const createFetch = vi.fn().mockRejectedValue(new TypeError("offline"));
    const client = new ProjectWorkflowClient({ serverOrigin: "https://fgui.test", pluginToken: "token", fetchImpl: createFetch });
    await expect(client.createProject({ projectName: "Quiz", templateId: "fgui-2024-web" })).rejects.toMatchObject({ code: "network" });
    await expect(client.uploadProject(new File(["zip"], "Quiz.zip", { type: "application/zip" }))).rejects.toMatchObject({ code: "network" });
    expect(createFetch).toHaveBeenCalledTimes(2);
  });

  it.each([
    [401, "anything", "unauthorized"],
    [400, "invalid_archive", "invalid_zip"],
    [404, "template_not_found", "unknown_template"],
    [409, "package_request_conflict", "conversion_conflict"],
  ])("maps HTTP %i/%s to a safe distinct error", async (status, serverCode, expectedCode) => {
    const fetchImpl = vi.fn().mockResolvedValue(json({ detail: { code: serverCode, message: "C:\\secret\\raw:node plugin-token" } }, status));
    const client = new ProjectWorkflowClient({ serverOrigin: "https://fgui.test", pluginToken: "plugin-token", fetchImpl });
    const call = status === 404 ? client.createProject({ projectName: "Quiz", templateId: "missing" }) : status === 400 ? client.uploadProject(new File(["bad"], "bad.zip", { type: "application/zip" })) : client.buildPackage("job-1", "update", "Quiz");
    const error = await call.catch((reason: unknown) => reason) as WorkflowError;
    expect(error.code).toBe(expectedCode);
    expect(error.message).not.toMatch(/secret|raw:node|plugin-token/);
  });

  it("rejects malformed JSON, failed conversion and failed packages distinctly", async () => {
    const malformed = new ProjectWorkflowClient({ serverOrigin: "https://fgui.test", pluginToken: "token", fetchImpl: vi.fn().mockResolvedValue(json({ version: 1, options: "wrong" })) });
    await expect(malformed.options()).rejects.toMatchObject({ code: "invalid_response" });

    const conversion = new ProjectWorkflowClient({ serverOrigin: "https://fgui.test", pluginToken: "token", fetchImpl: vi.fn().mockResolvedValue(json({ ...job, status: "conversion_failed" })) });
    await expect(conversion.createJob(selection.selection_id, { projectId: "project-1", displayName: "Quiz", packages: [{ name: "Quiz", resourceCount: 1 }] }, "Quiz")).rejects.toMatchObject({ code: "conversion_failed" });

    const packaging = new ProjectWorkflowClient({ serverOrigin: "https://fgui.test", pluginToken: "token", fetchImpl: vi.fn().mockResolvedValue(json(packageView("failed"))) });
    await expect(packaging.waitForPackage("job-1")).rejects.toMatchObject({ code: "package_failed" });
  });

  it("uses a fallback filename for hostile Content-Disposition and forwards abort to download", async () => {
    const fetchImpl = vi.fn(async (_url: string, init: RequestInit) => {
      if (init.signal?.aborted) throw new DOMException("Aborted", "AbortError");
      return new Response(new Blob(["zip"]), { headers: { "Content-Disposition": "attachment; filename=../../secret.exe" } });
    });
    const client = new ProjectWorkflowClient({ serverOrigin: "https://fgui.test", pluginToken: "token", fetchImpl });
    await expect(client.downloadPackage("job-1")).resolves.toMatchObject({ downloadName: "FairyGUI-project.zip" });
    const controller = new AbortController();
    const blobStarted = vi.fn();
    const bodyResponse = new Response();
    Object.defineProperty(bodyResponse, "blob", { value: () => new Promise<Blob>((_resolve, reject) => {
      blobStarted();
      controller.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }) });
    const downloading = new ProjectWorkflowClient({ serverOrigin: "https://fgui.test", pluginToken: "token", fetchImpl: vi.fn().mockResolvedValue(bodyResponse) }).downloadPackage("job-1", controller.signal);
    await vi.waitFor(() => expect(blobStarted).toHaveBeenCalled());
    controller.abort();
    await expect(downloading).rejects.toMatchObject({ code: "aborted" });
  });

  it("forwards abort through project upload and package polling requests", async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn((_url: string, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
      expect(init.signal).toBe(controller.signal);
      init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }));
    const client = new ProjectWorkflowClient({ serverOrigin: "https://fgui.test", pluginToken: "token", fetchImpl });
    const uploading = client.uploadProject(new File(["zip"], "Quiz.zip", { type: "application/zip" }), controller.signal);
    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalled());
    controller.abort();
    await expect(uploading).rejects.toMatchObject({ code: "aborted" });
    const pollingController = new AbortController();
    const pollFetch = vi.fn((_url: string, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
      expect(init.signal).toBe(pollingController.signal);
      init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }));
    const polling = new ProjectWorkflowClient({ serverOrigin: "https://fgui.test", pluginToken: "token", fetchImpl: pollFetch }).waitForPackage("job-1", { signal: pollingController.signal });
    await vi.waitFor(() => expect(pollFetch).toHaveBeenCalled());
    pollingController.abort();
    await expect(polling).rejects.toMatchObject({ code: "aborted" });
  });
});
