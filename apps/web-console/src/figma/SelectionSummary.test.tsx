import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SelectionSummary } from "./SelectionSummary";

const selection = {
  version: 1 as const,
  selection_id: "a".repeat(32),
  display_name: "Checkout",
  top_level_summaries: [{ name: "Checkout", type: "FRAME" }],
  preview_urls: ["/preview"],
  warnings: [{ code: "unsupported", message: "一个图层未包含在转换中" }],
};

describe("SelectionSummary", () => {
  it("shows safe names, thumbnails, and warnings without internal identifiers", async () => {
    render(<SelectionSummary selection={selection} session="browser-only" loadPreview={vi.fn().mockResolvedValue("blob:preview")} />);
    expect(screen.getByRole("heading", { name: "Checkout" })).toBeVisible();
    expect(screen.getByText("Checkout · FRAME")).toBeVisible();
    expect(screen.getByText("一个图层未包含在转换中")).toBeVisible();
    expect(await screen.findByRole("img", { name: "Checkout 选择预览 1" })).toHaveAttribute("src", "blob:preview");
    expect(screen.queryByText("a".repeat(32))).not.toBeInTheDocument();
  });
});
