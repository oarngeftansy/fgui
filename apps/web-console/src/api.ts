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

export function safeUploadMessage(error: unknown): string {
  if (error instanceof UploadApiError) return error.message;
  return "上传未完成，请检查网络后重试";
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
      const code = (request.response as ServerError | null)?.detail?.code;
      reject(new UploadApiError((code && safeMessages[code]) || "上传未完成，请稍后重试"));
    };
    const body = new FormData();
    body.append("project", file);
    request.send(body);
  });
}
