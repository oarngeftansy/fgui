import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { NewProjectCandidate, NewProjectReview } from "../../../figma-plugin/src/project-client";
import type { SelectionManifest } from "../../../figma-plugin/src/selection";
import { NewProjectWriterPanel } from "./NewProjectWriterPanel";

const manifest: SelectionManifest = { version: 1, display_name: "Writer", top_level_nodes: [{ id: "node-1", name: "Screen", type: "FRAME", bounds: { x: 0, y: 0, width: 100, height: 80 }, children: [], resource_keys: [] }], resources: [], warnings: [] };
const candidate = (generation = 1, status: NewProjectCandidate["status"] = "awaiting_review", buildId = String(generation).repeat(32)): NewProjectCandidate => ({ buildId, generation, status, stage: status, progress: 100, downloadName: "Writer-FairyGUI.zip", sha256: "a".repeat(64), byteSize: 3, artifactReady: true, diagnostics: [] });
const review = (generation = 1, buildId = String(generation).repeat(32)): NewProjectReview => ({
  version: 1, buildId, generation,
  dispositions: [
    { version: 1, id: "native", sourceNodeId: "node-native", sourceName: "标题", sourceType: "TEXT", level: "native", reason: "visual_style", allowedStrategies: [], visualImpact: "unchanged", editabilityImpact: "unchanged", componentImpact: "unchanged", blocksApproval: false },
    { version: 1, id: "raster", sourceNodeId: "node-raster", sourceName: "复杂阴影", sourceType: "FRAME", level: "raster_preserved", reason: "visual_effect", defaultStrategy: "rasterize-subtree", allowedStrategies: ["rasterize-subtree"], visualImpact: "visual_preserved", editabilityImpact: "subtree_not_editable", componentImpact: "unchanged", blocksApproval: false },
    { version: 1, id: "risk", sourceNodeId: "node-risk", sourceName: "富文本", sourceType: "TEXT", level: "editable_risk", reason: "rich_text_runs", defaultStrategy: "rasterize-subtree", allowedStrategies: ["rasterize-subtree", "preserve-editable"], visualImpact: "visual_preserved", editabilityImpact: "text_not_editable", componentImpact: "unchanged", blocksApproval: false },
  ],
  imageReviews: [{ resourceId: "asset", label: "Hero", evidenceKind: "source-image", generatedAssetUrl: `/v1/new-fgui-projects/${buildId}/previews/resources/asset`, width: 100, height: 80, nineSlice: false, cropBoundsMatch: true, transparencyPreserved: true }],
  componentReviews: [{ componentId: "screen", label: "Screen", evidenceKind: "structured-summary", objectCount: 4, textCount: 1, resourceRefs: 1, componentRefs: 0, hierarchyValid: true, geometryValid: true, textValid: true }],
  packageReview: { packageName: "Generated", fairyguiVersion: "6.1.4", publishTarget: "unity", componentsAdded: 1, resourcesAdded: 1, componentNames: ["Screen"], resourceNames: ["Hero"], resourceClosureValid: true, namingConflicts: [], integrityValid: true },
  checks: [{ id: "review:0123456789abcdef", severity: "WARNING", message: "请确认布局", issueId: "review:0123456789abcdef", issueKind: "raster-fallback", uirNodeId: "uir-node-1", sourceNodeId: "node-1", actionable: true, allowedStrategies: ["preserve-editable"] }],
  warningIds: ["review:0123456789abcdef"], approvable: true,
});

function sendPreflight(sendable = true) {
  window.dispatchEvent(new MessageEvent("message", { data: { pluginMessage: { type: "selection-preflight", preflight: { manifest: sendable ? manifest : null, nodeCount: sendable ? 1 : 0, assetCount: 0, estimatedBytes: 0, warnings: sendable ? [] : [{ code: "selection_empty", message: "请选择图层" }], sendable } } } }));
}

function writerClient(overrides: Record<string, unknown> = {}) {
  return {
    createNewProjectCandidate: vi.fn().mockResolvedValue({ selection: { version: 1, selection_id: "a".repeat(32), display_name: "Writer", top_level_summaries: [], preview_urls: [], warnings: [] }, candidate: candidate() }),
    reviewNewProject: vi.fn().mockResolvedValue(review()),
    adjustNewProject: vi.fn().mockResolvedValue(candidate(1, "adjusting")),
    regenerateNewProject: vi.fn().mockResolvedValue(candidate(2, "awaiting_review")),
    approveNewProject: vi.fn().mockResolvedValue(candidate(1, "approved")),
    rejectNewProject: vi.fn().mockResolvedValue(candidate(1, "rejected")),
    downloadNewProject: vi.fn().mockResolvedValue({ blob: new Blob(["zip"]), downloadName: "Writer-FairyGUI.zip" }),
    newProjectPreview: vi.fn().mockResolvedValue(new Blob(["image"], { type: "image/png" })),
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, decline) => { resolve = accept; reject = decline; });
  return { promise, resolve, reject };
}

function changeSelection() {
  window.dispatchEvent(new MessageEvent("message", { data: { pluginMessage: { type: "selection-changed", preflight: { manifest, nodeCount: 1, assetCount: 0, estimatedBytes: 0, warnings: [], sendable: true } } } }));
}

async function reachReview(client = writerClient(), postToFigma = vi.fn()) {
  render(<NewProjectWriterPanel client={client as never} postToFigma={postToFigma} />);
  sendPreflight();
  await userEvent.type(screen.getByLabelText("工程名称"), "Writer");
  await userEvent.click(screen.getByRole("button", { name: "生成候选工程" }));
  const attempt = postToFigma.mock.calls.at(-1)?.[0].attempt;
  window.dispatchEvent(new MessageEvent("message", { data: { pluginMessage: { type: "selection-export", attempt, manifest, resources: [] } } }));
  await screen.findByRole("tab", { name: "图片" });
  return { client, postToFigma };
}

describe("NewProjectWriterPanel", () => {
  it("shows the approved single-screen inputs without legacy template/version controls", async () => {
    const postToFigma = vi.fn();
    render(<NewProjectWriterPanel client={writerClient() as never} postToFigma={postToFigma} />);
    sendPreflight();
    expect(await screen.findByText(/1 个图层/)).toBeVisible();
    expect(screen.getByText("Screen · FRAME")).toBeVisible();
    expect(screen.getByLabelText("工程名称")).toBeRequired();
    expect(screen.getByText("FairyGUI 6.1.4")).toBeVisible();
    expect(screen.getByText("新建独立工程")).toBeVisible();
    expect(screen.getByText("可选设置")).toBeVisible();
    expect(screen.queryByLabelText("FairyGUI 版本")).not.toBeInTheDocument();
    expect(screen.queryByText("1. Figma 选择")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "生成候选工程" })).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "更多操作" }));
    expect(screen.getByRole("menuitem", { name: "更新现有工程" })).toBeVisible();
  });

  it("renders every review type, honest evidence labels, issue actions and declared strategies", async () => {
    const { postToFigma } = await reachReview();
    for (const name of ["图片", "组件 / 界面", "Package / 资源", "统一检查"]) expect(screen.getByRole("tab", { name })).toBeVisible();
    expect(screen.getByText("source image")).toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: "组件 / 界面" }));
    expect(screen.getByText("structured summary")).toBeVisible();
    expect(screen.queryByText("rendered")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Package / 资源" }));
    expect(screen.getAllByText(/FairyGUI 6.1.4/).at(-1)).toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: "统一检查" }));
    await userEvent.click(screen.getByRole("button", { name: "定位到图层" }));
    expect(postToFigma).toHaveBeenCalledWith(expect.objectContaining({ type: "locate-node", nodeId: "node-1", attempt: expect.any(String) }));
    await userEvent.click(screen.getByRole("button", { name: "查看原因" }));
    expect(screen.getByText("请确认布局")).toBeVisible();
    expect(screen.getByRole("button", { name: "保留可编辑结构" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "栅格化子树" })).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("tab", { name: "统一检查" }), { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "Package / 资源" })).toHaveFocus();
  });

  it("groups conversion results into automatic, recommended-review and blocked decisions", async () => {
    await reachReview();
    expect(screen.getByRole("heading", { name: "转换结果" })).toBeVisible();
    expect(screen.getByText("自动转换 2")).toBeVisible();
    expect(screen.getByText("建议审核 1")).toBeVisible();
    expect(screen.getByText("必须处理 0")).toBeVisible();
    expect(screen.getByText(/复杂阴影/)).toBeVisible();
    expect(screen.getByText("富文本")).toBeVisible();
  });

  it("shows blocked analysis without an artifact and never enables approval", async () => {
    const blockedCandidate = { ...candidate(), artifactReady: false, downloadName: undefined, sha256: undefined, byteSize: undefined };
    const blockedReview = {
      ...review(),
      dispositions: [{ version: 1, id: "blocked", sourceNodeId: "node-instance", sourceName: "按钮实例", sourceType: "INSTANCE", level: "blocked", reason: "component_definition_missing", allowedStrategies: [], visualImpact: "may_differ", editabilityImpact: "unchanged", componentImpact: "instance_not_reusable", blocksApproval: true }],
      imageReviews: [], componentReviews: [], checks: [], warningIds: [], approvable: false,
    } satisfies NewProjectReview;
    await reachReview(writerClient({
      createNewProjectCandidate: vi.fn().mockResolvedValue({ selection: { version: 1, selection_id: "a".repeat(32), display_name: "Writer", top_level_summaries: [], preview_urls: [], warnings: [] }, candidate: blockedCandidate }),
      reviewNewProject: vi.fn().mockResolvedValue(blockedReview),
    }));
    expect(screen.getByText("必须处理 1")).toBeVisible();
    expect(screen.getByText(/按钮实例/)).toBeVisible();
    expect(screen.getByRole("button", { name: "确认并下载 ZIP" })).toBeDisabled();
  });

  it("regenerates, visibly invalidates v1 and resets warning acknowledgement for v2", async () => {
    const client = writerClient({ reviewNewProject: vi.fn().mockResolvedValueOnce(review()).mockResolvedValueOnce(review(2, "2".repeat(32))) });
    await reachReview(client);
    await userEvent.click(screen.getByRole("tab", { name: "统一检查" }));
    await userEvent.click(screen.getByRole("button", { name: "保留可编辑结构" }));
    expect(screen.getByRole("button", { name: "重新生成候选" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "重新生成候选" }));
    expect(await screen.findByText(/候选 v1 已失效/)).toBeVisible();
    expect(screen.getByText("候选 v2")).toBeVisible();
    expect(screen.getByRole("checkbox", { name: /已阅读并确认全部警告/ })).not.toBeChecked();
  });

  it("blocks approval until warnings are acknowledged, then downloads and offers re-download", async () => {
    const createObjectURL = vi.fn().mockReturnValue("blob:writer");
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const { client } = await reachReview();
    await userEvent.click(screen.getByRole("tab", { name: "统一检查" }));
    expect(screen.getByRole("button", { name: "确认并下载 ZIP" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /已阅读并确认全部警告/ }));
    await userEvent.click(screen.getByRole("button", { name: "确认并下载 ZIP" }));
    expect(await screen.findByRole("button", { name: "再次下载" })).toBeVisible();
    expect(client.approveNewProject).toHaveBeenCalled();
    expect(client.downloadNewProject).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "再次下载" }));
    expect(client.downloadNewProject).toHaveBeenCalledTimes(2);
  });

  it("fails closed when required generated preview evidence cannot load", async () => {
    vi.stubGlobal("URL", { createObjectURL: vi.fn(), revokeObjectURL: vi.fn() });
    await reachReview(writerClient({ newProjectPreview: vi.fn().mockRejectedValue(new Error("preview unavailable")) }));
    await screen.findByText(/预览证据加载失败/);
    await userEvent.click(screen.getByRole("tab", { name: "统一检查" }));
    await userEvent.click(screen.getByRole("checkbox", { name: /已阅读并确认全部警告/ }));
    expect(screen.getByRole("button", { name: "确认并下载 ZIP" })).toBeDisabled();
  });

  it("rejects only the whole candidate and never exposes per-file approval", async () => {
    const { client } = await reachReview();
    expect(screen.queryByText(/逐文件批准|批准此文件/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "拒绝候选" }));
    expect(await screen.findByText("当前候选已拒绝，不会提供下载。")).toBeVisible();
    expect(client.rejectNewProject).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "确认并下载 ZIP" })).not.toBeInTheDocument();
  });

  it("rejects the whole candidate, retries failures, cancels active work and ignores stale bridge attempts", async () => {
    const deferred: { reject?: (reason: unknown) => void } = {};
    const client = writerClient({ createNewProjectCandidate: vi.fn((_m, _r, _n, options) => new Promise((_resolve, reject) => { deferred.reject = reject; options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))); })) });
    const postToFigma = vi.fn();
    render(<NewProjectWriterPanel client={client as never} postToFigma={postToFigma} />);
    sendPreflight();
    await userEvent.type(screen.getByLabelText("工程名称"), "Writer");
    await userEvent.click(screen.getByRole("button", { name: "生成候选工程" }));
    const attempt = postToFigma.mock.calls.at(-1)?.[0].attempt;
    window.dispatchEvent(new MessageEvent("message", { data: { pluginMessage: { type: "selection-export", attempt: `${attempt}-stale`, manifest, resources: [] } } }));
    expect(client.createNewProjectCandidate).not.toHaveBeenCalled();
    window.dispatchEvent(new MessageEvent("message", { data: { pluginMessage: { type: "selection-export", attempt, manifest, resources: [] } } }));
    await screen.findByRole("button", { name: "取消" });
    await userEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "生成候选工程" })).toBeEnabled());
  });

  it("invalidates and rejects active review on an ordinary Figma selection change", async () => {
    const { client } = await reachReview();
    changeSelection();
    expect(await screen.findByText(/旧候选已失效并清除/)).toBeVisible();
    expect(screen.queryByRole("tab", { name: "图片" })).not.toBeInTheDocument();
    await waitFor(() => expect(client.rejectNewProject).toHaveBeenCalledOnce());
    expect(document.querySelectorAll(".primary-button")).toHaveLength(1);
  });

  it("keeps idle and rejects the server candidate when selection changes during adjustment", async () => {
    const pending = deferred<NewProjectCandidate>();
    const client = writerClient({ adjustNewProject: vi.fn().mockReturnValue(pending.promise) });
    await reachReview(client);
    await userEvent.click(screen.getByRole("tab", { name: "统一检查" }));
    await userEvent.click(screen.getByRole("button", { name: "保留可编辑结构" }));
    changeSelection();
    await act(async () => pending.resolve(candidate(1, "adjusting")));

    expect(await screen.findByText(/本次生成已取消并清除/)).toBeVisible();
    expect(screen.getByRole("button", { name: "生成候选工程" })).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await waitFor(() => expect(client.rejectNewProject).toHaveBeenCalledWith(expect.objectContaining({ generation: 1 })));
  });

  it("keeps idle and rejects the server candidate when selection changes during regeneration", async () => {
    const pending = deferred<NewProjectCandidate>();
    const live = candidate(2, "regenerating", "2".repeat(32));
    const client = writerClient({ regenerateNewProject: vi.fn((_candidate, options) => {
      options.onStage(live);
      return pending.promise;
    }) });
    await reachReview(client);
    await userEvent.click(screen.getByRole("tab", { name: "统一检查" }));
    await userEvent.click(screen.getByRole("button", { name: "保留可编辑结构" }));
    await userEvent.click(screen.getByRole("button", { name: "重新生成候选" }));
    changeSelection();
    await act(async () => pending.resolve(candidate(2)));

    expect(await screen.findByText(/本次生成已取消并清除/)).toBeVisible();
    expect(screen.getByRole("button", { name: "生成候选工程" })).toBeEnabled();
    expect(screen.queryByText("候选 v2")).not.toBeInTheDocument();
    await waitFor(() => expect(client.rejectNewProject).toHaveBeenCalledWith(expect.objectContaining({ buildId: "2".repeat(32), generation: 2 })));
    expect(client.rejectNewProject).not.toHaveBeenCalledWith(expect.objectContaining({ buildId: "1".repeat(32) }));
  });

  it("keeps idle and rejects the server candidate when selection changes during approval", async () => {
    vi.stubGlobal("URL", { createObjectURL: vi.fn().mockReturnValue("blob:writer"), revokeObjectURL: vi.fn() });
    const pending = deferred<NewProjectCandidate>();
    const client = writerClient({ approveNewProject: vi.fn().mockReturnValue(pending.promise) });
    await reachReview(client);
    await userEvent.click(screen.getByRole("tab", { name: "统一检查" }));
    await userEvent.click(screen.getByRole("checkbox", { name: /已阅读并确认全部警告/ }));
    await userEvent.click(screen.getByRole("button", { name: "确认并下载 ZIP" }));
    changeSelection();
    await act(async () => pending.resolve(candidate(1, "approved")));

    expect(await screen.findByText(/本次生成已取消并清除/)).toBeVisible();
    expect(screen.getByRole("button", { name: "生成候选工程" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "再次下载" })).not.toBeInTheDocument();
    expect(client.downloadNewProject).not.toHaveBeenCalled();
    await waitFor(() => expect(client.rejectNewProject).toHaveBeenCalledWith(expect.objectContaining({ generation: 1 })));
  });
});
