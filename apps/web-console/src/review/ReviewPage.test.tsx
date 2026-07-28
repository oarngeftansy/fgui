import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { AdvancedDesignerPreview, ReviewData } from "../api";
import { ReviewPage } from "./ReviewPage";

const normalReview: ReviewData = {
  status: "ready_for_review",
  preview: {
    summary: "1 项新增 · 2 项更新",
    changes: [
      {
        action: "更新",
        label: "图片：主视觉",
        thumbnail_available: true,
        before_image_url: "/v1/jobs/internal-job-id/designer-preview/images/0/before",
        after_image_url: "/v1/jobs/internal-job-id/designer-preview/images/0/after",
      },
      { action: "更新", label: "组件：按钮", thumbnail_available: false },
      { action: "新增", label: "资源：图标", thumbnail_available: false },
    ],
    checks: [{ status: "success", message: "工程结构正常" }],
  },
};

const warningReview: ReviewData = {
  ...normalReview,
  preview: {
    ...normalReview.preview,
    checks: [{ status: "warning", message: "2 处位置有轻微调整" }],
  },
};

const errorReview: ReviewData = {
  ...normalReview,
  preview: {
    ...normalReview.preview,
    checks: [{ status: "error", message: "发现需要处理的问题" }],
  },
};

const createdImageReview: ReviewData = {
  status: "ready_for_review",
  preview: {
    summary: "1 项新增 · 0 项更新",
    changes: [{ action: "新增", label: "图片：新主视觉", thumbnail_available: false, after_image_url: "/v1/jobs/internal-job-id/designer-preview/images/0/after" }],
    checks: [{ status: "success", message: "工程结构正常" }],
  },
};

const advancedPreview: AdvancedDesignerPreview = {
  preview: normalReview.preview,
  details: {
    files: [{ operation: "replace", relative_path: "Sample/Panel/Main.xml", before_sha256: "a", after_sha256: "b", before_xml: "<component/>", after_xml: "<component name='Main'/>" }],
    diagnostics: [],
  },
};

function renderPage(
  review: ReviewData | Promise<ReviewData> = normalReview,
  actions: Partial<React.ComponentProps<typeof ReviewPage>> = {},
) {
  const props = {
    jobId: "internal-job-id",
    loadReview: vi.fn().mockResolvedValue(review),
    loadAdvancedPreview: vi.fn().mockResolvedValue(advancedPreview),
    approveJob: vi.fn().mockResolvedValue({ status: "approved" }),
    rejectJob: vi.fn().mockResolvedValue({ status: "rejected" }),
    ...actions,
  };
  render(<ReviewPage {...props} />);
  return props;
}

describe("ReviewPage", () => {
  it("shows a loading state before rendering the three-column review workspace", async () => {
    let resolveReview: ((value: ReviewData) => void) | undefined;
    renderPage(new Promise((resolve) => { resolveReview = resolve; }));

    expect(screen.getByText("正在准备本次更新…")).toBeVisible();
    resolveReview?.(normalReview);

    expect(await screen.findByRole("heading", { name: "本次会发生什么" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "查看变化" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "检查与决定" })).toBeVisible();
    expect(screen.getByTestId("review-workspace")).toHaveClass("review-workspace");
  });

  it("keeps designer labels visible while hiding normal technical details", async () => {
    renderPage();

    expect(await screen.findByText("1 项新增 · 2 项更新")).toBeVisible();
    expect(screen.getByRole("button", { name: /图片：主视觉/ })).toBeVisible();
    expect(screen.queryByText("internal-job-id")).not.toBeInTheDocument();
    expect(screen.queryByText(/Sample\/Panel\/Main\.xml/)).not.toBeInTheDocument();
    expect(screen.queryByText(/changeset|sha256|resource_id/i)).not.toBeInTheDocument();
  });

  it("switches the center summary by keyboard change selection", async () => {
    renderPage();
    const first = await screen.findByRole("button", { name: /图片：主视觉/ });

    first.focus();
    await userEvent.keyboard("{ArrowDown}");

    expect(screen.getByRole("button", { name: /组件：按钮/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("组件更新摘要")).toBeVisible();
    expect(screen.getByText("按钮")).toBeVisible();
  });

  it("shows image comparison with Chinese alternative text and reserved dimensions", async () => {
    renderPage();

    expect(await screen.findByAltText("当前工程中的主视觉视觉效果")).toHaveAttribute("src", "/v1/jobs/internal-job-id/designer-preview/images/0/before");
    expect(screen.getByAltText("更新以后主视觉视觉效果")).toHaveAttribute("src", "/v1/jobs/internal-job-id/designer-preview/images/0/after");
    expect(screen.getByTestId("image-comparison")).toHaveClass("image-comparison");
  });

  it("explains that a newly created image has no current visual instead of rendering a placeholder", async () => {
    renderPage(createdImageReview);

    expect(await screen.findByText("新增图片，当前工程中没有对应视觉")).toBeVisible();
    expect(screen.queryByAltText("当前工程中的新主视觉视觉效果")).not.toBeInTheDocument();
    expect(screen.getByAltText("更新以后新主视觉视觉效果")).toHaveAttribute("src", "/v1/jobs/internal-job-id/designer-preview/images/0/after");
  });

  it("keeps warnings visible without blocking the whole-update approval", async () => {
    renderPage(warningReview);

    expect(await screen.findByText("2 处位置有轻微调整")).toBeVisible();
    expect(screen.getByRole("button", { name: "确认更新到本地工程" })).toBeEnabled();
  });

  it("blocks approval when checks contain an error", async () => {
    renderPage(errorReview);

    expect(await screen.findByText("发现需要处理的问题")).toBeVisible();
    expect(screen.getByRole("button", { name: "确认更新到本地工程" })).toBeDisabled();
  });

  it("keeps review actions view-only at mobile widths", async () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    const { approveJob, rejectJob } = renderPage();

    expect(await screen.findByText("请在桌面浏览器中确认或暂不更新本次完整改动。")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "确认更新到本地工程" }));
    await userEvent.click(screen.getByRole("button", { name: "暂不更新" }));

    expect(approveJob).not.toHaveBeenCalled();
    expect(rejectJob).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("opens an accessible confirmation dialog and can cancel approval", async () => {
    const { approveJob } = renderPage();
    const trigger = await screen.findByRole("button", { name: "确认更新到本地工程" });
    await userEvent.click(trigger);

    expect(screen.getByRole("dialog", { name: "确认更新到本地工程" })).toBeVisible();
    expect(screen.getByRole("button", { name: "取消" })).toHaveFocus();
    await userEvent.keyboard("{Tab}");
    expect(screen.getByRole("button", { name: "确认更新" })).toHaveFocus();
    await userEvent.keyboard("{Tab}");
    expect(screen.getByRole("button", { name: "取消" })).toHaveFocus();
    await userEvent.keyboard("{Shift>}{Tab}{/Shift}");
    expect(screen.getByRole("button", { name: "确认更新" })).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: "取消" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(approveJob).not.toHaveBeenCalled();
  });

  it("closes the confirmation dialog with Escape and restores the trigger focus", async () => {
    renderPage();
    const trigger = await screen.findByRole("button", { name: "确认更新到本地工程" });
    await userEvent.click(trigger);

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("approves the complete update once after confirmation and reports success", async () => {
    const { approveJob } = renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "确认更新到本地工程" }));
    const confirm = screen.getByRole("button", { name: "确认更新" });

    await userEvent.dblClick(confirm);

    await waitFor(() => expect(approveJob).toHaveBeenCalledTimes(1));
    expect(approveJob).toHaveBeenCalledWith("internal-job-id");
    expect(await screen.findByText("已确认完整更新，正在等待本地助手处理。", { exact: false })).toBeVisible();
  });

  it("reports a safe approval failure and allows retry", async () => {
    const approveJob = vi.fn().mockRejectedValueOnce(new Error("无法完成更新，请稍后重试")).mockResolvedValue({ status: "approved" });
    renderPage(normalReview, { approveJob });
    await userEvent.click(await screen.findByRole("button", { name: "确认更新到本地工程" }));
    await userEvent.click(screen.getByRole("button", { name: "确认更新" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("无法完成更新，请稍后重试");
    await userEvent.click(screen.getByRole("button", { name: "确认更新到本地工程" }));
    await userEvent.click(screen.getByRole("button", { name: "确认更新" }));
    await waitFor(() => expect(approveJob).toHaveBeenCalledTimes(2));
  });

  it("rejects the complete update once and reports completion", async () => {
    const { rejectJob } = renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "暂不更新" }));
    await userEvent.dblClick(screen.getByRole("button", { name: "暂不更新" }));

    await waitFor(() => expect(rejectJob).toHaveBeenCalledTimes(1));
    expect(rejectJob).toHaveBeenCalledWith("internal-job-id");
    expect(await screen.findByText("已暂不更新本次完整改动。", { exact: false })).toBeVisible();
  });

  it("loads raw details only after the advanced disclosure is requested", async () => {
    const { loadAdvancedPreview } = renderPage();
    expect(await screen.findByRole("button", { name: "查看高级详情" })).toBeVisible();
    expect(loadAdvancedPreview).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "查看高级详情" }));

    await waitFor(() => expect(loadAdvancedPreview).toHaveBeenCalledWith("internal-job-id"));
    expect(await screen.findByText("Sample/Panel/Main.xml")).toBeVisible();
    expect(screen.getByText("<component/>")).toBeVisible();
  });

  it("collapses advanced details without making a second request", async () => {
    const { loadAdvancedPreview } = renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "查看高级详情" }));
    expect(await screen.findByText("Sample/Panel/Main.xml")).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "隐藏高级详情" }));

    expect(screen.queryByText("Sample/Panel/Main.xml")).not.toBeInTheDocument();
    expect(loadAdvancedPreview).toHaveBeenCalledTimes(1);
  });

  it("renders a safe loading failure", async () => {
    renderPage(Promise.reject(new Error("无法加载本次更新，请稍后重试")));

    expect(await screen.findByRole("alert")).toHaveTextContent("无法加载本次更新，请稍后重试");
  });

  it("retries the initial review load after a safe failure", async () => {
    const loadReview = vi.fn().mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce(normalReview);
    renderPage(normalReview, { loadReview });

    expect(await screen.findByRole("alert")).toHaveTextContent("无法加载本次更新，请稍后重试");
    await userEvent.click(screen.getByRole("button", { name: "重试加载" }));

    await waitFor(() => expect(loadReview).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("1 项新增 · 2 项更新")).toBeVisible();
  });
});
