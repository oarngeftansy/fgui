import { useState } from "react";
import type {
  HifiBatch,
  HifiExportMode,
  HifiReplacement,
} from "../../../figma-plugin/src/project-client";

const GROUP_STATUS_LABELS: Record<HifiReplacement["status"], string> = {
  mapping: "映射中",
  building: "生成中",
  review_ready: "待审核",
  approved: "已批准",
  rejected: "已退回",
  failed: "失败",
  superseded: "已过期",
};

export function HifiBatchGroupsPanel({
  batch,
  busy,
  exportMode,
  fidelity,
  onExportMode,
  onLoadFidelity,
  onEnterGroup,
  onBuildPackage,
  onDownload,
  onWriteback,
  onBack,
}: {
  batch: HifiBatch;
  busy: boolean;
  exportMode: HifiExportMode;
  fidelity: Record<string, { total: number; passed: number } | undefined>;
  onExportMode(mode: HifiExportMode): void;
  onLoadFidelity(sessionId: string): void;
  onEnterGroup(sessionId: string): void;
  onBuildPackage(): void;
  onDownload(): void;
  onWriteback(localPath: string): void;
  onBack(): void;
}) {
  const [localPath, setLocalPath] = useState("");
  const approved = batch.groups.filter(
    (group) => group.status === "approved",
  ).length;
  const delivered = batch.status === "delivered";
  const packaging = busy && !batch.artifactReady && !delivered;
  return (
    <section className="local-hifi-card hifi-batch-groups">
      <div className="local-hifi-card-title">
        <div>
          <span>06</span>
          <h2>批次分组</h2>
        </div>
        <strong>
          已批准 {approved}/{batch.groups.length}
        </strong>
      </div>
      {batch.warnings.length > 0 && (
        <div className="hifi-batch-warnings" role="alert">
          <strong>建批警示</strong>
          <ul>
            {batch.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}
      <ul className="hifi-batch-group-list">
        {batch.groups.map((group) => (
          <li key={group.sessionId} className="hifi-batch-group">
            <div className="hifi-batch-group-name">
              <strong>
                {group.psdName} → {group.targetName}
              </strong>
              <small>
                {group.unresolvedCount} 项待确认
                {group.approvalReady ? " · ✓ 可批准" : ""}
              </small>
            </div>
            <span className={`hifi-batch-status is-${group.status}`}>
              {GROUP_STATUS_LABELS[group.status]}
            </span>
            <button
              type="button"
              className="secondary-button"
              disabled={busy}
              onClick={() => onEnterGroup(group.sessionId)}
            >
              {group.status === "approved" ? "查看交付" : "进入审核"}
            </button>
          </li>
        ))}
      </ul>
      {batch.exportReady && (
        <div className="hifi-batch-export">
          <h3>导出与写回</h3>
          <ul className="hifi-batch-export-preview">
            {batch.groups.map((group) => (
              <li key={group.sessionId}>
                <strong>
                  {group.psdName} → {group.targetName}
                </strong>
                {fidelity[group.sessionId] ? (
                  <small>
                    保真 通过 {fidelity[group.sessionId]?.passed}/
                    {fidelity[group.sessionId]?.total}
                  </small>
                ) : (
                  <button
                    type="button"
                    className="secondary-button compact"
                    disabled={busy}
                    onClick={() => onLoadFidelity(group.sessionId)}
                  >
                    查看保真
                  </button>
                )}
              </li>
            ))}
          </ul>
          <div className="hifi-batch-export-mode">
            <label>
              <input
                type="radio"
                name="hifi-batch-export-mode"
                checked={exportMode === "package"}
                disabled={busy || delivered}
                onChange={() => onExportMode("package")}
              />
              导出新版合并 ZIP，旧工程保持不变
            </label>
            <label>
              <input
                type="radio"
                name="hifi-batch-export-mode"
                checked={exportMode === "overwrite"}
                disabled={busy || delivered}
                onChange={() => onExportMode("overwrite")}
              />
              覆盖本机旧工程，历史版本仍可回退
            </label>
          </div>
          <div className="local-hifi-action-buttons">
            <button
              type="button"
              disabled={busy || delivered}
              onClick={onBuildPackage}
            >
              {packaging ? "正在构建合并包…" : "构建合并包"}
            </button>
            {exportMode === "package" ? (
              <button
                type="button"
                className="secondary-button"
                disabled={busy || !batch.artifactReady}
                onClick={onDownload}
              >
                下载合并包
              </button>
            ) : (
              <button
                type="button"
                disabled={
                  busy ||
                  delivered ||
                  !batch.artifactReady ||
                  !localPath.trim()
                }
                onClick={() => onWriteback(localPath)}
              >
                写回原工程
              </button>
            )}
          </div>
          {exportMode === "overwrite" && (
            <div className="hifi-batch-writeback">
              <label className="local-hifi-file">
                本机工程路径
                <input
                  type="text"
                  value={localPath}
                  placeholder="本机旧工程文件夹路径，如 D:/项目/Assets/Tower"
                  disabled={busy || delivered}
                  onChange={(event) => setLocalPath(event.currentTarget.value)}
                />
              </label>
            </div>
          )}
          {batch.artifactName && (
            <p className="hifi-batch-artifact">
              合并包：{batch.artifactName}
            </p>
          )}
          {delivered && (
            <p className="writer-inline-note">
              批次已交付写回，构建与写回已禁用。
            </p>
          )}
          {batch.writeback && (
            <p className="hifi-batch-writeback-result" role="status">
              已写回 · 备份 {batch.writeback.backupDir} · 变更{" "}
              {batch.writeback.changedPaths.length} 个文件
            </p>
          )}
        </div>
      )}
      <div className="local-hifi-action-buttons hifi-batch-groups-actions">
        <button
          type="button"
          className="secondary-button"
          disabled={busy}
          onClick={onBack}
        >
          返回材料页
        </button>
      </div>
    </section>
  );
}
