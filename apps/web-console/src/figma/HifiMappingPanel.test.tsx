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
});
