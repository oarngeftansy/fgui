import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { HifiRemovalReview } from "../../../figma-plugin/src/project-client";
import { HifiRemovalReviewPanel } from "./HifiRemovalReviewPanel";

const review: HifiRemovalReview = {
  pending: true,
  totalCandidateCount: 3,
  groups: [
    {
      groupId: "grp-1",
      semanticRoot: "assets/Pkg/Panel/Panel_One.xml",
      region: "",
      riskTier: 4,
      recommendation: "remove",
      autoResolved: false,
      mergedTemplate: false,
      objects: [
        {
          itemId: "old:badge",
          objectId: "badge",
          name: "old_badge",
          objectType: "image",
          riskTier: 4,
          reason: "PSD 目标态未找到对应内容，疑似被 UX 淘汰的旧视觉（§8 REMOVE_CANDIDATE）",
          controllerRefs: [],
          transitionRefs: [],
          relationRefs: [],
          referencedBy: [],
          runtimeBound: false,
          previewUrl: "data:image/png;base64,QUJD",
          text: "",
          size: [24, 18],
          location: "",
        },
        {
          itemId: "old:note",
          objectId: "note",
          name: "old_note",
          objectType: "text",
          riskTier: 4,
          reason: "PSD 目标态未找到对应内容，疑似被 UX 淘汰的旧视觉（§8 REMOVE_CANDIDATE）",
          controllerRefs: [],
          transitionRefs: [],
          relationRefs: [],
          referencedBy: [],
          runtimeBound: false,
          previewUrl: "",
          text: "限時活動",
          size: [100, 24],
          location: "",
        },
        {
          itemId: "old:deco",
          objectId: "deco",
          name: "old_deco",
          objectType: "graph",
          riskTier: 5,
          reason: "PSD 目标态未找到对应内容，疑似被 UX 淘汰的旧视觉（§8 REMOVE_CANDIDATE）",
          controllerRefs: [],
          transitionRefs: [],
          relationRefs: [],
          referencedBy: [],
          runtimeBound: false,
          previewUrl: "",
          text: "",
          size: [40, 40],
          location: "",
        },
      ],
    },
  ],
  autoResolvedGroups: [],
};

describe("HifiRemovalReviewPanel", () => {
  it("shows the old visual evidence before the operator decides", () => {
    render(<HifiRemovalReviewPanel review={review} busy={false} onDecide={vi.fn()} />);
    expect(screen.getByRole("img", { name: "旧视觉预览 old_badge" })).toHaveAttribute(
      "src",
      "data:image/png;base64,QUJD",
    );
    expect(screen.getByText("限時活動")).toBeVisible();
    expect(screen.getByText(/无静态贴图（graph）/)).toBeVisible();
    expect(screen.getByText("24×18")).toBeVisible();
    expect(screen.getByText("100×24")).toBeVisible();
  });

  it("shows the PSD same-position crop as absence evidence", async () => {
    const loadPsdCrop = vi.fn(async () => "blob:crop");
    render(
      <HifiRemovalReviewPanel
        review={review}
        busy={false}
        onDecide={vi.fn()}
        psdCanvas={[1000, 1000]}
        itemBounds={{ "old:badge": [0.1, 0.2, 0.05, 0.04] }}
        loadPsdCrop={loadPsdCrop}
      />,
    );
    const crop = await screen.findByRole("img", {
      name: "PSD · 同位置画面（应无对应内容）",
    });
    expect(crop).toHaveAttribute("src", "blob:crop");
    expect(loadPsdCrop).toHaveBeenCalledWith([90, 190, 160, 250]);
  });

  it("submits group decisions with the current choices", async () => {
    const decide = vi.fn();
    render(<HifiRemovalReviewPanel review={review} busy={false} onDecide={decide} />);
    await userEvent.click(screen.getByRole("button", { name: "保留" }));
    await userEvent.click(screen.getByRole("button", { name: /确认并继续/ }));
    expect(decide).toHaveBeenCalledWith([{ groupId: "grp-1", decision: "preserve" }]);
  });
});
