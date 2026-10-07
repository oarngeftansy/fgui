import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { HifiMappingDraft, PsdLayer } from "../../../figma-plugin/src/project-client";
import { HifiMappingPanel } from "./HifiMappingPanel";

const mapping: HifiMappingDraft = { mappingRevision: 2, unresolvedCount: 2, items: [
  { itemId: "old:done", oldObjectId: "done", oldName: "Done", figmaNodeId: "figma-done", figmaName: "Done", status: "matched", score: 1, action: "accept", candidates: ["figma-done"], oldBounds: [.02, .02, .06, .04], figmaBounds: [.02, .02, .06, .04] },
  { itemId: "old:title", oldObjectId: "title", oldName: "Title", figmaNodeId: "figma-title", figmaName: "Title", status: "uncertain", score: .7, candidates: ["figma-title"], oldBounds: [.1, .1, .2, .1], figmaBounds: [.1, .1, .2, .1] },
  { itemId: "new:dialog", figmaNodeId: "figma-dialog", figmaName: "Dialog", status: "blocked", score: 1, candidates: [], figmaBounds: [.4, .3, .3, .4] },
] };

describe("HifiMappingPanel", () => {
  it("explains automatically preserved structures without allowing manual structure waivers", () => {
    const structural: HifiMappingDraft = { mappingRevision: 1, unresolvedCount: 0, items: [{ itemId: "old:layout", oldObjectId: "layout", oldName: "Layout", oldObjectType: "group", status: "structural", action: "preserve_structure", score: 0, candidates: [], oldBounds: [0,0,1,1] }] };
    const { container } = render(<HifiMappingPanel mapping={structural} busy={false} onCurrentChange={vi.fn()} onDecision={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("button", { name: "保留旧对象" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "确认对应" })).not.toBeInTheDocument();
  });
  it("navigates pending items and resolves a blocked item as an exception", async () => {
    const decide = vi.fn();
    function Harness() {
      const [current, setCurrent] = useState("old:title");
      return <HifiMappingPanel mapping={mapping} currentItemId={current} busy={false} onCurrentChange={setCurrent} onDecision={decide} onLocate={vi.fn()} />;
    }
    render(<Harness />);
    expect(screen.getByText("1 / 2")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "下一项" }));
    expect(screen.getByText("2 / 2")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "列为例外（人工处理）" }));
    expect(decide).toHaveBeenCalledWith(expect.objectContaining({ itemId: "new:dialog" }), "exception");
  });

  it("shows the old FGUI look and a native-resolution PSD crop of the current object", async () => {
    const loadPsdCrop = vi.fn(async () => "blob:psd-crop");
    render(<HifiMappingPanel mapping={mapping} currentItemId="old:title" busy={false} onCurrentChange={vi.fn()} onDecision={vi.fn()} psdCanvas={[1000, 2000]} loadPsdCrop={loadPsdCrop} oldPreviewUrl="blob:old-resource" />);
    const crop = await screen.findByRole("img", { name: /PSD · 该位置目标态画面/ });
    expect(crop).toHaveAttribute("src", "blob:psd-crop");
    expect(loadPsdCrop).toHaveBeenCalledWith([64, 164, 336, 436]);
    expect(screen.getByRole("img", { name: "旧 FGUI 对象资源图" })).toHaveAttribute("src", "blob:old-resource");
  });

  it("offers to map an unmatched PSD item to an existing FGUI object first", async () => {
    const decide = vi.fn();
    render(<HifiMappingPanel mapping={{ ...mapping, items: [...mapping.items, { itemId: "new:art", figmaNodeId: "figma-art", figmaName: "Artwork", status: "hifi_added", score: 1, candidates: [], figmaBounds: [.2, .2, .1, .1] }], unresolvedCount: 3 }} currentItemId="new:art" busy={false} onCurrentChange={vi.fn()} onDecision={decide} />);

    await userEvent.click(screen.getByRole("button", { name: "更换图层" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "对应的旧 FGUI 对象" }), "old:title");
    await userEvent.click(screen.getByRole("button", { name: "建立对应" }));
    expect(decide).toHaveBeenCalledWith(expect.objectContaining({ itemId: "old:title" }), "retarget", "figma-art");
  });

  it("does not offer direct visual addition in the PSD replacement workflow", () => {
    render(<HifiMappingPanel mapping={{ ...mapping, items: [...mapping.items, { itemId: "new:art", figmaNodeId: "figma-art", figmaName: "Artwork", status: "hifi_added", score: 1, candidates: [], figmaBounds: [.2, .2, .1, .1] }] }} currentItemId="new:art" busy={false} onCurrentChange={vi.fn()} onDecision={vi.fn()} allowVisualAddition={false} />);

    expect(screen.queryByRole("button", { name: "标记为新增视觉" })).not.toBeInTheDocument();
    expect(screen.getByText(/当前不能直接新增/)).toBeVisible();
    expect(screen.getByRole("button", { name: "暂不处理" })).toBeVisible();
  });

  it("can show extended review without offering old PSD visuals as a resolution", () => {
    const excessive = { ...mapping, unresolvedCount: 6, items: Array.from({ length: 6 }, (_, index) => ({ ...mapping.items[1], itemId: `old:${index}`, oldObjectId: `${index}` })) };
    render(<HifiMappingPanel mapping={excessive} currentItemId="old:0" busy={false} onCurrentChange={vi.fn()} onDecision={vi.fn()} allowKeepOld={false} />);
    expect(screen.getByText("1 / 6")).toBeVisible();
    expect(screen.getByRole("button", { name: "确认对应" })).toBeVisible();
    expect(screen.getByRole("button", { name: "更换图层" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /列为例外|暂不处理|隐藏旧视觉/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "保留旧对象" })).not.toBeInTheDocument();
  });

  it("offers PSD-undrawn old objects an explicit exception path", async () => {
    const decide = vi.fn();
    const unmapped = { ...mapping, unresolvedCount: 2, items: [mapping.items[0], { itemId: "old:loader", oldObjectId: "loader", oldName: "icon", oldObjectType: "loader", status: "fgui_only" as const, score: .4, candidates: [], oldBounds: [.1, .5, .05, .03] as [number, number, number, number] }] };
    render(<HifiMappingPanel mapping={unmapped} currentItemId="old:loader" busy={false} onCurrentChange={vi.fn()} onDecision={decide} />);

    expect(screen.getByText(/PSD 没有画这个旧对象/)).toBeVisible();
    const skip = screen.getByRole("button", { name: "隐藏旧视觉" });
    expect(skip).toBeVisible();
    await userEvent.click(skip);
    expect(decide).toHaveBeenCalledWith(expect.objectContaining({ itemId: "old:loader" }), "exception");
    expect(screen.queryByRole("button", { name: "确认对应" })).not.toBeInTheDocument();
  });

  it("lets an operator pair a PSD-undrawn object with a designer cutout", async () => {
    const decide = vi.fn();
    const unmapped = { ...mapping, unresolvedCount: 2, items: [mapping.items[0], { itemId: "old:badge", oldObjectId: "badge", oldName: "Badge", oldObjectType: "image", status: "fgui_only" as const, score: .4, candidates: [], oldBounds: [.1, .5, .05, .03] as [number, number, number, number] }] };
    render(<HifiMappingPanel mapping={unmapped} currentItemId="old:badge" busy={false} onCurrentChange={vi.fn()} onDecision={vi.fn()} />);

    expect(screen.queryByRole("combobox", { name: "从切图池人工配对" })).not.toBeInTheDocument();

    render(
      <HifiMappingPanel
        mapping={unmapped}
        currentItemId="old:badge"
        busy={false}
        onCurrentChange={vi.fn()}
        onDecision={decide}
        cutouts={["PVP金币底.png", "宝箱关闭.png"]}
        cutoutThumbnails={{ "PVP金币底.png": "data:image/png;base64,QUJD" }}
      />,
    );
    const select = screen.getByRole("combobox", { name: "从切图池人工配对" });
    await userEvent.selectOptions(select, "PVP金币底.png");
    expect(
      screen.getByRole("img", { name: "切图预览 PVP金币底.png" }),
    ).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "使用所选切图" }));
    expect(decide).toHaveBeenCalledWith(
      expect.objectContaining({ itemId: "old:badge" }),
      "retarget",
      "cutout:PVP金币底.png",
    );
  });

  it("labels controller-hidden objects as non-default state work", () => {
    const hidden = { ...mapping, items: mapping.items.map((item) => item.itemId === "old:title" ? { ...item, defaultVisible: false } : item) };
    render(<HifiMappingPanel mapping={hidden} currentItemId="old:title" busy={false} onCurrentChange={vi.fn()} onDecision={vi.fn()} />);
    expect(screen.getByText(/单独验收非默认页的新视觉/)).toBeVisible();
  });
});
