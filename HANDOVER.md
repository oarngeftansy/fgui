# 交接文档：PSD → FairyGUI HIFI 语义换皮工具（Policy 28）

> 本文档为跨会话交接而写。新会话请先读完本文，再按"新会话开场白"一节与用户对话。

## 1. 项目一句话

把设计同学的 **PSD 效果图**换肤到**旧 FairyGUI 工程**上：PSD 是视觉/结构权威，旧 FGUI 是程序逻辑基线（换皮不换骨）。工具链 = FastAPI 后端 + 共享 TS 客户端（figma-plugin 包内 `project-client.ts`）+ 本地 Web 控制台（web-console，浏览器操作）+ 可选 FairyGUI Editor 6.1.4 实机核验。

- 代码根：`D:\project-fixed-policy25\project`
- 规格：`C:\Users\momoca\Downloads\Policy_28_PSD_First_Semantic_Reskin.md`（唯一主逻辑来源，revision 28）
- 服务：`http://127.0.0.1:8766`（本地控制台 + API）
- 用户在本机浏览器实测，真实工程为 isekaiUI 风格项目。

## 2. 当前状态（2026-10-06）

**Policy 28 差距地图全部落地并验证**（最新：后端 1667 passed / figma-plugin 276 passed / web-console 88，双端 tsc 0；第二批见 §2.1、第三批见 §2.2、第四批见 §2.3、第五批见 §2.4、第六批见 §2.5、第七批见 §2.6、第八批见 §2.7）：

| 阶段 | 内容 | 关键落点 |
|---|---|---|
| P1c §13 | GList 完整盘点+行模板换皮+行组剥离+七态 draft 分类 | `hifi_mapping.py`（`_list_row_groups`/`_list_row_repeat_ids`/`_list_template_pairs`/`auto_legacy_state`）、`hifi_nested.py` list 展开 |
| P2 §14/16 | 双向 Visual Closure + BLOCK 硬门槛 | `hifi_mapping.py`（`_psd_coverage`/`visual_closure`/`require_visual_closure`）、`HifiVisualClosureReport` 模型、`GET /closure` |
| P3 §8-11 | Legacy Removal Review（≤5 组）+ Reference Closure | `hifi_removal_review.py`（新模块）、`remove_old` 动作、`hifi_patch.py` 删除+引用闭合+`hifi_reference_closure_invalid`、API `/removal-review(+/decide)`、控制台 `HifiRemovalReviewPanel.tsx` |
| P5 §12/§7 | Novelty Check（证据化自动新增）+ gear/relation 几何检查 | `novelty_proven` 字段、`hifi_novelty_evidence_missing` 硬门槛、闭包计 Proven New Visual、`_local_plans` add 路由、嵌套审计 stale_gear_refs/relation_drifts |
| P6 §17 | Editor 对比不达标→差异定位+归因+修正闭环 | `fairygui_editor_verify.py` `editor_mismatch_regions`、`HifiEditorMismatchRegion`、api editor-verify 富化、控制台差异区域清单 |
| 热修 | **两套所有权模型掉叶子的闭包假阴性**（见 §4） | `hifi_semantic_reskin.py` 三处修改 |

另有更早落地：状态运行时取证（`hifi_controller_states.py` + `/state-evidence` 端点 + IoU/方向一致率指标）、transition 关键帧陈旧几何核对、工作台自动续跑（`useHifiWorkflow.ts` auto pipeline）、程序逻辑保留审计（`hifi_nested.py` validate_nested_candidate）。

## 2.2 本批新增（2026-10-05 第三批：决策可见性 + 自动化补强）

后端 1656 passed / web-console 92，双端 tsc 0。全部按用户实测反馈落地：

| 改进 | 内容 | 关键落点 |
|---|---|---|
| 删除评审预览 | 每个候选对象直接看到旧皮肤实物：image/loader 解析包内贴图缩略图（数据 URL）；graph/text/component 等无静态贴图对象做**原位区域渲染**（把旧组件平面画出来、红框标出拟删对象、裁剪放大），文字对象另附内容文本与旧尺寸 | `hifi_removal_review.py` `enrich_removal_previews`（`_package_image_paths`/`_preview_data_url`/`_render_component_region`，含 `_argb`/`_pair`/`_preview_font`），`HifiRemovalObject` 增 `preview_url`/`text`/`size`，`workflow.removal_review` 接线；前端 `HifiRemovalReviewPanel.tsx` 预览块 + `project-client.ts` 解析 |
| Editor 常驻检测 + 自动重试 | 自动流水线核验失败不再一次性落人工：未找到 Editor（`editor_found=false`，无进程开销）→ 每 10 秒轮询共 6 次，装好/打开即自动续跑；启动抛错（`fgui_editor_start_failed`）→ 20 秒退避重试 2 次；最终失败按"未找到/核验不达标"给出可行动的两种错误文案 | `useHifiWorkflow.ts` `runEditorVerification` + `editorWaitConfig`（测试可注入快时钟）；`App.test.tsx` 新增"轮询后自动交付"用例并适配"耗尽后走人工"用例 |
| 变体守卫可见化 | 推导被守卫拦下不再静默退回占位图：评审 warnings 里逐条给出"哪个组件哪个 local id、哪一态、中文原因"（遮罩重合度不足/拟合残差超限/共同像素不足/结构塌缩/空基图），真实会话验证：金币底钉红点后 unlock/gift 是残差超限、new/up 家族是形状不一致 | `hifi_variant_colour.py` learn/apply 增可选 `explain` 出参；`hifi_state_visuals.py` `derive_state_nodes` 第三返回值 `state_variant_guard` warnings（`_GUARD_MESSAGES`）；`workflow._manifest` 并入 manifest.warnings，`build()` 汇入 review.warnings |
| 切图目录记忆 | 新 PSD 源自动沿用上次关联的设计资产根目录（记忆文件 `<psd-sources>/design-root-memory.json`，目录仍存在才采用，幂等、手动 re-link 随时覆盖），新会话免手动关联 | `psd_source_store.py` `link_design_assets` 记忆 + `design_assets` 缺省时 `_adopt_remembered_design_root` |
| GList lineGap 同步（P5 老账） | 行模板定义被 resize 后，实例化它的 `<list>` 的 lineGap（vt）/colGap（hz）按相同比例缩放，保住旧间距节奏；比例变化 <5% 或无 gap 不动 | `hifi_nested.py` `_sync_list_line_gaps`（对比 staged/root 的 defaultItem 定义尺寸，`_resolve_component_reference` 解析引用），挂在 `build_nested_bundle` 的 `_resize_mapped_component_definitions` 之后 |
| occlusion 审计覆盖映射放大（§16 老账） | 旧审计只看新增 `hifi_` 元素盖住受保护对象；现在**被映射（accept/retarget）后放大的元素**盖住受保护对象也会告警（旧皮肤本就叠放的不算），warning 文案改为"新增或放大" | `hifi_patch.py` `_behavior_occlusions(document, inventory, mapping=None)` 增 mapped 分支；`validate_hifi_candidate` 调用传入 mapping |

关于 §16 "无 Old+New 重复 ownership / 无重复 Text" 的架构结论（动这块前必读）：对普通视觉（image/graph/text/richtext）该门槛已由闭包系统结构性强制——每个旧视觉最终必为 REPLACE/RETIRE/REMOVE 之一（被映射图盖住的 graph 还有 0.8 覆盖自动 retire）；`duplicate_psd_pixel_ownership` + `duplicate_figma_mapping` 拦 PSD 源/节点双占；novelty 门槛（新视觉与任何旧盒零相交才 proven）使 add_visual 与旧视觉重叠在数学上不可达。真正可达的残留是"受保护运行时对象被映射放大的视觉盖住"——现为 warning + Editor 核验（有意不 BLOCK，行为对象可能被运行时有意置顶）。

## 2.1 本轮新增（2026-10-05 第二批：切图配对闭环 + 状态族变体推导 + 缩略图）

后端 1656 passed / figma-plugin 270 passed（plugin-harness 5 失败为既有 .venv 环境问题）/ web-console 92，双端 tsc 0。真实会话 98a27b6d… 双演示通过：单对象钉图（138 文件、布局保真）与红点家族钉图（136 文件、13 个状态变体推导）。

| 能力 | 内容 | 关键落点 |
|---|---|---|
| 切图人工配对 | fgui_only（PSD 没画）对象在映射面板从切图池手动选一张设计切图配对（retarget，`figma_node_id=cutout:文件名`），沿用全部既有门禁/审计/撤销 | `psd_source_store.py` `cutout_resource`（物化 `psd-cutout-<sha32>`）、`hifi_replacement_workflow.py` `_manifest` 注入 `hifiCutoutPool` 节点+资源并转发 `variant_sources`、`hifi_mapping.py` 池节点不进 real_nodes / collect_unmatched / `_psd_coverage` 必需集、`hifi_semantic_reskin.py` 归一化双保护（disposition 跳过 cutout: 项 + bundle 宿主候选排除）、`hifi_patch.py` 平铺路径布局改写、`hifi_nested.py` 嵌套路径改写（viewport 偏移）、`fairygui_editor_verify.py` 对比掩码豁免 |
| 状态族变体推导 | 一张切图钉到状态族基态 → 未画的兄弟态按"旧家族颜色关系"从切图基图自动推导新材质 | `hifi_replacement_workflow.py` `_variant_sources`（owned/composite 优先、`cutout:` 分支、psd-layer 兜底）、`hifi_state_visuals.py`（local_object_id 共享键、基态复用、learned 缓存、三守卫：mask IoU≥0.8 / 像素残留≤24 / 方差地板 12） |
| 切图下拉缩略图 | 配对下拉选中即显示 56px 预览（数据 URL） | `psd_source_store.py` `cutout_thumbnails`（`psd-cutoutthumb-<sha32>` 缓存 + base64 PNG）、`api.py` `GET /v1/hifi-sources/psd/{id}/cutouts`、`project-client.ts` `psdCutoutThumbnails`、`useHifiWorkflow.ts` 状态+effect、`HifiMappingPanel.tsx` 预览 |

演示暴露并修掉的三个真 bug（均已用测试锁死）：
1. `_manifest` 收了 `variant_sources` 却没转发给 `derive_state_nodes`——单测直连函数所以全绿，线上是死代码；
2. 变体键误用实例限定键 → 共享实例签名分歧 → 冲突风暴 → 在 `<list>` 子元素上要求不可能的克隆（`hifi_variant_instance_missing`）——改 local_object_id 寻址；
3. 无 size 的 `<image>` 按贴图自然尺寸渲染，更大的新切图会悄悄拉伸对象——cutout 节点改写为旧对象几何（三级兜底：元素 size → 旧对象 size → `_legacy_texture_size` 直查 package.xml）。

关键不变量（动这块代码前必读）：
- 切图是**操作员证据**：绝不做自动候选、绝不受 PSD 闭包约束、绝不被分配器抢占、只换贴图不改程序布局；
- 变体资源键必须按 local_object_id 寻址（否则引爆共享实例冲突检测）；
- `(path, local_object_id) → (c14n preview, material)` 签名必须跨实例一致；
- `_package_resource_index` 只索引组件不索引图片，旧贴图尺寸要 package.xml xpath 直查；
- 用户约定：Figma 插件入口不做；MovieClip 帧族用户侧使用、素材不经 PSD 上传；红点家族等设计师补 1 张新红点切图（放 `D:\P-PVP爬塔\P-PVP爬塔\切图\`；Common_Tag_RedDot 7 状态 / 13 处引用的实物解释图：工作区 `reddot_explain.png`）。

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
python -m pytest D:\project-fixed-policy25\project\tests -q

# 前端（figma-plugin 275 / web-console 87）
# plugin-harness 依赖 Python：仓库无 .venv 时设 FGUI_TEST_PYTHON 指向系统 Python
$env:FGUI_TEST_PYTHON="C:\Users\momoca\AppData\Local\Programs\Python\Python311\python.exe"
cd apps\figma-plugin; npx tsc --noEmit; npx vitest run
cd apps\web-console; npx tsc --noEmit; npx vitest run

# 重建控制台产物
cd apps\web-console; npm run build

# 重启服务（8766）
$env:PYTHONPATH="D:\project-fixed-policy25\project\src"
python -m figma_to_fgui.cli serve --local-app `
  --data-dir D:\project-fixed-policy25\project\.local-hifi-run\data `
  --rules D:\project-fixed-policy25\project
ules\default\classification.yaml `
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
`C:\Users\momoca\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6ac29029e1e6bad9a167adeb\`

上一轮关键脚本：`wire_policy28_closure.py`、`wire_policy28_removal*.py`、`wire_policy28_novelty.py`、`wire_policy28_correction_loop.py`、`fix_semantic_reskin_closure{,2}.py`、`fix_reconcile_gate.py`；诊断：`diag_coverage_session.py`、`diag_begin_pipeline.py`、`diag_normalize_trace.py`（复刻 begin_psd 四阶段流水线，验证修复用）。

本轮（变体推导 / 切图配对 / 缩略图）：变体推导 `wire_variant_derivation.py`、`extend_variant_sources.py`、`fix_variant_{forward,shared_key,apply}.py`、`variant_colour.py`、`replay_variant_derive.py`、`diag_variant_families.py`；切图配对 `impl_cutout_{store,workflow,guards,frontend}.py`、`write_cutout_tests.py`、`fix_cutout_{coverage,e2e_keys,owner_guard,layout_node,layout_node2,natural_size}.py`、`replay_cutout_pool.py`；缩略图 `impl_cutout_thumbs.py`、`impl_cutout_thumbs_frontend.py`、`add_thumb_test.py`、`fix_tsc_cutout_thumbs.py`；演示 `demo_cutout_pairing.py` / `demo_cutout_family.py`（真实会话 98a27b6d…，产物 demo_cutout_preview.png / demo_family_preview.png）；红点解释 `probe_reddot_family.py`、`make_reddot_explain.py`（产物 reddot_explain.png）。

坑：PowerShell 多行 python -c 引号会被吞→写脚本文件；HifiMappingItem 的新增 wire 字段在测试里必须显式给（Strict 模式）；测试断言改动后先用探针脚本跑事实再改断言。

## 7. 下一步（新会话的待办）

1. **用户继续网页实测**（优先）：删除评审面板现在带旧视觉实物预览（纹理或红框区域图）——重点验证这个决策体验；fgui_only 对象走映射面板"切图"下拉（带缩略图预览）人工配对；切图目录对新 PSD 自动沿用，无需手动关联。红点家族（Common_Tag_RedDot，7 状态、13 处引用）等设计师补 1 张新红点切图放进 `D:\P-PVP爬塔\P-PVP爬塔\切图\`——钉一次即可全家族换肤；实物解释图见工作区 `reddot_explain.png`。
2. Editor 核验若因未开 Editor 失败：流水线会每 10 秒自动检测共 1 分钟，期间打开 Editor 即自动续跑；MovieClip 帧族属用户侧流程；Figma 插件入口按用户约定不做。
3. 已知待观察：动 §2.1/§2.2 相关代码前先读其中的不变量与架构结论清单；变体推导被守卫拦下的原因会出现在评审 warnings（`状态族变体推导被守卫拦下：…`）；配对/推导出问题先跑工作区 `replay_variant_derive.py` / `replay_cutout_pool.py` / `diag_variant_families.py` 复现事实再改；本 §2 热修的和解逻辑只救"语义处理过的组"的 raw bundle，若再掉叶用 `diag_begin_pipeline.py` 同法定位。
4. 可选后续：列表行实例若带显式 size 属性，模板定义 resize 后实例渲染尺寸不变（FairyGUI 按实例 size 缩放定义）——lineGap 同步以定义尺寸为准，若实测发现行高未变而 gap 变了，需改用实例尺寸信号；§16 行为对象遮挡仍为 warning（有意），若 Editor 核验频繁因此失败再评估升级为 BLOCK。

## 8. 新会话开场白（复制给新会话即可）

见下方对话消息——直接粘贴用户侧开场白。

## 2.3 本批新增（2026-10-05 第四批：流程可见性 + 切图池细分 + 评审去重 + 界面简化 + 视觉修复）

**① 流水线进度条**：`useHifiWorkflow.ts` `AUTO_PIPELINE_STEPS=6` + `autoProgress{step,total,label}`；
`setPipelineStep` 推进、`refinePipelineLabel` 只改文案（Editor 轮询/重试倒计时）；等待删除评审时保持可见。
`App.tsx` 渲染 `.hifi-pipeline-progress`（done 绿 / current 条纹动画，`workspace.css`）。

**② 切图池细分**：切图目录通常混装多个 PSD 的导出。`psd_source_store.cutout_families(psd_name, names)`
纯函数：签名归一（去空格/连字符）→ 最长公共前缀在 `_` 边界切分聚类（成员直接延伸当前前缀时并入，
见 `fix_family_extend`）→ 相关度三档：`this_psd`（签名以 PSD stem 或其去 `P_` 变体开头）/
`shared`（通用/公共/common/shared 前缀）/ `other`。`cutout_thumbnails` 返回四元组
(name, thumbnail, family, relevance)，`/cutouts` 端点带出；映射面板配对下拉按
「本 PSD 切图 / 通用切图 / <家族> · 其他 PSD」optgroup 分组，混池时显示选用提示。
真实池验证：48 张 → 6 家族（PVP爬塔 33 / P_PVP爬塔 6 / PVP塔 4 / P-PVP塔 2 / 通用 2 / 爬塔币 1），
this_psd 4、shared 2。

**③ 删除评审去重**：`hifi_removal_review.py` 同共享模板的多处实例合并为一组
（key=`template:<local_id>`，`merged_template=True`，区域标签「共享模板 X · N 处实例」），
成员带 `location`（instance_path › local）；客户端解析 + 面板位置徽标；映射面板对
REMOVE_CANDIDATE 未决策对象显示指路提示（去删除评审面板决策，或就地切图配对）。

**④ 映射阶段界面简化**：删除线框结构视图（MappingCanvas / 单位与叶子诊断 / 聚焦过滤）与全部死 CSS；
改为「当前对象的样子」双证据：旧 FGUI 对象资源图（`oldPreviewUrl`）+ PSD 合成图带当前对象位置蓝框
（`current.figmaBounds` 百分比 overlay）。决策列表、处理方式、切图配对保持不变。

**⑤ 审核阶段简化**：`HifiReplacementReviewPanel` 删除「对象差异 / 文件差异」几百项清单与
「一键隐藏无 PSD 对应的保留对象」（hook `hideKeptObjects` 一并删除；后端 keep_old+retire 能力保留但 UI 不再暴露），
改为「候选核验」：结构保护结论 + 候选哈希 + 指引文案（直接看 Editor 预览比对后交付）；
保真度卡只列「与效果图不符」的切图单位（含对比按钮），全过则显示 ✓ 汇总。
Editor 检查区（自动截图 + PSD 对齐预览 + 三项勾选）与交付/下载按钮不变。

**视觉修复（用户实测三问题）**：
- 脏边缘 = 硬投影烘焙：PSD「矩形 1183」带 size=0 的纯黑 DropShadow，被 `composite_visual_effects`
  烘进精灵形成底部 alpha≈74 黑带。方案 A：`_is_hard_shadow`（DropShadow 且 size==0）在
  `layer_viewport` 扩边与合成时跳过；`fidelity_metrics(exclude_boxes)` + workflow
  `_hard_shadow_exclude_boxes` 在保真比对排除阴影带。修复后按钮纹理 374×77→371×72、无黑带。
  `composite_hard_shadow` 死代码与其测试已删。
- 中心点偏移 / 内外层不一致 = 变体框架未重锚：隔离变体保留旧定义框架（325×75、pivot 0.5,0.5），
  子对象按「PSD 全局−旧实例 xy」写入，帧中心与视觉中心差 41px（Button 按下缩放绕帧中心），
  编辑器内视图内容挂在框外。新增 `_reanchor_isolated_variants`（build_nested_bundle 内、
  `_resize_mapped_component_definitions` 之后）：单实例链定义（`__hifi_` 克隆或私有定义；
  共享非变体与目标根组件除外；resize 策略与带 gearXY/gearSize 的实例保守跳过）→
  实例 xy/size = PSD 内容节点（叶子并集）在属主帧的位置/尺寸、定义 size 同步、
  全部子对象（含 gearXY values）统一平移 delta=旧−新，页面渲染位置不变。
  真实会话验证：n30_gm65 (59,776)→(22,734) 375×72、loader 帧内 (1,0)。
- 关系锚点警告（relation->n46_hhx9 等）仍保留为 Editor 核验闸，未静默。

**质量稳定化**：5 处默认 NEAREST 重采样改 LANCZOS（state 变体 resize、切图采纳 resize、
比对 downsample×2、effect crop resize），消除尺寸不一致时的锯齿边。

**计数**：后端 1657 通过 / 4 跳过；web-console 87 通过；figma-plugin 275 通过
（此前 harness 5 失败确认为环境缺 .venv，设 `FGUI_TEST_PYTHON` 指向系统 Python 后全绿）；
`npx tsc --noEmit` 0 错误；

## 2.4 第五批（2026-10-06：映射页去重精简 + 中断构建自愈 + gearXY 一致性）

用户实测反馈：映射页与删除评审功能重复、PSD 证据图糊、文案赘余、工作台未删、
以及服务重启后会话永久卡 `building` 报“请求与当前状态冲突”。本批修复：

- **中断构建自愈**：`HifiReplacementStore._active_builds` 进程内登记；`mark_building`
  发现 `status='building'` 但本进程无在跑构建时回收槽位（服务重启即此情形），
  真并发仍报 `hifi_build_in_progress`。客户端透传该码及 `stale_mapping`、
  `hifi_removal_review_empty` 等，`decideRemoval` 遇版本冲突自动刷新映射与评审后提示重试。
- **映射页重构**：删除「组件对齐工作台」外壳（审计摘要、待确认/全部页签、258 项清单、
  分页导航）；只保留待决策队列（REMOVE_CANDIDATE 交由删除评审一次处理，不再两处出现）；
  证据图改为 `composite-crop` 原生分辨率裁剪（新增端点 + `psdCompositeCrop`），不再整图缩放下糊图。
- **删除评审**：intro 精简为两句；每组附 PSD 同位置裁剪图（应无对应内容的直接证据）。
- **gearXY 一致性**：patch writer 改写映射对象 xy 时同步平移其 gearXY 各控制器页值
  （`_shift_gear_xy`），消除换页回跳；校验器对“gearXY 随 xy 均匀平移（±1 像素舍入）”
  做归一化（`_uniform_gear_shift`），非均匀漂移仍按 `hifi_protected_structure_changed` 拦截。
  真实会话 3108da9a… 借此通过构建并进入 review_ready。
- **设计资产卡细分**：manifest 增加派生字段 `cutout_groups`（家族×相关性计数），
  旧档读取时自动补齐；指纹改哈希稳定子集，渲染缓存不受影响；设计资产卡展示
  本 PSD / 通用 / 其他 PSD 计数与家族 chips。

**计数**：后端 1660 通过 / 4 跳过；web-console 88 通过；figma-plugin 276 通过；
双端 tsc 0；dist `index-BFD9aewi.js`；服务 8766 已重启，真实会话验证 review_ready、
`/composite-crop` 200。
dist `index-B74fPxRt.js`；服务 8766 已重启并验证（/cutouts 带 family+relevance）。

## 2.5 第六批（2026-10-06：三视觉问题真因修复——脏边缘/中心点偏移/外内不一致）

用户实测"脏边缘、中心点偏移、外层和点进去不一样依旧存在"。深取证发现上一轮"验证通过"
不可信的教训：保真度门禁整链曾静默失效（effect_crop 视口错配→except 吞掉→指标全 null→
面板显示"无失败"），此后先修门禁再谈验证。本批在 Fix A/B/C（视口换算/变体框归一化/
真值颜色替换）之上补齐三个真缺口，全部以真实会话像素级取证实证：

- **关系门禁豁免（外内不一致收口）**：`_normalize_variant_frame` 删除的 frame-relative
  relation（空 target，如 center-center）会被 `hifi_protected_structure_changed` 拦死。
  `validate_hifi_candidate` 新增 `_variant_isolation` 豁免通道（hifi_nested 的变体调用
  传入）：变体定义中空 target relation 的**删除**按严格子集语义（只容删、不容增改，
  `_frame_relation_keys`/`_drop_frame_relations`）在受保护比较前从双侧剥离。
- **真值页接入兜底渲染器**：`render_owned_visual` 遇复杂混合走 psd-tools 合成器兜底时
  `_flatten_hybrid` 没传 `truth_page`（provenance 停在 flatten_hybrid/engine，颜色修复
  对这些组完全失效）。兜底路径现在传真值页并输出三态 provenance（flatten_effect）。
- **负视口钳位（rank/record 图标）**：所有权视口常越出画布（花纹层 x=-22、效果外扩
  y=-25），旧门禁 `left<0 or top<0` 直接拒绝整个真值替换。改为钳位到画布内裁剪并贴回
  视口框架，画布外由 covered mask 保持引擎像素（Photoshop 自家导出同样裁掉画布外）。
- **relation 清理无条件化**：`_normalize_variant_frame` 的 frame-relative relation 删除
  与位移解耦——变体框已贴合内容时（早退路径）也删锚点，否则早退变体（如 Btn_Primary
  的 n6_r29p）运行时 center-center 会把改写过的子对象拉回旧布局。

**实证（真实会话 3108da9a… 重建，非单测）**：
- 中心点偏移：`Common_Btn_IconText__hifi_e24bb8d…` 框 184×152（内容 135×104@(39,40)）
  → 135×104 origin(0,0)；IconText/Tab/Enter/Primary 全部变体框==可见内容并集，
  实例 xy/size 与变体框一致。
- 颜色/脏边缘（对效果图逐像素）：rank 图标 meanDiff 128.9→**0.57**、record 67.1→
  **1.29**、challenge 41.7→**9.84**、noble 按钮非文字区→**0.21**、merit→**0.56**
  （文字区差异为 FGUI 运行时画字，精灵按保留文本挖空，属正确行为）。owned-visual
  provenance 分布 flatten_effect 18 / flatten_hybrid 78 / engine 137（含旧缓存键残留）。
- 外内不一致：normalize 覆盖的变体 relation 泄漏清零；残留 relation 均为"子对象未改写
  的遗留自洽"（Btn_Icon×2 仅做 RedDot 重定向）或"仅父容器 resize 时触发的遗留锚"
  （Window_MainUI 标题/Tab，全屏固定窗口不触发）或惰性 group 节点，按原样保留。
- 诚实失败项：window_title 留 engine 色——所有权分区 retained 含非文本兄弟（fail-closed
  设计）且整体为半透明软边艺术；masked_or_clipping / outside_canvas 人工核验项在
  warnings 里如实列出，不再宣称全过。

**计数**：后端 1663 通过 / 4 跳过（新增 3 个回归测试：变体 relation 豁免端到端、负视口
钳位、兜底真值替换）；figma-plugin 276（harness 需 `FGUI_TEST_PYTHON`，单文件跑加
`--testTimeout=60000`）；web-console 88；双端 tsc 0；dist `index-BFD9aewi.js`；
服务 8766 已重启。渲染缓存键由渲染器源码哈希派生（`render_cache_version`），真值/钳位
修复自动失效旧 owned-visual 缓存，无需手动清。

## 2.6 第七批（2026-10-06：核验项闭环——设计师效果图成为机器核验基准）

用户指令"window_title / masked_or_clipping / outside_canvas 不能放着，也得处理"。本批把
"留人工核验"的三类警告全部转为机器核验，基准是设计师效果图（最强参考）：

- **真值核验主通道**（`hifi_replacement_workflow.py` `_lossless_evidence_impl`）：每个
  bundle 先尝试与 `effect_crop_path` 的真值裁剪比对（mean≤6/max≤96/离群≤1%）。三种模式：
  密集 bundle 直接比对（半透明边缘跳过、计入覆盖率）；半透明 bundle（半透明像素 >30% 且
  铺满）先 psd-tools 合成"组以下底栈"、把 bake 压平上去再比（**这就是 window_title 的
  正确比法**——实测非 retained 区 mean 1.56，引擎渲染本来就是对的，上轮报"失败"是取证
  方法错误）；稀疏 bundle（painted<50%）只比不透明核心、免 bounds 排除、void/fringe
  不计覆盖率。失败的 bundle 回落旧的 psd-tools 合成比对（无损语义）。
- **±1px 亚像素对齐重试**：编辑器整数放置与栅格 painted bounds 各自取整，允许以
  `align(+0,-1)` 等标注记录 1px 取整差后判通过（merit 按钮 round vs floor 实证）。
- **truth_verified 证据**（`psd_lossless_evidence.py`）：`verified_leaf_ids` 让对应
  bundle 的全部叶子记 proven（"经设计师效果图真值逐点核验"——比逐层导出等价更强的证明），
  同时清除这些叶子的 outside_canvas 残留。真值失败的叶子照旧人工核验（诚实失败）。
- **排除与覆盖语义修正**：`extra_exclude` 改子树感知（中间组含 owned 叶子时不再把整个
  bake 从比对中抹掉——此前 rank/record/shop/challenge 全部因此 count=0 假失败）；
  `probe_bundle_against_composite` 新增 `excluded_counts_coverage`（retained 盒不计
  覆盖率）、`fringe_counts_coverage`（稀疏免计）、`void_counts_coverage`（透明 void
  非 bundle 领地、不计覆盖率——record 差 34 像素卡 35% 红线的根因）、`outlier_tolerance`
  （JPEG 锐边振铃单像素不再一票否决）。

**实证（3108da9a 重建）**：六类无损证据全部"已机器核验"——layer_effects 8 层、
pixel_layers 全部 bundle、shape_styles 47 层、outside_canvas no_out_of_canvas_content、
合成比对通过（truth371x72 mean0.022 / merit align(+0,-1) 0.062 / rank 3.509 / record
0.043 / shop 1.866 / challenge 0.295 / 标题图标 424x64 1.528 / 131x135 0.000）。
残留警告均为真正需要 Editor 实机的运行时行为项（状态/交互/gear/relation-drift）。

**计数**：后端 1666 通过 / 4 跳过（新增 3 个测试：truth_verified 叶子+outside 清除、
排除盒免计覆盖率、void/outlier 语义）；前端无改动（figma-plugin 276 / web-console 88 /
dist 沿用今早构建）；服务 8766 已重启。

## 2.7 第八批（2026-10-06：脏边缘真因 = 代理 graph 撑大 variant frame；UI 单一路径化）

用户实测截图：Challenge 按钮左右竖直脏边带、圆形返回按钮外方形光晕。对最新产物
（1baf49fb，23:03）像素取证：整幅底图 bake（`___749` 1092×2457）在所有按钮区域 100%
不透明——底图自带全部按钮 artwork；按钮组件又自贴 sprite，两者**错位数像素**时底图副本
从 sprite 边缘露出 = 脏边。错位来源：`_normalize_variant_frame` 的可见子对象并集把
**无 fillColor、无描边的透明代理 graph**（如 Common_Btn_Primary 的 `autosize_provt`
402×132）计为视觉内容 → frame 412×140 ≠ sprite 原生 403×135 → 实例落点偏离 PSD 位置
(-9,-5)。对齐时底图副本与 sprite 像素完全重合（不可见），错位时才露边——这就是此前
颜色/真值/框内容修复都未触及的独立机制。

- **修复**：`hifi_nested._is_layout_proxy`（graph 且 fillColor 缺省/alpha=0 且无 lineSize）
  在 frame 并集中跳过代理 graph。实证：challenge 实例 (662,1762,403,135) == PSD plate
  视口；record 实例+loader 偏移 = (53,1599) == PSD；title (0,216)/(26,217) == PSD。
- 旧灰底 `bg_common_gary` 经核查仅 isGray 页可见（gearDisplay pages=1），非常态页脏边
  来源，未动（保留禁用态视觉）。
- **UI 单一路径化**（用户反馈按钮重复/文案冗余）：删除评审页=每组“本组处理”分段选择
  （移除/保留，选中高亮）+ 唯一主按钮“确认并继续（N 组）”；映射面板无待确认项时不再
  渲染回声文案；步骤头按状态三选一（删除确认中 / 生成中“无需操作” / 待确认计数），
  生成期（step≥3）隐藏返回与手动生成按钮；过期 autoResolveNote 横幅在删除确认期间
  抑制、进入生成阶段清空。
- **计数**：后端 1667 通过 / 4 跳过（新增 proxy frame 测试）；web-console 88；
  figma-plugin tsc 0；dist `index-cMnFV3BO.js`；服务 8766 已重启。

## 2.8 第九批（2026-10-07：脏边缘终极真因 = 人造羽化环；硬边 alpha + 反预乘 plate 定案）

第八批对齐修复后用户实测仍有脏边。环区指标取证（sim=底图叠 sprite vs 设计师效果图）：
方案 1（羽化 ramp）下 challenge 环带 meanDiff 30.78 / circle 47.48，远超 ≤6 阈值 → 按既定
策略升级方案 3；方案 3 首版（U=引擎叠背景）仍 30.9/31.8 → 像素级 dump 钉死两个事实：

1. **底图 bake 在按钮区域只有背景**（木纹 (58,28,12)，无按钮 artwork、无阴影）——
   “底图双绘露边”机制不成立，运行时按钮视觉 = 背景 bake ⊕ sprite 单层；
2. **设计师效果图自身是硬边**（环带像素与核心同色 (110,135,96)，无 AA 坡）——此前所有
   “羽化/坡重建/薄特征保护”都在制造效果图里不存在的 2px 半透明带：运行时背景从该带
   透出 = 钝色/发暗描边，即用户看到的脏边缘。引擎黑色阴影尾同理：其颜色是引擎黑而非
   设计师阴影色。

**定案配方**（`psd_effect_render._flatten_hybrid` 尾部重写）：
- alpha = 引擎 alpha 原样（硬边核心 + 效果尾部的真实半透明），删除全部人造 ramp/
  feather/fringe 逻辑；
- 颜色门限 = covered − polluted（真值模式）：真值色覆盖所有非污染像素（含阴影尾）；
- `_solve_plates` 逐像素反预乘：`plate = (T − (1−a)·bg)/a`，bg = 轮廓外真值背景色经
  **金字塔孔洞填充**（log 尺度加权均值，可达任意深度；3px 膨胀对大面积半透明板不够）；
  a=1 时退化为 plate=T；无外部种子时原样返回（fail-closed）。
- 运行时合成恒等式：`a·plate + (1−a)·bg = T`，逐像素复现效果图。

**指标**（重建 3108da9a 后）：challenge 环带 meanDiff 30.90→**1.52**、core 9.67
（文字区诚实差异：贴纸不带字、运行时写 PSD 同款文字）；circle 环带 31.77→**3.18**、
core **0.00**。边缘像素 α255 且色值与真值逐点相同；半透明尾 = 设计师阴影色反解。
sprite 尺寸含效果尾margin（403×135 / 131×135）属正确行为。

**n30_gm65 删除评审定性**：n30 是旧按钮内黄色占位 rect（fillColor #ffffcc00），其视觉
职责已被变体 loader 的全框 sprite 接管；PSD 目标态无对应黄色块 → REMOVE_CANDIDATE
判定正确。Panel_Tower_Main 上 target="n30_gm65" 的 relation 由移除决策同步闭合，非匹配
失败。

**计数**：后端 1670 通过 / 4 跳过（羽毛三测试改写为硬边语义：引擎 alpha 保留+阴影尾
反解、均匀半透明板 plate 反解、硬边真值不造环；fallback 尺寸回归 1×1）；前端无改动；
服务 8766 已重启（渲染缓存键随渲染器源码哈希自动失效）。

## 2.9 第十批（2026-10-07：入口多对多匹配 + 批次化审核 + 合并导出/写回）

用户需求：一个 FGUI 工程含 N 个待替换 panel，一次任务上传多个 PSD、指定一个切图文件夹
（所有 PSD 的切图自动定位）、以「1 PSD ↔ 1 panel」为一组逐组审核、全部批准后才进入导出、
导出二选一（写回原 FGUI 工程 / 手动下载合并包），不再自动下载。

**后端**
- `psd_source_store.scan_design_assets(psd_name, root, cutout_dir=None)`：切图目录可显式
  指定（不再硬编码「切图」）；`link_design_assets(..., cutout_dir)`；设计根记忆同时记
  cutout_dir，`_adopt_remembered_design_root` 一并套用。
- `hifi_project_inspector`：组件选项新增 width/height（component xml 根属性），供匹配打分。
- 新表 `hifi_batches`（batch_id/owner/project_id/fingerprint/source_ids/design_root/
  cutout_dir/status/warnings_json/artifact 三元组/writeback_json）+ `hifi_replacements`
  新增 `batch_id` 列（PRAGMA 迁移）；store 新增 begin_batch/get_batch/batch_sessions/
  attach_batch/set_batch_warnings/set_batch_artifact/set_batch_writeback。
- `workflow.match_suggest`：尺寸比例（1x/2x/0.5x，2%/5% 容差）0.5 + 名称 token 0.3 +
  切图文件名族 0.2 打分，贪心给出一对一 suggested 标记；`begin_batch` 逐对 link 资产 +
  `begin_psd(batch_id=...)`，单对失败记 warnings 不阻断整批；`batch_view` 汇总组状态与
  export_ready（全部 approved）。
- 合并导出：`_session_bundle(current, root)` 从 build() 抽出（build 改为调用它）；
  `build_combined_package` 在 staged 副本上按组顺序重放 bundle（共享 package.xml 的
  before-hash 因此自洽），`project_package.diff_project_trees` 字节差异汇总成单一
  ChangeBundle 后 `build_project_package` 出合并 zip；`writeback_batch` 校验本机目录
  指纹 == 批次指纹（`agent.fingerprint_local_project`）后对原工程目录一次性
  `apply_bundle`（事务+备份+回滚），记录 backup_dir/changed_paths；批次下载端点重算
  sha256 校验。闸门：`hifi_batch_not_export_ready` / `hifi_batch_not_packaged` /
  `local_project_missing` / `local_project_changed`。
- 端点：`POST /v1/hifi-batches/match-suggest`、`POST /v1/hifi-batches`、
  `GET /v1/hifi-batches/{id}`、`POST .../package`、`POST .../writeback`、`GET .../download`。

**前端**（web-console）
- prepare：PSD input multiple + 多 PSD 清单 + 切图文件夹路径输入；「多 PSD 批量配对」入口。
- 新页 matching（HifiBatchMatchingPanel：候选下拉默认 suggested、reasons 可见、可改配）
  与 groups（HifiBatchGroupsPanel：组卡片状态 chip、已批准 X/N、进入审核/返回批次、
  export_ready 才渲染导出区：构建合并包/手动下载/写回原工程+备份路径展示）。
- Stage 扩展 matching/groups；组内复用既有 mapping/review/delivered 子流程。
- **自动下载全部移除**（runAutoPipeline 第 6 步与 approve 内），仅保留手动下载按钮。

**计数**：后端 1675 通过 / 4 跳过（新增 test_hifi_batches.py 5 例：cutout 覆盖、批次
store 往返与归属隔离、diff_project_trees 往返 apply、合并/写回闸门、batch_id 挂接）；
web-console 101 测试（含 Matching/Groups 新组件与“approve 不自动下载”断言）；figma-plugin
276；双端 tsc 0；dist `index-D1hXXr0B.js`；服务 8766 已重启。


