import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UploadApiError, createConsolePairing, createSelectionProjectJob, getConsolePairingStatus, uploadProject } from "./api";

class MockXmlHttpRequest {
  static response: unknown = null;
  static status = 201;
  static instance: MockXmlHttpRequest | undefined;

  body: Document | XMLHttpRequestBodyInit | null = null;
  method = "";
  response: unknown = null;
  status = 0;
  upload = { onprogress: null as ((event: ProgressEvent) => void) | null };
  onerror: (() => void) | null = null;
  onload: (() => void) | null = null;
  url = "";

  constructor() {
    MockXmlHttpRequest.instance = this;
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  send(body: Document | XMLHttpRequestBodyInit | null) {
    this.body = body;
    this.upload.onprogress?.({ lengthComputable: true, loaded: 3, total: 4 } as ProgressEvent);
    this.status = MockXmlHttpRequest.status;
    this.response = MockXmlHttpRequest.response;
    this.onload?.();
  }
}

describe("uploadProject", () => {
  beforeEach(() => {
    vi.stubGlobal("XMLHttpRequest", MockXmlHttpRequest);
    MockXmlHttpRequest.status = 201;
    MockXmlHttpRequest.response = {
      version: 1,
      project_id: "internal-id",
      display_name: "GameUI.zip",
      packages: [],
    };
  });

  afterEach(() => vi.unstubAllGlobals());

  it("posts the ZIP as the project field and reports computable progress", async () => {
    const progress = vi.fn();
    const file = new File(["zip"], "GameUI.zip", { type: "application/zip" });

    await uploadProject(file, progress);

    const request = MockXmlHttpRequest.instance!;
    expect(request.method).toBe("POST");
    expect(request.url).toBe("/v1/projects/uploads");
    expect((request.body as FormData).get("project")).toBe(file);
    expect(progress).toHaveBeenCalledWith(75);
  });

  it("uses local safe copy for a known upload error", async () => {
    MockXmlHttpRequest.status = 400;
    MockXmlHttpRequest.response = {
      detail: { code: "unsafe_archive", message: "C:\\Users\\designer\\GameUI\\package.xml" },
    };

    await expect(uploadProject(new File(["zip"], "GameUI.zip"), vi.fn())).rejects.toEqual(
      new UploadApiError("无法安全读取这个压缩包"),
    );
  });

  it("does not expose an unknown server detail", async () => {
    MockXmlHttpRequest.status = 400;
    MockXmlHttpRequest.response = {
      detail: { code: "unexpected", message: "C:\\private\\project.xml" },
    };

    await expect(uploadProject(new File(["zip"], "GameUI.zip"), vi.fn())).rejects.toEqual(
      new UploadApiError("上传未完成，请稍后重试"),
    );
  });
});

describe("live Figma console API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses the short-lived console session for pairing status and selection-backed jobs", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ version: 1, code: "123456", expires_at: "2026-07-29T10:00:00Z", console_credential: "browser-only" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ version: 1, state: "paired", device: { version: 1, device_id: "device-internal", device_name: "Figma desktop", created_at: "2026-07-29T09:00:00Z" } })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ version: 1, job_id: "review-1", project_id: "project-internal", status: "ready_for_review" })));
    vi.stubGlobal("fetch", fetch);

    const pairing = await createConsolePairing();
    await getConsolePairingStatus(pairing.console_credential);
    await createSelectionProjectJob(pairing.console_credential, "selection-internal", "project-internal", "Sample");

    expect(fetch.mock.calls[1][1].headers).toEqual({ "X-Figma-Console-Session": "browser-only" });
    expect(fetch.mock.calls[2]).toEqual([
      "/v1/figma/selections/selection-internal/projects/project-internal/jobs",
      expect.objectContaining({
        headers: { "Content-Type": "application/json", "X-Figma-Console-Session": "browser-only" },
        body: JSON.stringify({ version: 1, selection_id: "selection-internal", project_id: "project-internal", package_name: "Sample" }),
      }),
    ]);
    expect(String(fetch.mock.calls[2][1].body)).not.toContain("fixture_name");
  });

  it("maps raw console errors to local safe copy", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { message: "C:\\private\\selection" } }), { status: 401 })));
    await expect(getConsolePairingStatus("browser-only")).rejects.toThrow("配对会话已失效");
  });
});
