import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { HifiBatch } from "../../../figma-plugin/src/project-client";
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

function renderPanel(batch: HifiBatch, busy = false) {
  const handlers = {
    onEnterGroup: vi.fn(),
    onBuildPackage: vi.fn(),
    onDownload: vi.fn(),
    onWriteback: vi.fn(),
    onBack: vi.fn(),
  };
  render(
    <HifiBatchGroupsPanel batch={batch} busy={busy} {...handlers} />,
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

  it("renders the export zone only when every group is approved", async () => {
    const handlers = renderPanel(
      makeBatch({
        exportReady: true,
        groups: makeBatch().groups.map((group) => ({
          ...group,
          status: "approved" as const,
        })),
      }),
    );
    const build = screen.getByRole("button", { name: "构建合并包" });
    expect(build).toBeEnabled();
    expect(screen.getByRole("button", { name: "下载合并包" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "写回原工程" })).toBeDisabled();
    await userEvent.click(build);
    expect(handlers.onBuildPackage).toHaveBeenCalledOnce();
  });

  it("shows the packaging loading state while busy", () => {
    renderPanel(makeBatch({ exportReady: true }), true);
    expect(
      screen.getByRole("button", { name: "正在构建合并包…" }),
    ).toBeDisabled();
  });

  it("gates the manual download and writeback on the artifact", async () => {
    const handlers = renderPanel(
      makeBatch({
        exportReady: true,
        artifactReady: true,
        artifactName: "Tower-batch.zip",
      }),
    );
    expect(screen.getByText("合并包：Tower-batch.zip")).toBeVisible();
    const download = screen.getByRole("button", { name: "下载合并包" });
    expect(download).toBeEnabled();
    await userEvent.click(download);
    expect(handlers.onDownload).toHaveBeenCalledOnce();
    await userEvent.type(
      screen.getByLabelText("本机工程路径"),
      "D:/Projects/Tower",
    );
    await userEvent.click(screen.getByRole("button", { name: "写回原工程" }));
    expect(handlers.onWriteback).toHaveBeenCalledWith("D:/Projects/Tower");
  });

  it("disables build and writeback after delivery and shows the result", () => {
    renderPanel(
      makeBatch({
        exportReady: true,
        artifactReady: true,
        status: "delivered",
        writeback: {
          localPath: "D:/Projects/Tower",
          backupDir: "D:/Projects/Tower/.hifi-backup/20260101",
          changedPaths: ["assets/Tower/Panel.xml", "assets/Tower/icon.png"],
          appliedAt: "2026-01-01T00:00:00+00:00",
        },
      }),
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
