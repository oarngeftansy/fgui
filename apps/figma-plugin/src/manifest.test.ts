import { describe, expect, it } from "vitest";
import { buildManifest } from "../scripts/build-manifest.mjs";

describe("plugin manifest security", () => {
  it("allows exactly one HTTPS company origin", () => {
    expect(buildManifest("https://fgui.corp.example", "123456789").networkAccess.allowedDomains).toEqual([
      "https://fgui.corp.example",
    ]);
  });

  it.each(["http://fgui.corp.example", "*", "https://one.example,https://two.example"])(
    "rejects unsafe origin %s",
    (origin) => expect(() => buildManifest(origin, "123456789")).toThrow(),
  );

  it.each(["", "plugin-id", "*"])("rejects non-numeric plugin id %s", (pluginId) => {
    expect(() => buildManifest("https://fgui.corp.example", pluginId)).toThrow();
  });
});
