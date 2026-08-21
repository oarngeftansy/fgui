# Wiki — 当前项目事实

## 2026-08-21 Writer capability review alignment

- Writer 的能力判定现由后端单一 `NewProjectConversionDisposition` 合同负责，闭合等级为
  `native`、`raster_preserved`、`editable_risk`、`blocked`。渐变、复杂阴影、遮罩、实例、
  普通视觉样式、不可原生表达的变换和复杂文本在存在受控 PNG fallback 时不再直接导致通用
  validation failure；审核明确区分画面保真与可编辑性影响。
- 插件审核先显示“自动转换 / 建议审核 / 必须处理”三类汇总；选择阶段重复的 fallback warning
  已合并为一条摘要。只有红色 blocked disposition 阻止批准。分析被阻断时仍返回可定位、可拒绝的
  review，但 `artifactReady=false`，不得批准、预览生成资源或下载 ZIP。
- 本轮无 Project Binding、无村庄/页面名/节点 ID 特例。村庄升阶仍仅是通用回归输入。
- 自动化门：Python 全量 `1154 passed, 4 skipped`；Web Console `35 passed`、typecheck/build 通过；
  Figma plugin focused/full 与 package parity 已验证（一次全量 harness 5 秒超时，单独立即重跑
  `7 passed`）；Ruff 和 strict mypy 59 个源文件通过。
- 本地验收插件已重建到
  `.local-acceptance/plugin-current-http/manifest.json`（plugin ID `987654321012348`），服务为
  `http://localhost:8765`，当前后台 PID `31504`。正式分发仍需用真实 HTTPS 服务地址、原插件 ID
  和部署 token 重新构建；localhost 目录只用于本机验收。
- 360×680 插件布局只保留 `.writer-shell` 一条纵向滚动轴；review tab panel 不再限制为 200px
  内层滚动，底部操作区不再 sticky 覆盖审核内容。布局回归会直接锁定这两个 CSS 不变量。

## 2026-08-21 Plugin Writer final delivery batch

- Whole-branch review fix wave replaced cosmetic adjustments with compiler-code-authored typed issues and
  closed workflow adjustments. Public HTTP E2E proves archive SHA/output warning change, generation
  invalidation, exact warnings and no SQLite injection. Generation is server-authoritative; build and
  regeneration are observable asynchronous stages; terminal retry creates a fresh generation.
- Review now carries explicit crop/transparency, hierarchy/geometry/text, naming-conflict, closure and
  integrity facts. Unkeyed selection previews are not position-joined, and preview fetch failure blocks
  approval. Final regression is `1146 passed, 4 skipped`; plugin `171 passed`; Web Console `30 passed`;
  Ruff, strict mypy, both typechecks/builds and package `5 passed` are green.

- 公开交付 E2E 现覆盖中立 PNG manifest/resource 上传、批准前下载阻断、四类 review、
  服务端声明 adjustment、v1 永久失效、v2 精确 warning acknowledgment、whole-candidate
  approval、两次下载的 bytes/name/size/SHA-256 一致及生产 archive validator 闭包。请求
  记录证明未使用 template、pairing、`/v1/agents/`、existing-project 或 Project Binding 路由/字段。
- no-special-case 扫描已扩展到 `src/figma_to_fgui`、`apps/figma-plugin/src`、
  `apps/web-console/src/figma` 与 `rules/default`，并以 backend 和 Writer panel 注入测试证明
  village/rank/node 唯一标记会被检出；通用需求方 mapping 仍只有原 allowlist。
- 包装门会验证 Writer 可见文案、新路由 token、`defaultMode="writer"`，并对交付 ZIP 四个
  成员与经验证构建输入做逐文件 SHA-256 字节闭包。
- 最终自检：focused `5 passed`；Python 全量 `1141 passed, 4 skipped, 1 failed`，唯一失败是
  已知且未修改的 Task 3 报告 `Capture/capture` 大小写断言（测试和报告均来自
  `0bb55f93`）；Ruff 通过；strict mypy 58 个源文件通过；Figma plugin `171 passed`、
  typecheck/build/package `5 passed`；Web Console `29 passed`、typecheck/build 通过。
- 2026-08-21 新鲜 GUI 尝试未通过：Figma 和 FairyGUI Editor 6.1.4 都能启动且返回唯一
  窗口，但 native capture 均失败于 `0x80004002`；Figma 元素输入还失败于
  `coordinate input geometry is unavailable`，FairyGUI 可访问性仅暴露标题栏且 `Ctrl+O`
  未产生可目标的打开对话框。因无法证明 Figma 当前选择为中立数据，未上传、未截图、未下载；
  也未宣称新鲜 Editor open/save/reopen 通过。详情在
  `docs/validation/2026-08-21-plugin-writer-final-acceptance.md`。

## 2026-08-20 Plugin Writer frontend batch

- Figma 插件入口显式启用 `defaultMode="writer"`；`ProjectWorkflowPage` 默认仍为 `legacy`，因此 Web Console
  四步 create/update 流不变。Writer 的“更新现有工程”只从插件 overflow 进入，并复用隔离的旧 update 流。
- Writer 客户端现覆盖 selection upload、新建候选 start/poll、严格 review、服务端声明 adjustment、regenerate、
  whole-candidate approve/reject、鉴权 preview，以及 approval-gated ZIP 下载；下载同时复验安全文件名、精确大小
  和 SHA-256。公开错误新增 `review_required` / `stale_candidate`。
- 360×680 Writer UI 使用单工程名、只读 FairyGUI 6.1.4/新建独立工程、inline stages、四类 review tab、
  真实 evidence 标签、candidate generation 失效、warning 重新确认、统一批准下载与再次下载；无模板、
  Project Binding、既有资源字段、per-file approval 或业务样例特例。
- 后端最小前端集成补丁为 review check 投影闭合 `allowed_strategies`，并从 adjustment request 删除冗余且不应公开的
  selection fingerprint；候选 owner/ID/generation/issue/node 及不可变 selection 关联仍由服务端验证。

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

## 2026-08-20 Plugin Writer Task 1：committed-selection workflow

- 新增纯 `build_selection_new_project` 编排器：仅使用 selection、闭合资源目录、公开 fingerprint、
  project name 和输出目录，按 `selection → normalize → mapping → UIR → Plan v2 → Writer ZIP` 执行；
  固定 `fgui-6.1.4-v1`、rule 1、`Generated` 包、FairyGUI 6.1.4 与 Unity。
- 工作流会在 Writer 之前复验 selection 资源的 logical/source asset identity、MIME、SHA-256 和字节大小；
  Writer/转换异常只会变成新的 allow-listed public diagnostics，并切断 cause/context。
- 组件 candidate 不升级为可生成定义；selection 没有 definition tree 时，命中的 INSTANCE 以
  `fgui.component.definition_missing` 阻断。focused workflow tests 为 `10 passed`，Ruff 与 strict mypy
  （57 source files）通过。

### 2026-08-20 Task 1 review fix

- candidate blocking 现在直接使用 committed `SelectionManifest` 中的 canonical Figma INSTANCE ID；
  不再把 catalog `nodeIds` 与 normalize 后的派生 ID 比较，也不依赖显示名猜测。未验证 candidates
  不传入 UIR compiler，因此不会被升级为可生成 component。
- selection assets 与 Plan logical asset IDs 必须精确集合闭合；payload reader 采用单项/合计上限、
  regular-file handle、读前/读后身份复验和有界读取。UIR source asset ID 复用
  `uir_compile.uir_asset_id` 的唯一 canonical 实现。

### 2026-08-20 Task 1 second re-review fix

- committed-selection workflow 在 normalize 前以 catalog 原始 source `nodeIds` 或 catalog
  `names` 的精确 OR 语义匹配所有 INSTANCE；未匹配或 candidate-only 的实例稳定以
  `fgui.component.definition_missing` 关闭，歧义或 `conflict` 映射稳定以
  `fgui.writer.workflow.mapping_conflict` 关闭，均不会发布 ZIP。
- workflow 依据 source/normalized 同构树桥接 original Figma ID 到 normalized UIR ID，并只把
  non-candidate catalog copy 传给 UIR compiler；因此 verified/missing/conflict 状态保持标准
  UIR→Plan 行为。`missing` 仅在已有有效 raster asset 时走显式 fallback，而不匹配实例不能沉默
  降级为 native image。

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
- Task 2 privacy review follow-up：public-text validation is now shared by card rendering and canonical
  JSON serialization. It rejects embedded POSIX absolute, Windows drive-rooted, rooted-backslash, and
  UNC paths before any card/result bytes are written. The focused suite is now `16 passed`.
- Task 2 privacy re-review: the public-path check now uses a token-aware scanner rather than a fragile
  slash regex. It rejects POSIX root/dot-segment/repeated-separator and file-URI forms, while preserving
  safe public codes such as `image/png` and constrained `ui://...` references. Focused verification is
  now `22 passed`.
- Task 2 HTTP re-review: `http://` and `https://` are not public-text exemptions. This prevents an
  external-URL token from hiding a local-looking suffix, keeps cards self-contained, and leaves only a
  constrained `ui://...` URI exemption. Focused verification is now `26 passed`.

## 2026-08-20 Writer acceptance Task 3 handoff

- AC-01 now consumes the tracked fresh, bounded `GenericWriterFixture` Editor 6.1.4 transcript rather
  than a pending placeholder. It records exactly two save rounds, returned title
  `GenericWriterFixture`, `delayedCloseObservation=true`, final window count zero, no observed modal,
  the unsupported state-screenshot API error `0x80004002`, and 4/4 equal pre/post hashes. The runner
  rejects transcript additions or alterations instead of widening GUI claims.
- The runner can generate the final canonical JSON and six-section Markdown report only after all six
  PNGs close at exact `1440x1000`; each report section repeats the machine fields and has exactly one
  local screenshot link and matching SHA-256. `--screenshots-pending` can render cards for capture but
  cannot write the final report.
- Evidence cards carry the `1440x1000-no-scroll` layout contract. A headless Edge measurement of all
  six freshly rendered cards found `documentElement.scrollHeight == 1000`; the compact layout keeps the
  decisive evidence visible without full-page overflow.
- The existing user-supplied TC-01 and TC-05 PNGs were inspected but not changed; their headers are
  `1440x1080` and `1440x1042`, respectively, so strict finalization will intentionally require their
  recapture alongside AC-01 at exact `1440x1000`.

## 2026-08-20 Plugin Writer backend batch

- 插件现可从 committed selection 创建专用新建 FairyGUI 工程候选；公开合同严格、
  owner-only，产物路径不公开。候选使用随机 32-hex build ID、selection fingerprint/
  request identity、generation 和 lease 独立持久化。
- 完整后端状态机已包含 typed review，严格 warning acknowledgment，whole-candidate approve/
  reject，闭合 adjustment strategy，以及从原不可变 selection 全管线重生的新 build ID/
  generation；旧候选对 review/preview/approval/download 永久失效。
- 候选 ZIP 在 review、approval、preview、download 和 restart 都会重做 expected storage root、
  regular-file/link/reparse identity、size 和 SHA-256 闭合；失败或篡改不可下载。
- 本批次 focused 为 `19 passed`，旧 API/store 相关回归 `107 passed`，Ruff 通过，
  strict mypy 对 58 个 source files 通过。全套排除一个未修改的 acceptance 报告文案
  大小写断言后为 `1140 passed, 4 skipped, 1 deselected`。

## 2026-08-21 Plugin Writer portrait review workflow

- Figma 插件 Writer 审核窗口改为 `640×800` 竖屏，并把候选展示拆成三个独立步骤：先展示自动转换，
  再逐项展示带图示的建议/阻断审核，最后展示确认下载与折叠的工程详情；不再常驻四类 tab 和转换目录。
- 自动转换项明确区分原生转换与视觉保真图片；建议/阻断项逐个显示 Figma 来源证据与 FairyGUI 结果。
  缺少真实截图时 UI 必须标注“结构示意（非截图）”，不得冒充真实画面。
- `复制到 Figma 审核区` 使用新的 strict/bounded plugin message，把已认证生成 PNG 与来源节点副本放入
  当前选择右侧的独立顶层 `FairyGUI 待审核` frame。审核 frame 使用 plugin-data ownership 标记，
  不会仅凭同名删除用户 frame，也不会重排或修改原来源节点。
- 当前验证：Web Console `38 passed`、Figma plugin `185 passed`、Writer focused `16 passed`、
  plugin contracts/bridge `28 passed`，两端 TypeScript 与 Web build 通过，tracked plugin dist/package parity `5/5`。
- 功能基线 `782520a` 已在清理前推送到 GitHub `oarngeftansy/fgui`的
  `codex/writer-review-alignment` 分支；本机 `origin` 仍仅作 recovery remote。
- `ai-codebase-cleanup` 首批只清理 Writer 三段式流程已替代的四标签审核 CSS 和重复 shell
  声明，并把依赖旧 `.writer-tab-panel` 的测试改为验证当前单滚动区/独立操作栏。Web Console
  后续整理又把预览下载、Blob/Object URL 所有权和释放提取为专用 Hook，删除未读取的
  `runResult` 重复状态和未使用测试导入。Web Console 全套 `40 passed`，TypeScript 常规/未使用符号检查
  与 Vite build 通过。候选生成/调整/失效仍保持在同一状态机内，避免为拆文件破坏取消令牌与服务端失效顺序。
