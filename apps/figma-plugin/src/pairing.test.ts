import { afterEach, describe, expect, it, vi } from "vitest";
import { buildManifest } from "../scripts/build-manifest.mjs";
import { postToFigma } from "./bootstrap";
import { startPlugin } from "./code";
import {
  CredentialStore,
  PairingClient,
  PairingValidationError,
  createMainPairingController,
  validatePairingCode,
} from "./pairing";

class FakeStorage {
  value: unknown;

  async getAsync(_key: string) {
    return this.value;
  }

  async setAsync(_key: string, value: unknown) {
    this.value = value;
  }

  async deleteAsync(_key: string) {
    this.value = undefined;
  }
}

afterEach(() => vi.unstubAllGlobals());

describe("plugin manifest", () => {
  it("accepts exactly one HTTPS company origin and plugin id", () => {
    expect(buildManifest("https://fgui.corp.example", "123456789").networkAccess.allowedDomains).toEqual([
      "https://fgui.corp.example",
    ]);
  });

  it.each(["http://fgui.corp.example", "*", "https://one.example,https://two.example"])(
    "rejects unsafe origin %s",
    (origin: string) => expect(() => buildManifest(origin, "123456789")).toThrow(),
  );

  it.each(["", "plugin-id", "*"])("rejects a non-numeric plugin id %s", (pluginId: string) => {
    expect(() => buildManifest("https://fgui.corp.example", pluginId)).toThrow();
  });
});

describe("pairing", () => {
  it.each(["12345", "1234567", "12ab56", "１２３４５６"])("rejects an invalid local pairing code", (code: string) => {
    expect(() => validatePairingCode(code)).toThrow(PairingValidationError);
  });

  it("exchanges a valid code and maps server errors without exposing details", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ version: 1, credential: "credential", device: { device_id: "device" } }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: { code: "pairing_code_expired", message: "C:\\private\\secret" } }), { status: 400 }),
      );
    const client = new PairingClient(fetchImpl);

    await expect(client.exchange("123456", "Figma desktop")).resolves.toEqual({
      credential: "credential",
      deviceId: "device",
    });
    await expect(client.exchange("123456", "Figma desktop")).rejects.toThrow("配对码已过期，请获取新的配对码");
    expect(fetchImpl).toHaveBeenCalledWith(
      "/v1/figma/pairings/exchange",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("calls the browser fetch function without rebinding its receiver", async () => {
    const browserFetch = vi.fn(function (this: unknown) {
      expect(this).toBeUndefined();
      return Promise.resolve(
        new Response(JSON.stringify({ version: 1, credential: "credential", device: { device_id: "device" } }), {
          status: 200,
        }),
      );
    });
    vi.stubGlobal("fetch", browserFetch);

    const client = new PairingClient();

    await expect(client.exchange("123456", "Figma desktop")).resolves.toEqual({
      credential: "credential",
      deviceId: "device",
    });
  });

  it.each([
    { version: 1, credential: "credential", device: { device_id: "" } },
    { version: 1, credential: "", device: { device_id: "device" } },
  ])("rejects an incomplete successful pairing response", async (payload: { version: number; credential: string; device: { device_id: string } }) => {
    const client = new PairingClient(vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 })));

    await expect(client.exchange("123456", "Figma desktop")).rejects.toThrow("配对未完成");
  });

  it("restores and revokes the main-owned credential while targeting only the company origin", async () => {
    const storage = new FakeStorage();
    const store = new CredentialStore(storage);
    await store.save("credential");
    const post = vi.fn();
    const controller = createMainPairingController(
      { serverOrigin: "https://fgui.corp.example", pluginId: "123456789" },
      store,
      post,
    );

    await controller.restore();
    expect(post).toHaveBeenLastCalledWith(
      { type: "credential", credential: "credential" },
      "https://fgui.corp.example",
    );
    await controller.handle({ type: "unpair" });
    expect(await store.load()).toBeNull();
    expect(post).toHaveBeenLastCalledWith({ type: "pairing-status", status: "unpaired" }, "https://fgui.corp.example");
  });

  it("ignores sensitive hosted messages from a missing or wrong Figma UI origin", async () => {
    vi.stubGlobal("__html__", "<html></html>");
    const storage = new FakeStorage();
    const runtime = {
      clientStorage: storage,
      showUI: vi.fn(),
      ui: { onmessage: undefined as ((message: unknown, props: { origin: string }) => void) | undefined, postMessage: vi.fn() },
    };
    startPlugin({ serverOrigin: "https://fgui.corp.example", pluginId: "123456789" }, runtime);
    const receive = runtime.ui.onmessage!;

    receive({ type: "pairing-credential", credential: "wrong-origin" }, { origin: "https://other.example" });
    await Promise.resolve();
    expect(await storage.getAsync("figma-to-fairygui-plugin-credential")).toBeUndefined();

    receive({ type: "pairing-credential", credential: "missing-origin" }, { origin: "" });
    await Promise.resolve();
    expect(await storage.getAsync("figma-to-fairygui-plugin-credential")).toBeUndefined();
  });

  it("stores a credential only when Figma reports the exact hosted UI origin", async () => {
    vi.stubGlobal("__html__", "<html></html>");
    const storage = new FakeStorage();
    const runtime = {
      clientStorage: storage,
      showUI: vi.fn(),
      ui: { onmessage: undefined as ((message: unknown, props: { origin: string }) => void) | undefined, postMessage: vi.fn() },
    };
    startPlugin({ serverOrigin: "https://fgui.corp.example", pluginId: "123456789" }, runtime);

    runtime.ui.onmessage!({ type: "pairing-credential", credential: "trusted" }, { origin: "https://fgui.corp.example" });
    await Promise.resolve();
    expect(await storage.getAsync("figma-to-fairygui-plugin-credential")).toBe("trusted");
  });

  it("targets hosted iframe messages to Figma with the exact configured plugin id", () => {
    const post = vi.fn();

    postToFigma(post, "123456789", { type: "unpair" });

    expect(post).toHaveBeenCalledWith(
      { pluginId: "123456789", pluginMessage: { type: "unpair" } },
      "https://www.figma.com",
    );
  });

  it("snapshots only the current selection and sends preflight data to the exact hosted origin", async () => {
    vi.stubGlobal("__html__", "<html></html>");
    const postMessage = vi.fn();
    const selected = {
      id: "raw:node-id", name: "Checkout", type: "FRAME", visible: true, locked: false, opacity: 1,
      absoluteBoundingBox: { x: 0, y: 0, width: 1, height: 1 }, children: [],
    } as unknown as SceneNode;
    const runtime = {
      clientStorage: new FakeStorage(), showUI: vi.fn(), currentPage: { selection: [selected] },
      ui: { onmessage: undefined as ((message: unknown, props: { origin: string }) => void) | undefined, postMessage },
    };
    startPlugin({ serverOrigin: "https://fgui.corp.example", pluginId: "123456789" }, runtime);

    runtime.ui.onmessage!({ type: "selection-preflight" }, { origin: "https://fgui.corp.example" });
    await Promise.resolve();

    expect(postMessage).toHaveBeenLastCalledWith(expect.objectContaining({ type: "selection-preflight", preflight: expect.objectContaining({ sendable: true }) }), { origin: "https://fgui.corp.example" });
    expect(JSON.stringify(postMessage.mock.calls)).not.toContain("raw:node-id");
  });
});
