import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { UploadApiError } from "../api";
import { UploadPage } from "./UploadPage";

const uploadedProject = {
  version: 1,
  project_id: "internal-project-id",
  display_name: "GameUI.zip",
  packages: [{ name: "Sample", resource_count: 28 }],
};

function renderPage(upload = vi.fn(), createJob = vi.fn()) {
  render(<UploadPage uploadProject={upload} createJob={createJob} />);
  return { createJob, upload };
}

describe("UploadPage", () => {
  it("uploads a selected ZIP file", async () => {
    const { upload } = renderPage(vi.fn().mockResolvedValue(uploadedProject));
    const file = new File(["zip"], "GameUI.zip", { type: "application/zip" });

    await userEvent.upload(screen.getByLabelText("上传 FairyGUI 工程 ZIP"), file);

    await waitFor(() => expect(upload).toHaveBeenCalledWith(file, expect.any(Function)));
  });

  it("rejects non-ZIP files before uploading", async () => {
    const { upload } = renderPage();

    fireEvent.change(screen.getByLabelText("上传 FairyGUI 工程 ZIP"), {
      target: { files: [new File(["no"], "notes.txt")] },
    });

    expect(screen.getByRole("alert")).toHaveTextContent("请选择 .zip 格式的 FairyGUI 工程文件");
    expect(upload).not.toHaveBeenCalled();
  });

  it("uploads a ZIP dropped on the keyboard-usable drop target", async () => {
    const { upload } = renderPage(vi.fn().mockResolvedValue(uploadedProject));
    const dropTarget = screen.getByRole("button", { name: /拖放 ZIP 到这里/i });
    const file = new File(["zip"], "GameUI.zip", { type: "application/zip" });

    fireEvent.drop(dropTarget, { dataTransfer: { files: [file] } });

    await waitFor(() => expect(upload).toHaveBeenCalledWith(file, expect.any(Function)));
    expect(dropTarget).toHaveAttribute("tabindex", "0");
  });

  it("shows upload progress and prevents duplicate submission", async () => {
    let resolveUpload: ((project: typeof uploadedProject) => void) | undefined;
    const { upload } = renderPage(
      vi.fn(
        (_file: File, onProgress: (value: number) => void) =>
          new Promise<typeof uploadedProject>((resolve) => {
            onProgress(42);
            resolveUpload = resolve;
          }),
      ),
    );
    const file = new File(["zip"], "GameUI.zip", { type: "application/zip" });

    await userEvent.upload(screen.getByLabelText("上传 FairyGUI 工程 ZIP"), file);

    expect(screen.getByRole("progressbar")).toHaveValue(42);
    expect(screen.getByText("42%")).toBeVisible();
    await userEvent.upload(screen.getByLabelText("上传 FairyGUI 工程 ZIP"), file);
    expect(upload).toHaveBeenCalledTimes(1);
    resolveUpload?.(uploadedProject);
  });

  it("shows only the safe server error copy and retries the selected ZIP", async () => {
    const upload = vi
      .fn()
      .mockRejectedValueOnce(new UploadApiError("无法安全读取这个压缩包"))
      .mockResolvedValueOnce(uploadedProject);
    renderPage(upload);
    const file = new File(["zip"], "GameUI.zip", { type: "application/zip" });

    await userEvent.upload(screen.getByLabelText("上传 FairyGUI 工程 ZIP"), file);

    expect(await screen.findByRole("alert")).toHaveTextContent("无法安全读取这个压缩包");
    expect(screen.queryByText(/private|project\.xml/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "重试上传" }));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
  });

  it("shows the original ZIP name and package summary after success", async () => {
    renderPage(vi.fn().mockResolvedValue(uploadedProject));

    await userEvent.upload(
      screen.getByLabelText("上传 FairyGUI 工程 ZIP"),
      new File(["zip"], "GameUI.zip", { type: "application/zip" }),
    );

    expect(await screen.findByText("GameUI.zip")).toBeVisible();
    expect(screen.getByText("Sample 包 · 28 个资源")).toBeVisible();
    expect(screen.queryByText("internal-project-id")).not.toBeInTheDocument();
    expect(screen.queryByText("还没有上传过工程。完成上传后，任务会显示在这里。")).not.toBeInTheDocument();
    expect(screen.getByText("刚刚上传")).toBeVisible();
  });

  it("opens the native file chooser with Enter", async () => {
    renderPage();
    const input = screen.getByLabelText("上传 FairyGUI 工程 ZIP") as HTMLInputElement;
    const click = vi.spyOn(input, "click");

    await userEvent.keyboard("{Tab}{Enter}");

    expect(click).toHaveBeenCalled();
  });

  it("creates one review for the selected package after a successful upload", async () => {
    const createJob = vi.fn().mockResolvedValue({ job_id: "review-1", status: "ready_for_review" });
    renderPage(vi.fn().mockResolvedValue(uploadedProject), createJob);

    await userEvent.upload(
      screen.getByLabelText(/ZIP$/),
      new File(["zip"], "GameUI.zip", { type: "application/zip" }),
    );
    await userEvent.click(await screen.findByTestId("create-review"));

    await waitFor(() => expect(createJob).toHaveBeenCalledWith("internal-project-id", "Sample"));
    expect(window.location.pathname).toBe("/jobs/review-1");
  });
});
