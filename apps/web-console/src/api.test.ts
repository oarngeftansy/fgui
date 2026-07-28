import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UploadApiError, uploadProject } from "./api";

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

  it("uses the server's structured designer message for a known upload error", async () => {
    MockXmlHttpRequest.status = 400;
    MockXmlHttpRequest.response = {
      detail: { code: "unsafe_archive", message: "无法安全读取这个压缩包，请重新导出后再试" },
    };

    await expect(uploadProject(new File(["zip"], "GameUI.zip"), vi.fn())).rejects.toEqual(
      new UploadApiError("无法安全读取这个压缩包，请重新导出后再试"),
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
