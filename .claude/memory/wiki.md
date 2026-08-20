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

## Writer 实现状态与保留边界

- 最终安全收口后，Pillow probe 使用绝对 Python/绝对脚本、`-I`、可信 cwd 和
  最小 Windows 环境 allow-list，不继承 PYTHONPATH 或秘密；恶意 CWD `PIL` shadow 不会执行。
  资源编码字节限制为单文件 64 MiB、构建合计 256 MiB，目录加载和内存 payload gate
  均在 probe 前 fail closed。Editor 门禁的机器可读证据位于
  `docs/validation/2026-08-18-fgui-6.1.4-new-project-editor-transcript.json`。最终全套为
  `1072 passed, 4 skipped`，Ruff 通过，strict mypy 56 个源码文件通过。
  合计 payload cap 在每个文件读取时传入剩余预算，并在保留实际 bytes 前复验；
  精确边界允许，stat 后增长超出剩余预算时 fail closed。机器可读 Editor transcript
  由 golden 测试重建确定性 ZIP 后对精确成员闭包逐项重算 SHA-256。

- Writer Task 10 自动化验收已收口：通用工程 ZIP 以固定 SHA-256
  `bf62cd2789a7d0a44336e28a4c257d4fe91bee34c7673738bdf3f0662217c4ca` 作字节级
  golden，安全回归覆盖路径逸出/绝对路径、重复与 casefold 成员、symlink ZIP
  成员、DOCTYPE 和非法图片；失败不发布。村庄样例仅通过通用映射输入进入
  UIR/Plan，并因 UIR v1 无可生成组件树以 `fgui.component.definition_missing`
  在 Writer 之前 fail closed；无页面特例，无 Project Binding。完整自检为
  `1061 passed, 4 skipped`，Ruff 通过，strict mypy 55 个源码文件通过。单一中立代表
  `GenericWriterFixture` 已在 FairyGUI Editor 6.1.4 完成打开、保存、关闭、重开、
  再保存与关闭；未观察到 modal，4/4 声明文件保持字节哈希一致。

- Writer Task 9 已实现新建工程 CLI：`fgui-tool build-fgui-project PLAN CONFIG ASSET_DIRECTORY
  OUTPUT_DIRECTORY`。CLI 仅接受严格、可绑定的 Plan v2 和 `NewProjectConfig`，通过闭合
  asset manifest 加载资源，拒绝未声明文件、绝对/穿越路径、Windows casefold 冲突、
  symlink/reparse 和非普通文件；成功结果不暴露本地路径，失败不发布 ZIP。中立端到端
  fixture 已验证 ZIP 可重开，未引入 Project Binding、需求方映射硬编码或村庄特例。
  审查收口后，Plan/config/asset manifest 会拒绝重复 JSON key；Plan/config 还要求 exact builtin header
  与 canonical bytes。资源使用 handle/path identity 和前后元数据复验、link/reparse component 检查及闭包
  快照复验，检测到 swap 即 fail closed。中立 E2E 现含真实 1x1 PNG consumer，连续两次 CLI 构建 ZIP
  字节一致。最终审查又加入 POSIX `st_ctime_ns` 与跨平台最终内容摘要复读；Windows 不把创建时间误作变更时间。
  Task 9 自检：focused `39 passed`，全套 `1052 passed, 4 skipped`，Ruff 通过，mypy 55 个源码
  文件 0 error。

- Writer Task 8 已实现新建工程五道门与原子 ZIP 发布：输入 payload、Manifest、XML/file closure、落盘目录
  重开和 ZIP 重开全部通过后，才以 `os.replace` 发布。目录/归档门拒绝 link/reparse、未声明文件、路径
  traversal、重复或 Windows casefold 冲突成员、Unix symlink/special mode、CRC/资源哈希/XML 引用错误；
  ZIP 元数据与排序固定，重复构建字节一致。评审修复后所有 public build error 均切断 cause/context 与
  traceback 私密异常链，归档 SHA-256/大小及返回字段在 publish 前确定，临时目录也在最终 `os.replace`
  前清理；cleanup 失败同样走闭合错误并尝试 fd close/tmp unlink，双重清理均被系统拒绝时只保证隐藏 tmp
  从未 publish，不承诺无残留。已有 BuildError 也只提取 allow-list boundary code 并重建静态错误，不信任
  其 diagnostics/cause/context。publish 后不再 read/hash/stat。最终自检为 `1037 passed, 4 skipped`，
  Ruff 与 55 个源码文件
  strict mypy 通过。

- Writer Task 7 已实现 FairyGUI 6.1.4 的纯内存 XML serializer 与独立 XML/file-closure gate：
  只接受二次 canonical 验证的 `NewProjectManifest` 和匹配的 `ValidatedAssetPayload` 闭包，使用
  lxml 构树并固定 UTF-8/LF、属性/资源/组件顺序、finite canonical decimals；闭合分派覆盖 7 个
  Plan node type，以及组件根上的 rectangle clip、rounded clip、image mask 三条实证路径。
  `package.xml` 闭包覆盖 components/images、same-package component `src/pkg`、loader `ui://`、
  nine-slice 与资源文件；独立 gate 会安全重解析并拒绝 DOCTYPE/entity、未知结构、坏引用、非 canonical
  数字、全局 ID 冲突、Windows casefold 路径冲突和任何未声明/缺失文件。parent-local 几何在 group
  扁平 XML 中累加为 component-local 坐标。golden matrix 覆盖 11 个中立样例。
- Task 7 本机最终回归：focused `64 passed, 1 skipped`；全套 `995 passed, 3 skipped`；
  Ruff 与 54 个源码文件 strict mypy 通过。
- Task 7 原定 11 个对象 fixture 的逐一 GUI round-trip 已根据用户决定缩减：
  11 个中立样例仅声明 serializer/XML golden 自动化覆盖，不声明 11/11 真实 Editor
  通过。真实 Editor 证据限定为 Task 10 的单一 `GenericWriterFixture` 双保存闭环。
  Unity 窗口 state/screenshot API 不受支持，不声明截图或完整 accessibility 审计。
  嵌套 container native mask 因无实证编码继续
  fail closed；三个 native mask 路径当前只在组件根目标上发射。
- Writer Task 6 已实现纯内存 `NewProjectManifest` 编译与验证：输入会重新验证
  Plan bindability/语义和 validated payload 闭包；所有目标 ID 只在 Manifest 层按逻辑键分配并
  复验。定义按依赖拓扑序位于 roots 之前，document tree 与 definition-local tree 使用
  独立 ownership domain；对象保留父级局部几何、children/z-index、visibility、mask scope/order、
  resource consumer 和 raster-consumed UIR refs。Manifest gate 迭代校验路径/ID/所有权/引用/消费者/
  mask/raster/环/深度，公开诊断固定排序且含建议动作；不写磁盘或 XML。
  最终收口后，Manifest standalone gate 会在任何 JSON coercion 前检查 Plan/Config/
  Manifest 的 exact builtin headers，并扫描整个 Manifest 字符串闭包；仅用户可见
  `TextPlan.content`/run content 豁免。`projectName` 同时经过 target-name policy。

- Writer Task 4 已实现资源 payload 输入门：它要求 Plan/resource payload 精确键集合、流式 SHA-256、
  Pillow 实测的 PNG/JPEG/WebP 格式/MIME/尺寸和九宫格边界完全一致；截断图和解压炸弹会拒绝，
  Writer v1 明确拒绝 SVG。Pillow 探测在受控子进程完成，父进程不修改 Pillow 全局状态；失败仅输出
  排序后的公开诊断，且不会包含资源字节。

- 通用 FGUI XML Writer 、新建工程 CLI、五道校验门和原子 ZIP 发布已实现。
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
- 真实 FairyGUI 6.1.4 新建工程加载验收已对单一中立代表工程完成；
  该证据不扩展为所有对象类型的真实 GUI 覆盖。
- Controller、Gear、List、复杂 Auto Layout、不可表示的 transform/rotation 和复杂 RichText 目前按规则阻断。
- REST 路径对遮罩比实时插件路径更保守；歧义遮罩会阻断。
- “更新已有工程”的 Project Binding、existingResource 复用/所有权语义属于后续可选能力，不应阻塞新建工程主流程。

## 已完成阶段：通用 XML Writer

已实现仅消费已验证且 `bindable=True` 的 FGUI Plan 的新建工程链路：
`NewProjectConfig` / payload 验证、Manifest 编译、FairyGUI 6.1.4 XML、五道重开校验、
确定性 ZIP 和 CLI。该链路不依赖已有工程扫描，已通过自动化矩阵和单一中立代表
Editor 双保存闭环。

### 2026-08-18 已批准的 Writer 设计决策

- 新建工程正式产物是可由 FairyGUI Editor 6.1.4 直接打开的完整工程 ZIP。
- 第一版每次生成一个工程、一个包；每个 Plan root 是一个顶层组件，共享资源和自包含组件定义位于同包。
- Writer 输入为 `Validated FGUI Plan + NewProjectConfig + AssetPayloadSet`。
- 采用 `NewProjectManifest` 两阶段架构；它只为新工程确定性分配 ID 和路径，不是 Project Binding。
- `componentReference` 必须引用 FGUI Plan schema v2 中完整可生成的自包含组件定义；Writer 不从 candidate 名称猜组件。无组件引用的 v1 可显式迁移，其他 v1 必须重新编译或安全降级。
- 需求方 7 项通用组件映射仍是 candidate 需求数据，不包含组件定义；新建模式下缺少定义时只能按安全 raster fallback 或 unsupported 处理。
- 设计规格：`docs/superpowers/specs/2026-08-18-new-project-fgui-xml-writer-design.md`。
- 已完成实施计划：`docs/superpowers/plans/2026-08-18-new-project-fgui-xml-writer.md`，
  10 个 TDD 任务均已收口。

## 当前交接状态

通用新建工程 Writer 已完成。下一阶段尚未选择；当前应等待需求方验收或新的
明确计划。Project Binding 仍只是“更新已有工程/复用既有资源”的后续可选模式，
不应在未获得新授权时自行开始。

## 2026-08-20 Writer acceptance Task 1

- 已新增隐私安全的六用例 acceptance runner：TC-01/TC-02/AC-01/TC-03/TC-04/TC-05。
  它经现有 CLI loader、Writer build、archive validator 和通用 mapping→UIR→Plan 路径执行，
  canonical JSON 使用 UTF-8、排序 compact key 与唯一 LF，不记录本地绝对路径、环境值、资源原始字节或异常链。
- AC-01 仅消费 durable Editor transcript 并明确 `guiActionPending=true`；PNG evidence cards、fresh GUI
  action 和最终 acceptance pack 仍由后续 Tasks 2/3 完成。Task 1 focused verification：`15 passed`，
  runner contract：`3 passed`，Ruff 与 `git diff --check` clean。
- 评审修复：TC-05 现将 non-bindable village Plan 真实传入 public `build-fgui-project` CLI，并把实际
  `tc-05-output` 作为 publish argument；它同时记录 definition-missing 与闭合 `PLAN` rejection，再验证零 ZIP。
  village fixture marker scan 已抽取到 `tests/support/village_writer_regression.py`，由 acceptance 与集成回归共享；
  复验 acceptance + village regression 为 `8 passed`，Ruff/mypy clean。
- 直接调用修复：runner 在 import shared test-support helper 前，从自身 resolved file 建立可信 repo/src import
  roots，不依赖 ambient CWD/PYTHONPATH。sanitized-PYTHONPATH subprocess 覆盖 exact `python scripts/run_new_project_writer_acceptance.py --help`
  与最小完整 CLI 运行；acceptance + village regression 最新为 `9 passed`，Ruff/mypy clean。

## 2026-08-20 Writer acceptance Task 2

- 验收 runner 现在能把固定六用例结果渲染成六张本地、自包含的 `1440x1000` HTML evidence cards；所有动态
  文本均经 HTML escaping，卡片不加载网络字体、脚本、图像或其他外部资源，且拒绝私有绝对路径。
- `finalize_screenshot_closure` 在最终模式下要求每个 canonical PNG 引用都存在、具有 PNG/IHDR、精确
  `1440x1000` 尺寸，且将 SHA-256 写回结果；已有 hash 不匹配或任一缺图都会 fail closed。仅明确
  `screenshots_pending=True` 或 CLI `--screenshots-pending` 能在 Task 3 前跳过该闭合，且不会记录 hash。
- Task 2 focused verification：`11 passed`；Ruff、strict mypy（56 source files）与 `git diff --check` 通过。
- 本任务无新的通用过程经验；Task 3 仍负责实际 Playwright/FairyGUI 执行、PNG 生成与最终人类报告。
