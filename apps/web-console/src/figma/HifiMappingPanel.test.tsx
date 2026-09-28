import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { HifiMappingDraft } from "../../../figma-plugin/src/project-client";
import { HifiMappingPanel } from "./HifiMappingPanel";

const mapping: HifiMappingDraft = { mappingRevision: 2, unresolvedCount: 2, items: [
  { itemId: "old:done", oldObjectId: "done", oldName: "Done", figmaNodeId: "figma-done", figmaName: "Done", status: "matched", score: 1, action: "accept", candidates: ["figma-done"], oldBounds: [.02, .02, .06, .04], figmaBounds: [.02, .02, .06, .04] },
  { itemId: "old:title", oldObjectId: "title", oldName: "Title", figmaNodeId: "figma-title", figmaName: "Title", status: "uncertain", score: .7, candidates: ["figma-title"], oldBounds: [.1, .1, .2, .1], figmaBounds: [.1, .1, .2, .1] },
  { itemId: "new:dialog", figmaNodeId: "figma-dialog", figmaName: "Dialog", status: "blocked", score: 1, candidates: [], figmaBounds: [.4, .3, .3, .4] },
] };

describe("HifiMappingPanel", () => {
  it("moves both structure highlights and resolves a blocked item as an exception", async () => {
    const decide = vi.fn();
    function Harness() {
      const [current, setCurrent] = useState("old:title");
      return <HifiMappingPanel mapping={mapping} currentItemId={current} busy={false} onCurrentChange={setCurrent} onDecision={decide} onLocate={vi.fn()} />;
    }
    render(<Harness />);
    expect(screen.getByRole("button", { name: "待确认 2" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("1 / 2")).toBeVisible();
    expect(screen.getByTestId("fgui-focus")).toHaveAccessibleName("旧 FGUI · Title");
    expect(screen.getByTestId("hifi-focus")).toHaveAccessibleName("HIFI · Title");
    await userEvent.click(screen.getByRole("button", { name: "下一项" }));
    expect(screen.getByText("2 / 2")).toBeVisible();
    expect(screen.getByTestId("fgui-focus")).toHaveTextContent("此侧无对应对象");
    expect(screen.getByTestId("hifi-focus")).toHaveAccessibleName("HIFI · Dialog");
    await userEvent.click(screen.getByRole("button", { name: "列为例外并保留人工处理" }));
    expect(decide).toHaveBeenCalledWith(expect.objectContaining({ itemId: "new:dialog" }), "exception");
  });

  it("shows the actual PSD image behind the HIFI focus instead of an empty grid", () => {
    render(<HifiMappingPanel mapping={mapping} currentItemId="old:title" busy={false} onCurrentChange={vi.fn()} onDecision={vi.fn()} psdPreviewUrl="blob:psd-composite" canvasSize={{ width: 1080, height: 2340 }} />);

    expect(screen.getByRole("img", { name: "HIFI PSD 实际画面" })).toHaveAttribute("src", "blob:psd-composite");
  });

  it("offers to map an unmatched PSD item to an existing FGUI object first", async () => {
    const decide = vi.fn();
    render(<HifiMappingPanel mapping={{ ...mapping, items: [...mapping.items, { itemId: "new:art", figmaNodeId: "figma-art", figmaName: "Artwork", status: "hifi_added", score: 1, candidates: [], figmaBounds: [.2, .2, .1, .1] }], unresolvedCount: 3 }} currentItemId="new:art" busy={false} onCurrentChange={vi.fn()} onDecision={decide} />);

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "对应的旧 FGUI 对象" }), "old:title");
    await userEvent.click(screen.getByRole("button", { name: "建立一对一对应" }));
    expect(decide).toHaveBeenCalledWith(expect.objectContaining({ itemId: "old:title" }), "retarget", "figma-art");
  });

  it("does not offer direct visual addition in the PSD replacement workflow", () => {
    render(<HifiMappingPanel mapping={{ ...mapping, items: [...mapping.items, { itemId: "new:art", figmaNodeId: "figma-art", figmaName: "Artwork", status: "hifi_added", score: 1, candidates: [], figmaBounds: [.2, .2, .1, .1] }] }} currentItemId="new:art" busy={false} onCurrentChange={vi.fn()} onDecision={vi.fn()} allowVisualAddition={false} />);

    expect(screen.queryByText("确实没有旧对象？")).not.toBeInTheDocument();
    expect(screen.getByText(/当前不能直接新增/)).toBeVisible();
  });

  it("stops manual review when automatic mapping exceeds five object decisions", () => {
    const excessive = { ...mapping, unresolvedCount: 6, items: Array.from({ length: 6 }, (_, index) => ({ ...mapping.items[1], itemId: `old:${index}`, oldObjectId: `${index}` })) };
    render(<HifiMappingPanel mapping={excessive} currentItemId="old:0" busy={false} onCurrentChange={vi.fn()} onDecision={vi.fn()} reviewLimit={5} />);

    expect(screen.getByText(/超过最多 5 个对象的人工判断上限/)).toBeVisible();
    expect(screen.getByText("1 / 5")).toBeVisible();
    expect(screen.queryByRole("button", { name: "应用对应" })).not.toBeInTheDocument();
  });
});
