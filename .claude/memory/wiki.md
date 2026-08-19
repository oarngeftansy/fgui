# Wiki — 当前项目事实

## 仓库与分支

- 工作树：`C:\Users\momoca\Documents\figma转fgui\source\.worktrees\uir-v1`
- 当前分支：`codex/uir-v1`
- 2026-08-18 完成的核心修复提交：`4a251ea4d2d76395242fe4f424fce920110065da`（`fix: close generation plan integrity gaps`）。
- `origin` 当前是本机恢复仓库 `C:\Users\momoca\Documents\figma转fgui\_recovery_repo`，不是公网 GitHub 远端。

## 已完成的通用管线

- Figma 插件选择数据和 REST 数据可进入规范化层。
- 已建立严格、可序列化且可验证的 UIR v1。
- 已建立 FairyGUI 通用能力分析与 FGUI Plan 编译/验证。
- 已覆盖基础容器、文本、图片/矢量资源、组件引用、有限的矩形/圆角/图片遮罩、九宫格事实和安全 PNG 降级。
- 资源具有逻辑身份、内容哈希、导出参数哈希、MIME/格式、尺寸、消费者和降级理由。
- UIR/Plan 不允许混入目标 FairyGUI 工程真实 ID、私密字段、本地路径或原始秘密数据。
- 复杂能力不能被可靠表达时会阻断，而不是生成表面成功但失真的结果。
- 已重建插件实际加载的 `apps/figma-plugin/dist/code.js`，并验证与 fresh build 字节一致。
- 组件映射需求模板位于 `docs/templates/`，其中 JSON 是候选格式，不是已经验证的生产映射。

## 最近一次完整自检证据

- Python：`749 passed, 2 skipped, 0 failed`。
- Python focused：`355 passed`；golden：`5 passed`。
- Ruff：通过。
- mypy：48 个源码文件，0 error。
- Figma 插件 Vitest：`162 passed`。
- TypeScript：通过。
- 插件可复现构建/打包检查：`5 passed`。
- 已安装 CLI 的 `build-uir → build-fgui-plan → parse/validate` 冒烟验证成功，`bindable=True`。
- 详细报告：`.superpowers/sdd/final-fix-report.md`。

## 2026-08-18 FairyGUI 6.1.4 Writer 方言证据

- `tests/fixtures/fgui-editor-6.1.4/minimal/` 是从已由 FairyGUI Editor 6.1.4
  打开并保存的 `FairyGUI-project3` 提炼的项目中立最小格式证据；不包含村庄或其他业务资源。
- 新建工程方言常量为 `FAIRYGUI_VERSION="6.1.4"`、`PROJECT_SUFFIX=".fairy"`、
  `ASSETS_DIRECTORY="assets"`；`parse_editor_fixture` 通过唯一工程标记、唯一包清单及其组件 XML
  识别编辑器夹具。
- Task 1 评审修复后，方言 fixture parser 会严格验证 marker/package/component 根与结构、
  observed marker `version="5.0"`、Unity target、ID 唯一性，以及资源 package-virtual POSIX
  路径、package-root 边界和 symlink/reparse point。资源路径允许单个 leading `/`；组件 XML
  `name` 可选且不定义组件身份；`publish` 只验证唯一的空元素结构，不猜测属性语义。
- Task 1 修复自检：`794 passed, 3 skipped`，Ruff 和 mypy 通过。
- 2026-08-19，中立化后的最终 `Minimal` fixture 已通过 FairyGUI Editor 6.1.4 两次保存、
  中间关闭重开的 GUI gate；无 repair/migration modal，三个 tracked fixture 文件保持字节一致。
  Editor `.objs/` 缓存已删除并由 fixture-local `.gitignore` 排除。

## 尚未实现的边界

- Writer Task 4 已实现资源 payload 输入门：它要求 Plan/resource payload 精确键集合、流式 SHA-256、
  Pillow 实测的 PNG/JPEG/WebP 格式/MIME/尺寸和九宫格边界完全一致；截断图和解压炸弹会拒绝，
  Writer v1 明确拒绝 SVG。Pillow 探测在受控子进程完成，父进程不修改 Pillow 全局状态；失败仅输出
  排序后的公开诊断，且不会包含资源字节。

- 尚未实现通用 FGUI XML Writer，因此当前 Plan 还不是最终可导入的 FairyGUI 工程。
- FGUI Plan 已升级为 schema v2，组件引用必须通过 `definitionRef` 闭包到 Plan 内的完整
  `componentDefinitions`；无组件引用的严格 v1 可显式迁移，包含组件引用的 v1 必须重新编译。
- Plan v2 定义局部树与定义引用图的 256 层边界均从实际 root 用迭代 DAG 最长路径计算，
  不依赖逻辑 ID 排序；reviewed component→raster fallback 会按最终 decision 安全消费后代，
  并在最终所有权确定后抑制已被外层 fallback 消费的内层 raster MaskPlan/专属资源 consumer；
  mask 最终还必须闭包到实际 emitted node target，blocked/definition-missing/不可发射祖先下不保留
  orphan mask/resource；不可栅格化行为后代继续阻断。评审修复后全套为 `819 passed, 3 skipped`。
- 当前 UIR v1 的组件定义只有来源/名称/属性元数据，没有独立可生成节点树；因此编译器不会把
  verified candidate 猜成组件定义。缺少完整定义时只接受上游明确批准的 PNG raster fallback，
  否则以 `fgui.component.definition_missing` 阻断。
- 尚未完成真实 FairyGUI 6.1.4 的新建工程加载验收。
- Controller、Gear、List、复杂 Auto Layout、不可表示的 transform/rotation 和复杂 RichText 目前按规则阻断。
- REST 路径对遮罩比实时插件路径更保守；歧义遮罩会阻断。
- “更新已有工程”的 Project Binding、existingResource 复用/所有权语义属于后续可选能力，不应阻塞新建工程主流程。

## 下一阶段：通用 XML Writer

目标：仅消费已经验证且 `bindable=True` 的 FGUI Plan，创建全新的 FairyGUI 工程，不依赖已有工程扫描。

建议顺序：

1. 先写 XML Writer 设计规格，明确稳定 ID、目录布局、坐标/层级、文本、图片、遮罩、九宫格和资源所有权。
2. 定义 `NewProjectConfig`（工程名、包名、目标 FairyGUI 版本/Unity 目标等），不得把真实目标 ID反向写入 UIR/Plan。
3. 测试驱动实现确定性的 `package.xml`、组件 XML、资源目录和 ZIP 输出。
4. 写严格的引用、XML schema/结构、资源哈希和路径安全校验；校验失败不得提供成功下载。
5. 用最小通用 fixtures 先验收，再用“村庄升阶”作为非特化回归样例。
6. 最后用 FairyGUI Editor 6.1.4 实际打开生成工程，记录截图和差异；必要时再补通用映射规则。
7. 完成新建工程后，再独立设计可选的“更新已有工程/Project Binding”阶段。

### 2026-08-18 已批准的 Writer 设计决策

- 新建工程正式产物是可由 FairyGUI Editor 6.1.4 直接打开的完整工程 ZIP。
- 第一版每次生成一个工程、一个包；每个 Plan root 是一个顶层组件，共享资源和自包含组件定义位于同包。
- Writer 输入为 `Validated FGUI Plan + NewProjectConfig + AssetPayloadSet`。
- 采用 `NewProjectManifest` 两阶段架构；它只为新工程确定性分配 ID 和路径，不是 Project Binding。
- `componentReference` 必须引用 FGUI Plan schema v2 中完整可生成的自包含组件定义；Writer 不从 candidate 名称猜组件。无组件引用的 v1 可显式迁移，其他 v1 必须重新编译或安全降级。
- 需求方 7 项通用组件映射仍是 candidate 需求数据，不包含组件定义；新建模式下缺少定义时只能按安全 raster fallback 或 unsupported 处理。
- 设计规格：`docs/superpowers/specs/2026-08-18-new-project-fgui-xml-writer-design.md`。
- 已批准规格的实施计划：`docs/superpowers/plans/2026-08-18-new-project-fgui-xml-writer.md`，共 10 个 TDD 任务；第一任务先用真实 FairyGUI Editor 6.1.4 锁定工程方言。

## 新会话启动方式

新会话先读取：

1. `.claude/memory/{memory,wiki,learnings}.md`
2. `docs/superpowers/specs/2026-08-17-universal-uir-design.md`
3. `docs/superpowers/specs/2026-08-17-generic-fgui-generation-plan-design.md`
4. `.superpowers/sdd/final-fix-report.md`

然后从“新建工程模式的通用 XML Writer 设计”继续。不要先做 Project Binding，也不要为村庄升阶写特例。
