import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App, type LocalHifiClientLike } from "./App";

const project = { projectId: "a".repeat(32), displayName: "HIFI_Replace.zip", packages: [{ name: "Tower", resourceCount: 98 }] };
const tree = {
  projectId: project.projectId,
  projectFingerprint: "b".repeat(64),
  packages: [{ packageId: "tgn8y213", name: "Tower", directories: [{
    path: "Panel",
    selectable: true,
    components: [{ resourceId: "main", name: "Panel_Tower_Main", relativePath: "assets/Tower/Panel/Panel_Tower_Main.xml", selectable: true }],
  }] }],
};

function client(): LocalHifiClientLike {
  return {
    fixedFonts: vi.fn(async () => [
      { family: "HYZhengYuan-75S", postscriptName: "HYZhengYuan-GES", sourceFilename: "HYZhengYuan-75S.ttf", sha256: "0".repeat(64), installed: true, matchedFilename: "HYZhengYuan-75S.ttf" },
      { family: "CoreSansESW01-55Medium", postscriptName: "CoreSansESW01-55Medium", sourceFilename: "core sans es w01_55 medium.ttf", sha256: "a".repeat(64), installed: true, matchedFilename: "core sans es w01_55 medium.ttf" },
    ]),
    uploadProject: vi.fn(async () => project),
    hifiTargets: vi.fn(async () => tree),
    uploadPsd: vi.fn(async () => ({
      sourceId: "e".repeat(64),
      inspection: {
        sourceName: "P_PVP爬塔_主页.psd", byteSize: 266052490, sha256: "e".repeat(64), width: 1080, height: 2340,
        depth: 16 as const, colorMode: "RGB" as const, layerCount: 438,
        kindCounts: { curves: 3, group: 66, huesaturation: 2, pixel: 57, shape: 230, smartobject: 44, type: 36 },
        textLayerCount: 36, smartObjectCount: 44, adjustmentLayerCount: 5, effectLayerCount: 140,
        blockingIssues: ["smart_objects_require_equivalence_check", "adjustment_layers_require_equivalence_check", "layer_effects_require_equivalence_check"],
        warnings: ["16_bit_pixels_must_not_be_downconverted"],
      },
      layers: [],
    })),
  };
}

describe("standalone PSD HIFI app", () => {
  it("prepares the old project, target, fixed fonts and PSD without Figma", async () => {
    const api = client();
    render(<App client={api} />);

    expect(await screen.findByText("固定字体 2 / 2")).toBeVisible();
    expect(screen.getByText("外部切图和效果图均为可选材料")).toBeVisible();
    await userEvent.upload(screen.getByLabelText("旧 FairyGUI 工程 ZIP"), new File(["zip"], "HIFI_Replace.zip", { type: "application/zip" }));
    await userEvent.click(await screen.findByRole("button", { name: /Panel_Tower_Main/ }));
    await userEvent.upload(screen.getByLabelText("HIFI PSD"), new File(["8BPS"], "P_PVP爬塔_主页.psd", { type: "image/vnd.adobe.photoshop" }));

    expect(screen.getByText("Tower / Panel")).toBeVisible();
    expect(screen.getByText("1080 × 2340 · 16-bit RGB")).toBeVisible();
    expect(screen.getByText(/3 项无损阻断/)).toBeVisible();
    expect(screen.getByText("PSD 已保存在本机，后续映射不会重复上传。")).toBeVisible();
    expect(screen.getByRole("button", { name: "进入盘点与映射" })).toBeDisabled();
    expect(api.uploadProject).toHaveBeenCalledOnce();
    expect(api.uploadPsd).toHaveBeenCalledOnce();
  });

  it("keeps optional PNG and reference-image inputs optional", async () => {
    render(<App client={client()} />);

    expect(screen.getByLabelText("可选 PNG 切图")).not.toBeRequired();
    expect(screen.getByLabelText("可选效果图")).not.toBeRequired();
  });
});
