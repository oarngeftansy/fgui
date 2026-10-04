import { useEffect, useMemo, useRef, useState } from "react";

import type {
  DesignAssetStatus,
  FixedFontStatus,
  HifiEditorVerification,
  HifiExportMode,
  HifiFidelityReport,
  HifiFidelityUnit,
  HifiMappingAction,
  HifiMappingDraft,
  HifiMappingItem,
  HifiProjectTree,
  HifiRemovalDecision,
  HifiRemovalReview,
  HifiReplacement,
  HifiReplacementReview,
  HifiTargetRef,
  ProjectView,
  ProjectWorkflowClient,
  PsdSource,
} from "../../../figma-plugin/src/project-client";
import {
  selectedHifiTarget,
  type HifiTargetSelection,
} from "../figma/HifiTargetPicker";
import {
  canDeliverHifi,
  type HifiEditorCheckState,
} from "../figma/HifiReplacementReviewPanel";

export type LocalHifiClientLike = Pick<
  ProjectWorkflowClient,
  | "resumePsdHifiReplacement"
  | "fixedFonts"
  | "uploadProject"
  | "hifiTargets"
  | "uploadPsd"
  | "psdComposite"
  | "effectViewport"
  | "effectCrop"
  | "psdResource"
  | "getDesignAssets"
  | "linkDesignAssets"
  | "hifiFidelity"
  | "projectAssetThumbnail"
  | "createPsdHifiReplacement"
  | "createPsdHifiReplacementBatch"
  | "hifiMapping"
  | "decideHifiMapping"
  | "autoResolveHifiMapping"
  | "buildHifiReplacement"
  | "reviewHifiReplacement"
  | "verifyHifiReplacementInEditor"
  | "hifiStateEvidence"
  | "hifiRemovalReview"
  | "decideHifiRemovalReview"
  | "hifiEditorScreenshot"
  | "approveHifiReplacement"
  | "rejectHifiReplacement"
  | "downloadHifiReplacement"
>;

type Stage = "prepare" | "sessions" | "mapping" | "review" | "delivered";
const EMPTY_CHECKS: HifiEditorCheckState = {
  layout: false,
  references: false,
  interactions: false,
};

function downloadBlob(download: { blob: Blob; downloadName: string }) {
  const url = URL.createObjectURL(download.blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = download.downloadName;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

function errorText(error: unknown): string {
  const code = (error as { code?: string } | null)?.code;
  if (code === "invalid_zip") return "旧 FairyGUI 工程压缩包无效。";
  if (code === "hifi_in_place_raster_unsupported")
    return "该旧对象无法原位承载位图，已阻止生成覆盖层。";
  if (code === "hifi_nested_visual_mapping_required")
    return "组件内部视觉和状态尚未对应，不能生成候选。";
  if (code === "hifi_shared_scope_violation")
    return "共享组件会影响未选中的页面，已阻止写入。";
  if (code === "hifi_shared_instance_conflict")
    return "共享组件的不同实例要求不同视觉，不能写成同一份资源。";
  if (code === "hifi_nested_geometry_unverified")
    return "嵌套对象的缩放或旋转坐标尚未验证，不能写入。";
  if (code === "hifi_instance_override_conflict")
    return "替换与既有按钮标题或图标实例参数冲突，已阻止写入。";
  if (code === "hifi_type_conversion_not_authorized")
    return "该对象没有原位改类型许可，已阻止转换。";
  if (code === "psd_stroke_only_raster_unsupported")
    return "当前渲染器会错误填满此描边图层，已阻止导出；需要修复并验证图层渲染。";
  if (code === "invalid_psd") return "PSD 文件无效或无法解析。";
  if (code === "psd_too_large") return "PSD 文件超过本地检查上限。";
  if (code === "psd_source_unavailable")
    return "本机保存的 PSD 来源已损坏或丢失，请重新导入。";
  if (code === "hifi_owned_visual_requires_regeneration")
    return "该对象承载多层 PSD 视觉包，换层需要重新生成视觉包；请确认当前对应或列为例外。";
  if (code === "hifi_mapping_policy_stale")
    return "映射政策版本已升级，旧会话不能继续；请重新选择材料建立新会话。";
  if (code === "insufficient_disk_space")
    return "磁盘空间不足，无法生成候选，请清理磁盘后重试。";
  if (code === "hifi_mapping_coverage_incomplete")
    return "仍有对象未覆盖 PSD 视觉，不能生成候选；请补全对应或列为例外。";
  if (code === "hifi_legacy_closure_incomplete")
    return "仍有旧视觉未进入明确处置（七态之一），不能生成候选；请在删除评审中确认移除或保留。";
  if (code === "hifi_reference_closure_invalid")
    return "删除后仍有悬空引用未闭合，已阻止生成候选。";
  if (code === "hifi_removal_requires_candidate")
    return "只有被分类为删除候选的旧对象才能移除。";
  if (code === "hifi_removal_review_empty")
    return "当前没有待确认的删除评审。";
  if (code === "hifi_removal_decision_incomplete")
    return "删除评审需对全部展示分组做出选择。";
  if (code === "hifi_incompatible_mapping")
    return "对应关系与对象类型不兼容，已阻止写入。";
  if (code === "hifi_mapping_incomplete")
    return "映射尚未完成，请先处理全部未决项。";
  if (code === "hifi_mapping_stale" || code === "hifi_target_stale")
    return "映射或目标已过期，请刷新后重试。";
  if (code === "hifi_candidate_stale")
    return "候选已过期，请重新生成候选。";
  if (code === "hifi_build_failed")
    return "生成候选失败，请查看服务日志后重试。";
  if (code === "hifi_editor_checks_incomplete")
    return "Editor 检查尚未完成，不能交付。";
  if (code === "hifi_download_blocked")
    return "当前状态不可下载，请先完成审核。";
  if (code === "hifi_review_budget_exceeded")
    return "审核次数已达上限，请重新生成候选。";
  if (code === "network")
    return "无法连接本地服务，请确认服务正在运行后重试。";
  if (code === "unauthorized")
    return "访问令牌无效或已过期，请重新打开控制台。";
  if (code === "aborted") return "操作已取消。";
  if (code === "timeout")
    return "处理超时，请重试；若反复超时请检查 PSD 复杂度。";
  if (code === "invalid_response")
    return "服务返回的数据格式异常，请重试。";
  if (code === "review_required") return "该操作需要先完成审核。";
  if (code === "stale_candidate") return "候选已过期，请重新生成后再操作。";
  if (code === "conversion_conflict") return "请求与当前状态冲突，请刷新后重试。";
  if (code === "conversion_failed") return "本地处理失败，请检查材料后重试。";
  if (code === "package_failed") return "打包失败，请检查工程完整性后重试。";
  if (code === "selection_invalid") return "选区无效，请重新选择。";
  if (code === "unknown_template") return "模板不存在。";
  if (code === "validation") return "输入不合法，请检查后重试。";
  return `本地处理失败（${code ?? "unknown"}），请检查文件后重试。`;
}

export function useHifiWorkflow(client: LocalHifiClientLike) {
  const [fonts, setFonts] = useState<FixedFontStatus[]>([]);
  const [project, setProject] = useState<ProjectView>();
  const [tree, setTree] = useState<HifiProjectTree>();
  const [selectedList, setSelectedList] = useState<HifiTargetSelection[]>([]);
  const [sessions, setSessions] = useState<HifiReplacement[]>([]);
  const [exportMode, setExportMode] = useState<HifiExportMode>("package");
  const [psdSource, setPsdSource] = useState<PsdSource>();
  const [compositeUrl, setCompositeUrl] = useState<string>();
  const [oldPreviewUrl, setOldPreviewUrl] = useState<string>();
  const [stage, setStage] = useState<Stage>("prepare");
  const [replacement, setReplacement] = useState<HifiReplacement>();
  const [mapping, setMapping] = useState<HifiMappingDraft>();
  const [removalReview, setRemovalReview] = useState<HifiRemovalReview>();
  const [review, setReview] = useState<HifiReplacementReview>();
  const [editorVerification, setEditorVerification] =
    useState<HifiEditorVerification>();
  const [editorScreenshotUrl, setEditorScreenshotUrl] = useState<string>();
  const [checks, setChecks] = useState<HifiEditorCheckState>(EMPTY_CHECKS);
  const [currentItemId, setCurrentItemId] = useState<string>();
  const [projectBusy, setProjectBusy] = useState(false);
  const [psdBusy, setPsdBusy] = useState(false);
  const [projectError, setProjectError] = useState("");
  const [error, setError] = useState("");
  const [restoreNote, setRestoreNote] = useState("");
  const [autoResolveNote, setAutoResolveNote] = useState("");
  const [autoNote, setAutoNote] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [fontError, setFontError] = useState("");
  const [operation, setOperation] = useState("");
  const [designAssets, setDesignAssets] = useState<DesignAssetStatus>({ linked: false });
  const [designRootInput, setDesignRootInput] = useState("");
  const [assetsBusy, setAssetsBusy] = useState(false);
  const [assetsError, setAssetsError] = useState("");
  const [fidelity, setFidelity] = useState<HifiFidelityReport>();
  const [comparison, setComparison] = useState<{
    unit: HifiFidelityUnit;
    bakedUrl: string;
    truthUrl: string;
  } | null>(null);
  const [batchFidelity, setBatchFidelity] = useState<
    Record<string, { total: number; passed: number }>
  >({});
  const targets = useMemo(
    () =>
      project && tree
        ? selectedList
            .map((item) => selectedHifiTarget(project, tree, item))
            .filter((item): item is HifiTargetRef => Boolean(item))
        : [],
    [project, selectedList, tree],
  );
  const installedFonts = fonts.filter((font) => font.installed).length;
  const inspection = psdSource?.inspection;
  const ready = Boolean(
    targets.length > 0 &&
    psdSource &&
    fonts.length > 0 &&
    installedFonts === fonts.length,
  );
  const toggleTarget = (selection: HifiTargetSelection) => {
    const matches = (item: HifiTargetSelection) =>
      item[0] === selection[0] &&
      item[1] === selection[1] &&
      item[2] === selection[2];
    clearSession();
    setSelectedList((current) =>
      current.some(matches)
        ? current.filter((item) => !matches(item))
        : [...current, selection],
    );
  };

  useEffect(() => {
    if (!psdSource) {
      setDesignAssets({ linked: false });
      return;
    }
    let active = true;
    void client
      .getDesignAssets(psdSource.sourceId)
      .then((status) => {
        if (active) setDesignAssets(status);
      })
      .catch(() => {
        /* Design assets are optional. */
      });
    return () => {
      active = false;
    };
  }, [client, psdSource]);

  useEffect(() => {
    const controller = new AbortController();
    void client
      .fixedFonts(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setFonts(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFontError("字体检查失败，请重试。");
      });
    return () => controller.abort();
  }, [client]);
  useEffect(
    () => () => {
      if (compositeUrl) URL.revokeObjectURL(compositeUrl);
    },
    [compositeUrl],
  );
  useEffect(() => {
    const current = mapping?.items.find(
      (item) => item.itemId === currentItemId,
    );
    if (
      !project ||
      (current?.oldObjectType !== "image" &&
        current?.oldObjectType !== "loader") ||
      !current.oldResourceId
    ) {
      setOldPreviewUrl(undefined);
      return;
    }
    setOldPreviewUrl(undefined);
    const controller = new AbortController();
    let objectUrl: string | undefined;
    void client
      .projectAssetThumbnail(
        project.projectId,
        current.oldResourceId,
        controller.signal,
      )
      .then((blob) => {
        if (!controller.signal.aborted) {
          objectUrl = URL.createObjectURL(blob);
          setOldPreviewUrl(objectUrl);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setOldPreviewUrl(undefined);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [client, project, mapping, currentItemId]);
  useEffect(
    () => () => {
      if (editorScreenshotUrl) URL.revokeObjectURL(editorScreenshotUrl);
    },
    [editorScreenshotUrl],
  );

  useEffect(() => {
    if (replacement)
      setSessions((current) =>
        current.map((session) =>
          session.sessionId === replacement.sessionId ? replacement : session,
        ),
      );
  }, [replacement]);

  const clearSession = () => {
    autoContinueRef.current = false;
    setSessions([]);
    setReplacement(undefined);
    setMapping(undefined);
    setRemovalReview(undefined);
    setReview(undefined);
    setEditorVerification(undefined);
    setEditorScreenshotUrl(undefined);
    setChecks(EMPTY_CHECKS);
    setCurrentItemId(undefined);
    setStage("prepare");
    setError("");
    setRestoreNote("");
    window.history.replaceState(
      null,
      "",
      window.location.pathname + window.location.search,
    );
    try {
      localStorage.removeItem("hifi-last-session");
    } catch {
      /* Storage may be disabled. */
    }
  };

  const compositeRef = useRef<string | undefined>(undefined);
  const autoContinueRef = useRef(false);
  useEffect(() => {
    compositeRef.current = compositeUrl;
  }, [compositeUrl]);
  const ensureComposite = () => {
    if (compositeRef.current || !psdSource) return;
    const source = psdSource;
    void client
      .psdComposite(source.sourceId)
      .then((blob) => {
        if (typeof URL.createObjectURL === "function")
          setCompositeUrl(URL.createObjectURL(blob));
      })
      .catch(() =>
        setPreviewError("PSD 预览加载失败，材料已保留。请重试加载预览。"),
      );
  };

  const retryPreview = async () => {
    if (!psdSource || psdBusy) return;
    setPsdBusy(true);
    setOperation("正在加载 PSD 预览…");
    setPreviewError("");
    try {
      setCompositeUrl(
        URL.createObjectURL(await client.psdComposite(psdSource.sourceId)),
      );
    } catch {
      setPreviewError("PSD 预览加载失败，材料已保留。请重试加载预览。");
    } finally {
      setPsdBusy(false);
    }
  };

  const retryFonts = async () => {
    setFontError("");
    setFonts([]);
    try {
      setFonts(await client.fixedFonts());
    } catch {
      setFontError("字体检查失败，请重试。");
    }
  };

  const closeComparison = () => {
    setComparison((current) => {
      if (current) {
        URL.revokeObjectURL(current.bakedUrl);
        URL.revokeObjectURL(current.truthUrl);
      }
      return null;
    });
  };

  const linkAssets = async () => {
    const root = designRootInput.trim();
    if (!psdSource || !root || assetsBusy) return;
    setAssetsBusy(true);
    setAssetsError("");
    try {
      const status = await client.linkDesignAssets(psdSource.sourceId, root);
      setDesignAssets(status);
      const manifest = status.manifest;
      if (!manifest?.effectImage && !manifest?.cutouts.length)
        setAssetsError("该文件夹里没有找到效果图或切图。");
    } catch (cause) {
      setAssetsError(errorText(cause));
    } finally {
      setAssetsBusy(false);
    }
  };

  const loadFidelity = async (sessionId: string) => {
    try {
      setFidelity(await client.hifiFidelity(sessionId));
    } catch {
      /* Fidelity is advisory and never blocks delivery. */
    }
  };

  const loadSessionFidelity = async (sessionId: string) => {
    try {
      const report = await client.hifiFidelity(sessionId);
      setBatchFidelity((current) => ({
        ...current,
        [sessionId]: report.summary,
      }));
    } catch {
      /* Per-session fidelity is advisory. */
    }
  };

  const openComparison = async (unit: HifiFidelityUnit) => {
    if (!psdSource || !unit.resourceKey || !unit.bounds) return;
    closeComparison();
    setPsdBusy(true);
    setOperation("正在加载对比图…");
    try {
      const baked = await client.psdResource(psdSource.sourceId, unit.resourceKey);
      const truth = await client.effectCrop(psdSource.sourceId, unit.bounds);
      setComparison({
        unit,
        bakedUrl: URL.createObjectURL(baked),
        truthUrl: URL.createObjectURL(truth),
      });
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  const chooseProject = async (file?: File) => {
    if (!file) return;
    clearSession();
    setProject(undefined);
    setTree(undefined);
    setSelectedList([]);
    setProjectError("");
    setProjectBusy(true);
    try {
      const uploaded = await client.uploadProject(file);
      const targets = await client.hifiTargets(uploaded.projectId);
      setProject(uploaded);
      setTree(targets);
    } catch (cause) {
      setProjectError(`${errorText(cause)}请检查文件并重新选择。`);
    } finally {
      setProjectBusy(false);
    }
  };

  const choosePsd = async (file?: File) => {
    if (!file) return;
    clearSession();
    setPsdSource(undefined);
    setCompositeUrl(undefined);
    setPreviewError("");
    setPsdBusy(true);
    setOperation("正在解析 PSD 并保存材料…");
    try {
      const uploaded = await client.uploadPsd(file);
      setPsdSource(uploaded);
      try {
        const composite = await client.psdComposite(uploaded.sourceId);
        if (typeof URL.createObjectURL === "function")
          setCompositeUrl(URL.createObjectURL(composite));
      } catch {
        setPreviewError("PSD 预览加载失败，材料已保留。请重试加载预览。");
      }
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  const enterSession = (session: HifiReplacement, draft: HifiMappingDraft) => {
    setReplacement(session);
    setMapping(draft);
    setReview(undefined);
    setEditorVerification(undefined);
    setEditorScreenshotUrl(undefined);
    setChecks(EMPTY_CHECKS);
    setCurrentItemId(
      draft.items.find((item) => !item.action)?.itemId ??
        draft.items[0]?.itemId,
    );
    setStage("mapping");
    ensureComposite();
  };

  const startMapping = async (): Promise<
    { replacement: HifiReplacement; mapping: HifiMappingDraft } | undefined
  > => {
    if (
      !ready ||
      !project ||
      !targets.length ||
      !psdSource ||
      projectBusy ||
      psdBusy
    )
      return;
    setPsdBusy(true);
    setOperation("正在盘点图层并建立映射…");
    setError("");
    try {
      if (targets.length === 1) {
        const started = await client.createPsdHifiReplacement(
          psdSource.sourceId,
          project,
          targets[0],
        );
        enterSession(started.replacement, started.mapping);
        return {
          replacement: started.replacement,
          mapping: started.mapping,
        };
      }
      setSessions(
        await client.createPsdHifiReplacementBatch(
          psdSource.sourceId,
          targets,
        ),
      );
      setStage("sessions");
      return undefined;
    } catch (cause) {
      setError(errorText(cause));
      return undefined;
    } finally {
      setPsdBusy(false);
    }
  };

  const openSession = async (session: HifiReplacement): Promise<
    { replacement: HifiReplacement; mapping: HifiMappingDraft } | undefined
  > => {
    setPsdBusy(true);
    setOperation("正在打开会话…");
    setError("");
    try {
      const draft = await client.hifiMapping(session.sessionId);
      enterSession(session, draft);
      if (session.status === "approved") {
        setExportMode("package");
        setStage("delivered");
        return undefined;
      }
      if (session.status === "review_ready") {
        setReview(await client.reviewHifiReplacement(session.sessionId));
        setStage("review");
        return undefined;
      }
      return { replacement: session, mapping: draft };
    } catch (cause) {
      setError(errorText(cause));
      return undefined;
    } finally {
      setPsdBusy(false);
    }
  };

  const queueAutoContinue = (
    sessionId: string,
    nextMapping: HifiMappingDraft,
  ) => {
    if (!autoContinueRef.current || nextMapping.unresolvedCount > 0) return;
    autoContinueRef.current = false;
    const revision = nextMapping.mappingRevision;
    queueMicrotask(() => void continueAutoPipeline(sessionId, revision));
  };

  const decide = async (
    item: HifiMappingItem,
    action: HifiMappingAction,
    nodeId?: string,
  ) => {
    if (!replacement || !mapping || psdBusy) return;
    setPsdBusy(true);
    setOperation("正在保存映射…");
    setError("");
    try {
      const next = await client.decideHifiMapping(
        replacement.sessionId,
        mapping.mappingRevision,
        item.itemId,
        action,
        nodeId,
      );
      const nextMapping = await client.hifiMapping(next.sessionId);
      setReplacement(next);
      setMapping(nextMapping);
      queueAutoContinue(next.sessionId, nextMapping);
      setCurrentItemId(
        nextMapping.items.find((entry) => !entry.action)?.itemId ?? item.itemId,
      );
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  const decideRemoval = async (decisions: HifiRemovalDecision[]) => {
    if (!replacement || !mapping || psdBusy) return;
    setPsdBusy(true);
    setOperation("正在应用删除评审决策…");
    setError("");
    try {
      const next = await client.decideHifiRemovalReview(
        replacement.sessionId,
        mapping.mappingRevision,
        decisions,
      );
      const nextMapping = await client.hifiMapping(next.sessionId);
      setReplacement(next);
      setMapping(nextMapping);
      setRemovalReview(undefined);
      setCurrentItemId(
        nextMapping.items.find((entry) => !entry.action)?.itemId ??
          nextMapping.items[0]?.itemId,
      );
      queueAutoContinue(next.sessionId, nextMapping);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  const decideBatch = async (
    kind: "suggested" | "hifi_added" | "blocked" | "fgui_only",
  ) => {
    if (!replacement || !mapping || psdBusy) return;
    setPsdBusy(true);
    setOperation("正在批量保存映射…");
    setError("");
    try {
      let nextReplacement = replacement;
      let nextMapping = mapping;
      const itemIds = mapping.items
        .filter((item) => item.action === undefined && item.status === kind)
        .map((item) => item.itemId);
      for (const itemId of itemIds) {
        const item = nextMapping.items.find((entry) => entry.itemId === itemId);
        if (!item || item.action !== undefined) continue;
        const action: HifiMappingAction =
          kind === "suggested"
            ? "accept"
            : kind === "hifi_added"
              ? "add_visual"
              : "exception"; // blocked / fgui_only -> exception
        nextReplacement = await client.decideHifiMapping(
          nextReplacement.sessionId,
          nextMapping.mappingRevision,
          item.itemId,
          action,
        );
        nextMapping = await client.hifiMapping(nextReplacement.sessionId);
        setReplacement(nextReplacement);
        setMapping(nextMapping);
      }
      setReplacement(nextReplacement);
      setMapping(nextMapping);
      queueAutoContinue(nextReplacement.sessionId, nextMapping);
      setCurrentItemId(
        nextMapping.items.find((entry) => !entry.action)?.itemId ??
          nextMapping.items[0]?.itemId,
      );
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  const autoResolveBest = async () => {
    if (!replacement || !mapping || psdBusy) return;
    setPsdBusy(true);
    setOperation("正在自动选择最优候选…");
    setError("");
    setAutoResolveNote("");
    try {
      const before = mapping.items.filter(
        (item) => item.action === undefined,
      ).length;
      const next = await client.autoResolveHifiMapping(replacement.sessionId);
      const nextMapping = await client.hifiMapping(next.sessionId);
      setReplacement(next);
      setMapping(nextMapping);
      setCurrentItemId(
        nextMapping.items.find((entry) => !entry.action)?.itemId ??
          nextMapping.items[0]?.itemId,
      );
      const pending = nextMapping.items.filter(
        (item) => item.action === undefined,
      ).length;
      setAutoResolveNote(
        pending > 0
          ? `已自动处理 ${before - pending} 项；剩余 ${pending} 项无法自动决策，请逐项处理或调整 PSD。`
          : "已自动处理全部待确认项，可生成审核候选。",
      );
      queueAutoContinue(next.sessionId, nextMapping);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  const runAutoPipeline = async (initial: {
    replacement: HifiReplacement;
    mapping: HifiMappingDraft;
  }) => {
    setPsdBusy(true);
    setError("");
    setAutoResolveNote("");
    setAutoNote("正在自动匹配…");
    try {
      let currentReplacement = initial.replacement;
      let currentMapping = initial.mapping;
      if (currentMapping.unresolvedCount > 0) {
        currentReplacement = await client.autoResolveHifiMapping(
          currentReplacement.sessionId,
        );
        currentMapping = await client.hifiMapping(
          currentReplacement.sessionId,
        );
        setReplacement(currentReplacement);
        setMapping(currentMapping);
        setCurrentItemId(
          currentMapping.items.find((entry) => !entry.action)?.itemId ??
            currentMapping.items[0]?.itemId,
        );
      }
      if (currentMapping.unresolvedCount > 0) {
        autoContinueRef.current = true;
        const decided =
          initial.mapping.unresolvedCount - currentMapping.unresolvedCount;
        const remaining = currentMapping.unresolvedCount;
        let removal: HifiRemovalReview | undefined;
        try {
          removal = await client.hifiRemovalReview(
            currentReplacement.sessionId,
          );
        } catch {
          removal = undefined;
        }
        setRemovalReview(removal?.pending ? removal : undefined);
        setAutoResolveNote(
          removal?.pending
            ? `已自动处理 ${decided} 项；发现 ${removal.totalCandidateCount} 个 PSD 中不存在的旧对象，请在“旧视觉删除确认”中逐组选择移除或保留；确认后自动继续交付。`
            : `已自动处理 ${decided} 项；剩余 ${remaining} 项无法自动决策（多为 PSD 多余视觉或类型不兼容），请逐项处理或调整 PSD；处理完最后一项后自动继续交付。`,
        );
        return;
      }
      autoContinueRef.current = false;
      await continueAutoPipeline(
        currentReplacement.sessionId,
        currentMapping.mappingRevision,
      );
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setAutoNote("");
      setPsdBusy(false);
    }
  };

  const continueAutoPipeline = async (
    sessionId: string,
    mappingRevision: number,
  ) => {
    setPsdBusy(true);
    setError("");
    try {
      setAutoNote("正在生成替换包…");
      const built = await client.buildHifiReplacement(
        sessionId,
        mappingRevision,
      );
      setAutoNote("正在运行时状态取证…");
      try {
        await client.hifiStateEvidence(built.sessionId);
      } catch {
        // Fail-open: without evidence the review keeps the manual state gate.
      }
      const nextReview = await client.reviewHifiReplacement(built.sessionId);
      setReplacement(built);
      setReview(nextReview);
      setEditorVerification(undefined);
      setEditorScreenshotUrl(undefined);
      setChecks(EMPTY_CHECKS);
      setStage("review");
      setAutoNote("正在编辑器核验…");
      const verification = await client.verifyHifiReplacementInEditor(
        built.sessionId,
      );
      setEditorVerification(verification);
      if (
        !verification.approvable ||
        !verification.fullFrame ||
        !nextReview.candidateSha256
      ) {
        setAutoNote("");
        setError(
          "自动编辑器核验未通过：请打开 FairyGUI 编辑器后在本页完成核验与交付。",
        );
        return;
      }
      setAutoNote("正在确认交付…");
      const approved = await client.approveHifiReplacement(
        built.sessionId,
        nextReview.candidateSha256,
        "package",
      );
      setReplacement(approved);
      setExportMode("package");
      setStage("delivered");
      downloadBlob(
        await client.downloadHifiReplacement(approved.sessionId, false),
      );
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setAutoNote("");
      setPsdBusy(false);
    }
  };

  const build = async () => {
    if (!replacement || !mapping || mapping.unresolvedCount || psdBusy) return;
    autoContinueRef.current = false;
    setPsdBusy(true);
    setOperation("正在生成审核候选…");
    setError("");
    try {
      const built = await client.buildHifiReplacement(
        replacement.sessionId,
        mapping.mappingRevision,
      );
      const nextReview = await client.reviewHifiReplacement(
        replacement.sessionId,
      );
      setReplacement(built);
      setReview(nextReview);
      setEditorVerification(undefined);
      setEditorScreenshotUrl(undefined);
      setChecks(EMPTY_CHECKS);
      setStage("review");
      void loadFidelity(built.sessionId);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  const hideKeptObjects = async (itemIds: string[]) => {
    if (!replacement || !review || psdBusy || !itemIds.length) return;
    autoContinueRef.current = false;
    setPsdBusy(true);
    setOperation("正在隐藏无 PSD 对应的保留对象…");
    setError("");
    try {
      let nextReplacement = replacement;
      let revision = (await client.hifiMapping(nextReplacement.sessionId))
        .mappingRevision;
      for (const itemId of itemIds) {
        nextReplacement = await client.decideHifiMapping(
          nextReplacement.sessionId,
          revision,
          itemId,
          "keep_old",
          undefined,
          undefined,
          "retire",
        );
        const nextMapping = await client.hifiMapping(nextReplacement.sessionId);
        revision = nextMapping.mappingRevision;
        setReplacement(nextReplacement);
        setMapping(nextMapping);
      }
      const built = await client.buildHifiReplacement(
        nextReplacement.sessionId,
        revision,
      );
      const nextReview = await client.reviewHifiReplacement(
        nextReplacement.sessionId,
      );
      setReplacement(built);
      setReview(nextReview);
      setEditorVerification(undefined);
      setEditorScreenshotUrl(undefined);
      setChecks(EMPTY_CHECKS);
      void loadFidelity(built.sessionId);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  const download = async (candidate: boolean) => {
    if (!replacement) return;
    try {
      downloadBlob(
        await client.downloadHifiReplacement(replacement.sessionId, candidate),
      );
    } catch (cause) {
      setError(errorText(cause));
    }
  };

  const verifyEditor = async () => {
    if (!replacement || psdBusy) return;
    setPsdBusy(true);
    setOperation("正在打开 Editor 并检查画面…");
    setError("");
    try {
      const verification = await client.verifyHifiReplacementInEditor(
        replacement.sessionId,
      );
      setEditorVerification(verification);
      setEditorScreenshotUrl(undefined);
      setChecks(EMPTY_CHECKS);
      setOperation("正在运行时状态取证…");
      try {
        await client.hifiStateEvidence(replacement.sessionId);
      } catch {
        // Fail-open: without evidence the review keeps the manual state gate.
      }
      setReview(await client.reviewHifiReplacement(replacement.sessionId));
      if (verification.screenshotUrl) {
        const screenshot = await client.hifiEditorScreenshot(
          replacement.sessionId,
        );
        setEditorScreenshotUrl(URL.createObjectURL(screenshot));
      }
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  const approve = async () => {
    if (
      !replacement ||
      !review ||
      !canDeliverHifi(review, checks, editorVerification) ||
      !review.candidateSha256 ||
      psdBusy
    )
      return;
    setPsdBusy(true);
    setOperation("正在确认交付…");
    setError("");
    try {
      const approved = await client.approveHifiReplacement(
        replacement.sessionId,
        review.candidateSha256,
        exportMode,
      );
      setReplacement(approved);
      setStage("delivered");
      if (exportMode === "package") {
        downloadBlob(
          await client.downloadHifiReplacement(approved.sessionId, false),
        );
      }
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  const reject = async (reason: string) => {
    if (!replacement || psdBusy) return;
    autoContinueRef.current = false;
    setPsdBusy(true);
    setOperation("正在退回候选…");
    setError("");
    try {
      const rejected = await client.rejectHifiReplacement(
        replacement.sessionId,
        reason,
      );
      setReplacement(rejected);
      setMapping(await client.hifiMapping(replacement.sessionId));
      setStage("mapping");
      setReview(undefined);
      setEditorVerification(undefined);
      setEditorScreenshotUrl(undefined);
      setChecks(EMPTY_CHECKS);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  return {
    fonts,
    project,
    tree,
    selectedList,
    setSelectedList,
    sessions,
    exportMode,
    setExportMode,
    psdSource,
    compositeUrl,
    oldPreviewUrl,
    stage,
    setStage,
    replacement,
    mapping,
    removalReview,
    review,
    editorVerification,
    editorScreenshotUrl,
    checks,
    setChecks,
    currentItemId,
    setCurrentItemId,
    projectBusy,
    psdBusy,
    projectError,
    error,
    restoreNote,
    previewError,
    fontError,
    operation,
    targets,
    installedFonts,
    inspection,
    ready,
    toggleTarget,
    clearSession,
    retryPreview,
    retryFonts,
    chooseProject,
    choosePsd,
    startMapping,
    openSession,
    decide,
    decideRemoval,
    decideBatch,
    autoResolveBest,
    autoResolveNote,
    autoNote,
    runAutoPipeline,
    build,
    hideKeptObjects,
    download,
    verifyEditor,
    approve,
    reject,
    designAssets,
    designRootInput,
    setDesignRootInput,
    assetsBusy,
    assetsError,
    linkAssets,
    fidelity,
    comparison,
    openComparison,
    closeComparison,
    batchFidelity,
    loadSessionFidelity,
    EMPTY_CHECKS,
  };
}
