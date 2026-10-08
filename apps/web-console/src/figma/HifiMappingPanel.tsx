import { useEffect, useMemo, useState } from "react";
import type {
  HifiMappingAction,
  HifiMappingDraft,
  HifiMappingItem,
  PsdLayer,
} from "../../../figma-plugin/src/project-client";

const STATUS_LABELS: Record<HifiMappingItem["status"], string> = {
  matched: "已对应",
  suggested: "建议对应",
  uncertain: "待判断",
  fgui_only: "仅旧工程",
  hifi_added: "PSD 未对应",
  blocked: "PSD 容器待对应",
  structural: "非绘制结构已保留",
  out_of_scope: "范围外（跨包共享组件）",
  occluded: "已遮挡（上层不透明全幅图层）",
};

export function PsdCropFigure({
  bounds,
  canvas,
  loadPsdCrop,
  caption,
}: {
  bounds?: [number, number, number, number];
  canvas?: [number, number];
  loadPsdCrop?: (
    bounds: [number, number, number, number],
  ) => Promise<string | undefined>;
  caption: string;
}) {
  const [url, setUrl] = useState<string>();
  const key = bounds ? bounds.map((value) => value.toFixed(4)).join(",") : "";
  useEffect(() => {
    let alive = true;
    setUrl(undefined);
    if (!bounds || !canvas || !loadPsdCrop) return;
    const [canvasWidth, canvasHeight] = canvas;
    const left = bounds[0] * canvasWidth;
    const top = bounds[1] * canvasHeight;
    const width = bounds[2] * canvasWidth;
    const height = bounds[3] * canvasHeight;
    const pad = Math.max(10, Math.round(0.18 * Math.max(width, height)));
    const crop: [number, number, number, number] = [
      Math.max(0, Math.round(left - pad)),
      Math.max(0, Math.round(top - pad)),
      Math.min(canvasWidth, Math.round(left + width + pad)),
      Math.min(canvasHeight, Math.round(top + height + pad)),
    ];
    if (crop[2] - crop[0] < 2 || crop[3] - crop[1] < 2) return;
    void loadPsdCrop(crop)
      .then((next) => {
        if (alive) setUrl(next);
      })
      .catch(() => {
        if (alive) setUrl(undefined);
      });
    return () => {
      alive = false;
    };
  }, [key, canvas, loadPsdCrop]);
  return (
    <figure className="hifi-evidence-figure">
      {url ? (
        <img src={url} alt={caption} className="hifi-evidence-crop" />
      ) : (
        <div className="hifi-evidence-empty">无 PSD 同位置画面</div>
      )}
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

export function HifiMappingPanel({
  mapping,
  currentItemId,
  busy,
  onCurrentChange,
  onDecision,
  onLocate,
  psdCanvas,
  loadPsdCrop,
  oldPreviewUrl,
  psdLayers,
  cutouts,
  cutoutThumbnails,
  cutoutInfo,
  allowVisualAddition = true,
  allowKeepOld = true,
}: {
  mapping: HifiMappingDraft;
  currentItemId?: string;
  busy: boolean;
  onCurrentChange(itemId: string): void;
  onDecision(
    item: HifiMappingItem,
    action: HifiMappingAction,
    figmaNodeId?: string,
    visualDisposition?: "retire",
  ): void;
  onLocate?(nodeId: string): void;
  psdCanvas?: [number, number];
  loadPsdCrop?: (
    bounds: [number, number, number, number],
  ) => Promise<string | undefined>;
  oldPreviewUrl?: string;
  psdLayers?: PsdLayer[];
  cutouts?: string[];
  cutoutThumbnails?: Record<string, string>;
  cutoutInfo?: Record<string, { family: string; relevance: string }>;
  allowVisualAddition?: boolean;
  allowKeepOld?: boolean;
}) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [oldChoices, setOldChoices] = useState<Record<string, string>>({});
  const [cutoutChoices, setCutoutChoices] = useState<Record<string, string>>(
    {},
  );
  const [picked, setPicked] = useState<string>();
  const cutoutEntries = (cutouts ?? []).map((name) => {
    const info = cutoutInfo?.[name];
    return {
      name,
      family: info?.family ?? "",
      relevance: info?.relevance ?? "other",
    };
  });
  const thisPsdCutouts = cutoutEntries.filter(
    (entry) => entry.relevance === "this_psd",
  );
  const sharedCutouts = cutoutEntries.filter(
    (entry) => entry.relevance === "shared",
  );
  const otherCutoutFamilies = new Map<string, string[]>();
  for (const entry of cutoutEntries) {
    if (entry.relevance !== "other") continue;
    const label = entry.family || "未分组";
    const bucket = otherCutoutFamilies.get(label) ?? [];
    bucket.push(entry.name);
    otherCutoutFamilies.set(label, bucket);
  }
  const cutoutPoolMixed =
    thisPsdCutouts.length > 0
    && cutoutEntries.length > thisPsdCutouts.length + sharedCutouts.length;
  const pendingItems = mapping.items.filter(
    (item) =>
      (!item.action && item.legacyState !== "REMOVE_CANDIDATE") ||
      item.legacyState === "USER_DECISION_CONFLICT",
  );
  const currentIndex = Math.max(
    0,
    pendingItems.findIndex((item) => item.itemId === currentItemId),
  );
  const current = pendingItems[currentIndex];
  useEffect(() => {
    if (current && current.itemId !== currentItemId)
      onCurrentChange(current.itemId);
  }, [current?.itemId, currentItemId, onCurrentChange]);
  const figmaNames = useMemo(
    () =>
      new Map(
        mapping.items
          .filter((item) => item.figmaNodeId)
          .map((item) => [
            item.figmaNodeId!,
            item.figmaName ?? item.figmaNodeId!,
          ]),
      ),
    [mapping.items],
  );
  if (!current) return null;
  const selectedCandidate =
    choices[current.itemId] ?? current.figmaNodeId ?? current.candidates[0];
  const distanceToCurrent = (item: HifiMappingItem): number => {
    const target = current.figmaBounds ?? current.oldBounds;
    const source = item.oldBounds;
    if (!target || !source) return Number.MAX_SAFE_INTEGER;
    return (
      Math.abs(source[0] + source[2] / 2 - (target[0] + target[2] / 2)) +
      Math.abs(source[1] + source[3] / 2 - (target[1] + target[3] / 2))
    );
  };
  const availableOldItems = mapping.items
    .filter(
      (item) => item.oldObjectId && (!item.action || item.action === "keep_old"),
    )
    .sort((left, right) => distanceToCurrent(left) - distanceToCurrent(right))
    .slice(0, 20);
  const selectedOldItem =
    availableOldItems.find(
      (item) => item.itemId === oldChoices[current.itemId],
    ) ?? availableOldItems[0];
  const hasOld = Boolean(current.oldObjectId);
  const hasFigma = Boolean(current.figmaNodeId);
  const hasOwnedVisual = Boolean(
    current.ownedSourceIds && current.ownedSourceIds.length > 0,
  );
  const canPickLayer =
    hasOld && !hasOwnedVisual && current.candidates.length > 0;
  const canPickOld = !hasOld && hasFigma && availableOldItems.length > 0;
  const pickerOpen = picked === current.itemId;
  const candidateLabel = (nodeId: string): string => {
    const layer = psdLayers?.find((entry) => entry.id === nodeId);
    if (layer) return `${layer.name}（${layer.kind}）`;
    return figmaNames.get(nodeId) ?? nodeId.split(":").pop() ?? nodeId;
  };
  const canConfirm = hasOld && hasFigma && current.status !== "blocked";
  const unmappedOld = current.status === "fgui_only" && hasOld && !hasFigma;
  const canSkipBlocked =
    current.status === "blocked" && (!hasOld || allowKeepOld);
  const noWayOut =
    current.status === "blocked" &&
    hasOld &&
    !allowKeepOld &&
    current.candidates.length === 0;
  return (
    <>
      <div className="hifi-mapping-filter" role="group" aria-label="待确认映射决策">
        <button
          type="button"
          disabled={currentIndex === 0}
          onClick={() => onCurrentChange(pendingItems[currentIndex - 1].itemId)}
        >
          上一项
        </button>
        <strong>
          {currentIndex + 1} / {pendingItems.length}
        </strong>
        <button
          type="button"
          disabled={currentIndex === pendingItems.length - 1}
          onClick={() =>
            onCurrentChange(pendingItems[currentIndex + 1].itemId)
          }
        >
          下一项
        </button>
      </div>
      <section className="hifi-structure" aria-label="当前对象视觉证据">
        <h3>当前对象的样子</h3>
        <div className="hifi-canvas-pair">
          <figure className="hifi-evidence-figure">
            {oldPreviewUrl ? (
              <img src={oldPreviewUrl} alt="旧 FGUI 对象资源图" />
            ) : (
              <div className="hifi-evidence-empty">旧对象无静态资源图</div>
            )}
            <figcaption>旧 FGUI · 该对象现在的样子</figcaption>
          </figure>
          <PsdCropFigure
            bounds={current.figmaBounds ?? current.oldBounds}
            canvas={psdCanvas}
            loadPsdCrop={loadPsdCrop}
            caption={
              hasFigma
                ? "PSD · 该位置目标态画面（原生分辨率裁剪）"
                : "PSD · 旧对象同位置画面（此处应无对应内容）"
            }
          />
        </div>
      </section>
      <section className="hifi-current-card">
        <div>
          <strong>{current.oldName ?? "HIFI 新增视觉"}</strong>
          <span> → </span>
          <strong>
            {current.figmaName ??
              (current.action === "keep_old"
                ? "旧对象保留"
                : "尚未找到对应")}
          </strong>
          <small>
            {STATUS_LABELS[current.status]}
            {current.oldObjectId
              ? ` · 匹配分 ${Math.round(current.score * 100)}/100`
              : ""}
          </small>
        </div>
        {current.ownedSourceIds && current.ownedSourceIds.length > 0 && (
          <p className="writer-inline-note">
            该旧对象承载 {current.ownedSourceIds.length} 个 PSD
            视觉叶图层的合成资源；{current.retainedSourceIds?.length ?? 0}{" "}
            个文字叶图层仍由原文字对象承载。
          </p>
        )}
        {current.defaultVisible === false && (
          <p className="writer-inline-note">
            此对象在控制器默认页不可见；保留原有状态逻辑，并单独验收非默认页的新视觉。
          </p>
        )}
        {hasOwnedVisual && current.candidates.length > 0 && (
          <p className="writer-inline-note">
            该对象承载多层 PSD 视觉包；换层须重新生成视觉包。可确认当前对应，或列为例外人工处理。
          </p>
        )}
        {current.status === "blocked" && (
          <p className="writer-inline-note">
            {current.preserveRuntimeText
              ? "已按实例传入的文字精确找到 PSD 图层，但共享组件各实例的布局不同，须生成实例视觉变体并验证后才能写入。"
              : "该节点是容器、组件实例或其他非静态叶子，当前不会自动写入 FGUI。"}
          </p>
        )}
        {current.legacyState === "USER_DECISION_CONFLICT" && (
          <div className="hifi-decision-actions">
            <p className="writer-inline-note">
              与 PSD 冲突：这是可见的静态旧视觉，而新设计稿没有为它分配对应内容。保留原样会一直阻止候选生成；可退隐（保留对象与逻辑、隐藏旧画面），或先补设计稿后重新映射。
            </p>
            <div className="hifi-decision-choices" role="group" aria-label="冲突处置">
              <button
                className="primary-button compact"
                type="button"
                disabled={busy}
                onClick={() =>
                  onDecision(current, "keep_old", undefined, "retire")
                }
              >
                退隐旧视觉（保留对象）
              </button>
            </div>
          </div>
        )}
        {current.action !== "preserve_structure" &&
          current.legacyState !== "USER_DECISION_CONFLICT" && (
          <div className="hifi-decision-actions">
            <p className="hifi-decision-prompt">处理方式</p>
            <div
              className="hifi-decision-choices"
              role="group"
              aria-label="处理方式"
            >
              {canConfirm && (
                <button
                  className="primary-button compact"
                  type="button"
                  disabled={busy}
                  onClick={() => onDecision(current, "accept")}
                >
                  确认对应
                </button>
              )}
              {(canPickLayer || canPickOld) && (
                <button
                  className="secondary-button compact"
                  type="button"
                  aria-pressed={pickerOpen}
                  disabled={busy}
                  onClick={() =>
                    setPicked(pickerOpen ? undefined : current.itemId)
                  }
                >
                  {pickerOpen ? "收起" : "更换图层"}
                </button>
              )}
              {unmappedOld && (
                <p className="writer-inline-note">
                  PSD 没有画这个旧对象。隐藏旧视觉会保留对象与程序逻辑。
                </p>
              )}
              {current.status === "hifi_added" &&
                allowVisualAddition &&
                current.action !== "add_visual" && (
                  <button
                    className="secondary-button compact"
                    type="button"
                    disabled={busy}
                    onClick={() => onDecision(current, "add_visual")}
                  >
                    标记为新增视觉
                  </button>
                )}
              {current.status === "hifi_added" && !allowVisualAddition && (
                <p className="writer-inline-note">
                  PSD 替换须先找到旧对象；独立新增需要明确归属，当前不能直接新增。
                </p>
              )}
              {current.status === "hifi_added" &&
                current.action !== "exception" && (
                  <button
                    className="secondary-button compact"
                    type="button"
                    disabled={busy}
                    onClick={() => onDecision(current, "exception")}
                  >
                    暂不处理
                  </button>
                )}
              {canSkipBlocked && current.action !== "exception" && (
                <button
                  className="primary-button compact"
                  type="button"
                  disabled={busy}
                  onClick={() => onDecision(current, "exception")}
                >
                  列为例外（人工处理）
                </button>
              )}
              {unmappedOld && current.action !== "exception" && (
                <button
                  className="primary-button compact"
                  type="button"
                  disabled={busy}
                  onClick={() => onDecision(current, "exception")}
                >
                  隐藏旧视觉
                </button>
              )}
              {allowKeepOld && hasOld && current.action !== "keep_old" && (
                <button
                  className="secondary-button compact"
                  type="button"
                  disabled={busy}
                  onClick={() => onDecision(current, "keep_old")}
                >
                  保留旧对象
                </button>
              )}
              {noWayOut && (
                <p className="writer-inline-note">
                  该项挂着旧对象且没有可对应的 PSD 候选；需要调整归属规则并重新映射后才能继续。
                </p>
              )}
            </div>
            {pickerOpen && canPickLayer && (
              <label className="hifi-candidate-select">
                换成哪个图层
                <select
                  aria-label="换成哪个图层"
                  value={selectedCandidate}
                  disabled={busy}
                  onChange={(event) =>
                    setChoices({
                      ...choices,
                      [current.itemId]: event.currentTarget.value,
                    })
                  }
                >
                  {current.candidates.map((nodeId) => (
                    <option value={nodeId} key={nodeId}>
                      {candidateLabel(nodeId)}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {pickerOpen && canPickLayer && selectedCandidate && (
              <button
                className="primary-button compact"
                type="button"
                disabled={busy}
                onClick={() =>
                  onDecision(current, "retarget", selectedCandidate)
                }
              >
                确认更换
              </button>
            )}
            {pickerOpen && canPickOld && selectedOldItem && (
              <label className="hifi-candidate-select">
                对应的旧 FGUI 对象
                <select
                  aria-label="对应的旧 FGUI 对象"
                  value={selectedOldItem.itemId}
                  disabled={busy}
                  onChange={(event) =>
                    setOldChoices({
                      ...oldChoices,
                      [current.itemId]: event.currentTarget.value,
                    })
                  }
                >
                  {availableOldItems.map((item) => (
                    <option value={item.itemId} key={item.itemId}>
                      {item.oldName}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {pickerOpen && canPickOld && selectedOldItem && (
              <button
                className="primary-button compact"
                type="button"
                disabled={busy}
                onClick={() =>
                  onDecision(
                    selectedOldItem,
                    "retarget",
                    current.figmaNodeId,
                  )
                }
              >
                建立对应
              </button>
            )}
            {hasOld && !hasOwnedVisual && cutouts && cutouts.length > 0 && (
              <label className="hifi-candidate-select">
                从切图池人工配对（PSD 未画时的新皮肤证据）
                <select
                  aria-label="从切图池人工配对"
                  value={cutoutChoices[current.itemId] ?? ""}
                  disabled={busy}
                  onChange={(event) =>
                    setCutoutChoices({
                      ...cutoutChoices,
                      [current.itemId]: event.currentTarget.value,
                    })
                  }
                >
                  <option value="">选择一张切图…</option>
                  {thisPsdCutouts.length > 0 && (
                    <optgroup label={`本 PSD 切图（${thisPsdCutouts.length}）`}>
                      {thisPsdCutouts.map((entry) => (
                        <option value={entry.name} key={entry.name}>
                          {entry.name}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {sharedCutouts.length > 0 && (
                    <optgroup label={`通用切图（${sharedCutouts.length}）`}>
                      {sharedCutouts.map((entry) => (
                        <option value={entry.name} key={entry.name}>
                          {entry.name}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {[...otherCutoutFamilies].map(([label, names]) => (
                    <optgroup
                      key={label}
                      label={`${label} · 其他 PSD（${names.length}）`}
                    >
                      {names.map((name) => (
                        <option value={name} key={name}>
                          {name}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </label>
            )}
            {cutoutPoolMixed && (
              <p className="writer-inline-note">
                切图池混有多个 PSD 的导出，优先在「本 PSD 切图」里选。
              </p>
            )}
            {hasOld
              && !hasOwnedVisual
              && cutouts
              && cutouts.length > 0
              && cutoutThumbnails?.[cutoutChoices[current.itemId]] && (
              <span className="hifi-cutout-preview">
                <img
                  src={cutoutThumbnails[cutoutChoices[current.itemId]]}
                  alt={`切图预览 ${cutoutChoices[current.itemId]}`}
                />
                <small>所选切图 · 按旧对象的位置与尺寸应用</small>
              </span>
            )}
            {hasOld && !hasOwnedVisual && cutouts && cutouts.length > 0 && (
              <button
                className="primary-button compact"
                type="button"
                disabled={busy || !cutoutChoices[current.itemId]}
                onClick={() =>
                  onDecision(
                    current,
                    "retarget",
                    `cutout:${cutoutChoices[current.itemId]}`,
                  )
                }
              >
                使用所选切图
              </button>
            )}
            {current.figmaNodeId && onLocate && (
              <button
                className="secondary-button compact"
                type="button"
                onClick={() => onLocate(current.figmaNodeId!)}
              >
                定位到来源图层
              </button>
            )}
            {current.action &&
              current.candidates.length > 0 &&
              current.figmaNodeId !== current.candidates[0] &&
              !(
                current.ownedSourceIds && current.ownedSourceIds.length > 0
              ) && (
                <button
                  className="secondary-button compact"
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    onDecision(current, "retarget", current.candidates[0])
                  }
                >
                  恢复自动建议
                </button>
              )}
          </div>
        )}
      </section>
    </>
  );
}
