import { useEffect, useMemo, useRef, useState } from "react";

import type {
  DesignAssetStatus,
  FixedFontStatus,
  HifiBatch,
  HifiEditorVerification,
  HifiExportMode,
  HifiFidelityReport,
  HifiFidelityUnit,
  HifiMappingAction,
  HifiMappingDraft,
  HifiMappingItem,
  HifiMatchSuggestion,
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
import { WorkflowError } from "../../../figma-plugin/src/project-client";
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
  | "getPsdSource"
  | "psdComposite"
  | "psdCompositeCrop"
  | "effectViewport"
  | "effectCrop"
  | "psdResource"
  | "psdCutoutThumbnails"
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
  | "suggestBatchMatches"
  | "createBatch"
  | "getBatch"
  | "buildBatchPackage"
  | "writebackBatch"
  | "downloadBatch"
>;

type Stage =
  | "prepare"
  | "groups"
  | "sessions"
  | "mapping"
  | "review"
  | "delivered";
const EMPTY_CHECKS: HifiEditorCheckState = {
  layout: false,
  references: false,
  interactions: false,
};

export const AUTO_PIPELINE_STEPS = 6;

export const editorWaitConfig = {
  missingPollMs: 10_000,
  missingPolls: 6,
  startRetryMs: 20_000,
  startRetries: 2,
};

const delay = (ms: number) =>
  new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });

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
  if (code === "hifi_batch_not_found")
    return "批次不存在或已被清理，请重新建批。";
  if (code === "hifi_batch_not_export_ready")
    return "仍有分组未批准，不能构建合并包或写回。";
  if (code === "hifi_batch_not_packaged")
    return "合并包尚未构建，请先构建合并包。";
  if (code === "hifi_batch_build_failed")
    return "合并包构建失败，请检查工程完整性后重试。";
  if (code === "hifi_writeback_failed")
    return "写回原工程失败，请检查本机工程后重试。";
  if (code === "local_project_missing")
    return "本机工程路径不存在，请填写正确的工程文件夹。";
  if (code === "local_project_changed")
    return "本机工程与上传时的指纹不一致，可能已被修改；请重新导入后再写回。";
  if (code === "design_assets_root_invalid")
    return "设计资产文件夹路径无效或不存在。";
  if (code === "design_assets_cutout_dir_invalid")
    return "切图文件夹路径无效或不存在。";
  if (code === "network")
    return "无法连接本地服务，请确认服务正在运行后重试。";
  if (code === "unauthorized")
    return "访问令牌无效或已过期，请重新打开控制台。";
  if (code === "aborted") return "操作已取消。";
  if (code === "timeout")
    return "处理超时，请重试；若反复超时请检查 PSD 复杂度。";
  if (code === "invalid_response")
    return "服务返回的数据格式异常，请重试。";
  if (code === "hifi_ownership_conservation_violation")
    return "转换阶段守恒检查失败：PSD 图层所有权被无解释丢弃，已阻止本次转换；请查看服务日志中的丢失清单。";
  if (code === "hifi_removal_review_pending")
    return "存在待确认的旧视觉删除评审，请先在删除评审面板完成确认。";
  if (code === "review_required") return "该操作需要先完成审核。";
  if (code === "stale_candidate") return "候选已过期，请重新生成后再操作。";
  if (code === "conversion_conflict") return "请求与当前状态冲突，请刷新后重试。";
  if (code === "hifi_build_in_progress")
    return "上一次候选生成仍在进行中，请稍后重试；若服务曾中途重启，重试会自动恢复。";
  if (code === "stale_mapping")
    return "映射版本已变化，界面已自动刷新，请重新点击一次。";
  if (code === "hifi_removal_review_empty")
    return "删除评审已确认完毕，可直接继续下一步。";
  if (code === "hifi_removal_decision_incomplete")
    return "还有删除评审组未做选择，请补全后提交。";
  if (code === "hifi_review_unavailable")
    return "审核结果尚未生成，请先生成候选。";
  if (code === "psd_source_unavailable")
    return "PSD 材料不可用，请重新上传或重新链接设计资产。";
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
  const [autoProgress, setAutoProgress] = useState<{
    step: number;
    total: number;
    label: string;
  }>();
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
  const [cutoutThumbnails, setCutoutThumbnails] = useState<Record<string, string>>({});
  const [cutoutInfo, setCutoutInfo] = useState<
    Record<string, { family: string; relevance: string }>
  >({});
  const cutoutThumbSourceRef = useRef<string | undefined>(undefined);
  const [psdItems, setPsdItems] = useState<
    Array<{ sourceId: string; name: string }>
  >([]);
  const [pairTargets, setPairTargets] = useState<
    Record<string, HifiTargetRef>
  >({});
  const [batchId, setBatchId] = useState<string>();
  const [batch, setBatch] = useState<HifiBatch>();
  const [batchBusy, setBatchBusy] = useState(false);
  const batchIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    const sourceId = psdSource?.sourceId;
    if (!sourceId || cutoutThumbSourceRef.current === sourceId) return;
    cutoutThumbSourceRef.current = sourceId;
    void (async () => {
      try {
        const entries = await client.psdCutoutThumbnails(sourceId);
        setCutoutThumbnails(
          Object.fromEntries(entries.map((entry) => [entry.name, entry.thumbnail])),
        );
        setCutoutInfo(
          Object.fromEntries(
            entries.map((entry) => [
              entry.name,
              { family: entry.family, relevance: entry.relevance },
            ]),
          ),
        );
      } catch {
        setCutoutThumbnails({});
        setCutoutInfo({});
      }
    })();
  }, [psdSource?.sourceId, client]);
  const [designRootInput, setDesignRootInput] = useState("");
  const [cutoutDirInput, setCutoutDirInput] = useState("");
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
    setBatchId(undefined);
    batchIdRef.current = undefined;
    setBatch(undefined);
    setPairTargets({});
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

  const cropCacheRef = useRef(new Map<string, string>());
  const loadPsdCrop = async (bounds: [number, number, number, number]) => {
    if (!psdSource) return undefined;
    const key = bounds.map((value) => Math.round(value)).join(",");
    const cached = cropCacheRef.current.get(key);
    if (cached) return cached;
    const blob = await client.psdCompositeCrop(psdSource.sourceId, bounds);
    const url = URL.createObjectURL(blob);
    cropCacheRef.current.set(key, url);
    return url;
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
      const status = await client.linkDesignAssets(
        psdSource.sourceId,
        root,
        cutoutDirInput.trim() || undefined,
      );
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

  const choosePsds = async (files?: File[] | FileList) => {
    const list = Array.from(files ?? []);
    if (!list.length) return;
    clearSession();
    setPreviewError("");
    cropCacheRef.current = new Map();
    setPsdBusy(true);
    setOperation(
      list.length > 1
        ? `正在解析 ${list.length} 个 PSD 并保存材料…`
        : "正在解析 PSD 并保存材料…",
    );
    try {
      const items = [...psdItems];
      let first: PsdSource | undefined;
      for (const file of list) {
        const uploaded = await client.uploadPsd(file);
        first ??= uploaded;
        if (!items.some((item) => item.sourceId === uploaded.sourceId)) {
          items.push({
            sourceId: uploaded.sourceId,
            name: uploaded.inspection.sourceName,
          });
        }
        setPsdItems([...items]);
      }
      if (targets.length === 1) {
        const only = targets[0];
        setPairTargets((current) => {
          const next = { ...current };
          for (const item of items) {
            if (!next[item.sourceId]) next[item.sourceId] = only;
          }
          return next;
        });
      }
      if (!first) return;
      setPsdSource(first);
      try {
        const composite = await client.psdComposite(first.sourceId);
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

  const selectPsd = async (sourceId: string) => {
    if (psdBusy || psdSource?.sourceId === sourceId) return;
    setPsdBusy(true);
    setPreviewError("");
    try {
      const source = await client.getPsdSource(sourceId);
      setPsdSource(source);
      setCompositeUrl((current) => {
        if (current && typeof URL.revokeObjectURL === "function")
          URL.revokeObjectURL(current);
        return undefined;
      });
      try {
        const composite = await client.psdComposite(sourceId);
        if (typeof URL.createObjectURL === "function")
          setCompositeUrl(URL.createObjectURL(composite));
      } catch {
        setPreviewError("PSD 预览加载失败，材料已保留。请重试加载预览。");
      }
      try {
        setDesignAssets(await client.getDesignAssets(sourceId));
      } catch {
        setDesignAssets({ linked: false });
      }
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  const targetOptions = useMemo(() => {
    if (!project || !tree) return [] as Array<{ label: string; ref: HifiTargetRef }>;
    const options: Array<{ label: string; ref: HifiTargetRef }> = [];
    for (const pkg of tree.packages) {
      for (const dir of pkg.directories) {
        for (const comp of dir.components) {
          if (!comp.selectable) continue;
          options.push({
            label: `${pkg.name}/${dir.path}/${comp.name}`,
            ref: {
              version: 1,
              projectId: project.projectId,
              projectFingerprint: tree.projectFingerprint,
              packageId: pkg.packageId,
              packageName: pkg.name,
              directory: dir.path,
              componentId: comp.resourceId,
              componentName: comp.name,
              componentRelativePath: comp.relativePath,
            },
          });
        }
      }
    }
    return options;
  }, [project, tree]);

  const setPairTarget = (sourceId: string, relativePath: string) => {
    setPairTargets((current) => {
      if (!relativePath) {
        const rest = { ...current };
        delete rest[sourceId];
        return rest;
      }
      const found = targetOptions.find(
        (option) => option.ref.componentRelativePath === relativePath,
      );
      if (!found) return current;
      return { ...current, [sourceId]: found.ref };
    });
  };

  const prelinkAssets = async () => {
    const root = designRootInput.trim();
    const cutout = cutoutDirInput.trim();
    if (!root && !cutout) return;
    await Promise.allSettled(
      psdItems.map((item) =>
        client.linkDesignAssets(item.sourceId, root || cutout, cutout || undefined),
      ),
    );
  };

  const autoFillPairs = async () => {
    if (!project || !psdItems.length || psdBusy) return;
    setPsdBusy(true);
    setOperation("正在按评分补全未配对 PSD…");
    setError("");
    try {
      await prelinkAssets();
      const suggestions = await client.suggestBatchMatches(
        project.projectId,
        psdItems.map((item) => item.sourceId),
      );
      setPairTargets((current) => {
        const next = { ...current };
        for (const suggestion of suggestions) {
          if (next[suggestion.sourceId]) continue;
          const pick =
            suggestion.candidates.find((candidate) => candidate.suggested) ??
            suggestion.candidates[0];
          if (pick) next[suggestion.sourceId] = pick.target;
        }
        return next;
      });
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  const createBatchFromPairs = async () => {
    const pairs = psdItems
      .map((item) => ({
        sourceId: item.sourceId,
        target: pairTargets[item.sourceId],
      }))
      .filter(
        (
          pair,
        ): pair is { sourceId: string; target: HifiTargetRef } =>
          Boolean(pair.target),
      );
    if (!project || !pairs.length || psdBusy) return;
    setPsdBusy(true);
    setOperation("正在建立 HIFI 批次…");
    setError("");
    try {
      await prelinkAssets();
      const created = await client.createBatch({
        projectId: project.projectId,
        designRoot: designRootInput.trim() || null,
        cutoutDir: cutoutDirInput.trim() || null,
        pairs,
      });
      setBatchId(created.batchId);
      batchIdRef.current = created.batchId;
      setBatch(created);
      setStage("groups");
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  const refreshBatch = async (options?: { quiet?: boolean }) => {
    const id = batchIdRef.current;
    if (!id) return;
    try {
      setBatch(await client.getBatch(id));
    } catch (cause) {
      if (!options?.quiet) setError(errorText(cause));
    }
  };

  useEffect(() => {
    if (stage !== "groups" || !batchId) return;
    const timer = window.setInterval(() => {
      void refreshBatch({ quiet: true });
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [stage, batchId]);

  const buildBatchPackage = async () => {
    const id = batchIdRef.current;
    if (!id || batchBusy) return;
    setBatchBusy(true);
    setError("");
    try {
      setBatch(await client.buildBatchPackage(id));
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBatchBusy(false);
    }
  };

  const downloadBatchManual = async () => {
    const id = batchIdRef.current;
    if (!id || batchBusy) return;
    setBatchBusy(true);
    setError("");
    try {
      const downloaded = await client.downloadBatch(id);
      downloadBlob({
        blob: downloaded.blob,
        downloadName: downloaded.fileName,
      });
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBatchBusy(false);
    }
  };

  const writebackBatch = async (localPath: string) => {
    const id = batchIdRef.current;
    const path = localPath.trim();
    if (!id || !path || batchBusy) return;
    setBatchBusy(true);
    setError("");
    try {
      setBatch(await client.writebackBatch(id, path));
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBatchBusy(false);
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

  const presentSession = async (
    session: HifiReplacement,
    draft: HifiMappingDraft,
  ): Promise<
    { replacement: HifiReplacement; mapping: HifiMappingDraft } | undefined
  > => {
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
  };

  const openSession = async (session: HifiReplacement): Promise<
    { replacement: HifiReplacement; mapping: HifiMappingDraft } | undefined
  > => {
    setPsdBusy(true);
    setOperation("正在打开会话…");
    setError("");
    try {
      const draft = await client.hifiMapping(session.sessionId);
      return await presentSession(session, draft);
    } catch (cause) {
      setError(errorText(cause));
      return undefined;
    } finally {
      setPsdBusy(false);
    }
  };

  const enterGroup = async (sessionId: string): Promise<
    { replacement: HifiReplacement; mapping: HifiMappingDraft } | undefined
  > => {
    if (psdBusy) return undefined;
    setPsdBusy(true);
    setOperation("正在打开批次分组…");
    setError("");
    try {
      const resumed = await client.resumePsdHifiReplacement(sessionId);
      cropCacheRef.current = new Map();
      setPsdSource(resumed.source);
      setCompositeUrl(undefined);
      setPreviewError("");
      try {
        const composite = await client.psdComposite(resumed.source.sourceId);
        if (typeof URL.createObjectURL === "function")
          setCompositeUrl(URL.createObjectURL(composite));
      } catch {
        setPreviewError("PSD 预览加载失败，材料已保留。请重试加载预览。");
      }
      return await presentSession(resumed.replacement, resumed.mapping);
    } catch (cause) {
      setError(errorText(cause));
      return undefined;
    } finally {
      setPsdBusy(false);
    }
  };

  const leaveGroup = async () => {
    autoContinueRef.current = false;
    setReview(undefined);
    setRemovalReview(undefined);
    setEditorVerification(undefined);
    setEditorScreenshotUrl(undefined);
    setChecks(EMPTY_CHECKS);
    setAutoProgress(undefined);
    setAutoNote("");
    setStage("groups");
    await refreshBatch();
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
      const code =
        cause instanceof WorkflowError
          ? (cause.code as string | undefined)
          : undefined;
      if (code === "stale_mapping" || code === "hifi_removal_review_empty") {
        try {
          const [nextMapping, nextReview] = await Promise.all([
            client.hifiMapping(replacement.sessionId),
            client.hifiRemovalReview(replacement.sessionId),
          ]);
          setMapping(nextMapping);
          if (nextReview.groups.length === 0) {
            setRemovalReview(undefined);
            queueAutoContinue(replacement.sessionId, nextMapping);
            if (code === "hifi_removal_review_empty") return;
          } else {
            setRemovalReview(nextReview);
          }
        } catch {
          /* Keep the original guidance below. */
        }
      }
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
          ? `剩余 ${pending} 项无法自动决策，请在对象清单中逐项处理。`
          : "待确认项已全部自动处理。",
      );
      queueAutoContinue(next.sessionId, nextMapping);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setPsdBusy(false);
    }
  };

  const setPipelineStep = (step: number, label: string) => {
    setAutoNote(label);
    setAutoProgress({ step, total: AUTO_PIPELINE_STEPS, label });
  };

  const refinePipelineLabel = (label: string) => {
    setAutoNote(label);
    setAutoProgress((current) =>
      current ? { ...current, label } : current,
    );
  };

  const runAutoPipeline = async (initial: {
    replacement: HifiReplacement;
    mapping: HifiMappingDraft;
  }) => {
    setPsdBusy(true);
    setError("");
    setAutoResolveNote("");
    let waitingForUser = false;
    setPipelineStep(1, "自动匹配与决议…");
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
            ? `发现 ${removal.totalCandidateCount} 个旧对象在新设计（PSD）中不存在，请在下方逐组确认移除或保留；确认后自动继续。`
            : `剩余 ${remaining} 项无法自动决策，请在下方对象清单中逐项处理；处理完最后一项后自动继续。`,
        );
        waitingForUser = true;
        setPipelineStep(
          2,
          "等待删除评审确认（在该面板选择移除/保留后自动继续）…",
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
      setAutoProgress(undefined);
    } finally {
      setAutoNote("");
      if (!waitingForUser) {
        setAutoProgress(undefined);
      }
      setPsdBusy(false);
    }
  };

  const runEditorVerification = async (
    sessionId: string,
  ): Promise<HifiEditorVerification> => {
    let startAttempts = 0;
    let missingPolls = 0;
    for (;;) {
      let verification: HifiEditorVerification;
      try {
        verification = await client.verifyHifiReplacementInEditor(sessionId);
      } catch (cause) {
        if (startAttempts >= editorWaitConfig.startRetries) throw cause;
        startAttempts += 1;
        refinePipelineLabel(
          `FairyGUI Editor 启动未就绪，${Math.round(editorWaitConfig.startRetryMs / 1000)} 秒后自动重试（第 ${startAttempts}/${editorWaitConfig.startRetries} 次）…`,
        );
        await delay(editorWaitConfig.startRetryMs);
        continue;
      }
      if (verification.editorFound) return verification;
      if (missingPolls >= editorWaitConfig.missingPolls) return verification;
      missingPolls += 1;
      refinePipelineLabel(
        `未找到 FairyGUI Editor——持续检测中（第 ${missingPolls}/${editorWaitConfig.missingPolls} 次，安装或打开后自动继续）…`,
      );
      await delay(editorWaitConfig.missingPollMs);
    }
  };

  const continueAutoPipeline = async (
    sessionId: string,
    mappingRevision: number,
  ) => {
    setPsdBusy(true);
    setError("");
    setAutoResolveNote("");
    try {
      setPipelineStep(3, "生成替换包…");
      const built = await client.buildHifiReplacement(
        sessionId,
        mappingRevision,
      );
      setPipelineStep(4, "运行时状态取证与候选评审…");
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
      setPipelineStep(5, "正在编辑器核验…");
      const verification = await runEditorVerification(built.sessionId);
      setEditorVerification(verification);
      if (
        !verification.approvable ||
        !verification.fullFrame ||
        !nextReview.candidateSha256
      ) {
        setAutoNote("");
        setAutoProgress(undefined);
        setError(
          verification.editorFound
            ? "自动编辑器核验未通过：请查看差异区域清单，在本页完成核验与交付。"
            : "未找到 FairyGUI Editor 6.1.4：安装或启动后重跑流水线；交付前必须完成编辑器核验。",
        );
        return;
      }
      setPipelineStep(6, "确认交付…");
      const approved = await client.approveHifiReplacement(
        built.sessionId,
        nextReview.candidateSha256,
        "package",
      );
      setReplacement(approved);
      setExportMode("package");
      setStage("delivered");
    } catch (cause) {
      setError(errorText(cause));
      setAutoProgress(undefined);
    } finally {
      setAutoNote("");
      setAutoProgress(undefined);
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
    loadPsdCrop,
    stage,
    setStage,
    replacement,
    mapping,
    removalReview,
    autoProgress,
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
    choosePsds,
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
    download,
    verifyEditor,
    approve,
    reject,
    designAssets,
    cutoutThumbnails,
    cutoutInfo,
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
    psdItems,
    cutoutDirInput,
    setCutoutDirInput,
    selectPsd,
    pairTargets,
    targetOptions,
    setPairTarget,
    autoFillPairs,
    createBatchFromPairs,
    batchId,
    batch,
    batchBusy,
    refreshBatch,
    enterGroup,
    leaveGroup,
    buildBatchPackage,
    downloadBatchManual,
    writebackBatch,
    EMPTY_CHECKS,
  };
}
