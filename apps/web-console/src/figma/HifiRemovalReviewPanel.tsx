import { useMemo, useState } from "react";

import type {
  HifiRemovalDecision,
  HifiRemovalReview,
} from "../../../figma-plugin/src/project-client";
import { PsdCropFigure } from "./HifiMappingPanel";

const TIER_LABELS: Record<number, string> = {
  1: "影响运行时逻辑",
  2: "影响 Controller / Gear",
  3: "影响独立组件",
  4: "影响当前可见视觉",
  5: "普通旧视觉",
};

export type HifiRemovalReviewPanelProps = {
  review: HifiRemovalReview;
  busy: boolean;
  onDecide: (decisions: HifiRemovalDecision[]) => void;
  psdCanvas?: [number, number];
  itemBounds?: Record<string, [number, number, number, number]>;
  loadPsdCrop?: (
    bounds: [number, number, number, number],
  ) => Promise<string | undefined>;
};

export function HifiRemovalReviewPanel({
  review,
  busy,
  onDecide,
  psdCanvas,
  itemBounds,
  loadPsdCrop,
}: HifiRemovalReviewPanelProps) {
  const initial = useMemo(() => {
    const map: Record<string, "remove" | "preserve"> = {};
    for (const group of review.groups) map[group.groupId] = group.recommendation;
    return map;
  }, [review]);
  const [choices, setChoices] = useState<Record<string, "remove" | "preserve">>(
    initial,
  );
  const choiceFor = (
    groupId: string,
    fallback: "remove" | "preserve",
  ): "remove" | "preserve" => choices[groupId] ?? fallback;

  const submit = () => {
    const decisions: HifiRemovalDecision[] = review.groups.map((group) => ({
      groupId: group.groupId,
      decision: choiceFor(group.groupId, group.recommendation),
    }));
    onDecide(decisions);
  };

  return (
    <section
      className="local-hifi-card hifi-removal-review"
      aria-label="旧视觉删除评审"
    >
      <div className="local-hifi-card-title">
        <div>
          <span>删除评审</span>
          <h2>旧视觉删除确认</h2>
        </div>
        <strong>{review.totalCandidateCount} 个候选</strong>
      </div>
      <p className="hifi-removal-intro">
        这些旧对象在新设计（PSD）里没有对应内容：选“移除”会连引用一起删掉，选“保留”则只停用旧外观、程序逻辑不变。系统推荐已预选。
      </p>
      <ol className="hifi-removal-groups">
        {review.groups.map((group) => {
          const decision = choiceFor(group.groupId, group.recommendation);
          let groupBounds: [number, number, number, number] | undefined;
          for (const object of group.objects) {
            const bounds = itemBounds?.[object.itemId];
            if (!bounds) continue;
            const left = bounds[0];
            const top = bounds[1];
            const right = bounds[0] + bounds[2];
            const bottom = bounds[1] + bounds[3];
            groupBounds = groupBounds
              ? [
                  Math.min(groupBounds[0], left),
                  Math.min(groupBounds[1], top),
                  Math.max(groupBounds[2], right) -
                    Math.min(groupBounds[0], left),
                  Math.max(groupBounds[3], bottom) -
                    Math.min(groupBounds[1], top),
                ]
              : [left, top, right - left, bottom - top];
          }
          return (
            <li key={group.groupId} className="hifi-removal-group">
              <div className="hifi-removal-group-head">
                <strong>
                  {group.mergedTemplate
                    ? group.region
                    : group.region
                      ? `区域 ${group.region}`
                      : "顶层对象"}
                </strong>
                <small className="hifi-removal-root">
                  {group.semanticRoot.split("/").pop()}
                </small>
                <span className="hifi-removal-tier">
                  风险 {group.riskTier} · {TIER_LABELS[group.riskTier] ?? ""}
                </span>
                <span className="hifi-removal-rec">
                  系统推荐：
                  {group.recommendation === "remove" ? "移除" : "保留"}
                </span>
              </div>
              {groupBounds && (
                <PsdCropFigure
                  bounds={groupBounds}
                  canvas={psdCanvas}
                  loadPsdCrop={loadPsdCrop}
                  caption="PSD · 同位置画面（应无对应内容）"
                />
              )}
              <ul className="hifi-removal-objects">
                {group.objects.map((object) => (
                  <li key={object.itemId} className="hifi-removal-object">
                    <div className="hifi-removal-object-head">
                      <code>{object.objectId}</code>
                      <span>{object.name}</span>
                      <small>{object.objectType}</small>
                      {object.location && (
                        <small className="hifi-removal-location">
                          位置 {object.location}
                        </small>
                      )}
                      {object.size && (
                        <small className="hifi-removal-size">
                          {Math.round(object.size[0])}×{Math.round(object.size[1])}
                        </small>
                      )}
                      {object.runtimeBound && (
                        <span className="hifi-removal-flag">运行时绑定</span>
                      )}
                    </div>
                    <div className="hifi-removal-preview">
                      {object.previewUrl ? (
                        <img
                          src={object.previewUrl}
                          alt={`旧视觉预览 ${object.name}`}
                        />
                      ) : object.text ? (
                        <span className="hifi-removal-preview-text">{object.text}</span>
                      ) : (
                        <span className="hifi-removal-preview-none">{`无静态贴图（${object.objectType}）`}</span>
                      )}
                      {(object.previewUrl || object.text) && <small>旧皮肤现状</small>}
                    </div>
                    <p className="hifi-removal-reason">{object.reason}</p>
                    {(object.controllerRefs.length > 0 ||
                      object.transitionRefs.length > 0 ||
                      object.relationRefs.length > 0 ||
                      object.referencedBy.length > 0) && (
                      <p className="hifi-removal-refs">
                        {object.controllerRefs.length > 0 && (
                          <span>控制器：{object.controllerRefs.join(", ")}</span>
                        )}
                        {object.transitionRefs.length > 0 && (
                          <span>动画：{object.transitionRefs.join(", ")}</span>
                        )}
                        {object.relationRefs.length > 0 && (
                          <span>关系→：{object.relationRefs.join(", ")}</span>
                        )}
                        {object.referencedBy.length > 0 && (
                          <span>被引用：{object.referencedBy.join(", ")}</span>
                        )}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
              <div className="hifi-removal-choice">
                <span className="hifi-removal-choice-label">本组处理</span>
                <button
                  type="button"
                  aria-pressed={decision === "remove"}
                  className={
                    decision === "remove"
                      ? "secondary-button compact is-active"
                      : "secondary-button compact"
                  }
                  disabled={busy}
                  onClick={() =>
                    setChoices((current) => ({
                      ...current,
                      [group.groupId]: "remove",
                    }))
                  }
                >
                  移除
                </button>
                <button
                  type="button"
                  aria-pressed={decision === "preserve"}
                  className={
                    decision === "preserve"
                      ? "secondary-button compact is-active"
                      : "secondary-button compact"
                  }
                  disabled={busy}
                  onClick={() =>
                    setChoices((current) => ({
                      ...current,
                      [group.groupId]: "preserve",
                    }))
                  }
                >
                  保留
                </button>
              </div>
            </li>
          );
        })}
      </ol>
      {review.autoResolvedGroups.length > 0 && (
        <p className="local-hifi-note">
          另有 {review.autoResolvedGroups.length} 组低风险纯视觉对象已按推荐方案自动处理并记录（超出每工程 5 组上限）。
        </p>
      )}
      <div className="local-hifi-action-buttons">
        <button
          type="button"
          className="primary-button"
          disabled={busy || review.groups.length === 0}
          onClick={submit}
        >
          确认并继续（{review.groups.length} 组）
        </button>
      </div>
    </section>
  );
}
