import type {
  DesignAssetStatus,
  FixedFontStatus,
  HifiProjectTree,
  HifiTargetRef,
  ProjectView,
  PsdSource,
} from "../../../figma-plugin/src/project-client";

export type PreparedPsdItem = { sourceId: string; name: string };
import { PROJECT_ARCHIVE_ACCEPT } from "../../../figma-plugin/src/project-client";
import {
  HifiTargetPicker,
  type HifiTargetSelection,
} from "../figma/HifiTargetPicker";

export function MaterialPreparation({
  project,
  tree,
  selectedList,
  fonts,
  fontError,
  psdSource,
  compositeUrl,
  previewError,
  projectBusy,
  psdBusy,
  projectError,
  onProject,
  onPsd,
  onToggle,
  onRetryPreview,
  onRetryFonts,
  designAssets,
  designRootInput,
  assetsBusy,
  assetsError,
  onDesignRootChange,
  onLinkAssets,
  psdItems,
  cutoutDirInput,
  onCutoutDirChange,
  onSelectPsd,
  pairTargets,
  targetOptions,
  onPairTarget,
}: {
  project?: ProjectView;
  tree?: HifiProjectTree;
  selectedList: HifiTargetSelection[];
  fonts: FixedFontStatus[];
  fontError: string;
  psdSource?: PsdSource;
  compositeUrl?: string;
  previewError: string;
  projectBusy: boolean;
  psdBusy: boolean;
  projectError: string;
  onProject(file?: File): void;
  onPsd(files: File[]): void;
  onToggle(selection: HifiTargetSelection): void;
  onRetryPreview(): void;
  onRetryFonts(): void;
  designAssets: DesignAssetStatus;
  designRootInput: string;
  assetsBusy: boolean;
  assetsError: string;
  onDesignRootChange(value: string): void;
  onLinkAssets(): void;
  psdItems: PreparedPsdItem[];
  cutoutDirInput: string;
  onCutoutDirChange(value: string): void;
  onSelectPsd(sourceId: string): void;
  pairTargets: Record<string, HifiTargetRef>;
  targetOptions: Array<{ label: string; ref: HifiTargetRef }>;
  onPairTarget(sourceId: string, relativePath: string): void;
}) {
  const inspection = psdSource?.inspection;
  const installed = fonts.filter((font) => font.installed).length;
  const visibleText =
    psdSource?.layers.filter(
      (layer) => layer.kind.toLowerCase() === "type" && layer.effectiveVisible,
    ) ?? [];
  const styled = visibleText.filter((layer) => layer.textStyle?.runs.length);
  const runs = styled.flatMap((layer) => layer.textStyle?.runs ?? []);
  const cutoutGroups = designAssets.manifest?.cutoutGroups ?? [];
  const cutoutGroupTotal = (relevance: string) =>
    cutoutGroups
      .filter((group) => group.relevance === relevance)
      .reduce((sum, group) => sum + group.count, 0);
  return (
    <>
      <div className="local-page-heading">
        <h2>准备替换材料</h2>
        <p>导入旧工程，选择需要更新的组件，再添加对应的 PSD 设计稿。</p>
      </div>
      <div className="local-prepare-layout local-prepare-columns">
        <section className="local-hifi-card local-col-project">
            <div className="local-hifi-card-title">
              <div>
                <span>01</span>
                <h2>旧 FairyGUI 工程</h2>
              </div>
              <small>
                {projectBusy ? "正在读取…" : project ? "已导入" : "必需"}
              </small>
            </div>
            <label className="local-hifi-file">
              旧 FairyGUI 工程压缩包
              <input
                type="file"
                onClick={(event) => {
                  event.currentTarget.value = "";
                }}
                accept={PROJECT_ARCHIVE_ACCEPT}
                disabled={projectBusy || psdBusy}
                onChange={(event) => {
                  onProject(event.currentTarget.files?.[0]);
                }}
              />
            </label>
            {project && (
              <p className="local-hifi-file-name">{project.displayName}</p>
            )}
            {projectError && (
              <p className="local-hifi-error" role="alert">
                {projectError}
              </p>
            )}
            {tree && project ? (
              <HifiTargetPicker
                key={project.projectId}
                project={project}
                tree={tree}
                values={selectedList}
                disabled={projectBusy || psdBusy}
                onToggle={onToggle}
              />
            ) : (
              <div className="local-empty">
                <strong>选择要更新的组件</strong>
                <p>导入工程后，这里会显示包、目录和根组件。</p>
              </div>
            )}
        </section>
        <div className="local-col-psd">
          <section className="local-hifi-card">
            <div className="local-hifi-card-title">
              <div>
                <span>02</span>
                <h2>HIFI PSD</h2>
              </div>
              <small>
                {psdBusy
                  ? "处理中…"
                  : inspection
                    ? psdItems.length > 1
                      ? `已导入 ${psdItems.length} 个`
                      : "已导入"
                    : "必需"}
              </small>
            </div>
            <label className="local-hifi-file">
              HIFI PSD
              <input
                type="file"
                onClick={(event) => {
                  event.currentTarget.value = "";
                }}
                accept=".psd,image/vnd.adobe.photoshop,image/x-photoshop"
                disabled={psdBusy || projectBusy}
                onChange={(event) => {
                  onPsd(Array.from(event.currentTarget.files ?? []));
                }}
              />
            </label>
            {psdItems.length > 0 && (
              <ul className="local-psd-items">
                {psdItems.map((item, index) => (
                  <li key={item.sourceId}>
                    <button
                      type="button"
                      className={
                        item.sourceId === psdSource?.sourceId
                          ? "is-current"
                          : ""
                      }
                      disabled={psdBusy}
                      onClick={() => onSelectPsd(item.sourceId)}
                    >
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <strong>{item.name}</strong>
                    </button>
                    <label className="local-pair-target">
                      对应目标
                      <select
                        value={
                          pairTargets[item.sourceId]?.componentRelativePath ??
                          ""
                        }
                        disabled={psdBusy || targetOptions.length === 0}
                        onChange={(event) =>
                          onPairTarget(item.sourceId, event.currentTarget.value)
                        }
                      >
                        <option value="">未配对</option>
                        {targetOptions.map((option) => (
                          <option
                            key={option.ref.componentRelativePath}
                            value={option.ref.componentRelativePath}
                          >
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  </li>
                ))}
              </ul>
            )}
            {inspection && (
              <div className="local-psd-summary">
                <strong>{inspection.sourceName}</strong>
                <p>
                  {inspection.width} × {inspection.height} · {inspection.depth}
                  -bit {inspection.colorMode}
                </p>
                <p>
                  {inspection.layerCount} 个图层 · {inspection.textLayerCount}{" "}
                  个文字层 · {inspection.smartObjectCount} 个智能对象
                </p>
                <p>PSD 已保存在本机，后续映射不会重复上传。</p>
                {visibleText.length > 0 && (
                  <p className="local-text-evidence">
                    可见文字样式 {styled.length} / {visibleText.length} 层 ·
                    字体名称 {runs.filter((run) => run.fontName).length} /{" "}
                    {runs.length} 个运行已解析
                  </p>
                )}
              </div>
            )}
          </section>
          <section className="local-hifi-card local-font-card">
            <div className="local-hifi-card-title">
              <div>
                <span>03</span>
                <h2>固定字体</h2>
              </div>
              <strong
                className={
                  fonts.length > 0 && installed === fonts.length
                    ? "is-ok"
                    : "is-warn"
                }
              >
                {fonts.length
                  ? `固定字体 ${installed} / ${fonts.length}`
                  : fontError
                    ? "检查失败"
                    : "正在检查…"}
              </strong>
            </div>
            <p>自动检查本机字体，供文字图层转换使用。</p>
            <ul>
              {fonts.map((font) => (
                <li key={font.sha256}>
                  <span
                    className={font.installed ? "is-installed" : "is-missing"}
                  >
                    {font.installed ? "✓" : "!"}
                  </span>
                  <div>
                    <strong>{font.family}</strong>
                    <small>
                      {font.installed
                        ? font.postscriptName
                        : "未安装，请安装字体后重新检查"}
                    </small>
                  </div>
                </li>
              ))}
            </ul>
            {fontError && (
              <p className="local-hifi-error" role="alert">
                {fontError}
              </p>
            )}
            {(fontError || installed < fonts.length) && (
              <button
                type="button"
                className="secondary-button"
                onClick={onRetryFonts}
              >
                重新检查字体
              </button>
            )}
          </section>
          <details className="local-hifi-card local-cutout-settings">
            <summary>切图 / 设计资产设置（可选，默认隐藏）</summary>
            <div className="local-hifi-card-title">
              <div>
                <span>04</span>
                <h2>设计资产（可选）</h2>
              </div>
              <small>
                {designAssets.linked
                  ? "已链接"
                  : assetsBusy
                    ? "识别中…"
                    : "未链接"}
              </small>
            </div>
            <p>
              指定 PSD 所在文件夹，自动识别其中的“切图”目录和“效果图”：切图会优先作为权威皮肤，效果图用于逐单位保真度对比。
            </p>
            <label className="local-hifi-file">
              设计资产文件夹路径
              <input
                type="text"
                value={designRootInput}
                placeholder="例如 D:/P-PVP爬塔/P-PVP爬塔"
                disabled={assetsBusy || !inspection}
                onChange={(event) => onDesignRootChange(event.currentTarget.value)}
              />
            </label>
            <label className="local-hifi-file">
              切图文件夹路径（可选）
              <input
                type="text"
                value={cutoutDirInput}
                placeholder="切图文件夹路径，如 D:/交付/切图"
                disabled={assetsBusy || !inspection}
                onChange={(event) => onCutoutDirChange(event.currentTarget.value)}
              />
            </label>
            <p className="writer-inline-note">
              批量建批时，这两个路径会作为整批的设计资产根目录与切图目录一并提交；留空则跳过。
            </p>
            <button
              type="button"
              className="secondary-button"
              disabled={assetsBusy || !inspection || !designRootInput.trim()}
              onClick={onLinkAssets}
            >
              {assetsBusy ? "正在识别…" : "识别切图 / 效果图"}
            </button>
            {assetsError && (
              <p className="local-hifi-error" role="alert">
                {assetsError}
              </p>
            )}
            {designAssets.linked && designAssets.manifest && (
              <div className="local-psd-summary">
                <strong>
                  {designAssets.manifest.effectImage
                    ? `效果图：${designAssets.manifest.effectImage.split(/[\\/]/).pop()}`
                    : "未找到效果图"}
                </strong>
                <p>
                  切图 {designAssets.manifest.cutouts.length} 张
                  {designAssets.manifest.cutoutDir
                    ? ` · ${designAssets.manifest.cutoutDir}`
                    : ""}
                </p>
                {cutoutGroups.length > 0 && (
                  <div className="local-cutout-families">
                    <p>
                      本 PSD {cutoutGroupTotal("this_psd")} 张 · 通用{" "}
                      {cutoutGroupTotal("shared")} 张 · 其他 PSD{" "}
                      {cutoutGroupTotal("other")} 张
                    </p>
                    <ul>
                      {cutoutGroups.map((group) => (
                        <li
                          key={`${group.relevance}:${group.family}`}
                          className={`is-${group.relevance}`}
                        >
                          <strong>{group.family || "未分组"}</strong>
                          <span>{group.count} 张</span>
                        </li>
                      ))}
                    </ul>
                    {cutoutGroupTotal("other") > 0 && (
                      <small>
                        切图目录混有多个 PSD 的导出，已按文件名家族分组；配对时优先看「本 PSD」与「通用」。
                      </small>
                    )}
                  </div>
                )}
              </div>
            )}
          </details>
        </div>
        <aside className="local-source-preview" aria-label="PSD 设计稿预览">
          <div className="local-preview-heading">
            <h2>设计稿预览</h2>
            <span>
              {inspection
                ? `${inspection.width} × ${inspection.height}`
                : "等待 PSD"}
            </span>
          </div>
          {compositeUrl ? (
            <figure className="local-psd-composite">
              <a
                href={compositeUrl}
                target="_blank"
                rel="noreferrer"
                aria-label="打开 PSD 原图"
              >
                <img src={compositeUrl} alt="PSD 合成基准图" />
              </a>
              <figcaption>PSD 内嵌合成基准 · 点击查看原图</figcaption>
            </figure>
          ) : (
            <div className="local-preview-empty">
              <span aria-hidden="true">PSD</span>
              <strong>
                {psdBusy
                  ? "正在准备设计稿…"
                  : inspection
                    ? "预览暂不可用"
                    : "在这里核对设计稿"}
              </strong>
              <p>导入 PSD 后显示完整画面，便于确认来源和尺寸。</p>
            </div>
          )}
          {previewError && (
            <div className="local-hifi-error" role="alert">
              <p>{previewError}</p>
              <button
                type="button"
                className="secondary-button"
                disabled={psdBusy}
                onClick={onRetryPreview}
              >
                重新加载预览
              </button>
            </div>
          )}
        </aside>
      </div>
    </>
  );
}
