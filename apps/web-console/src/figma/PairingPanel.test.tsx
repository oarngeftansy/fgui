import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PairingPanel } from "./PairingPanel";

const pairing = { version: 1 as const, code: "123456", expires_at: new Date(Date.now() + 60_000).toISOString(), console_credential: "browser-only-session" };
const device = { version: 1 as const, device_id: "internal-device", device_name: "Figma desktop", created_at: "2026-07-29T09:00:00Z" };
const selection = { version: 1 as const, selection_id: "a".repeat(32), display_name: "Checkout", top_level_summaries: [{ name: "Checkout", type: "FRAME" }], preview_urls: [], warnings: [] };

describe("PairingPanel", () => {
  it("shows a fresh six-digit code, devices, and the received selection", async () => {
    const onSelection = vi.fn();
    render(<PairingPanel
      onSelection={onSelection}
      createPairing={vi.fn().mockResolvedValue(pairing)}
      getStatus={vi.fn().mockResolvedValue({ version: 1, state: "paired", expires_at: pairing.expires_at, device })}
      getSelection={vi.fn().mockResolvedValue(selection)}
      listDevices={vi.fn().mockResolvedValue([device])}
      revokeDevice={vi.fn().mockResolvedValue(device)}
      cancelPairing={vi.fn().mockResolvedValue(null)}
    />);

    expect(await screen.findByText("123456")).toBeVisible();
    expect(screen.getByText("Figma desktop")).toBeVisible();
    await waitFor(() => expect(onSelection).toHaveBeenCalledWith(selection, pairing.console_credential));
    expect(screen.getByText("已连接 Figma，正在等待选择")).toBeVisible();
  });

  it("regenerates or cancels the code and can revoke a listed device", async () => {
    const createPairing = vi.fn().mockResolvedValue(pairing);
    const cancelPairing = vi.fn().mockResolvedValue(null);
    const revokeDevice = vi.fn().mockResolvedValue(device);
    render(<PairingPanel
      onSelection={vi.fn()}
      createPairing={createPairing}
      getStatus={vi.fn().mockResolvedValue({ version: 1, state: "waiting_for_device", expires_at: pairing.expires_at })}
      getSelection={vi.fn().mockResolvedValue(null)}
      listDevices={vi.fn().mockResolvedValue([device])}
      revokeDevice={revokeDevice}
      cancelPairing={cancelPairing}
    />);
    await screen.findByText("123456");
    await userEvent.click(screen.getByRole("button", { name: "重新生成配对码" }));
    await waitFor(() => expect(cancelPairing).toHaveBeenCalledWith(pairing.console_credential));
    expect(createPairing).toHaveBeenCalledTimes(2);
    await userEvent.click(screen.getByRole("button", { name: "撤销 Figma desktop" }));
    await waitFor(() => expect(revokeDevice).toHaveBeenCalledWith(pairing.console_credential, "internal-device"));
    await userEvent.click(screen.getByRole("button", { name: "取消配对" }));
    expect(screen.getByText("尚未创建配对码")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "开始配对" }));
    await waitFor(() => expect(createPairing).toHaveBeenCalledTimes(3));
  });

  it("does not start a follow-up selection request after unmount", async () => {
    let resolveStatus: ((value: { version: 1; state: "paired"; expires_at: string; device: typeof device }) => void) | undefined;
    const getSelection = vi.fn();
    const view = render(<PairingPanel
      onSelection={vi.fn()}
      createPairing={vi.fn().mockResolvedValue(pairing)}
      getStatus={vi.fn().mockImplementation(() => new Promise((resolve) => { resolveStatus = resolve; }))}
      getSelection={getSelection}
      listDevices={vi.fn().mockResolvedValue([])}
      revokeDevice={vi.fn()}
      cancelPairing={vi.fn()}
    />);
    await screen.findByText("123456");
    view.unmount();
    resolveStatus?.({ version: 1, state: "paired", expires_at: pairing.expires_at, device });
    await Promise.resolve();
    expect(getSelection).not.toHaveBeenCalled();
  });
});
