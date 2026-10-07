import { useState } from "react";
import type {
  HifiBatch,
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
  onEnterGroup,
  onBuildPackage,
  onDownload,
  onWriteback,
  onBack,
}: {
  batch: HifiBatch;
  busy: boolean;
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
          <div className="local-hifi-action-buttons">
            <button
              type="button"
              disabled={busy || delivered}
              onClick={onBuildPackage}
            >
              {packaging ? "正在构建合并包…" : "构建合并包"}
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={busy || !batch.artifactReady}
              onClick={onDownload}
            >
              下载合并包
            </button>
          </div>
          {batch.artifactName && (
            <p className="hifi-batch-artifact">
              合并包：{batch.artifactName}
            </p>
          )}
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
