import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { PluginFramePage } from "./PluginFramePage";

describe("PluginFramePage", () => {
  it("is available at the hosted /figma-plugin route", () => {
    window.history.pushState({}, "", "/figma-plugin?pluginId=123456789");
    render(<App />);

    expect(screen.getByRole("heading", { name: "连接 Figma 插件" })).toBeVisible();
  });

  it("shows an accessible pairing form and validates six-digit codes locally", async () => {
    const exchange = vi.fn();
    render(<PluginFramePage pluginId="123456789" exchange={exchange} postToFigma={vi.fn()} />);

    await userEvent.type(screen.getByLabelText("配对码"), "12345");
    await userEvent.click(screen.getByRole("button", { name: "完成配对" }));

    expect(screen.getByRole("alert")).toHaveTextContent("请输入六位数字配对码");
    expect(exchange).not.toHaveBeenCalled();
    expect(screen.getByLabelText("配对码")).toHaveFocus();
  });

  it("pairs once with safe status and targets the exact Figma origin and plugin id", async () => {
    const exchange = vi.fn().mockResolvedValue({ credential: "opaque-credential" });
    const postToFigma = vi.fn();
    render(<PluginFramePage pluginId="123456789" exchange={exchange} postToFigma={postToFigma} />);

    await userEvent.type(screen.getByLabelText("配对码"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "完成配对" }));

    await waitFor(() => expect(postToFigma).toHaveBeenCalledTimes(1));
    expect(postToFigma).toHaveBeenCalledWith(
      { pluginId: "123456789", pluginMessage: { type: "pairing-credential", credential: "opaque-credential" } },
      "https://www.figma.com",
    );
    expect(screen.getByText("已完成配对")).toBeVisible();
  });

  it("returns to pairing after requesting an unpair", async () => {
    const postToFigma = vi.fn();
    const exchange = vi.fn().mockResolvedValue({ credential: "opaque-credential" });
    render(<PluginFramePage pluginId="123456789" exchange={exchange} postToFigma={postToFigma} />);

    await userEvent.type(screen.getByLabelText("配对码"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "完成配对" }));
    await screen.findByText("已完成配对");
    await userEvent.click(screen.getByRole("button", { name: "取消配对" }));

    expect(postToFigma).toHaveBeenLastCalledWith(
      { pluginId: "123456789", pluginMessage: { type: "unpair" } },
      "https://www.figma.com",
    );
    expect(screen.getByLabelText("配对码")).toBeVisible();
  });

  it("prevents double submission and renders only safe server failure copy", async () => {
    let rejectExchange: ((reason?: unknown) => void) | undefined;
    const exchange = vi.fn<(code: string, deviceName: string) => Promise<{ credential: string }>>(
      () =>
        new Promise<{ credential: string }>((_, reject) => {
          rejectExchange = reject;
        }),
    );
    render(<PluginFramePage pluginId="123456789" exchange={exchange} postToFigma={vi.fn()} />);

    await userEvent.type(screen.getByLabelText("配对码"), "123456");
    const submit = screen.getByRole("button", { name: "完成配对" });
    await userEvent.dblClick(submit);
    expect(exchange).toHaveBeenCalledTimes(1);
    expect(submit).toBeDisabled();

    rejectExchange?.({ detail: { code: "pairing_code_expired", message: "C:\\private\\credential" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("配对码已过期，请获取新的配对码");
    expect(screen.queryByText(/private|credential/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试配对" })).toBeEnabled();
  });

  it("shows the revoked state and lets the user begin pairing again", async () => {
    const { rerender } = render(<PluginFramePage pluginId="123456789" exchange={vi.fn()} postToFigma={vi.fn()} status="revoked" />);

    expect(screen.getByText("此插件配对已撤销，请重新配对")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "重新配对" }));
    rerender(<PluginFramePage pluginId="123456789" exchange={vi.fn()} postToFigma={vi.fn()} />);
    expect(screen.getByLabelText("配对码")).toBeVisible();
  });
});
