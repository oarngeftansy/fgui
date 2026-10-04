# 交接文档：PSD → FairyGUI HIFI 语义换皮工具（Policy 28）

> 本文档为跨会话交接而写。新会话请先读完本文，再按"新会话开场白"一节与用户对话。

## 1. 项目一句话

把设计同学的 **PSD 效果图**换肤到**旧 FairyGUI 工程**上：PSD 是视觉/结构权威，旧 FGUI 是程序逻辑基线（换皮不换骨）。工具链 = FastAPI 后端 + 共享 TS 客户端（figma-plugin 包内 `project-client.ts`）+ 本地 Web 控制台（web-console，浏览器操作）+ 可选 FairyGUI Editor 6.1.4 实机核验。

- 代码根：`D:\project-fixed-policy25\project`
- 规格：`C:\Users\momoca\Downloads\Policy_28_PSD_First_Semantic_Reskin.md`（唯一主逻辑来源，revision 28）
- 服务：`http://127.0.0.1:8766`（本地控制台 + API）
- 用户在本机浏览器实测，真实工程为 isekaiUI 风格项目。

## 2. 当前状态（2026-10-05）

**Policy 28 差距地图全部落地并验证**（后端 1621 passed / figma-plugin 103 / web-console 88，双端 tsc 0）：

| 阶段 | 内容 | 关键落点 |
|---|---|---|
| P1c §13 | GList 完整盘点+行模板换皮+行组剥离+七态 draft 分类 | `hifi_mapping.py`（`_list_row_groups`/`_list_row_repeat_ids`/`_list_template_pairs`/`auto_legacy_state`）、`hifi_nested.py` list 展开 |
| P2 §14/16 | 双向 Visual Closure + BLOCK 硬门槛 | `hifi_mapping.py`（`_psd_coverage`/`visual_closure`/`require_visual_closure`）、`HifiVisualClosureReport` 模型、`GET /closure` |
| P3 §8-11 | Legacy Removal Review（≤5 组）+ Reference Closure | `hifi_removal_review.py`（新模块）、`remove_old` 动作、`hifi_patch.py` 删除+引用闭合+`hifi_reference_closure_invalid`、API `/removal-review(+/decide)`、控制台 `HifiRemovalReviewPanel.tsx` |
| P5 §12/§7 | Novelty Check（证据化自动新增）+ gear/relation 几何检查 | `novelty_proven` 字段、`hifi_novelty_evidence_missing` 硬门槛、闭包计 Proven New Visual、`_local_plans` add 路由、嵌套审计 stale_gear_refs/relation_drifts |
| P6 §17 | Editor 对比不达标→差异定位+归因+修正闭环 | `fairygui_editor_verify.py` `editor_mismatch_regions`、`HifiEditorMismatchRegion`、api editor-verify 富化、控制台差异区域清单 |
| 热修 | **两套所有权模型掉叶子的闭包假阴性**（见 §4） | `hifi_semantic_reskin.py` 三处修改 |

另有更早落地：状态运行时取证（`hifi_controller_states.py` + `/state-evidence` 端点 + IoU/方向一致率指标）、transition 关键帧陈旧几何核对、工作台自动续跑（`useHifiWorkflow.ts` auto pipeline）、程序逻辑保留审计（`hifi_nested.py` validate_nested_candidate）。

## 3. 架构速览

```
src/figma_to_fgui/
  hifi_mapping.py          映射引擎（匹配/分类/闭包）——最大最核心
  hifi_semantic_reskin.py  P27 语义规范化（组件↔PSD 组配对、owned bundle 分配）
  hifi_patch.py            bundle 生成 + validate（元素级改写 + 程序逻辑校验）
  hifi_nested.py           嵌套展开/局部计划/审计（inspect_component_tree 必走）
  hifi_removal_review.py   §8-11 删除评审计算
  hifi_controller_states.py Editor 状态取证
  fairygui_editor_verify.py Editor 截图核验 + 差异区域定位
  hifi_replacement_workflow.py  会话编排（begin/build/decide/closure_report/...）
  hifi_replacement_models.py    全部 wire 模型（StrictVersionedModel, extra=forbid）
  api.py                   FastAPI 路由
apps/figma-plugin/src/project-client.ts  唯一共享客户端（web-console 直接 import 源码）
apps/web-console/  本地控制台（useHifiWorkflow.ts = 状态机 + 自动流水线）
```

**会话数据**：`.local-hifi-run/data/hifi-replacements.db`（SQLite，表 `hifi_replacements`，注意是下划线）。诊断已存会话：直接用 sqlite3 读最新行 + `HifiReplacementStore.get()` + `workflow.closure_report()`（诊断脚本样例在工作区，见 §6）。

## 4. 最后修复的 bug（用户实测"仍有对象未覆盖 PSD 视觉"）

**现象**：用户 build 被闭包门槛拦，20 个 PSD 装饰叶子（按钮组"花纹2"系列 shape）无人认领。

**根因链**：
1. `build_mapping` 的 raw 分配器把整组 22 叶烘成 owned bundle 挂到宿主（渲染校验通过）→ 这些叶被 claimed，**不再生成 new: 项**；
2. `normalize_psd_semantic_reskin` 按设计剥掉 raw bundle、由语义引擎重新分区；语义分区**成功**但只给宿主 2 叶，其余 21 叶标记 retained 无人接盘；
3. 两套模型之间掉叶子 → `_psd_coverage` 报 20 个未解释 → BLOCK。

**修复（`hifi_semantic_reskin.py` 三处，已验证用户会话数据 194/194 全闭合）**：
- strip 前快照 raw bundles；
- 语义分区后逐 bundle 对账：bundle 的叶子若未被新分区消化（非 owned/非 text 复用）且其组**确被语义引擎处理过**（`pair_by_old.values()`，避免救回被否决的错误配对——P27 兼容测试保护此语义），整体恢复该 renderer-proven bundle；
- strip 的机械 keep_old 与 `REMOVE_CANDIDATE` 冲突项退回未决池（进删除评审面板）。

**修复后用户流程**：闭包通过 → 剩 2 个 `REMOVE_CANDIDATE`（n30_gm65 组）→ 控制台弹"旧视觉删除确认"面板 → 用户选移除/保留 → build 通过。用户旧会话（d3eb9e95…，坏数据）作废；幂等键每次随机，**直接新建会话即可**。

## 5. 运行与验证命令

```powershell
# 后端测试（全量 ~2 分钟）
$env:PYTHONPATH="D:\project-fixed-policy25\project\src"
python -m pytest D:\project-fixed-policy25\project	ests -q

# 前端（figma-plugin 103 / web-console 88；plugin-harness 5 个 .venv 失败为既有环境问题，忽略）
cd appsigma-plugin; npx tsc --noEmit; npx vitest run
cd apps\web-console; npx tsc --noEmit; npx vitest run

# 重建控制台产物
cd apps\web-console; npm run build

# 重启服务（8766）
$env:PYTHONPATH="D:\project-fixed-policy25\project\src"
python -m figma_to_fgui.cli serve --local-app `
  --data-dir D:\project-fixed-policy25\project\.local-hifi-run\data `
  --rules D:\project-fixed-policy25\projectules\default\classification.yaml `
  --fixtures-root D:\project-fixed-policy25\project	estsixtures `
  --web-dist D:\project-fixed-policy25\projectpps\web-console\dist `
  --plugin-access-token-file D:\project-fixed-policy25\project\.local-hifi-runccess-token.txt `
  --host 127.0.0.1 --port 8766

# figma-plugin dist 重建（需占位环境变量，与 dist/manifest.json 一致）
cd appsigma-plugin
$env:FGUI_SERVER_ORIGIN="https://fgui.corp.example"; $env:FIGMA_PLUGIN_ID="123456789"
$env:FGUI_PLUGIN_ACCESS_TOKEN="local-dev-placeholder-token-0123456789abcdef"; npm run build
```

## 6. 工作区脚本（TRAE 沙箱约束）

TRAE 对 `D:\` 只有读权限——**所有 D 盘写操作一律经工作区 Python 脚本**（锚点断言 + replace，幂等）。工作区：
`C:\Users\momoca\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6abe6661e1e6bad9a16788a5\`

本轮关键脚本：`wire_policy28_closure.py`、`wire_policy28_removal*.py`、`wire_policy28_novelty.py`、`wire_policy28_correction_loop.py`、`fix_semantic_reskin_closure{,2}.py`、`fix_reconcile_gate.py`；诊断：`diag_coverage_session.py`、`diag_begin_pipeline.py`、`diag_normalize_trace.py`（复刻 begin_psd 四阶段流水线，验证修复用）。

坑：PowerShell 多行 python -c 引号会被吞→写脚本文件；HifiMappingItem 的新增 wire 字段在测试里必须显式给（Strict 模式）；测试断言改动后先用探针脚本跑事实再改断言。

## 7. 下一步（新会话的待办）

1. **用户继续网页实测**（优先）：新建会话上传同 PSD（e6762c29…）+ 工程 → 应看到"旧视觉删除确认"面板（2 组）→ 确认后 build → review（含双向闭包注记）→ Editor 核验（不达标时看"差异区域（修正闭环）"清单）→ 交付。用户反馈问题按 §4 的诊断套路查 `.local-hifi-run/data`。
2. 已知待观察：本热修的和解逻辑只救"语义处理过的组"的 raw bundle；若未来出现其它掉叶形态，用 `diag_begin_pipeline.py` 同法定位。
3. 可选后续：§16 "无重复 Text / 无 Old+New 重复 ownership" 仍主要靠既有守卫（duplicate_psd_pixel_ownership 等）非显式专闸；列表 lineGap 随行高变化未同步（P5 有意未做）。

## 8. 新会话开场白（复制给新会话即可）

见下方对话消息——直接粘贴用户侧开场白。
