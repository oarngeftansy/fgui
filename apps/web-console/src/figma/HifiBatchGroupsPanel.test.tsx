import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  HifiBatch,
  HifiExportMode,
} from "../../../figma-plugin/src/project-client";
import { HifiBatchGroupsPanel } from "./HifiBatchGroupsPanel";

function makeBatch(overrides: Partial<HifiBatch> = {}): HifiBatch {
  return {
    batchId: "c".repeat(32),
    projectId: "a".repeat(32),
    status: "in_review",
    exportReady: false,
    artifactReady: false,
    warnings: [],
    groups: [
      {
        sessionId: "d".repeat(32),
        sourceId: "e".repeat(64),
        psdName: "MainPage.psd",
        targetName: "Panel_Tower_Main",
        status: "mapping",
        unresolvedCount: 2,
        approvalReady: false,
      },
      {
        sessionId: "f".repeat(32),
        sourceId: "e".repeat(64),
        psdName: "ShopPage.psd",
        targetName: "Panel_Shop",
        status: "approved",
        unresolvedCount: 0,
        approvalReady: true,
      },
    ],
    ...overrides,
  };
}

function approvedBatch(overrides: Partial<HifiBatch> = {}): HifiBatch {
  return makeBatch({
    exportReady: true,
    groups: makeBatch().groups.map((group) => ({
      ...group,
      status: "approved" as const,
      unresolvedCount: 0,
    })),
    ...overrides,
  });
}

function renderPanel(
  batch: HifiBatch,
  options: {
    busy?: boolean;
    exportMode?: HifiExportMode;
    fidelity?: Record<string, { total: number; passed: number } | undefined>;
  } = {},
) {
  const handlers = {
    onEnterGroup: vi.fn(),
    onBuildPackage: vi.fn(),
    onDownload: vi.fn(),
    onWriteback: vi.fn(),
    onBack: vi.fn(),
    onExportMode: vi.fn(),
    onLoadFidelity: vi.fn(),
  };
  render(
    <HifiBatchGroupsPanel
      batch={batch}
      busy={options.busy ?? false}
      exportMode={options.exportMode ?? "package"}
      fidelity={options.fidelity ?? {}}
      onExportMode={handlers.onExportMode}
      onLoadFidelity={handlers.onLoadFidelity}
      onEnterGroup={handlers.onEnterGroup}
      onBuildPackage={handlers.onBuildPackage}
      onDownload={handlers.onDownload}
      onWriteback={handlers.onWriteback}
      onBack={handlers.onBack}
    />,
  );
  return handlers;
}

describe("HifiBatchGroupsPanel", () => {
  it("lists groups with Chinese status chips and progress", () => {
    renderPanel(makeBatch());
    expect(screen.getByText("已批准 1/2")).toBeVisible();
    expect(
      screen.getByText("MainPage.psd → Panel_Tower_Main"),
    ).toBeVisible();
    expect(screen.getByText("映射中")).toBeVisible();
    expect(screen.getByText("已批准")).toBeVisible();
    expect(screen.getByText("2 项待确认")).toBeVisible();
    expect(screen.getByText("0 项待确认 · ✓ 可批准")).toBeVisible();
  });

  it("hides the export zone while export_ready is false", () => {
    renderPanel(makeBatch({ exportReady: false }));
    expect(
      screen.queryByRole("button", { name: "构建合并包" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "下载合并包" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "写回原工程" }),
    ).not.toBeInTheDocument();
  });

  it("previews per-group fidelity and offers the delivery choice", async () => {
    const handlers = renderPanel(
      approvedBatch(),
      {
        fidelity: { ["d".repeat(32)]: { total: 5, passed: 4 } },
      },
    );
    expect(screen.getByText("保真 通过 4/5")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "查看保真" }));
    expect(handlers.onLoadFidelity).toHaveBeenCalledWith("f".repeat(32));
    expect(
      screen.getByLabelText("导出新版合并 ZIP，旧工程保持不变"),
    ).toBeChecked();
    await userEvent.click(
      screen.getByLabelText("覆盖本机旧工程，历史版本仍可回退"),
    );
    expect(handlers.onExportMode).toHaveBeenCalledWith("overwrite");
  });

  it("builds then downloads in package mode without writeback controls", async () => {
    const handlers = renderPanel(approvedBatch({ artifactReady: true }));
    const build = screen.getByRole("button", { name: "构建合并包" });
    expect(build).toBeEnabled();
    const download = screen.getByRole("button", { name: "下载合并包" });
    expect(download).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "写回原工程" }),
    ).not.toBeInTheDocument();
    await userEvent.click(download);
    expect(handlers.onDownload).toHaveBeenCalledOnce();
  });

  it("gates the package download on the artifact", () => {
    renderPanel(approvedBatch());
    expect(screen.getByRole("button", { name: "下载合并包" })).toBeDisabled();
  });

  it("writes back through the overwrite mode with a local path", async () => {
    const handlers = renderPanel(approvedBatch({ artifactReady: true }), {
      exportMode: "overwrite",
    });
    expect(
      screen.queryByRole("button", { name: "下载合并包" }),
    ).not.toBeInTheDocument();
    const writeback = screen.getByRole("button", { name: "写回原工程" });
    expect(writeback).toBeDisabled();
    await userEvent.type(
      screen.getByLabelText("本机工程路径"),
      "D:/Projects/Tower",
    );
    expect(writeback).toBeEnabled();
    await userEvent.click(writeback);
    expect(handlers.onWriteback).toHaveBeenCalledWith("D:/Projects/Tower");
  });

  it("shows the packaging loading state while busy", () => {
    renderPanel(approvedBatch(), { busy: true });
    expect(
      screen.getByRole("button", { name: "正在构建合并包…" }),
    ).toBeDisabled();
  });

  it("disables build and writeback after delivery and shows the result", () => {
    renderPanel(
      approvedBatch({
        artifactReady: true,
        status: "delivered",
        writeback: {
          localPath: "D:/Projects/Tower",
          backupDir: "D:/Projects/Tower/.hifi-backup/20260101",
          changedPaths: ["assets/Tower/Panel.xml", "assets/Tower/icon.png"],
          appliedAt: "2026-01-01T00:00:00+00:00",
        },
      }),
      { exportMode: "overwrite" },
    );
    expect(screen.getByRole("button", { name: "构建合并包" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "写回原工程" })).toBeDisabled();
    expect(screen.getByLabelText("本机工程路径")).toBeDisabled();
    expect(
      screen.getByText(
        "已写回 · 备份 D:/Projects/Tower/.hifi-backup/20260101 · 变更 2 个文件",
      ),
    ).toBeVisible();
  });

  it("lists batch warnings after creation", () => {
    renderPanel(
      makeBatch({
        warnings: ["e3f1a2b4->Panel_Shop: psd_source_unavailable"],
      }),
    );
    expect(screen.getByText("建批警示")).toBeVisible();
    expect(
      screen.getByText("e3f1a2b4->Panel_Shop: psd_source_unavailable"),
    ).toBeVisible();
  });

  it("enters a group for review", async () => {
    const handlers = renderPanel(makeBatch());
    await userEvent.click(screen.getByRole("button", { name: "进入审核" }));
    expect(handlers.onEnterGroup).toHaveBeenCalledWith("d".repeat(32));
  });
});
