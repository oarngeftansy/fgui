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
const mapping = {
  mappingRevision: 1,
  unresolvedCount: 1,
  items: [{
    itemId: "old:title", oldObjectId: "title", oldName: "TitleBar", figmaNodeId: `psd-layer:${"e".repeat(64)}:11`, figmaName: "TitleBar",
    status: "suggested" as const, score: .86, candidates: [`psd-layer:${"e".repeat(64)}:11`], oldBounds: [.05, .07, .47, .11] as [number, number, number, number], figmaBounds: [.06, .07, .47, .11] as [number, number, number, number],
  }],
};
const psdSource = {
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
};

function client(): LocalHifiClientLike {
  return {
    fixedFonts: vi.fn(async () => [
      { family: "HYZhengYuan-75S", postscriptName: "HYZhengYuan-GES", sourceFilename: "HYZhengYuan-75S.ttf", sha256: "0".repeat(64), installed: true, matchedFilename: "HYZhengYuan-75S.ttf" },
      { family: "CoreSansESW01-55Medium", postscriptName: "CoreSansESW01-55Medium", sourceFilename: "core sans es w01_55 medium.ttf", sha256: "a".repeat(64), installed: true, matchedFilename: "core sans es w01_55 medium.ttf" },
    ]),
    uploadProject: vi.fn(async () => project),
    hifiTargets: vi.fn(async () => tree),
    uploadPsd: vi.fn(async () => psdSource),
    psdComposite: vi.fn(async () => new Blob(["png"], { type: "image/png" })),
    createPsdHifiReplacement: vi.fn(async () => ({
      project,
      replacement: { sessionId: "d".repeat(32), status: "mapping" as const, selectionId: "e".repeat(64), target: { version: 1 as const, projectId: project.projectId, projectFingerprint: tree.projectFingerprint, packageId: "tgn8y213", packageName: "Tower", directory: "Panel", componentId: "main", componentName: "Panel_Tower_Main", componentRelativePath: "assets/Tower/Panel/Panel_Tower_Main.xml" }, mappingRevision: 1, unresolvedCount: 1, artifactReady: false },
      mapping,
    })),
    hifiMapping: vi.fn(async () => mapping),
    decideHifiMapping: vi.fn(),
    buildHifiReplacement: vi.fn(),
    reviewHifiReplacement: vi.fn(),
    verifyHifiReplacementInEditor: vi.fn(),
    hifiEditorScreenshot: vi.fn(),
    approveHifiReplacement: vi.fn(),
    rejectHifiReplacement: vi.fn(),
    downloadHifiReplacement: vi.fn(),
  };
}

describe("standalone PSD HIFI app", () => {
  it("prepares the old project, target, fixed fonts and PSD without Figma", async () => {
    const api = client();
    render(<App client={api} />);

    expect(await screen.findByText("固定字体 2 / 2")).toBeVisible();
    expect(screen.getByText("外部切图和效果图均为可选材料")).toBeVisible();
    await userEvent.upload(screen.getByLabelText("旧 FairyGUI 工程 ZIP"), new File(["zip"], "HIFI_Replace.zip", { type: "application/zip" }));
    await userEvent.click(await screen.findByRole("button", { name: /Tower.*1 个目录/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Panel.*1 个组件/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Panel_Tower_Main/ }));
    await userEvent.upload(screen.getByLabelText("HIFI PSD"), new File(["8BPS"], "P_PVP爬塔_主页.psd", { type: "image/vnd.adobe.photoshop" }));

    expect(screen.getByText("Tower / Panel")).toBeVisible();
    expect(screen.getByText("1080 × 2340 · 16-bit RGB")).toBeVisible();
    expect(screen.getByText(/3 项无损阻断/)).toBeVisible();
    expect(screen.getByText("智能对象需要展开或通过像素等价检查")).toBeVisible();
    expect(screen.getByText("PSD 已保存在本机，后续映射不会重复上传。")).toBeVisible();
    expect(screen.getByRole("button", { name: "进入盘点与映射" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "进入盘点与映射" }));
    expect(await screen.findByText("组件对齐工作台")).toBeVisible();
    expect(screen.getByTestId("fgui-focus")).toHaveAccessibleName("旧 FGUI · TitleBar");
    expect(screen.getByTestId("hifi-focus")).toHaveAccessibleName("HIFI · TitleBar");
    expect(screen.getByRole("button", { name: "生成审核候选" })).toBeDisabled();
    expect(api.uploadProject).toHaveBeenCalledOnce();
    expect(api.uploadPsd).toHaveBeenCalledOnce();
    expect(api.psdComposite).toHaveBeenCalledOnce();
    expect(api.createPsdHifiReplacement).toHaveBeenCalledOnce();
  });

  it("keeps optional PNG and reference-image inputs optional", async () => {
    render(<App client={client()} />);

    expect(screen.getByLabelText("可选 PNG 切图")).not.toBeRequired();
    expect(screen.getByLabelText("可选效果图")).not.toBeRequired();
  });

  it("batch-accepts suggested mappings while keeping the focused review flow", async () => {
    const resolvedMapping = { ...mapping, mappingRevision: 2, unresolvedCount: 0, items: mapping.items.map((item) => ({ ...item, action: "accept" as const })) };
    const replacement = { sessionId: "d".repeat(32), status: "mapping" as const, selectionId: "e".repeat(64), target: { version: 1 as const, projectId: project.projectId, projectFingerprint: tree.projectFingerprint, packageId: "tgn8y213", packageName: "Tower", directory: "Panel", componentId: "main", componentName: "Panel_Tower_Main", componentRelativePath: "assets/Tower/Panel/Panel_Tower_Main.xml" }, mappingRevision: 1, unresolvedCount: 1, artifactReady: false };
    const api: LocalHifiClientLike = {
      ...client(),
      createPsdHifiReplacement: vi.fn(async () => ({ project, replacement, mapping })),
      decideHifiMapping: vi.fn(async () => ({ ...replacement, mappingRevision: 2, unresolvedCount: 0 })),
      hifiMapping: vi.fn(async () => resolvedMapping),
    };
    render(<App client={api} />);
    await screen.findByText("固定字体 2 / 2");
    await userEvent.upload(screen.getByLabelText("旧 FairyGUI 工程 ZIP"), new File(["zip"], "HIFI_Replace.zip", { type: "application/zip" }));
    await userEvent.click(await screen.findByRole("button", { name: /Tower.*1 个目录/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Panel.*1 个组件/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Panel_Tower_Main/ }));
    await userEvent.upload(screen.getByLabelText("HIFI PSD"), new File(["8BPS"], "P_PVP爬塔_主页.psd", { type: "image/vnd.adobe.photoshop" }));
    await userEvent.click(screen.getByRole("button", { name: "进入盘点与映射" }));

    await userEvent.click(await screen.findByRole("button", { name: "接受建议 1" }));

    expect(api.decideHifiMapping).toHaveBeenCalledWith(replacement.sessionId, 1, "old:title", "accept");
    expect(await screen.findByRole("button", { name: "生成审核候选" })).toBeEnabled();
  });

  it("continues from a resolved mapping through candidate review", async () => {
    const resolvedMapping = { ...mapping, unresolvedCount: 0, items: mapping.items.map((item) => ({ ...item, action: "accept" as const })) };
    const replacement = { sessionId: "d".repeat(32), status: "mapping" as const, selectionId: "e".repeat(64), target: { version: 1 as const, projectId: project.projectId, projectFingerprint: tree.projectFingerprint, packageId: "tgn8y213", packageName: "Tower", directory: "Panel", componentId: "main", componentName: "Panel_Tower_Main", componentRelativePath: "assets/Tower/Panel/Panel_Tower_Main.xml" }, mappingRevision: 1, unresolvedCount: 0, artifactReady: false };
    const review = {
      sessionId: replacement.sessionId, mappingRevision: 1,
      changedFiles: [{ relativePath: "assets/Tower/Panel/Panel_Tower_Main.xml", operation: "replace" as const, summary: "更新已确认的视觉属性" }],
      objectDiffs: [{ itemId: "old:title", kind: "changed" as const, oldObjectId: "title", oldName: "TitleBar", figmaNodeId: `psd-layer:${"e".repeat(64)}:11`, figmaName: "TitleBar", changedFields: ["xy"], summary: "修改视觉字段：xy" }],
      protectedChecksPassed: true, parseCoverageComplete: true, approvable: false, candidateSha256: "b".repeat(64), warnings: ["PSD 无损证据待验证：layer_effects_require_equivalence_check"], editorCheckRequired: true,
    };
    const api: LocalHifiClientLike = {
      ...client(),
      createPsdHifiReplacement: vi.fn(async () => ({ project, replacement, mapping: resolvedMapping })),
      hifiMapping: vi.fn(async () => resolvedMapping),
      buildHifiReplacement: vi.fn(async () => ({ ...replacement, status: "review_ready" as const, artifactReady: true })),
      reviewHifiReplacement: vi.fn(async () => review),
      verifyHifiReplacementInEditor: vi.fn(async () => ({
        sessionId: replacement.sessionId, candidateSha256: "b".repeat(64), editorFound: true, editorVersion: "6.1.4" as const,
        projectOpened: true, componentOpened: true, renderCaptured: true, screenshotUrl: `/v1/hifi-replacements/${replacement.sessionId}/editor-screenshot`, screenshotSha256: "c".repeat(64),
        screenshotWidth: 1078, screenshotHeight: 1855, expectedWidth: 1080, expectedHeight: 1920, fullFrame: false, approvable: false,
        warnings: ["Editor 截图不是完整画面。"],
      })),
      hifiEditorScreenshot: vi.fn(async () => new Blob(["png"], { type: "image/png" })),
    };
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:editor-evidence"), revokeObjectURL: vi.fn() });
    render(<App client={api} />);
    await screen.findByText("固定字体 2 / 2");
    await userEvent.upload(screen.getByLabelText("旧 FairyGUI 工程 ZIP"), new File(["zip"], "HIFI_Replace.zip", { type: "application/zip" }));
    await userEvent.click(await screen.findByRole("button", { name: /Tower.*1 个目录/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Panel.*1 个组件/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Panel_Tower_Main/ }));
    await userEvent.upload(screen.getByLabelText("HIFI PSD"), new File(["8BPS"], "P_PVP爬塔_主页.psd", { type: "image/vnd.adobe.photoshop" }));
    await userEvent.click(screen.getByRole("button", { name: "进入盘点与映射" }));
    const build = await screen.findByRole("button", { name: "生成审核候选" });
    expect(build).toBeEnabled();
    await userEvent.click(build);
    expect(await screen.findByText("候选差异审核")).toBeVisible();
    expect(screen.getByText("修改视觉字段：xy")).toBeVisible();
    expect(api.buildHifiReplacement).toHaveBeenCalledOnce();
    expect(api.reviewHifiReplacement).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button", { name: "自动打开并截图" }));
    expect(await screen.findByText("已取得 Editor 渲染证据")).toBeVisible();
    expect(screen.getByText("截图 1078 × 1855；目标 1080 × 1920")).toBeVisible();
    expect(screen.getByAltText("FairyGUI Editor 候选渲染截图")).toHaveAttribute("src", "blob:editor-evidence");
    expect(api.verifyHifiReplacementInEditor).toHaveBeenCalledWith(replacement.sessionId);
  });
});
