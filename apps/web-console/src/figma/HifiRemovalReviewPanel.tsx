import { useMemo, useState } from "react";

import type {
  HifiRemovalDecision,
  HifiRemovalReview,
} from "../../../figma-plugin/src/project-client";

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
};

export function HifiRemovalReviewPanel({
  review,
  busy,
  onDecide,
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
        下列旧对象在 PSD 目标态中没有对应内容（Policy 28 §8）。
        “移除”会同步闭合其 Gear / Relation / Transition 引用；
        “保留”会保留运行时身份与程序逻辑，仅停止它在目标态的旧视觉贡献（§11）。
        涉及运行时逻辑 / 控制器 / 动画的对象已默认推荐保留。
      </p>
      <ol className="hifi-removal-groups">
        {review.groups.map((group) => {
          const decision = choiceFor(group.groupId, group.recommendation);
          return (
            <li key={group.groupId} className="hifi-removal-group">
              <div className="hifi-removal-group-head">
                <strong>
                  {group.region ? `区域 ${group.region}` : "顶层对象"}
                </strong>
                <span className="hifi-removal-tier">
                  风险 {group.riskTier} · {TIER_LABELS[group.riskTier] ?? ""}
                </span>
                <span className="hifi-removal-rec">
                  系统推荐：
                  {group.recommendation === "remove" ? "移除" : "保留"}
                </span>
              </div>
              <ul className="hifi-removal-objects">
                {group.objects.map((object) => (
                  <li key={object.itemId} className="hifi-removal-object">
                    <div className="hifi-removal-object-head">
                      <code>{object.objectId}</code>
                      <span>{object.name}</span>
                      <small>{object.objectType}</small>
                      {object.runtimeBound && (
                        <span className="hifi-removal-flag">运行时绑定</span>
                      )}
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
                <button
                  type="button"
                  className={
                    decision === "remove" ? "primary-button" : "secondary-button"
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
                  className={
                    decision === "preserve"
                      ? "primary-button"
                      : "secondary-button"
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
          应用删除评审并继续
        </button>
      </div>
    </section>
  );
}
