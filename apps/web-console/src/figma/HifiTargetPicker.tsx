import { useState } from "react";
import type { HifiProjectTree, HifiTargetRef, ProjectView } from "../../../figma-plugin/src/project-client";

export type HifiTargetSelection = readonly [number, number, number];

function reasonLabel(reason?: string): string {
  const labels: Record<string, string> = {
    unsupported_fairygui_version: "仅支持 FairyGUI 6.1.4",
    component_unavailable: "组件文件不可读",
    invalid_component_root: "不是有效根组件",
    no_selectable_components: "没有可选组件",
  };
  return reason ? labels[reason] ?? "不可选择" : "不可选择";
}

export function selectedHifiTarget(
  project: ProjectView,
  tree: HifiProjectTree,
  selected?: HifiTargetSelection,
): HifiTargetRef | undefined {
  if (!selected) return undefined;
  const [packageIndex, directoryIndex, componentIndex] = selected;
  const packageItem = tree.packages[packageIndex];
  const directory = packageItem?.directories[directoryIndex];
  const component = directory?.components[componentIndex];
  if (!packageItem || !directory || !component?.selectable) return undefined;
  return {
    version: 1,
    projectId: project.projectId,
    projectFingerprint: tree.projectFingerprint,
    packageId: packageItem.packageId,
    packageName: packageItem.name,
    directory: directory.path,
    componentId: component.resourceId,
    componentName: component.name,
    componentRelativePath: component.relativePath,
  };
}

export function HifiTargetPicker({
  project,
  tree,
  value,
  disabled = false,
  onChange,
}: {
  project: ProjectView;
  tree: HifiProjectTree;
  value?: HifiTargetSelection;
  disabled?: boolean;
  onChange(value: HifiTargetSelection): void;
}) {
  const target = selectedHifiTarget(project, tree, value);
  const [expandedPackage, setExpandedPackage] = useState<number>();
  const [expandedDirectory, setExpandedDirectory] = useState<string>();
  return <section className="hifi-target-tree" aria-labelledby="hifi-target-title">
    <div className="hifi-section-heading">
      <div><h2 id="hifi-target-title">FGUI 修改位置</h2><p>选择目录，再选择该目录中的根组件。</p></div>
      <span>需确认</span>
    </div>
    {tree.packages.map((packageItem, packageIndex) => {
      const packageExpanded = expandedPackage === packageIndex;
      return <div className="hifi-package" key={packageItem.packageId}>
      <button className="hifi-package-toggle" type="button" aria-expanded={packageExpanded} disabled={disabled} onClick={() => { setExpandedPackage(packageExpanded ? undefined : packageIndex); setExpandedDirectory(undefined); }}><span>{packageExpanded ? "▾" : "▸"} {packageItem.name}</span><small>{packageItem.directories.length} 个目录</small></button>
      {packageExpanded && packageItem.directories.map((directory, directoryIndex) => {
        const directoryKey = `${packageIndex}:${directoryIndex}`;
        const expanded = expandedDirectory === directoryKey;
        return <div key={directory.path}>
        <button
          className={`hifi-tree-row hifi-directory ${value?.[0] === packageIndex && value[1] === directoryIndex ? "is-selected" : ""}`}
          type="button"
          aria-pressed={value?.[0] === packageIndex && value[1] === directoryIndex}
          aria-expanded={expanded}
          disabled={disabled || !directory.selectable}
          onClick={() => { setExpandedDirectory(expanded ? undefined : directoryKey); onChange([packageIndex, directoryIndex, -1]); }}
        ><span>{expanded ? "▾" : "▸"} {directory.path}</span><small>{directory.selectable ? `${directory.components.length} 个组件` : reasonLabel(directory.reason)}</small></button>
        {expanded && directory.components.map((component, componentIndex) => <button
          className={`hifi-tree-row hifi-component ${value?.[0] === packageIndex && value[1] === directoryIndex && value[2] === componentIndex ? "is-selected" : ""}`}
          type="button"
          aria-pressed={value?.[0] === packageIndex && value[1] === directoryIndex && value[2] === componentIndex}
          disabled={disabled || !component.selectable}
          onClick={() => onChange([packageIndex, directoryIndex, componentIndex])}
          key={component.resourceId}
        ><span>◆ {component.name}</span><small>{component.selectable ? "根组件" : reasonLabel(component.reason)}</small></button>)}
      </div>;})}
    </div>;})}
    {target && <dl className="hifi-target-summary">
      <div><dt>目标目录</dt><dd>{target.packageName} / {target.directory}</dd></div>
      <div><dt>根组件</dt><dd>{target.componentName}</dd></div>
    </dl>}
  </section>;
}
