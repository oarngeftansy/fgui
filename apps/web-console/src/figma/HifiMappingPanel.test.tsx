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
    render(<HifiMappingPanel mapping={structural} busy={false} onCurrentChange={vi.fn()} onDecision={vi.fn()} />);
    expect(screen.getByText(/审计摘要：非绘制结构已保留 1/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "保留旧对象" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "确认对应" })).not.toBeInTheDocument();
  });
  it("moves both structure highlights and resolves a blocked item as an exception", async () => {
    const decide = vi.fn();
    function Harness() {
      const [current, setCurrent] = useState("old:title");
      return <HifiMappingPanel mapping={mapping} currentItemId={current} busy={false} onCurrentChange={setCurrent} onDecision={decide} onLocate={vi.fn()} />;
    }
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "叶子诊断" }));
    expect(screen.getByRole("button", { name: "待确认 2" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("1 / 2")).toBeVisible();
    expect(screen.getByTestId("fgui-focus")).toHaveAccessibleName("旧 FGUI · Title");
    expect(screen.getByTestId("hifi-focus")).toHaveAccessibleName("HIFI · Title");
    await userEvent.click(screen.getByRole("button", { name: "下一项" }));
    expect(screen.getByText("2 / 2")).toBeVisible();
    expect(screen.getByTestId("fgui-focus")).toHaveTextContent("此侧无对应对象");
    expect(screen.getByTestId("hifi-focus")).toHaveAccessibleName("HIFI · Dialog");
    await userEvent.click(screen.getByRole("button", { name: "列为例外（人工处理）" }));
    expect(decide).toHaveBeenCalledWith(expect.objectContaining({ itemId: "new:dialog" }), "exception");
  });

  it("fits each preview to its own page dimensions and can focus the current object", async () => {
    const sized = { ...mapping, oldCanvasSize: { width: 1080, height: 1920 }, sourceCanvasSize: { width: 1080, height: 2340 } };
    render(<HifiMappingPanel mapping={sized} currentItemId="old:title" busy={false} onCurrentChange={vi.fn()} onDecision={vi.fn()} psdPreviewUrl="blob:psd-composite" />);

    const image = screen.getByRole("img", { name: "HIFI PSD 实际画面" });
    expect(image).toHaveAttribute("src", "blob:psd-composite");
    expect(image).toHaveStyle({ width: "100%", height: "100%" });
    expect(screen.getByLabelText("旧 FGUI 结构")).toHaveStyle({ aspectRatio: "1080 / 1920" });
    expect(screen.getByLabelText("HIFI 结构")).toHaveStyle({ aspectRatio: "1080 / 2340" });
    expect(screen.getByRole("button", { name: "完整页面" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "聚焦当前对象" }));
    expect(screen.getByRole("button", { name: "聚焦当前对象" })).toHaveAttribute("aria-pressed", "true");
    expect(image).not.toHaveStyle({ width: "100%" });
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

  it("labels controller-hidden objects as non-default state work", () => {
    const hidden = { ...mapping, items: mapping.items.map((item) => item.itemId === "old:title" ? { ...item, defaultVisible: false } : item) };
    render(<HifiMappingPanel mapping={hidden} currentItemId="old:title" busy={false} onCurrentChange={vi.fn()} onDecision={vi.fn()} />);
    expect(screen.getByText(/审计摘要：默认页不可见 1/)).toBeVisible();
    expect(screen.getByText(/单独验收非默认页的新视觉/)).toBeVisible();
  });
  it("shows semantic component and PSD group units instead of leaf wireframes", async () => {
    const grouped: HifiMappingDraft = { mappingRevision: 1, unresolvedCount: 0, items: [
      { itemId: "old:card", oldObjectId: "card", oldName: "Card", oldObjectType: "component", status: "matched", score: 1, action: "accept", candidates: [], oldBounds: [.1, .1, .5, .5], figmaNodeId: "psd-layer:s:10", figmaName: "Card Group", figmaBounds: [.1, .1, .5, .5], ownedGroupId: "psd-layer:s:10" },
      { itemId: "old:card:img", oldObjectId: "card:img", oldName: "img", oldObjectType: "image", status: "matched", score: .9, action: "accept", candidates: [], oldBounds: [.12, .12, .2, .2], figmaNodeId: "psd-layer:s:11", figmaBounds: [.12, .12, .2, .2] },
    ] };
    const layers = [
      { id: "psd-layer:s:10", name: "Card Group", kind: "group", bounds: [100, 100, 600, 600] },
      { id: "psd-layer:s:11", name: "img", kind: "pixel", parentId: "psd-layer:s:10", bounds: [120, 120, 320, 320] },
    ] as unknown as PsdLayer[];
    render(<HifiMappingPanel mapping={grouped} currentItemId="old:card:img" busy={false} onCurrentChange={vi.fn()} onDecision={vi.fn()} psdLayers={layers} />);
    expect(screen.getByRole("button", { name: "旧 FGUI · Card" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "旧 FGUI · img" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "HIFI · Card Group" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "叶子诊断" }));
    expect(screen.getByRole("button", { name: "旧 FGUI · img" })).toBeVisible();
  });

  it("previews the selected PSD candidate on the structure canvas before deciding", async () => {
    const layers = [
      { id: "psd-layer:s:20", name: "Alt", kind: "pixel", bounds: [200, 200, 400, 400] },
    ] as unknown as PsdLayer[];
    const draft: HifiMappingDraft = { mappingRevision: 1, unresolvedCount: 1, sourceCanvasSize: { width: 1000, height: 1000 }, items: [
      { itemId: "old:a", oldObjectId: "a", oldName: "A", oldObjectType: "image", status: "uncertain", score: .5, candidates: ["psd-layer:s:20"], oldBounds: [.1, .1, .2, .2], figmaNodeId: "psd-layer:s:21", figmaBounds: [.3, .3, .2, .2] },
    ] };
    render(<HifiMappingPanel mapping={draft} currentItemId="old:a" busy={false} onCurrentChange={vi.fn()} onDecision={vi.fn()} psdLayers={layers} />);
    expect(document.querySelectorAll(".hifi-canvas-preview")).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "更换图层" }));
    expect(document.querySelectorAll(".hifi-canvas-preview")).toHaveLength(1);
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "换成哪个图层" }), "psd-layer:s:20");
    expect(document.querySelectorAll(".hifi-canvas-preview")).toHaveLength(1);
  });

  it("selects a resolved canvas object by switching the list to all records", async () => {
    const select = vi.fn();
    function Harness() {
      const [current, setCurrent] = useState("old:title");
      return <HifiMappingPanel mapping={mapping} currentItemId={current} busy={false} onCurrentChange={(id) => { select(id); setCurrent(id); }} onDecision={vi.fn()} />;
    }
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "叶子诊断" }));
    await userEvent.click(screen.getByRole("button", { name: "旧 FGUI · Done" }));
    expect(screen.getByRole("button", { name: "全部 3" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("fgui-focus")).toHaveAccessibleName("旧 FGUI · Done");
    await userEvent.click(screen.getByRole("button", { name: "待确认 2" }));
    expect(select).toHaveBeenLastCalledWith("old:title");
    expect(screen.getByTestId("fgui-focus")).toHaveAccessibleName("旧 FGUI · Title");
  });

});
