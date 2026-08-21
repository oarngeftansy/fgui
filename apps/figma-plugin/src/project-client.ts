import type { ExportedResource } from "./assets";
import { MAX_SEMANTIC_SCREENSHOT_BYTES } from "./contracts";
import type { SelectionManifest } from "./selection";
import { parseSelectionView, SelectionUploadError, SelectionUploader, type FetchLike, type SelectionView } from "./upload";

export type WorkflowErrorCode = "network" | "invalid_zip" | "unknown_template" | "validation" | "conversion_conflict" | "conversion_failed" | "package_failed" | "unauthorized" | "aborted" | "timeout" | "invalid_response" | "review_required" | "stale_candidate";
export type WorkflowStageName = "uploading" | "parsing" | "converting" | "checking" | "awaiting_screenshot_consent" | "packaging" | "ready" | "failed";
export type WorkflowStage = { stage: WorkflowStageName; progress: number };
export type WorkflowStageCallback = (stage: WorkflowStage) => void;
export type ProjectOption = { templateId: string; fairyguiVersion: string; targetPlatform: string; displayName: string };
export type ProjectView = { projectId: string; displayName: string; packages: Array<{ name: string; resourceCount: number }> };
export type JobView = { jobId: string; projectId: string; status: string };
export type DiagnosticView = { code: string; severity: "ERROR" | "WARNING" | "INFO"; message: string; nodeId?: string; path?: string; ruleId?: string; ruleVersion?: number };
export type PackageStage = "uploading" | "parsing" | "converting" | "checking" | "awaiting_screenshot_consent" | "packaging" | "ready" | "failed";
export type PackageView = { jobId: string; status: PackageStage; stage: PackageStage; progress: number; downloadName?: string; sha256?: string; screenshotReason?: string; diagnostics: DiagnosticView[] };
export type DownloadedPackage = { blob: Blob; downloadName: string };
export type WorkflowResult = DownloadedPackage & { project: ProjectView; selection: SelectionView; job: JobView; package: PackageView };
export type SemanticScreenshot = { mimeType: "image/png"; bytes: Uint8Array };
export type ScreenshotConsentRequest = { jobId: string; reason: string; signal: AbortSignal };
export type ScreenshotWorkflowCallbacks = {
  onScreenshotConsent(request: ScreenshotConsentRequest): Promise<boolean>;
  requestScreenshot(jobId: string, signal: AbortSignal): Promise<SemanticScreenshot>;
};
type NoScreenshotWorkflowCallbacks = { onScreenshotConsent?: never; requestScreenshot?: never };
export type WorkflowRunOptions = (ScreenshotWorkflowCallbacks | NoScreenshotWorkflowCallbacks) & { signal?: AbortSignal; timeoutMs?: number };
export type WaitForPackageOptions = WorkflowRunOptions & { onStage?: WorkflowStageCallback };
export type NewProjectStage = "converting" | "checking" | "packaging" | "awaiting_review" | "adjusting" | "regenerating" | "approved" | "rejected" | "failed";
export type NewProjectCandidate = {
  buildId: string;
  generation: number;
  status: NewProjectStage;
  stage: NewProjectStage;
  progress: number;
  downloadName?: string;
  sha256?: string;
  byteSize?: number;
  artifactReady?: boolean;
  diagnostics: readonly DiagnosticView[];
};
export type NewProjectAdjustmentStrategy = "preserve-editable" | "rasterize-subtree" | "include-contained-definition";
export type NewProjectDispositionLevel = "native" | "raster_preserved" | "editable_risk" | "blocked";
export type NewProjectDispositionReason = "gradient_paint" | "visual_effect" | "blend_mode" | "multiple_paints" | "mask_composite" | "instance_composite" | "visual_style" | "unrepresentable_transform" | "rich_text_runs" | "component_definition_missing" | "interaction_unsupported" | "resource_missing";
export type NewProjectConversionDisposition = { version: 1; id: string; sourceNodeId: string; sourceName: string; sourceType: string; level: NewProjectDispositionLevel; reason: NewProjectDispositionReason; defaultStrategy?: NewProjectAdjustmentStrategy; allowedStrategies: NewProjectAdjustmentStrategy[]; visualImpact: "unchanged" | "visual_preserved" | "may_differ"; editabilityImpact: "unchanged" | "subtree_not_editable" | "text_not_editable"; componentImpact: "unchanged" | "instance_not_reusable"; blocksApproval: boolean };
export type NewProjectImageReview = { resourceId: string; label: string; evidenceKind: "source-image" | "generated-only"; sourcePreviewUrl?: string; generatedAssetUrl: string; width: number; height: number; nineSlice: boolean; cropBoundsMatch: boolean; transparencyPreserved: boolean };
export type NewProjectComponentReview = { componentId: string; label: string; evidenceKind: "rendered" | "structured-summary"; renderedPreviewUrl?: string; objectCount: number; textCount: number; resourceRefs: number; componentRefs: number; hierarchyValid: boolean; geometryValid: boolean; textValid: boolean };
export type NewProjectPackageReview = { packageName: string; fairyguiVersion: "6.1.4"; publishTarget: "unity"; componentsAdded: number; resourcesAdded: number; componentNames: string[]; resourceNames: string[]; resourceClosureValid: boolean; namingConflicts: string[]; integrityValid: boolean };
export type NewProjectCheck = { id: string; severity: "ERROR" | "WARNING" | "INFO"; message: string; issueId: string; issueKind?: "raster-fallback" | "definition-missing"; uirNodeId?: string; sourceNodeId?: string; actionable: boolean; allowedStrategies: NewProjectAdjustmentStrategy[] };
export type NewProjectReview = { version: 1; buildId: string; generation: number; dispositions: NewProjectConversionDisposition[]; imageReviews: NewProjectImageReview[]; componentReviews: NewProjectComponentReview[]; packageReview: NewProjectPackageReview; checks: NewProjectCheck[]; warningIds: string[]; approvable: boolean };
export type NewProjectRunResult = { selection: SelectionView; candidate: NewProjectCandidate };

type Wait = (milliseconds: number, signal?: AbortSignal) => Promise<void>;
type RecordValue = Record<string, unknown>;

function targetPackage(project: ProjectView): string | undefined {
  const featurePackages = project.packages.filter(({ name }) => !/^(?:base\d*|common|icons?)$/iu.test(name));
  return (featurePackages.length === 1 ? featurePackages[0] : project.packages[0])?.name;
}

const messages: Record<WorkflowErrorCode, string> = {
  network: "无法连接内网服务，请检查网络后重试",
  invalid_zip: "工程 ZIP 无效、已损坏或不是 FairyGUI 工程",
  unknown_template: "所选工程模板不可用，请刷新后重试",
  validation: "提交内容未通过检查，请修正后重试",
  conversion_conflict: "当前设计与工程存在冲突，请检查后重试",
  conversion_failed: "工程创建或更新失败，请检查设计内容后重试",
  package_failed: "工程打包失败，请重试",
  unauthorized: "插件未获服务授权，请联系管理员",
  aborted: "操作已取消",
  timeout: "处理超时，请重试",
  invalid_response: "服务返回的数据无法识别，请重试",
  review_required: "请先完整检查并确认当前候选工程",
  stale_candidate: "候选工程已失效，请基于当前选择重新生成",
};

export class WorkflowError extends Error {
  constructor(readonly code: WorkflowErrorCode) { super(messages[code]); this.name = "WorkflowError"; }
}

function record(value: unknown): RecordValue {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new WorkflowError("invalid_response");
  return value as RecordValue;
}

function exactRecord(value: unknown, keys: readonly string[]): RecordValue {
  const data = record(value);
  const actual = Object.keys(data).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) throw new WorkflowError("invalid_response");
  return data;
}

function requiredString(value: unknown): string {
  if (typeof value !== "string" || !value) throw new WorkflowError("invalid_response");
  return value;
}

function identifier(value: unknown): string {
  const result = requiredString(value);
  if (!/^[0-9a-f]{32}$/.test(result)) throw new WorkflowError("invalid_response");
  return result;
}

function optionalString(value: unknown): string | undefined {
  if (value == null) return undefined;
  return requiredString(value);
}

function natural(value: unknown): number {
  if (!Number.isInteger(value) || Number(value) < 0) throw new WorkflowError("invalid_response");
  return value as number;
}

function positive(value: unknown): number {
  const result = natural(value);
  if (!result) throw new WorkflowError("invalid_response");
  return result;
}

function exactString(value: unknown, allowed: readonly string[]): string {
  const result = requiredString(value);
  if (!allowed.includes(result)) throw new WorkflowError("invalid_response");
  return result;
}

function parseDiagnostic(value: unknown): DiagnosticView {
  const data = record(value);
  if (!["ERROR", "WARNING", "INFO"].includes(String(data.severity))) throw new WorkflowError("invalid_response");
  if (data.rule_version != null && (!Number.isInteger(data.rule_version) || Number(data.rule_version) < 0)) throw new WorkflowError("invalid_response");
  return {
    code: requiredString(data.code), severity: data.severity as DiagnosticView["severity"], message: requiredString(data.message),
    ...(optionalString(data.node_id) ? { nodeId: data.node_id as string } : {}), ...(optionalString(data.path) ? { path: data.path as string } : {}),
    ...(optionalString(data.rule_id) ? { ruleId: data.rule_id as string } : {}), ...(data.rule_version != null ? { ruleVersion: data.rule_version as number } : {}),
  };
}

function parseProject(value: unknown): ProjectView {
  const data = record(value);
  if (data.version !== 1 || !Array.isArray(data.packages)) throw new WorkflowError("invalid_response");
  const result: ProjectView = {
    projectId: identifier(data.project_id),
    displayName: requiredString(data.display_name),
    packages: data.packages.map((item) => {
      const itemData = record(item);
      if (!Number.isInteger(itemData.resource_count) || Number(itemData.resource_count) < 0) throw new WorkflowError("invalid_response");
      return { name: requiredString(itemData.name), resourceCount: itemData.resource_count as number };
    }),
  };
  if (!result.packages.length || new Set(result.packages.map((item) => item.name)).size !== result.packages.length) throw new WorkflowError("invalid_response");
  return result;
}

function parseJob(value: unknown, expectedProjectId?: string): JobView {
  const data = record(value);
  const statuses = new Set(["created", "ready_for_review", "conversion_failed", "approved", "applying", "applied", "failed", "rejected"]);
  if (data.version !== 1 || !statuses.has(String(data.status))) throw new WorkflowError("invalid_response");
  const result = { jobId: identifier(data.job_id), projectId: identifier(data.project_id), status: data.status as string };
  if (expectedProjectId && result.projectId !== expectedProjectId) throw new WorkflowError("invalid_response");
  return result;
}

function parsePackage(value: unknown, expectedJobId?: string): PackageView {
  const data = record(value);
  const valid = new Set<PackageStage>(["uploading", "parsing", "converting", "checking", "awaiting_screenshot_consent", "packaging", "ready", "failed"]);
  if (data.version !== 1 || !valid.has(data.status as PackageStage) || data.status !== data.stage || !Number.isInteger(data.progress) || Number(data.progress) < 0 || Number(data.progress) > 100 || !Array.isArray(data.diagnostics)) throw new WorkflowError("invalid_response");
  const result: PackageView = { jobId: identifier(data.job_id), status: data.status as PackageStage, stage: data.stage as PackageStage, progress: data.progress as number, diagnostics: data.diagnostics.map(parseDiagnostic) };
  if (expectedJobId && result.jobId !== expectedJobId) throw new WorkflowError("invalid_response");
  if (data.download_name != null) result.downloadName = requiredString(data.download_name);
  if (data.screenshot_reason != null) {
    const reason = requiredString(data.screenshot_reason).trim();
    if (!reason || reason.length > 240) throw new WorkflowError("invalid_response");
    result.screenshotReason = reason;
  }
  if (result.status === "awaiting_screenshot_consent" && !result.screenshotReason) throw new WorkflowError("invalid_response");
  if (data.sha256 != null) {
    if (typeof data.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(data.sha256)) throw new WorkflowError("invalid_response");
    result.sha256 = data.sha256;
  }
  if (result.status === "ready" && (!result.downloadName || !validWindowsZipName(result.downloadName) || !result.sha256 || result.progress !== 100)) throw new WorkflowError("invalid_response");
  return result;
}

const NEW_PROJECT_STAGES: readonly NewProjectStage[] = ["converting", "checking", "packaging", "awaiting_review", "adjusting", "regenerating", "approved", "rejected", "failed"];
const ADJUSTMENT_STRATEGIES: readonly NewProjectAdjustmentStrategy[] = ["preserve-editable", "rasterize-subtree", "include-contained-definition"];
const DISPOSITION_LEVELS: readonly NewProjectDispositionLevel[] = ["native", "raster_preserved", "editable_risk", "blocked"];
const DISPOSITION_REASONS: readonly NewProjectDispositionReason[] = ["gradient_paint", "visual_effect", "blend_mode", "multiple_paints", "mask_composite", "instance_composite", "visual_style", "unrepresentable_transform", "rich_text_runs", "component_definition_missing", "interaction_unsupported", "resource_missing"];

function parseNewProjectDiagnostic(value: unknown): DiagnosticView {
  const data = exactRecord(value, ["code", "severity", "message", "node_id", "path", "rule_id", "rule_version", "evidence", "suggested_action", "blocks_binding"]);
  if (!Array.isArray(data.evidence) || !data.evidence.every((item) => typeof item === "string") || typeof data.blocks_binding !== "boolean") throw new WorkflowError("invalid_response");
  return parseDiagnostic(data);
}

function parseNewProjectCandidate(value: unknown, expectedBuildId?: string, expectedGeneration?: number): NewProjectCandidate {
  const data = exactRecord(value, ["version", "build_id", "generation", "status", "stage", "progress", "download_name", "sha256", "byte_size", "artifact_ready", "diagnostics"]);
  if (data.version !== 1 || data.status !== data.stage || !NEW_PROJECT_STAGES.includes(data.stage as NewProjectStage) || typeof data.artifact_ready !== "boolean" || !Array.isArray(data.diagnostics)) throw new WorkflowError("invalid_response");
  const buildId = identifier(data.build_id);
  if (expectedBuildId && buildId !== expectedBuildId) throw new WorkflowError("stale_candidate");
  const generation = positive(data.generation);
  if (expectedGeneration != null && generation !== expectedGeneration) throw new WorkflowError("stale_candidate");
  const progress = natural(data.progress);
  if (progress > 100) throw new WorkflowError("invalid_response");
  const metadata = [data.download_name, data.sha256, data.byte_size];
  if (metadata.some((item) => item == null) !== metadata.every((item) => item == null)) throw new WorkflowError("invalid_response");
  const result: NewProjectCandidate = {
    buildId,
    generation: positive(generation),
    status: data.status as NewProjectStage,
    stage: data.stage as NewProjectStage,
    progress,
    artifactReady: data.artifact_ready,
    diagnostics: data.diagnostics.map(parseNewProjectDiagnostic),
  };
  if (data.download_name != null) {
    const name = requiredString(data.download_name);
    if (!validWindowsZipName(name) || !name.endsWith("-FairyGUI.zip")) throw new WorkflowError("invalid_response");
    result.downloadName = name;
    if (typeof data.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(data.sha256)) throw new WorkflowError("invalid_response");
    result.sha256 = data.sha256;
    result.byteSize = natural(data.byte_size);
  }
  if (result.artifactReady !== Boolean(result.downloadName) || result.status === "approved" && !result.artifactReady) throw new WorkflowError("invalid_response");
  return result;
}

function nullableUrl(value: unknown): string | undefined {
  if (value == null) return undefined;
  const result = requiredString(value);
  if (!/^\/v1\/[A-Za-z0-9_./-]+$/.test(result) || result.includes("..") || result.includes("//")) throw new WorkflowError("invalid_response");
  return result;
}

function parseConversionDisposition(value: unknown): NewProjectConversionDisposition {
  const item = exactRecord(value, ["version", "id", "sourceNodeId", "sourceName", "sourceType", "level", "reason", "defaultStrategy", "allowedStrategies", "visualImpact", "editabilityImpact", "componentImpact", "blocksApproval"]);
  if (item.version !== 1 || !/^disposition:[0-9a-f]{16}$/.test(String(item.id)) || !Array.isArray(item.allowedStrategies) || typeof item.blocksApproval !== "boolean") throw new WorkflowError("invalid_response");
  const level = exactString(item.level, DISPOSITION_LEVELS) as NewProjectDispositionLevel;
  const reason = exactString(item.reason, DISPOSITION_REASONS) as NewProjectDispositionReason;
  const allowedStrategies = item.allowedStrategies.map((strategy) => exactString(strategy, ADJUSTMENT_STRATEGIES) as NewProjectAdjustmentStrategy);
  const defaultStrategy = item.defaultStrategy == null ? undefined : exactString(item.defaultStrategy, ADJUSTMENT_STRATEGIES) as NewProjectAdjustmentStrategy;
  if (new Set(allowedStrategies).size !== allowedStrategies.length || Boolean(defaultStrategy) !== (allowedStrategies.length > 0) || defaultStrategy && !allowedStrategies.includes(defaultStrategy) || item.blocksApproval !== (level === "blocked")) throw new WorkflowError("invalid_response");
  return {
    version: 1,
    id: item.id as string,
    sourceNodeId: requiredString(item.sourceNodeId),
    sourceName: requiredString(item.sourceName),
    sourceType: exactString(item.sourceType, ["FRAME", "GROUP", "COMPONENT", "INSTANCE", "RECTANGLE", "ELLIPSE", "VECTOR", "BOOLEAN_OPERATION", "STAR", "LINE", "POLYGON", "TEXT", "IMAGE"]),
    level,
    reason,
    ...(defaultStrategy ? { defaultStrategy } : {}),
    allowedStrategies,
    visualImpact: exactString(item.visualImpact, ["unchanged", "visual_preserved", "may_differ"]) as NewProjectConversionDisposition["visualImpact"],
    editabilityImpact: exactString(item.editabilityImpact, ["unchanged", "subtree_not_editable", "text_not_editable"]) as NewProjectConversionDisposition["editabilityImpact"],
    componentImpact: exactString(item.componentImpact, ["unchanged", "instance_not_reusable"]) as NewProjectConversionDisposition["componentImpact"],
    blocksApproval: item.blocksApproval,
  };
}

function parseNewProjectReview(value: unknown, expectedBuildId: string, expectedGeneration?: number): NewProjectReview {
  const data = exactRecord(value, ["version", "build_id", "generation", "dispositions", "image_reviews", "component_reviews", "package_review", "checks", "warning_ids", "approvable"]);
  if (data.version !== 1 || identifier(data.build_id) !== expectedBuildId || !Array.isArray(data.dispositions) || !Array.isArray(data.image_reviews) || !Array.isArray(data.component_reviews) || !Array.isArray(data.checks) || !Array.isArray(data.warning_ids) || typeof data.approvable !== "boolean") throw new WorkflowError("invalid_response");
  const generation = positive(data.generation);
  if (expectedGeneration != null && generation !== expectedGeneration) throw new WorkflowError("stale_candidate");
  const imageReviews = data.image_reviews.map((value): NewProjectImageReview => {
    const item = exactRecord(value, ["resource_id", "label", "evidence_kind", "source_preview_url", "generated_asset_url", "width", "height", "nine_slice", "crop_bounds_match", "transparency_preserved"]);
    const evidenceKind = exactString(item.evidence_kind, ["source-image", "generated-only"]) as NewProjectImageReview["evidenceKind"];
    if (typeof item.nine_slice !== "boolean" || typeof item.crop_bounds_match !== "boolean" || typeof item.transparency_preserved !== "boolean") throw new WorkflowError("invalid_response");
    const sourcePreviewUrl = nullableUrl(item.source_preview_url);
    const generatedAssetUrl = nullableUrl(item.generated_asset_url);
    if (!generatedAssetUrl) throw new WorkflowError("invalid_response");
    if ((evidenceKind === "source-image") !== Boolean(sourcePreviewUrl)) throw new WorkflowError("invalid_response");
    return { resourceId: requiredString(item.resource_id), label: requiredString(item.label), evidenceKind, ...(sourcePreviewUrl ? { sourcePreviewUrl } : {}), generatedAssetUrl, width: natural(item.width), height: natural(item.height), nineSlice: item.nine_slice, cropBoundsMatch: item.crop_bounds_match, transparencyPreserved: item.transparency_preserved };
  });
  const componentReviews = data.component_reviews.map((value): NewProjectComponentReview => {
    const item = exactRecord(value, ["component_id", "label", "evidence_kind", "rendered_preview_url", "object_count", "text_count", "resource_refs", "component_refs", "hierarchy_valid", "geometry_valid", "text_valid"]);
    const kind = exactString(item.evidence_kind, ["rendered", "structured-summary"]) as NewProjectComponentReview["evidenceKind"];
    const url = nullableUrl(item.rendered_preview_url);
    if ((kind === "rendered") !== Boolean(url)) throw new WorkflowError("invalid_response");
    if (typeof item.hierarchy_valid !== "boolean" || typeof item.geometry_valid !== "boolean" || typeof item.text_valid !== "boolean") throw new WorkflowError("invalid_response");
    return { componentId: requiredString(item.component_id), label: requiredString(item.label), evidenceKind: kind, ...(url ? { renderedPreviewUrl: url } : {}), objectCount: natural(item.object_count), textCount: natural(item.text_count), resourceRefs: natural(item.resource_refs), componentRefs: natural(item.component_refs), hierarchyValid: item.hierarchy_valid, geometryValid: item.geometry_valid, textValid: item.text_valid };
  });
  const packageData = exactRecord(data.package_review, ["package_name", "fairy_gui_version", "publish_target", "components_added", "resources_added", "component_names", "resource_names", "resource_closure_valid", "naming_conflicts", "integrity_valid"]);
  if (packageData.fairy_gui_version !== "6.1.4" || packageData.publish_target !== "unity" || typeof packageData.resource_closure_valid !== "boolean" || typeof packageData.integrity_valid !== "boolean" || !Array.isArray(packageData.naming_conflicts) || !Array.isArray(packageData.component_names) || !Array.isArray(packageData.resource_names)) throw new WorkflowError("invalid_response");
  const packageReview: NewProjectPackageReview = { packageName: requiredString(packageData.package_name), fairyguiVersion: "6.1.4", publishTarget: "unity", componentsAdded: natural(packageData.components_added), resourcesAdded: natural(packageData.resources_added), componentNames: packageData.component_names.map(requiredString), resourceNames: packageData.resource_names.map(requiredString), resourceClosureValid: packageData.resource_closure_valid, namingConflicts: packageData.naming_conflicts.map(requiredString), integrityValid: packageData.integrity_valid };
  const checks = data.checks.map((value): NewProjectCheck => {
    const item = exactRecord(value, ["id", "severity", "message", "issue_id", "issue_kind", "uir_node_id", "source_node_id", "actionable", "allowed_strategies"]);
    if (!/^review:[0-9a-f]{16}$/.test(String(item.id)) || !/^review:[0-9a-f]{16}$/.test(String(item.issue_id)) || !["ERROR", "WARNING", "INFO"].includes(String(item.severity)) || typeof item.actionable !== "boolean" || !Array.isArray(item.allowed_strategies)) throw new WorkflowError("invalid_response");
    const allowedStrategies = item.allowed_strategies.map((strategy) => exactString(strategy, ADJUSTMENT_STRATEGIES) as NewProjectAdjustmentStrategy);
    const issueKind = item.issue_kind == null ? undefined : exactString(item.issue_kind, ["raster-fallback", "definition-missing"]) as NewProjectCheck["issueKind"];
    if (new Set(allowedStrategies).size !== allowedStrategies.length || item.actionable !== (allowedStrategies.length > 0) || item.actionable && (item.uir_node_id == null || item.source_node_id == null || !issueKind)) throw new WorkflowError("invalid_response");
    return { id: item.id as string, severity: item.severity as NewProjectCheck["severity"], message: requiredString(item.message), issueId: item.issue_id as string, ...(issueKind ? { issueKind } : {}), ...(optionalString(item.uir_node_id) ? { uirNodeId: item.uir_node_id as string } : {}), ...(optionalString(item.source_node_id) ? { sourceNodeId: item.source_node_id as string } : {}), actionable: item.actionable, allowedStrategies };
  });
  const warningIds = data.warning_ids.map((item) => requiredString(item));
  if (new Set(warningIds).size !== warningIds.length || warningIds.join("\0") !== checks.filter((item) => item.severity === "WARNING").map((item) => item.id).join("\0") || data.approvable && (!packageReview.resourceClosureValid || !packageReview.integrityValid || packageReview.namingConflicts.length > 0 || imageReviews.some((item) => !item.sourcePreviewUrl || !item.cropBoundsMatch || !item.transparencyPreserved) || componentReviews.some((item) => !item.hierarchyValid || !item.geometryValid || !item.textValid) || checks.some((item) => item.severity === "ERROR"))) throw new WorkflowError("invalid_response");
  const dispositions = data.dispositions.map(parseConversionDisposition);
  if (new Set(dispositions.map((item) => item.id)).size !== dispositions.length || data.approvable && dispositions.some((item) => item.blocksApproval)) throw new WorkflowError("invalid_response");
  return { version: 1, buildId: expectedBuildId, generation, dispositions, imageReviews, componentReviews, packageReview, checks, warningIds, approvable: data.approvable };
}

function errorCode(status: number, code: unknown): WorkflowErrorCode {
  if (status === 401 || status === 403) return "unauthorized";
  if (["new_project_download_blocked", "new_project_approval_blocked"].includes(String(code))) return "review_required";
  if (["new_project_adjustment_conflict", "new_project_generation_stale", "new_project_regeneration_conflict", "new_project_review_unavailable", "new_project_state_conflict", "new_project_artifact_invalid"].includes(String(code))) return "stale_candidate";
  if (code === "template_not_found") return "unknown_template";
  if (["invalid_archive", "invalid_zip", "invalid_fgui_project", "archive_too_large"].includes(String(code))) return "invalid_zip";
  if (code === "package_request_conflict") return "conversion_conflict";
  if (String(code).startsWith("package_")) return "package_failed";
  if (["project_mismatch", "artifact_integrity"].includes(String(code)) || status === 409) return "conversion_conflict";
  if (["invalid_project_name", "invalid_template_request", "invalid_package_request"].includes(String(code)) || status === 400 || status === 422) return "validation";
  return "conversion_failed";
}

function abortError(error: unknown, signal?: AbortSignal): boolean {
  return signal?.aborted === true || error instanceof DOMException && error.name === "AbortError";
}

const defaultWait: Wait = (milliseconds, signal) => new Promise((resolve, reject) => {
  if (signal?.aborted) { reject(new DOMException("Aborted", "AbortError")); return; }
  const finish = () => { signal?.removeEventListener("abort", abort); resolve(); };
  const timer = setTimeout(finish, milliseconds);
  const abort = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
  signal?.addEventListener("abort", abort, { once: true });
});

const SCREENSHOT_FALLBACK_TIMEOUT_MS = 1000;

export class ProjectWorkflowClient {
  private readonly fetchImpl: FetchLike;
  private readonly wait: Wait;
  private readonly pollIntervalMs: number;

  constructor(private readonly config: { serverOrigin: string; pluginToken: string; fetchImpl?: FetchLike; wait?: Wait; pollIntervalMs?: number }) {
    this.fetchImpl = config.fetchImpl ?? fetch;
    this.wait = config.wait ?? defaultWait;
    this.pollIntervalMs = config.pollIntervalMs ?? 1000;
  }

  private async response(path: string, init: RequestInit): Promise<Response> {
    const request = { ...init, headers: { "X-Figma-Plugin-Token": this.config.pluginToken, ...(init.headers ?? {}) } };
    const attempts = init.method === "GET" ? 2 : 1;
    const fetchImpl = this.fetchImpl;
    let response: Response | undefined;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try { response = await fetchImpl.call(globalThis, new URL(path, this.config.serverOrigin).toString(), request); }
      catch (error) {
        if (abortError(error, init.signal ?? undefined)) throw new WorkflowError("aborted");
        if (attempt + 1 === attempts) throw new WorkflowError("network");
        continue;
      }
      if (response.ok) return response;
      if (response.status < 500 || attempt + 1 === attempts) break;
    }
    let code: unknown;
    try { code = record(await response!.json()).detail; code = record(code).code; } catch { code = undefined; }
    throw new WorkflowError(errorCode(response!.status, code));
  }

  private async json(path: string, init: RequestInit): Promise<unknown> {
    const response = await this.response(path, init);
    try { return await response.json(); } catch { throw new WorkflowError("invalid_response"); }
  }

  private async beforeDeadline<T>(deadline: number, outerSignal: AbortSignal | undefined, operation: (signal: AbortSignal) => Promise<T>): Promise<T> {
    if (outerSignal?.aborted) throw new WorkflowError("aborted");
    const remaining = deadline - Date.now();
    if (remaining <= 0) throw new WorkflowError("timeout");
    const controller = new AbortController();
    let timedOut = false;
    let rejectControl: (error: WorkflowError) => void = () => {};
    const control = new Promise<never>((_resolve, reject) => { rejectControl = reject; });
    const abort = () => { controller.abort(); rejectControl(new WorkflowError("aborted")); };
    outerSignal?.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(() => { timedOut = true; controller.abort(); rejectControl(new WorkflowError("timeout")); }, remaining);
    try { return await Promise.race([operation(controller.signal), control]); }
    catch (error) {
      if (timedOut) throw new WorkflowError("timeout");
      if (outerSignal?.aborted) throw new WorkflowError("aborted");
      throw error;
    } finally {
      clearTimeout(timer);
      outerSignal?.removeEventListener("abort", abort);
    }
  }

  private async bestEffortScreenshotFallback(jobId: string, outerSignal?: AbortSignal): Promise<void> {
    if (outerSignal?.aborted) return;
    try {
      await this.beforeDeadline(
        Date.now() + SCREENSHOT_FALLBACK_TIMEOUT_MS,
        outerSignal,
        (signal) => this.screenshotConsent(jobId, false, signal),
      );
    } catch {
      // Cleanup failure must not replace the original timeout reported to the caller.
    }
  }

  async options(signal?: AbortSignal): Promise<ProjectOption[]> {
    const data = record(await this.json("/v1/figma/project-options", { method: "GET", signal }));
    if (data.version !== 1 || !Array.isArray(data.options)) throw new WorkflowError("invalid_response");
    const options = data.options.map((value) => {
      const item = record(value);
      return { templateId: requiredString(item.template_id), fairyguiVersion: requiredString(item.fairygui_version), targetPlatform: requiredString(item.target_platform), displayName: requiredString(item.display_name) };
    });
    if (new Set(options.map((item) => item.templateId)).size !== options.length) throw new WorkflowError("invalid_response");
    return options;
  }

  async createProject(params: { templateId: string; projectName: string }, signal?: AbortSignal): Promise<ProjectView> {
    return parseProject(await this.json("/v1/projects/from-template", { method: "POST", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: 1, template_id: params.templateId, project_name: params.projectName }) }));
  }

  async uploadProject(project: File, signal?: AbortSignal): Promise<ProjectView> {
    if (!project.name.toLowerCase().endsWith(".zip") || project.type && !["application/zip", "application/x-zip-compressed"].includes(project.type)) throw new WorkflowError("invalid_zip");
    const body = new FormData();
    body.append("project", project);
    return parseProject(await this.json("/v1/projects/uploads", { method: "POST", signal, body }));
  }

  async createJob(selectionId: string, project: ProjectView, packageName: string, signal?: AbortSignal): Promise<JobView> {
    const path = `/v1/figma/selections/${encodeURIComponent(selectionId)}/projects/${encodeURIComponent(project.projectId)}/jobs`;
    const job = parseJob(await this.json(path, { method: "POST", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: 1, selection_id: selectionId, project_id: project.projectId, package_name: packageName }) }), project.projectId);
    if (job.status !== "ready_for_review") throw new WorkflowError("conversion_failed");
    return job;
  }

  async buildPackage(jobId: string, mode: "create" | "update", projectName: string, signal?: AbortSignal): Promise<PackageView> {
    return parsePackage(await this.json(`/v1/jobs/${encodeURIComponent(jobId)}/package`, { method: "POST", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: 1, mode, project_name: projectName }) }), jobId);
  }

  async screenshotConsent(jobId: string, approved: boolean, signal?: AbortSignal): Promise<PackageView> {
    return parsePackage(await this.json(`/v1/jobs/${encodeURIComponent(jobId)}/semantic-screenshot-consent`, {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: 1, approved }),
    }), jobId);
  }

  async startNewProject(selectionId: string, projectName: string, signal?: AbortSignal): Promise<NewProjectCandidate> {
    const data = await this.json(`/v1/figma/selections/${encodeURIComponent(selectionId)}/new-fgui-projects`, {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: 1, project_name: projectName }),
    });
    return parseNewProjectCandidate(data);
  }

  async getNewProject(buildId: string, generation: number, signal?: AbortSignal): Promise<NewProjectCandidate> {
    return parseNewProjectCandidate(await this.json(`/v1/new-fgui-projects/${encodeURIComponent(buildId)}`, { method: "GET", signal }), buildId, generation);
  }

  async waitForNewProject(candidate: NewProjectCandidate, options: { signal?: AbortSignal; timeoutMs?: number; onStage?: (candidate: NewProjectCandidate) => void } = {}): Promise<NewProjectCandidate> {
    const deadline = Date.now() + (options.timeoutMs ?? 5 * 60_000);
    let current = candidate;
    while (!["awaiting_review", "approved", "rejected", "failed"].includes(current.status)) {
      current = await this.beforeDeadline(deadline, options.signal, (signal) => this.getNewProject(current.buildId, current.generation, signal));
      options.onStage?.(current);
      if (["awaiting_review", "approved", "rejected", "failed"].includes(current.status)) break;
      await this.beforeDeadline(deadline, options.signal, (signal) => this.wait(this.pollIntervalMs, signal));
    }
    return current;
  }

  async createNewProjectCandidate(manifest: SelectionManifest, resources: readonly ExportedResource[], projectName: string, options: { signal?: AbortSignal; timeoutMs?: number; onStage?: (candidate: NewProjectCandidate) => void } = {}): Promise<NewProjectRunResult> {
    const idempotencyKey = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
    const deadline = Date.now() + (options.timeoutMs ?? 5 * 60_000);
    let selection: SelectionView;
    try {
      selection = await this.beforeDeadline(deadline, options.signal, async (signal) => parseSelectionView(await new SelectionUploader({ serverOrigin: this.config.serverOrigin, pluginToken: this.config.pluginToken, fetchImpl: this.fetchImpl }).send(manifest, resources, idempotencyKey, undefined, signal)));
    } catch (error) {
      if (abortError(error, options.signal)) throw new WorkflowError("aborted");
      if (error instanceof SelectionUploadError) throw new WorkflowError(error.code === "network" ? "network" : error.code === "unauthorized" ? "unauthorized" : error.code === "invalid_response" ? "invalid_response" : "validation");
      throw error;
    }
    const started = await this.beforeDeadline(deadline, options.signal, (signal) => this.startNewProject(selection.selection_id, projectName, signal));
    options.onStage?.(started);
    const candidate = await this.waitForNewProject(started, { ...options, timeoutMs: Math.max(0, deadline - Date.now()) });
    return { selection, candidate };
  }

  async reviewNewProject(candidate: NewProjectCandidate, signal?: AbortSignal): Promise<NewProjectReview> {
    if (candidate.status !== "awaiting_review" && candidate.status !== "adjusting") throw new WorkflowError("review_required");
    return parseNewProjectReview(await this.json(`/v1/new-fgui-projects/${encodeURIComponent(candidate.buildId)}/review`, { method: "GET", signal }), candidate.buildId, candidate.generation);
  }

  async adjustNewProject(candidate: NewProjectCandidate, review: NewProjectReview, checkId: string, strategy: NewProjectAdjustmentStrategy, signal?: AbortSignal): Promise<NewProjectCandidate> {
    if (candidate.buildId !== review.buildId || candidate.generation !== review.generation) throw new WorkflowError("stale_candidate");
    const check = review.checks.find((item) => item.id === checkId);
    if (!check?.uirNodeId || !check.allowedStrategies.includes(strategy)) throw new WorkflowError("validation");
    const payload = { version: 1, candidate_id: candidate.buildId, generation: candidate.generation, issue_id: check.issueId, uir_node_id: check.uirNodeId, strategy };
    return parseNewProjectCandidate(await this.json(`/v1/new-fgui-projects/${encodeURIComponent(candidate.buildId)}/adjustments`, { method: "POST", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }), candidate.buildId, candidate.generation);
  }

  async regenerateNewProject(candidate: NewProjectCandidate, options: { signal?: AbortSignal; onStage?: (candidate: NewProjectCandidate) => void } = {}): Promise<NewProjectCandidate> {
    if (candidate.status !== "adjusting") throw new WorkflowError("review_required");
    const started = parseNewProjectCandidate(await this.json(`/v1/new-fgui-projects/${encodeURIComponent(candidate.buildId)}/regenerate`, { method: "POST", signal: options.signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: 1, generation: candidate.generation }) }), undefined, candidate.generation + 1);
    options.onStage?.(started);
    return this.waitForNewProject(started, options);
  }

  async approveNewProject(candidate: NewProjectCandidate, review: NewProjectReview, warningIds: readonly string[], signal?: AbortSignal): Promise<NewProjectCandidate> {
    if (candidate.buildId !== review.buildId || candidate.generation !== review.generation || !review.approvable || warningIds.join("\0") !== review.warningIds.join("\0")) throw new WorkflowError("review_required");
    return parseNewProjectCandidate(await this.json(`/v1/new-fgui-projects/${encodeURIComponent(candidate.buildId)}/approve`, { method: "POST", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: 1, generation: candidate.generation, warning_ids: warningIds }) }), candidate.buildId, candidate.generation);
  }

  async rejectNewProject(candidate: NewProjectCandidate, signal?: AbortSignal): Promise<NewProjectCandidate> {
    return parseNewProjectCandidate(await this.json(`/v1/new-fgui-projects/${encodeURIComponent(candidate.buildId)}/reject`, { method: "POST", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: 1, generation: candidate.generation }) }), candidate.buildId, candidate.generation);
  }

  async newProjectPreview(buildId: string, path: string, signal?: AbortSignal): Promise<Blob> {
    const prefix = `/v1/new-fgui-projects/${buildId}/previews/`;
    const ownedSelectionPreview = /^\/v1\/figma\/selections\/[0-9a-f]{32}\/previews\/[0-9]+$/.test(path);
    const ownedSelectionResource = /^\/v1\/figma\/selections\/[0-9a-f]{32}\/resources\/[A-Za-z0-9_-]{1,128}$/.test(path);
    if (!/^[0-9a-f]{32}$/.test(buildId) || (!path.startsWith(prefix) && !ownedSelectionPreview && !ownedSelectionResource) || path.includes("..") || path.includes("//")) throw new WorkflowError("invalid_response");
    const response = await this.response(path, { method: "GET", signal });
    const mediaType = response.headers.get("Content-Type")?.split(";", 1)[0].trim().toLowerCase();
    if (!mediaType || !["image/png", "image/jpeg", "image/webp"].includes(mediaType)) throw new WorkflowError("invalid_response");
    const blob = await response.blob();
    if (!blob.size) throw new WorkflowError("invalid_response");
    return blob;
  }

  async downloadNewProject(candidate: NewProjectCandidate, signal?: AbortSignal): Promise<DownloadedPackage> {
    if (candidate.status !== "approved" || !candidate.downloadName || candidate.byteSize == null || !candidate.sha256) throw new WorkflowError("review_required");
    const response = await this.response(`/v1/new-fgui-projects/${encodeURIComponent(candidate.buildId)}/download`, { method: "GET", signal });
    if (response.headers.get("Content-Type")?.split(";", 1)[0].trim().toLowerCase() !== "application/zip") throw new WorkflowError("invalid_response");
    const downloadName = safeDownloadName(response.headers.get("Content-Disposition"));
    if (downloadName !== candidate.downloadName) throw new WorkflowError("invalid_response");
    const blob = await response.blob();
    if (blob.size !== candidate.byteSize || await sha256Hex(new Uint8Array(await blob.arrayBuffer())) !== candidate.sha256) throw new WorkflowError("invalid_response");
    return { blob, downloadName };
  }

  async requestSemanticScreenshot(jobId: string, screenshot: SemanticScreenshot, signal?: AbortSignal): Promise<PackageView> {
    if (screenshot.mimeType !== "image/png" || !screenshot.bytes.length || screenshot.bytes.length > MAX_SEMANTIC_SCREENSHOT_BYTES) throw new WorkflowError("validation");
    return parsePackage(await this.json(`/v1/jobs/${encodeURIComponent(jobId)}/semantic-screenshot`, {
      method: "POST",
      signal,
      headers: { "Content-Type": "image/png" },
      body: screenshot.bytes as BodyInit,
    }), jobId);
  }

  async waitForPackage(jobId: string, options: WaitForPackageOptions = {}): Promise<PackageView> {
    const deadline = Date.now() + (options.timeoutMs ?? 5 * 60_000);
    let screenshotDecisionHandled = false;
    let screenshotFallbackPending = false;
    while (true) {
      const current = await this.beforeDeadline(deadline, options.signal, async (signal) => parsePackage(await this.json(`/v1/jobs/${encodeURIComponent(jobId)}/package`, { method: "GET", signal }), jobId));
      options.onStage?.({ stage: current.stage, progress: current.progress });
      if (current.status === "ready") return current;
      if (current.status === "failed") throw new WorkflowError("package_failed");
      if (current.status !== "awaiting_screenshot_consent") screenshotFallbackPending = false;
      if (current.status === "awaiting_screenshot_consent" && screenshotFallbackPending) {
        try {
          await this.beforeDeadline(deadline, options.signal, (signal) => this.screenshotConsent(jobId, false, signal));
          screenshotFallbackPending = false;
        } catch (error) {
          if (options.signal?.aborted || error instanceof WorkflowError && error.code === "aborted") throw new WorkflowError("aborted");
          if (error instanceof WorkflowError && error.code === "timeout") {
            await this.bestEffortScreenshotFallback(jobId, options.signal);
            throw error;
          }
        }
        if (!screenshotFallbackPending) continue;
      }
      if (current.status === "awaiting_screenshot_consent" && !screenshotDecisionHandled) {
        if (!options.onScreenshotConsent || !options.requestScreenshot) throw new WorkflowError("invalid_response");
        const approved = await this.beforeDeadline(deadline, options.signal, (signal) => options.onScreenshotConsent!({ jobId, reason: current.screenshotReason!, signal }));
        await this.beforeDeadline(deadline, options.signal, (signal) => this.screenshotConsent(jobId, approved, signal));
        screenshotDecisionHandled = true;
        if (approved) {
          try {
            const screenshot = await this.beforeDeadline(deadline, options.signal, (signal) => options.requestScreenshot!(jobId, signal));
            await this.beforeDeadline(deadline, options.signal, (signal) => this.requestSemanticScreenshot(jobId, screenshot, signal));
          } catch (error) {
            if (options.signal?.aborted || error instanceof WorkflowError && error.code === "aborted") throw new WorkflowError("aborted");
            if (error instanceof WorkflowError && error.code === "timeout") {
              await this.bestEffortScreenshotFallback(jobId, options.signal);
              throw error;
            }
            screenshotFallbackPending = true;
            try {
              await this.beforeDeadline(deadline, options.signal, (signal) => this.screenshotConsent(jobId, false, signal));
              screenshotFallbackPending = false;
            } catch (fallbackError) {
              if (options.signal?.aborted || fallbackError instanceof WorkflowError && fallbackError.code === "aborted") throw new WorkflowError("aborted");
              if (fallbackError instanceof WorkflowError && fallbackError.code === "timeout") {
                await this.bestEffortScreenshotFallback(jobId, options.signal);
                throw fallbackError;
              }
            }
          }
        }
        continue;
      }
      try { await this.beforeDeadline(deadline, options.signal, (signal) => this.wait(this.pollIntervalMs, signal)); }
      catch (error) {
        if (error instanceof WorkflowError) throw error;
        throw new WorkflowError(abortError(error, options.signal) ? "aborted" : "network");
      }
    }
  }

  async downloadPackage(jobId: string, signal?: AbortSignal): Promise<DownloadedPackage> {
    const response = await this.response(`/v1/jobs/${encodeURIComponent(jobId)}/package/download`, { method: "GET", signal });
    if (response.headers.get("Content-Type")?.split(";", 1)[0].trim().toLowerCase() !== "application/zip") throw new WorkflowError("invalid_response");
    let blob: Blob;
    try { blob = await response.blob(); } catch (error) { throw new WorkflowError(abortError(error, signal) ? "aborted" : "network"); }
    return { blob, downloadName: safeDownloadName(response.headers.get("Content-Disposition")) };
  }

  async runCreate(manifest: SelectionManifest, resources: readonly ExportedResource[], params: { templateId: string; projectName: string }, onStage: WorkflowStageCallback = () => {}, options: WorkflowRunOptions = {}): Promise<WorkflowResult> {
    onStage({ stage: "uploading", progress: 10 });
    return this.run("create", manifest, resources, await this.createProject(params, options.signal), params.projectName, onStage, options);
  }

  async runUpdate(manifest: SelectionManifest, resources: readonly ExportedResource[], archive: File, onStage: WorkflowStageCallback = () => {}, options: WorkflowRunOptions = {}): Promise<WorkflowResult> {
    onStage({ stage: "uploading", progress: 10 });
    const project = await this.uploadProject(archive, options.signal);
    return this.run("update", manifest, resources, project, safeProjectName(archive.name.replace(/\.zip$/i, ""), targetPackage(project)), onStage, options);
  }

  private async run(mode: "create" | "update", manifest: SelectionManifest, resources: readonly ExportedResource[], project: ProjectView, projectName: string, onStage: WorkflowStageCallback, options: WorkflowRunOptions): Promise<WorkflowResult> {
    const signal = options.signal;
    const idempotencyKey = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
    let selection: SelectionView;
    try { selection = parseSelectionView(await new SelectionUploader({ serverOrigin: this.config.serverOrigin, pluginToken: this.config.pluginToken, fetchImpl: this.fetchImpl }).send(manifest, resources, idempotencyKey, undefined, signal)); }
    catch (error) {
      if (abortError(error, signal)) throw new WorkflowError("aborted");
      if (error instanceof SelectionUploadError) throw new WorkflowError(error.code === "network" ? "network" : error.code === "unauthorized" ? "unauthorized" : error.code === "invalid_response" ? "invalid_response" : "validation");
      throw error;
    }
    onStage({ stage: "parsing", progress: 35 });
    const packageName = targetPackage(project);
    if (!packageName) throw new WorkflowError("invalid_response");
    onStage({ stage: "converting", progress: 50 });
    const job = await this.createJob(selection.selection_id, project, packageName, signal);
    onStage({ stage: "checking", progress: 70 });
    const started = await this.buildPackage(job.jobId, mode, projectName, signal);
    onStage({ stage: started.stage, progress: started.progress });
    if (started.status === "failed") throw new WorkflowError("package_failed");
    const finished = started.status === "ready" ? started : await this.waitForPackage(job.jobId, { ...options, signal, onStage });
    const download = await this.downloadPackage(job.jobId, signal);
    onStage({ stage: "ready", progress: 100 });
    return { ...download, project, selection, job, package: finished };
  }
}

function safeProjectName(preferred: string, fallback?: string): string {
  for (const value of [preferred, fallback ?? ""]) {
    const safe = value.replace(/[^\w\-\u4e00-\u9fff]+/gu, "-").replace(/^-+|-+$/g, "").slice(0, 64);
    if (safe) return safe;
  }
  return "FairyGUI";
}

function validWindowsZipName(value: string): boolean {
  if (!value || value.length > 180 || value.normalize("NFC") !== value || !value.toLowerCase().endsWith(".zip") || value.includes("/") || value.includes("\\") || value.includes("..") || /[\u0000-\u001f\u007f-\u009f<>:"|?*\u200e\u200f\u202a-\u202e\u2066-\u2069]/u.test(value)) return false;
  const stem = value.slice(0, -4);
  if (!stem || /[ .]$/.test(stem)) return false;
  return !/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/i.test(stem.split(".", 1)[0]!);
}

function safeDownloadName(contentDisposition: string | null): string {
  let candidate: string | undefined;
  const encoded = contentDisposition?.match(/filename\*\s*=\s*[^']*''([^;]+)/i)?.[1];
  try { if (encoded) candidate = decodeURIComponent(encoded.trim().replace(/^"|"$/g, "")); } catch { candidate = undefined; }
  candidate ??= contentDisposition?.match(/filename\s*=\s*(?:"([^"]+)"|([^;]+))/i)?.slice(1).find(Boolean)?.trim();
  if (!candidate || !validWindowsZipName(candidate)) return "FairyGUI-project.zip";
  return candidate;
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new WorkflowError("invalid_response");
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  const digest = new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", copy.buffer));
  return Array.from(digest, (value) => value.toString(16).padStart(2, "0")).join("");
}
