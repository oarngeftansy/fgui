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

  it("opens a real designer-safe selection landing route", async () => {
    window.history.pushState({}, "", `/figma/selections/${"a".repeat(32)}`);
    localStorage.setItem(`figma-selection-view:${"a".repeat(32)}`, JSON.stringify({ view: {
      version: 1, selection_id: "a".repeat(32), display_name: "Checkout", top_level_summaries: [{ name: "Checkout", type: "FRAME" }], preview_urls: [], warnings: [],
    }, expires_at: Date.now() + 60_000 }));
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Checkout" })).toBeVisible();
    expect(screen.getByRole("listitem")).toHaveTextContent("FRAME");
    expect(fetch).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
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

  it("honors a production Figma revoked status message", async () => {
    render(<PluginFramePage pluginId="123456789" exchange={vi.fn()} postToFigma={vi.fn()} />);

    window.dispatchEvent(
      new MessageEvent("message", {
        origin: "https://www.figma.com",
        source: window.parent,
        data: { pluginId: "123456789", pluginMessage: { type: "pairing-status", status: "revoked" } },
      }),
    );

    expect(await screen.findByText("此插件配对已撤销，请重新配对")).toBeVisible();
  });

  it("ignores sensitive messages from a wrong source, origin, or plugin id", async () => {
    render(<PluginFramePage pluginId="123456789" exchange={vi.fn()} postToFigma={vi.fn()} />);
    for (const event of [
      new MessageEvent("message", { origin: "https://www.figma.com", source: window, data: { pluginId: "123456789", pluginMessage: { type: "credential", credential: "secret" } } }),
      new MessageEvent("message", { origin: "https://other.example", source: window.parent, data: { pluginId: "123456789", pluginMessage: { type: "credential", credential: "secret" } } }),
      new MessageEvent("message", { origin: "https://www.figma.com", source: window.parent, data: { pluginId: "7", pluginMessage: { type: "credential", credential: "secret" } } }),
    ]) window.dispatchEvent(event);
    expect(screen.getByLabelText("配对码")).toBeVisible();
  });

  it("shows a current-selection preflight, prevents duplicate sends, and keeps task link fallbacks after opening", async () => {
    const postToFigma = vi.fn();
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<PluginFramePage pluginId="123456789" exchange={vi.fn()} postToFigma={postToFigma} upload={vi.fn().mockResolvedValue({ version: 1, selection_id: "a".repeat(32), display_name: "Checkout", top_level_summaries: [], preview_urls: [], warnings: [] })} />);

    window.dispatchEvent(new MessageEvent("message", { origin: "https://www.figma.com", source: window.parent, data: { pluginId: "123456789", pluginMessage: { type: "credential", credential: "opaque" } } }));
    await userEvent.click(await screen.findByRole("button", { name: "准备导出当前选择" }));
    expect(postToFigma).toHaveBeenLastCalledWith({ pluginId: "123456789", pluginMessage: { type: "selection-preflight" } }, "https://www.figma.com");

    const preflight = { sendable: true, nodeCount: 1, assetCount: 0, estimatedBytes: 0, warnings: [], manifest: { version: 1, display_name: "Checkout", top_level_nodes: [], resources: [], warnings: [] } };
    window.dispatchEvent(new MessageEvent("message", { origin: "https://www.figma.com", source: window.parent, data: { pluginId: "123456789", pluginMessage: { type: "selection-preflight", preflight } } }));
    await userEvent.click(await screen.findByRole("button", { name: "发送当前选择" }));
    expect(postToFigma).toHaveBeenLastCalledWith({ pluginId: "123456789", pluginMessage: expect.objectContaining({ type: "selection-export", attempt: expect.any(String) }) }, "https://www.figma.com");

    const manifest = { version: 1, display_name: "Checkout", top_level_nodes: [], resources: [], warnings: [] };
    window.dispatchEvent(new MessageEvent("message", { origin: "https://www.figma.com", source: window.parent, data: { pluginId: "123456789", pluginMessage: { type: "selection-export", attempt: postToFigma.mock.calls.at(-1)?.[0].pluginMessage.attempt, manifest, resources: [] } } }));
    expect(await screen.findByRole("link", { name: "打开任务" })).toBeVisible();
    expect(open).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "复制链接" })).toBeEnabled();
    open.mockRestore();
  });

  it("renders accessible progress reported by the hosted uploader", async () => {
    let reportProgress: ((progress: { completed: number; total: number }) => void) | undefined;
    const upload = vi.fn(async (_manifest, _resources, _credential, _idempotencyKey, onProgress) => {
      reportProgress = onProgress;
      return new Promise<never>(() => {});
    });
    const postToFigma = vi.fn();
    render(<PluginFramePage pluginId="123456789" exchange={vi.fn()} postToFigma={postToFigma} upload={upload} />);
    window.dispatchEvent(new MessageEvent("message", { origin: "https://www.figma.com", source: window.parent, data: { pluginId: "123456789", pluginMessage: { type: "credential", credential: "opaque" } } }));
    const preflight = { sendable: true, nodeCount: 1, assetCount: 2, estimatedBytes: 2, warnings: [], manifest: { version: 1 as const, display_name: "Checkout", top_level_nodes: [], resources: [], warnings: [] } };
    window.dispatchEvent(new MessageEvent("message", { origin: "https://www.figma.com", source: window.parent, data: { pluginId: "123456789", pluginMessage: { type: "selection-preflight", preflight } } }));
    await userEvent.click(await screen.findByRole("button", { name: "发送当前选择" }));
    window.dispatchEvent(new MessageEvent("message", { origin: "https://www.figma.com", source: window.parent, data: { pluginId: "123456789", pluginMessage: { type: "selection-export", attempt: postToFigma.mock.calls.at(-1)?.[0].pluginMessage.attempt, manifest: preflight.manifest, resources: [] } } }));

    await waitFor(() => expect(reportProgress).toBeTypeOf("function"));
    reportProgress?.({ completed: 1, total: 2 });
    expect(await screen.findByRole("progressbar")).toHaveAttribute("aria-valuenow", "1");
    expect(screen.getByRole("status")).toHaveTextContent("1 / 2");
  });

  it("keeps one idempotency key through a failed retry and reconnect, then rotates it for a new selection and cancellation", async () => {
    const upload = vi.fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({ version: 1, selection_id: "a".repeat(32), display_name: "Checkout", top_level_summaries: [], preview_urls: [], warnings: [] })
      .mockResolvedValueOnce({ version: 1, selection_id: "b".repeat(32), display_name: "Cart", top_level_summaries: [], preview_urls: [], warnings: [] });
    const postToFigma = vi.fn();
    render(<PluginFramePage pluginId="123456789" exchange={vi.fn()} postToFigma={postToFigma} upload={upload} />);
    const receive = (pluginMessage: object) => window.dispatchEvent(new MessageEvent("message", { origin: "https://www.figma.com", source: window.parent, data: { pluginId: "123456789", pluginMessage } }));
    const preflight = (name: string) => ({ sendable: true, nodeCount: 1, assetCount: 0, estimatedBytes: 0, warnings: [], manifest: { version: 1 as const, display_name: name, top_level_nodes: [], resources: [], warnings: [] } });
    const lastAttempt = () => postToFigma.mock.calls.at(-1)?.[0].pluginMessage.attempt;

    receive({ type: "credential", credential: "opaque" });
    receive({ type: "selection-preflight", preflight: preflight("Checkout") });
    await userEvent.click(await screen.findByRole("button", { name: "发送当前选择" }));
    const firstAttempt = lastAttempt();
    receive({ type: "selection-export", attempt: firstAttempt, manifest: preflight("Checkout").manifest, resources: [] });
    await screen.findByRole("alert");
    await userEvent.click(screen.getByRole("button", { name: "发送当前选择" }));
    const retryAttempt = lastAttempt();
    expect(retryAttempt).not.toBe(firstAttempt);
    receive({ type: "selection-export", attempt: firstAttempt, manifest: preflight("Checkout").manifest, resources: [] });
    receive({ type: "selection-export", attempt: retryAttempt, manifest: preflight("Checkout").manifest, resources: [] });
    await screen.findByRole("link", { name: "打开任务" });
    expect(upload.mock.calls[0]?.[3]).toBe(upload.mock.calls[1]?.[3]);

    receive({ type: "selection-preflight", preflight: preflight("Cart") });
    await userEvent.click(screen.getByRole("button", { name: "发送当前选择" }));
    receive({ type: "selection-export", attempt: lastAttempt(), manifest: preflight("Cart").manifest, resources: [] });
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(3));
    expect(upload.mock.calls[2]?.[3]).not.toBe(upload.mock.calls[1]?.[3]);

    await userEvent.click(screen.getByRole("button", { name: "取消配对" }));
    receive({ type: "credential", credential: "opaque" });
    receive({ type: "selection-export", attempt: lastAttempt(), manifest: preflight("Cart").manifest, resources: [] });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(upload).toHaveBeenCalledTimes(3);
  });

  it("keeps a committed upload successful when opening throws and gives safe clipboard recovery", async () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => { throw new Error("blocked popup"); });
    const clipboard = { writeText: vi.fn().mockRejectedValue(new Error("private clipboard details")) };
    Object.assign(navigator, { clipboard });
    const postToFigma = vi.fn();
    render(<PluginFramePage pluginId="123456789" exchange={vi.fn()} postToFigma={postToFigma} upload={vi.fn().mockResolvedValue({ version: 1, selection_id: "a".repeat(32), display_name: "Checkout", top_level_summaries: [], preview_urls: [], warnings: [] })} />);
    const receive = (pluginMessage: object) => window.dispatchEvent(new MessageEvent("message", { origin: "https://www.figma.com", source: window.parent, data: { pluginId: "123456789", pluginMessage } }));
    const preflight = { sendable: true, nodeCount: 1, assetCount: 0, estimatedBytes: 0, warnings: [], manifest: { version: 1 as const, display_name: "Checkout", top_level_nodes: [], resources: [], warnings: [] } };
    receive({ type: "credential", credential: "opaque" });
    receive({ type: "selection-preflight", preflight });
    await userEvent.click(await screen.findByRole("button", { name: "发送当前选择" }));
    receive({ type: "selection-export", attempt: postToFigma.mock.calls.at(-1)?.[0].pluginMessage.attempt, manifest: preflight.manifest, resources: [] });
    expect(await screen.findByRole("link", { name: "打开任务" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "复制链接" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("打开任务");
    expect(screen.queryByText(/private clipboard/i)).not.toBeInTheDocument();
    open.mockRestore();
  });

  it("ignores an old export message and deferred upload after a new preflight or unpair", async () => {
    let resolveUpload: ((view: { version: 1; selection_id: string; display_name: string; top_level_summaries: []; preview_urls: []; warnings: [] }) => void) | undefined;
    const upload = vi.fn(() => new Promise<{ version: 1; selection_id: string; display_name: string; top_level_summaries: []; preview_urls: []; warnings: [] }>((resolve) => { resolveUpload = resolve; }));
    const postToFigma = vi.fn();
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<PluginFramePage pluginId="123456789" exchange={vi.fn()} postToFigma={postToFigma} upload={upload} />);
    const receive = (pluginMessage: object) => window.dispatchEvent(new MessageEvent("message", { origin: "https://www.figma.com", source: window.parent, data: { pluginId: "123456789", pluginMessage } }));
    const preflight = (name: string) => ({ sendable: true, nodeCount: 1, assetCount: 0, estimatedBytes: 0, warnings: [], manifest: { version: 1 as const, display_name: name, top_level_nodes: [], resources: [], warnings: [] } });

    receive({ type: "credential", credential: "old-credential" });
    receive({ type: "selection-preflight", preflight: preflight("Checkout") });
    await userEvent.click(await screen.findByRole("button", { name: "发送当前选择" }));
    const firstAttempt = postToFigma.mock.calls.at(-1)?.[0].pluginMessage.attempt;
    receive({ type: "selection-export", attempt: firstAttempt, manifest: preflight("Checkout").manifest, resources: [] });
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));

    receive({ type: "selection-preflight", preflight: preflight("Cart") });
    receive({ type: "selection-export", attempt: firstAttempt, manifest: preflight("Checkout").manifest, resources: [] });
    resolveUpload?.({ version: 1, selection_id: "a".repeat(32), display_name: "Checkout", top_level_summaries: [], preview_urls: [], warnings: [] });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(upload).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link", { name: "打开任务" })).not.toBeInTheDocument();
    expect(open).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "发送当前选择" }));
    const secondAttempt = postToFigma.mock.calls.at(-1)?.[0].pluginMessage.attempt;
    receive({ type: "selection-export", attempt: secondAttempt, manifest: preflight("Cart").manifest, resources: [] });
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    await userEvent.click(screen.getByRole("button", { name: "取消配对" }));
    resolveUpload?.({ version: 1, selection_id: "b".repeat(32), display_name: "Cart", top_level_summaries: [], preview_urls: [], warnings: [] });
    receive({ type: "selection-export", attempt: firstAttempt, manifest: preflight("Checkout").manifest, resources: [] });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(upload).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("link", { name: "打开任务" })).not.toBeInTheDocument();
    expect(open).not.toHaveBeenCalled();
    open.mockRestore();
  });

  it("starts a new export attempt after the main plugin reports an export error", async () => {
    const postToFigma = vi.fn();
    render(<PluginFramePage pluginId="123456789" exchange={vi.fn()} postToFigma={postToFigma} upload={vi.fn()} />);
    const receive = (pluginMessage: object) => window.dispatchEvent(new MessageEvent("message", { origin: "https://www.figma.com", source: window.parent, data: { pluginId: "123456789", pluginMessage } }));
    const preflight = { sendable: true, nodeCount: 1, assetCount: 0, estimatedBytes: 0, warnings: [], manifest: { version: 1 as const, display_name: "Checkout", top_level_nodes: [], resources: [], warnings: [] } };
    receive({ type: "credential", credential: "opaque" });
    receive({ type: "selection-preflight", preflight });

    await userEvent.click(await screen.findByRole("button", { name: "发送当前选择" }));
    const firstAttempt = postToFigma.mock.calls.at(-1)?.[0].pluginMessage.attempt;
    receive({ type: "selection-error", attempt: firstAttempt, code: "selection_export_failed" });
    await screen.findByRole("alert");
    await userEvent.click(screen.getByRole("button", { name: "发送当前选择" }));

    expect(postToFigma.mock.calls.at(-1)?.[0].pluginMessage.attempt).not.toBe(firstAttempt);
  });
});
