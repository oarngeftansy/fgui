export type PackageSummary = {
  name: string;
  resource_count: number;
};

export type UploadedProject = {
  version: number;
  project_id: string;
  display_name: string;
  packages: PackageSummary[];
};

export type DesignerChange = {
  action: "新增" | "更新";
  label: string;
  thumbnail_available: boolean;
  before_image_url?: string | null;
  after_image_url?: string | null;
};

export type DesignerCheck = {
  status: "success" | "warning" | "error";
  message: string;
};

export type DesignerPreview = {
  summary: string;
  changes: DesignerChange[];
  checks: DesignerCheck[];
};

export type AdvancedDesignerPreview = {
  preview: DesignerPreview;
  details: {
    files: Array<{
      operation: string;
      relative_path: string;
      before_sha256: string | null;
      after_sha256: string;
      before_xml: string | null;
      after_xml: string | null;
    }>;
    diagnostics: unknown[];
  };
};

export type JobStatus = "created" | "ready_for_review" | "conversion_failed" | "approved" | "applying" | "applied" | "failed" | "rejected";

export type ReviewData = {
  preview: DesignerPreview;
  status: JobStatus;
};

export type FigmaSelectionView = {
  version: 1;
  selection_id: string;
  display_name: string;
  top_level_summaries: Array<{ name: string; type: string }>;
  preview_urls: string[];
  warnings: Array<{ code: string; message: string }>;
};

export type ConsolePairing = {
  version: 1;
  code: string;
  expires_at: string;
  console_credential: string;
};

export type FigmaDevice = {
  version: 1;
  device_id: string;
  device_name: string;
  created_at: string;
  revoked_at?: string | null;
};

export type ConsolePairingStatus = {
  version: 1;
  state: "waiting_for_device" | "paired";
  expires_at: string;
  device?: FigmaDevice | null;
};

type JobSummary = { job_id: string; status: JobStatus };

type ServerError = { detail?: { code?: string; message?: string } };

const safeMessages: Record<string, string> = {
  archive_too_large: "压缩包过大或包含过多文件",
  invalid_fgui_project: "这个 ZIP 不是有效的 FairyGUI 工程",
  unsafe_archive: "无法安全读取这个压缩包",
};

export class UploadApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UploadApiError";
  }
}

export class ReviewApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ReviewApiError";
  }
}

export class FigmaConsoleApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FigmaConsoleApiError";
  }
}

export function safeUploadMessage(error: unknown): string {
  if (error instanceof UploadApiError) return error.message;
  return "上传未完成，请检查网络后重试";
}

export function safeReviewMessage(error: unknown, fallback = "无法加载本次更新，请稍后重试"): string {
  return error instanceof ReviewApiError ? error.message : fallback;
}

async function reviewRequest<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new ReviewApiError("无法连接服务，请检查后重试");
  }
  if (!response.ok) {
    throw new ReviewApiError(response.status === 404 ? "找不到本次更新，请返回重新开始" : "此更新当前无法操作，请刷新后重试");
  }
  return response.json() as Promise<T>;
}

export function safeFigmaConsoleMessage(error: unknown): string {
  return error instanceof FigmaConsoleApiError ? error.message : "无法继续 Figma 配对，请稍后重试";
}

async function consoleRequest<T>(url: string, session?: string, init?: RequestInit): Promise<T | null> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: { ...(init?.headers ?? {}), ...(session ? { "X-Figma-Console-Session": session } : {}) },
    });
  } catch {
    throw new FigmaConsoleApiError("无法连接服务，请检查网络后重试");
  }
  if (response.status === 204) return null;
  if (!response.ok) {
    throw new FigmaConsoleApiError(response.status === 401 ? "配对会话已失效，请重新开始" : "当前操作无法完成，请刷新后重试");
  }
  return response.json() as Promise<T>;
}

export async function createConsolePairing(): Promise<ConsolePairing> {
  return (await consoleRequest<ConsolePairing>("/v1/figma/pairings", undefined, { method: "POST" }))!;
}

export async function getConsolePairingStatus(session: string): Promise<ConsolePairingStatus> {
  return (await consoleRequest<ConsolePairingStatus>("/v1/figma/pairings/status", session))!;
}

export function cancelConsolePairing(session: string): Promise<null> {
  return consoleRequest("/v1/figma/pairings/current", session, { method: "DELETE" });
}

export function getCurrentConsoleSelection(session: string): Promise<FigmaSelectionView | null> {
  return consoleRequest<FigmaSelectionView>("/v1/figma/pairings/current/selection", session);
}

export async function loadConsolePreview(session: string, url: string): Promise<string> {
  const response = await fetch(url, { headers: { "X-Figma-Console-Session": session } });
  if (!response.ok) throw new FigmaConsoleApiError("无法加载选择缩略图");
  return URL.createObjectURL(await response.blob());
}

export async function listFigmaDevices(session: string): Promise<FigmaDevice[]> {
  return (await consoleRequest<FigmaDevice[]>("/v1/figma/devices", session))!;
}

export async function revokeFigmaDevice(session: string, deviceId: string): Promise<FigmaDevice> {
  return (await consoleRequest<FigmaDevice>(`/v1/figma/devices/${encodeURIComponent(deviceId)}`, session, { method: "DELETE" }))!;
}

export function getDesignerPreview(jobId: string): Promise<DesignerPreview> {
  return reviewRequest(`/v1/jobs/${encodeURIComponent(jobId)}/designer-preview`);
}

export function getAdvancedDesignerPreview(jobId: string): Promise<AdvancedDesignerPreview> {
  return reviewRequest(`/v1/jobs/${encodeURIComponent(jobId)}/designer-preview?details=advanced`);
}

export async function loadReview(jobId: string): Promise<ReviewData> {
  const [preview, job] = await Promise.all([
    getDesignerPreview(jobId),
    reviewRequest<JobSummary>(`/v1/jobs/${encodeURIComponent(jobId)}`),
  ]);
  return { preview, status: job.status };
}

export function approveJob(jobId: string): Promise<JobSummary> {
  return reviewRequest(`/v1/jobs/${encodeURIComponent(jobId)}/approve`, { method: "POST" });
}

export function rejectJob(jobId: string): Promise<JobSummary> {
  return reviewRequest(`/v1/jobs/${encodeURIComponent(jobId)}/reject`, { method: "POST" });
}

export function createSelectionProjectJob(session: string, selectionId: string, projectId: string, packageName: string): Promise<JobSummary> {
  return consoleRequest<JobSummary>(
    `/v1/figma/selections/${encodeURIComponent(selectionId)}/projects/${encodeURIComponent(projectId)}/jobs`,
    session,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: 1, selection_id: selectionId, project_id: projectId, package_name: packageName }),
    },
  ).then((result) => result!);
}

export function uploadProject(file: File, onProgress: (percent: number) => void): Promise<UploadedProject> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", "/v1/projects/uploads");
    request.responseType = "json";
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    request.onerror = () => reject(new UploadApiError("上传未完成，请检查网络后重试"));
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(request.response as UploadedProject);
        return;
      }
      const detail = (request.response as ServerError | null)?.detail;
      const fallback = detail?.code && safeMessages[detail.code];
      reject(new UploadApiError(fallback || "上传未完成，请稍后重试"));
    };
    const body = new FormData();
    body.append("project", file);
    request.send(body);
  });
}
