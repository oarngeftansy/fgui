import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { HifiEditorVerification, HifiReplacementReview } from "../../../figma-plugin/src/project-client";
import {
  HifiReplacementReviewActions,
  HifiReplacementReviewPanel,
  editorAlignOffsetPx,
  editorAlignTopPercent,
  type HifiEditorCheckState,
} from "./HifiReplacementReviewPanel";

const review: HifiReplacementReview = {
  sessionId: "a".repeat(32), mappingRevision: 3, changedFiles: [{ relativePath: "assets/MyVillage/Panel/Root.xml", operation: "replace", summary: "更新视觉" }],
  objectDiffs: [
    { itemId: "old:title", kind: "changed", oldObjectId: "title", oldName: "Title", figmaNodeId: "figma-title", figmaName: "Title", changedFields: ["xy"], summary: "修改视觉字段：xy" },
    { itemId: "old:legacy", kind: "kept", oldObjectId: "legacy", oldName: "Legacy", changedFields: [], summary: "保留旧对象", action: "keep_old", visualDisposition: "preserve", oldObjectType: "image" },
    { itemId: "old:decor", kind: "kept", oldObjectId: "decor", oldName: "Decor", changedFields: [], summary: "保留旧对象", action: "keep_old", visualDisposition: "preserve", oldObjectType: "component" },
    { itemId: "old:retired", kind: "kept", oldObjectId: "retired", oldName: "Retired", changedFields: [], summary: "保留旧对象", action: "keep_old", visualDisposition: "retire", oldObjectType: "image" },
  ],
  protectedChecksPassed: true, parseCoverageComplete: true, approvable: true, candidateSha256: "b".repeat(64), warnings: [], editorCheckRequired: true,
};

const verification: HifiEditorVerification = {
  sessionId: "a".repeat(32), candidateSha256: "b".repeat(64), editorFound: true, editorVersion: "6.1.4",
  projectOpened: true, componentOpened: true, renderCaptured: true, screenshotWidth: 1080, screenshotHeight: 1920,
  expectedWidth: 1080, expectedHeight: 1920, fullFrame: true, approvable: true, warnings: [],
};

const idleChecks: HifiEditorCheckState = { layout: false, references: false, interactions: false };

describe("HifiReplacementReviewPanel", () => {
  it("shows object-level evidence and gates delivery on all Editor checks", async () => {
    const approve = vi.fn();
    function Harness() {
      const [checks, setChecks] = useState<HifiEditorCheckState>(idleChecks);
      return <><HifiReplacementReviewPanel review={review} checks={checks} busy={false} onChecksChange={setChecks} onDownloadCandidate={vi.fn()} onReject={vi.fn()} /><footer><HifiReplacementReviewActions review={review} checks={checks} busy={false} onReturn={vi.fn()} onApprove={approve} /></footer></>;
    }
    render(<Harness />);
    expect(screen.getByText("修改视觉字段：xy")).toBeVisible();
    expect(screen.getByText("b".repeat(64))).toBeVisible();
    const deliver = screen.getByRole("button", { name: "确认并交付 ZIP" });
    expect(deliver).toBeDisabled();
    for (const label of ["布局与图层顺序正确", "图片与共享组件引用正常", "Controller、Gear、Transition 正常"]) await userEvent.click(screen.getByRole("checkbox", { name: label }));
    expect(deliver).toBeDisabled();
    await userEvent.click(deliver);
    expect(approve).not.toHaveBeenCalled();
  });

  it("hides keep_old rows without PSD correspondence in bulk or individually", async () => {
    const onHide = vi.fn();
    render(<HifiReplacementReviewPanel review={review} checks={idleChecks} busy={false} onChecksChange={vi.fn()} onDownloadCandidate={vi.fn()} onReject={vi.fn()} onHideKeptObjects={onHide} />);
    const bulk = screen.getByRole("button", { name: /一键隐藏无 PSD 对应的保留对象/ });
    expect(bulk).toHaveTextContent("1");
    await userEvent.click(bulk);
    expect(onHide).toHaveBeenCalledWith(["old:legacy"]);
    await userEvent.click(screen.getByRole("button", { name: "隐藏" }));
    expect(onHide).toHaveBeenCalledTimes(2);
    expect(onHide).toHaveBeenLastCalledWith(["old:legacy"]);
  });

  it("disables bulk hide when no kept row is retirable", () => {
    const onHide = vi.fn();
    const plain: HifiReplacementReview = { ...review, objectDiffs: [review.objectDiffs[0]] };
    render(<HifiReplacementReviewPanel review={plain} checks={idleChecks} busy={false} onChecksChange={vi.fn()} onDownloadCandidate={vi.fn()} onReject={vi.fn()} onHideKeptObjects={onHide} />);
    expect(screen.getByRole("button", { name: /一键隐藏无 PSD 对应的保留对象/ })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "隐藏" })).not.toBeInTheDocument();
  });

  it("lists localised mismatch regions with suspect items when verification fails", () => {
    const failed: HifiEditorVerification = {
      ...verification,
      approvable: false,
      mismatchRegions: [
        { x: 0, y: 0, width: 80, height: 80, severity: 0.17, blockCount: 4, items: [{ itemId: "old:legacy", oldName: "Legacy", action: "keep_old" }] },
      ],
    };
    render(<HifiReplacementReviewPanel review={review} checks={idleChecks} busy={false} onChecksChange={vi.fn()} onDownloadCandidate={vi.fn()} onReject={vi.fn()} verification={failed} />);
    expect(screen.getByText("Editor 对比差异区域（修正闭环）")).toBeVisible();
    expect(screen.getByText(/疑似责任对象：Legacy（keep_old）/)).toBeVisible();
    expect(screen.getByText(/80×80/)).toBeVisible();
    expect(screen.getByText(/17.0%/)).toBeVisible();
  });

  it("aligns the editor screenshot with the PSD effect image at natural scale", () => {
    render(<HifiReplacementReviewPanel review={review} checks={idleChecks} busy={false} onChecksChange={vi.fn()} onDownloadCandidate={vi.fn()} onReject={vi.fn()} verification={verification} editorScreenshotUrl="blob:editor" psdPreviewUrl="blob:psd" />);
    expect(screen.getByAltText("PSD 效果图（文档坐标）")).toBeVisible();
    expect(screen.getByAltText("FairyGUI Editor 候选渲染截图")).toBeVisible();
    expect(editorAlignOffsetPx({ width: 1080, height: 2340 }, { width: 1080, height: 1920 })).toBe(210);
    expect(editorAlignTopPercent({ width: 1080, height: 2340 }, { width: 1080, height: 1920 })).toBeCloseTo((210 / 2340) * 100, 10);
    expect(editorAlignOffsetPx(undefined, undefined)).toBeUndefined();
    expect(editorAlignTopPercent(undefined, undefined)).toBe(0);
  });
});
