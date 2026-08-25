# Learnings — 过程经验（只追加）

## 2026-08-25 嵌套 clip 的能力角色和提升引用必须同时闭合

- 一个节点可以同时是外层 clip 的内容和内层 clip 的 source；能力协调不能因“当前在外层内容位置”就要求它退回普通 container rule。嵌套 mask/clip 校验必须承认节点的全局 native-clip-source 角色，否则会产生 `mask_requirement_incoherent` 并级联成大量无关文本 orphan。
- `clipsContent=true` 的可读 INSTANCE 与 FRAME 一样可表示为矩形容器裁切；显式复杂 mask 仍是另一条保守能力路径，不能因为放宽容器类型而放宽 mask composition。
- Writer 把嵌套 clip 子树提升为内部 component 后，父级 mask 的 `contentNodeRefs` 属于 UIR 身份域，必须从原子树 UIR ref 改指生成 component-reference UIR ref。只移动 Plan node 而不重写 mask 身份会让单层测试通过、真实双层 clip 在 manifest 前失败。
- Figma 为已栅格化矢量生成的 `TRANSFORM_GROUP` 是几何包装容器，不是未知视觉节点；保留其层级和 transform 才能避免再次栅格化或丢失角度。

## 2026-08-25 Writer 浅层构建通过不能覆盖 API 深层路径

- 可读 source name 会增长资源相对路径；当 API artifacts 根本身已有 129 字符时，`TemporaryDirectory(dir=output.parent)` 可把真实写入路径推到 265 字符。浅层单测和诊断 ZIP 都会成功，却不能证明 HTTP worker 可发布。
- 可编辑工程树应在系统短临时根展开并完成目录/ZIP 校验，再把已验证 ZIP 暂存到目标 output 内，最后执行同目录原子发布。这样既保留可读名称，也不把路径长度问题转嫁为截断业务图层名；临时清理失败和暂存失败仍须保持独立 fail-closed 门。

## 2026-08-25 嵌套矩形 clip 应提升为内部组件而不是整块 PNG

- FairyGUI 6.1.4 已验证的 `overflow="hidden"` 属于 component 根，不能臆造在嵌套 group 上；但这不意味着嵌套 `Frame clipsContent=true` 必须栅格化。Writer 可把该子树确定性提升为包内生成组件，定义根使用 native clip，父组件原位置放 component reference。
- 提升时必须把原 Frame 的位置、尺寸、opacity、visible 留在引用对象上；内部定义根归一到 `0,0`、rotation `0`、opacity `1`、visible `true`，子节点、资源 consumer、mask 事实和 canonical 顺序留在定义内。否则会出现双重位移/透明/隐藏。显示名称需通过 source-name alias 继续使用原 Figma Frame 名。

## 2026-08-25 PNG 的显示几何必须使用 absoluteRenderBounds

- Figma `exportAsync(PNG)` 对圆弧、部分路径和带 effect 的节点会裁到实际可见像素；`absoluteBoundingBox` 是节点编辑框，可能远大于导出 PNG。把裁剪后的 `141×141` PNG 放进 `378×378` edit box 会同时造成大小、位置和视觉角度偏差。
- 任意实际导出资源的 manifest bounds 应优先采用有限且为正的 `absoluteRenderBounds`，仅在 Figma 没有提供时回退 `absoluteBoundingBox`；未导出的原生可编辑节点仍使用 edit box。资源预估也必须使用同一边界，避免选择门与最终几何使用不同坐标空间。

## 2026-08-25 Figma ELLIPSE 不是“普通整圆”的充分证据

- `ELLIPSE` 类型同时承载整圆、圆弧、扇形、圆环和部分 sweep；只依据节点类型与纯色 paint 将其映射为 FairyGUI 原生椭圆，会静默丢失 start/end angle、inner radius 和路径轮廓。当前选择 manifest 中 15 个 ELLIPSE 被当作原生 Graph，正是圆环/弧形角度和形态偏差的通用来源。
- 在未建立完整、经 Editor 验证的 arc/ring 原生方言前，ELLIPSE 与任意 vector family 一样由 Figma 导出轴对齐透明 PNG；PNG 已烘焙源 transform，输出旋转必须归零。混合 PNG/Graph 引起的局部遮挡差异不能用全局 sibling 反转修复，仍保持 canonical child order。

## 2026-08-25 插件资产策略与后端 capability 判定必须在同一边界吸收变换

- 插件把 vector 导出成已经烘焙视觉的 PNG 后，仅修改 MIME 和 rotation 不够；后端若仍在 native-image 决策前执行原始 transform 校验，会一边报告 `unsupported.transform`，一边留下已上传但未消费的 PNG，最终只向用户暴露笼统 validation failure。
- 通用闭合规则是：单一、已验证资源支持且无 children 的叶节点，其 transform 和 visual style 已由资源像素承载，可被 image decision 吸收；interaction 等行为语义不能被图片默默吸收。真实重放必须同时核对 blocking diagnostics 和 `uploaded assets == planned assets`，只看 ZIP 构建异常码无法发现分类错位。

## 2026-08-25 vector PNG 的旋转必须在插件边界烘焙一次

- Figma 对任意 vector-family 节点导出 PNG 时已经给出透明、axis-aligned 的渲染结果；若仍把源 rotation 写入 FairyGUI，Editor 会再次旋转，位置、角度和组内视觉都会漂移。通用合同应是 `vector_asset + image/png + rotation=0`，显示几何继续使用 Figma bounds，PNG 固有像素尺寸只验证 payload，不能反向覆盖布局。
- vector 类型判定必须先于通用 `unrepresentable_transform`/effect fallback；否则旋转 vector 会误入 `composite_png`，绕过 vector 的 rotation-baked 合同。后端需拒绝新 vector 策略携带 SVG 或非零 rotation，防止新旧规则混装。
- FairyGUI group 自身 `xy/size` 与成员 component-space `xy/size` 是两组独立事实。不能用 PNG 固有尺寸或 group 派生包围盒缩放成员；嵌套回归应同时断言 group 和成员坐标、尺寸以及无二次 rotation。

## 2026-08-25 FairyGUI Editor 列表方向不能用来推断 XML 渲染堆叠方向

- 仅凭 Figma 和 FairyGUI 左侧列表的上下顺序差异，将所有 sibling 在 Writer 输出时整体反转，会真正改变渲染堆叠，导致背景和大量底层对象移到最上层。Editor 面板的展示方向不是可以单独作为序列化语义的证据；在没有重叠像素级对比时，Writer 必须保留 canonical Figma sibling order。
- 局部圆环看似顺序异常不应用全局反转修复；应分别检查实际资源透明区、栅格/原生 graph 边界、mask 和局部重叠证据。

## 2026-08-25 文字对齐属性正确仍可因丢失行高而视觉不居中

- Figma 按钮文字可同时为 `fontSize=52`、`lineHeight=40`、`CENTER/CENTER`。只保留 `align=center`/`vAlign=middle` 而丢掉像素行高，FairyGUI 会按默认 52px 行框计算字形中心，即使文本框中心与按钮中心一致，视觉上仍会偏移。FairyGUI 6.1.4 可用整数 `leading = lineHeight - fontSize` 表达像素行高，负 leading 是合法且必须通过 Int32 门。
- 像素行高应成为 UIR/Plan 的 typed fact，不再作为 `line_height` 可编辑风险；百分比行高、非数值像素行高或缺少 fontSize 时仍必须 fail/review closed。旧 generate 路径也要同步输出 leading，避免共享能力分类放宽后另一 Writer 静默丢属性。

## 2026-08-25 Figma 与 FairyGUI display list 的同级堆叠方向相反

- 实时插件捕获的 Figma 同级 children 按前景→背景，FairyGUI component XML displayList 按背景→前景存储；Writer 原样遍历会使 Editor 图层列表整组反向，并改变重叠元素的视觉遮挡。应在每一级 sibling 输出边界反转，不改 Plan 内的 source order/zIndex，也不按节点类型或名称特例。
- FairyGUI 结构顺序还有两个更强的约束：mask/clip source 必须先于被遮罩内容，plain group 必须在其成员之后。通用顺序函数必须在反转 sibling 的同时固定这两类拓扑约束，并以 mask 反例锁定。

## 2026-08-25 文本 RGBA 与 FairyGUI ARGB 不能和图形颜色共用转换边界

- Figma/Plan 文本的 8 位颜色是 `#RRGGBBAA`，FairyGUI Editor 6.1.4 XML 文本颜色按 `#AARRGGBB` 解析；原样写入会把棕/绿/白显示成蓝紫色。普通文本基础色、strokeColor 和 RichText run UBB color 均要在 Writer 边界换序，6 位 `#RRGGBB` 保持不变。
- GraphPlan 的 fill/line color 在上游已是 FairyGUI ARGB，不能复用文本 RGBA→ARGB 函数，否则会二次换序。应分开“仅校验目标颜色”和“转换文本源颜色”两个显式函数，并用图形不回归反例锁定。

## 2026-08-25 FairyGUI Editor 作者态几何需整体按 Int32 闭合

- `FObject.Read_beforeAdd` 的 `Int32.Parse` 不只覆盖 `rotation`，也覆盖 display object `xy`/`size`。只修 rotation 会让同一栈继续在 Figma 小数坐标/尺寸上失败，外观与旧包完全相同。针对 Editor 打开兼容的门必须以完整读取合同为单位：组件 size 及对象 xy/size/rotation 全部序列化为 Int32，且 XML 重开门同时拒绝小数和越界值。
- 自动 XML 门通过不能表述为“Editor 真实验收通过”；在用户真实打开前只能声明产物已通过静态/重放门。

## 2026-08-25 FairyGUI 6.1.4 rotation 是 Int32 而不是通用 decimal

- Figma 的 rotation 常带 `40.000000055...` 一类浮点噪声；FairyGUI Editor 6.1.4 在 `FObject.Read_beforeAdd` 中用 `Int32.Parse` 读取 XML `rotation`，直接写 canonical decimal 会让组件打开时崩溃、画布红叉且显示列表为空。Writer 必须按最近整数角度输出并限定 Int32 范围，独立 XML 门也要拒绝小数 rotation，不能只检查“有限 canonical decimal”。

## 2026-08-25 FairyGUI 可见名称与稳定身份必须分离

- FairyGUI `id` 需要稳定确定性不代表 Editor 中的 `name` 也应使用哈希；组件和 display-list 对象可继续用稳定 ID 做引用，同时用经过目标文件名策略处理的 Figma 图层名作为可见名称。否则结构虽正确，Editor 图层树仍不可维护。
- 实时 selection 的可见名称不应写回 canonical Plan 并迫使全部 golden/CLI 合同变化；应作为构建期闭合 sidecar，只对已知 UIR ref 投影到 Manifest。跨组件/资源命名域还需确定性消歧，但不能改写 Figma 层级或用业务样例特例。

## 2026-08-25 SVG 固有尺寸与 Writer 元数据闭包

- Figma 节点 bounds 不保证能提供正整数资源尺寸；安全 SVG 即使自带明确 `width`/`height`，若 normalize 只继承节点 bounds，Plan 仍可能产生 `null` 尺寸并在 Writer 输入门失败。应在同一 SVG 安全解析边界提取正整数固有尺寸作为资源事实，不能放宽 Writer 元数据校验，也不能按节点类型或名称猜尺寸。
- Windows 全量测试的 `basetemp` 不仅要是 ASCII 子目录名，完整绝对路径也必须足够短；深层中文 worktree 下的 ASCII 子目录仍会让原子 ZIP/工程测试误报。当前可靠门使用已存在系统 Temp 下的短子目录。

## 2026-08-24 原生可编辑性与审核证据身份

- “能保真显示”不等于“已原生支持”。旧流程把渐变、阴影等视觉 fallback 统一描述成兼容，实际可能是 PNG；正确做法是保留外围可编辑结构，只把 FairyGUI 确实无法表达的最小局部列入审核。
- 根 Frame 的纯色背景曾因容器本身不进入 FairyGUI display list 而丢失，也可能被误判为整块图片。引入 typed `GraphPlan` 并写出原生 `<graph>` 后，纯色矩形、椭圆、描边、统一圆角和根背景既能保留层级，也能保持画面。
- 插件侧分类器与后端 graph 提取器必须共享同一组保守能力边界：纯色 paint、可表达的 stroke alpha、统一圆角、无 effect/不支持的 transform。正反例要同时锁定，防止插件显示“原生”而后端拒绝产物。
- 审核 evidence 的数组顺序和显示名称都不是身份；选择刷新、分组或排序后会串图。必须用稳定的 `sourceNodeId` 关联证据与审核项。
- Windows pnpm worktree 的 junction 可能让 esbuild 0.25 在受限沙箱中触发 `EACCES`。构建脚本只在 `.worktrees` 环境使用 Vite fallback，并用 dist parity 测试证明输出仍确定一致。
- Writer 集成测试的临时路径会因深层 worktree 和 build ID 超过 Windows 路径限制；全量门应使用工作区内较短的 `--basetemp`。

## 2026-08-21 Pydantic strict JSON 与 before model validator

- strict Pydantic model 的 `model_validate_json` 原本可按 JSON 语义把 array 验证为 tuple；加入返回
  Python dict 的 `mode="before"` model validator 后，后续验证会按 strict Python 容器语义执行，
  同一 JSON array 可能因不是 tuple 而失败。迁移派生字段优先放在 after validator 中补齐，或在
  存储边界显式迁移，不要无意改变整个模型的 JSON/Python 验证模式。

## 2026-08-21 Desktop GUI 验收的观察与输入是两个独立能力边界

- Computer Use 能返回 Figma 的 accessibility tree 不等于能操作它；本次 native capture 以
  `0x80004002` 失败，同时基于可访问性元素的输入又独立以
  `coordinate input geometry is unavailable` 失败。验收报告必须分别记录
  “可读”、“可截取”和“可操作”，不能用其中一项推断另一项。
- 当真实插件会上传当前 Figma selection 时，“能读到选择名称”不足以证明其为授权的
  中立数据。若无法通过可观察 GUI 确认代表 selection，应停止上传而不是把当前文档
  默认为验收夹具。

## 2026-08-20 Plugin Writer 前端审查边界

- 插件鉴权预览不能把服务 URL 直接交给 `<img>`：浏览器图片请求不会携带插件 token。必须由严格客户端
  以认证 GET 获取 Blob，验证 MIME/非空后转换为短生命周期 object URL，并在 review 更新或卸载时撤销。
- selection fingerprint 是服务端不可变选择身份，不属于安全公开 SelectionView。adjustment 已由 owner、
  candidate ID、generation、issue/node 和服务端声明的闭合 strategy 绑定；不要为了前端提交 adjustment
  而公开 fingerprint 或在客户端重算服务端内部身份。
- Writer review 的“可调整”不能只给布尔值：服务端必须逐 issue 投影闭合 `allowed_strategies`，严格客户端
  拒绝额外/未知策略，UI 只渲染该集合。这样策略扩展不会退化成客户端根据文案猜测。
- Windows 受限运行环境中，esbuild 解析 pnpm-linked worktree 依赖可能需要沙箱外读取；构建入口使用
  repo-root 绝对路径更稳定。打包校验用 .NET SHA-256 API 可避免依赖 PowerShell 模块自动加载。

## 2026-08-20 Plugin Writer 候选产物边界

- 无资源 committed selection 不会创建 `resources/` 子目录；Writer 接入仍需要一个
  已存在的闭合资源根。资源集为空时应传 committed selection root，有资源时才传
  `resources/`，不应为了构建而修改不可变 selection artifact。
- HTTP 层的 Writer 产物需从 Writer 自身的内容地址文件名原子重命名为公开安全的
  download name，再将该精确路径、size 和 SHA-256 作为同一不可变候选身份持久化；
  review/approval/download/restart 都必须重做 expected-root、regular-file、link/reparse、identity、
  size 和 hash 闭合。
- Windows Writer 集成测试会因 pytest 默认深层 basetemp 加上每次 build ID 而触发路径上限；
  覆盖真实图片资源的 focused/full gate 必须使用工作区根下的短 `--basetemp`。

## 2026-08-20 Mapping catalog 语义必须跨 normalize 身份桥接

- catalog 的 exact `nodeIds` 与 `names` 是同一版本化匹配语义的两条分支；只在 source ID
  上预检 candidate、再把 catalog 置空给 UIR，会使 name-only candidate 和未匹配 INSTANCE
  悄悄走 native image 路径。每个 INSTANCE 必须先按原始 committed source identity 作完整
  exact match：无匹配/仅 candidate 均定义缺失，歧义为 mapping conflict。
- normalize 会替换节点 ID，因此要由 source 与 normalized 树的结构对应关系构造 source→normalized
  ID bridge，再将非 candidate catalog 副本交给 UIR compiler。这样 verified/missing/conflict
  仍按生产 mapping→UIR→Plan 语义执行，同时保留 compiler 对未验证 candidate 的全局拒绝。

## 2026-08-20 Committed selection mapping 与 payload closure 复审修复

- selection conversion 会把 raw Figma node ID 规范化为派生 UIR ID；默认 mapping catalog 的
  `nodeIds` 因而必须在 committed `SelectionManifest` 边界按原始 canonical ID 匹配，不能在
  normalized tree 中比较，也不能用显示名称猜测来掩盖 ID 失配。
- 资源闭包不是“每个 Plan resource 都有 payload”即可：committed assets 的逻辑 identity set 必须与
  Plan 需要的 logical asset set 完全相同。未消费 asset 也要 fail closed，避免把输入闭包悄悄扩大。
- payload 文件读取要在分配前检查单项与剩余额度，并以 regular-file handle 和读前/读后 identity
  复验包住有界读取；`Path.read_bytes()` 即使随后比较 hash，也会给增长文件留下内存可用性绕过。

## 2026-08-20 Committed selection 到 Writer 的资源身份

- `SelectionAsset.asset` 是 committed selection 的逻辑资源身份；Plan 的
  `sourceAssetRef` 则是由该逻辑身份、MIME、SHA-256、导出格式、尺寸和九宫格事实确定性派生的
  UIR asset ID。接入层必须同时复验 logical identity 和该派生 source ID，不能把两者混为同一字段。
- 未验证的默认组件 mapping candidate 不能被升级为可生成 component，也不能进入 Writer 产物；当当前
  INSTANCE 仅命中 candidate 且 selection 未提供完整 definition tree 时，必须以
  `fgui.component.definition_missing` 闭合。

## 2026-08-20 验收公开数据需要跨平台路径闭合

- 仅匹配 `C:\\Users` 或少数 Unix home 前缀不能构成公开数据边界：动态文本中的 POSIX
  absolute path、Windows drive-rooted/rooted-backslash 路径和 UNC 路径都会泄露本地上下文。
  应让卡片渲染与 canonical JSON 复用同一个递归公开文本校验器，并在写入前 fail closed。
- 路径边界不能用“slash 后不是 dot”一类正则代替解析：`/./`、`/../`、重复 separator 和
  `file:///` 都可在正规化后代表绝对位置。扫描器需要先精确豁免公开代码/URI 语法，再在 token
  boundary 识别其余 slash/backslash/drive 形式。
- URI 的整体跳过也会绕过其后的私有路径片段；若证据卡没有外部 URL 的产品需求，应拒绝
  `http(s)://` 而不是把整个 URL 当作安全文本。保留的 URI 豁免必须是精确、有限且业务必需的
  公开格式（当前为 `ui://`）。

## 2026-08-20 隔离子进程仍需要信任启动边界

- 仅把 Pillow 放进子进程不代表已隔离；`sys.executable -m package.module` 会让攻击者可控
  CWD/PYTHONPATH 参与模块解析，继承整个环境还会把秘密传入子进程。应使用绝对解释器与
  绝对 probe 脚本、`-I`、可信 cwd 和最小环境 allow-list，并用恶意 CWD shadow 回归证明。
- 图片解码像素限制不能代替编码字节限制。资源目录必须在分配/完整读取前检查
  单文件与合计大小，读取本身也必须有界；内存 API 边界还要独立复验，避免绕过 CLI。
- 合计限额不能只依赖读取前 `stat`；每次读取必须传入当前剩余合计预算，并在保留
  bytes 前用实际返回长度立即复验。否则文件在 stat 后增长可能在单文件限额内绕过
  aggregate cap。

## 2026-08-20 CLI canonical 输入与资源目录快照

- 严格模型验证不能替代原始 JSON 边界：CLI 输入应先拒绝 duplicate key 和非 builtin header 类型，再要求
  原始 bytes 与确定性 canonical serializer（含唯一 LF）完全一致，避免空白、键序与 coercion 形成多种表示。
- `is_file`/`read_bytes` 与一次目录遍历无法闭合资源快照。资源和 manifest 应通过 regular-file handle 读取，
  在读取前后比较 handle/path identity 与元数据，并在 closure walk 后复验根、父目录和文件；Windows 还需拒绝
  reparse point。该策略只能声明“检测到变化即 fail closed”，不能夸大为任意文件系统上的绝对无竞态事务。
- `st_ctime_ns` 在 POSIX 可补充检测 inode metadata change，但 Windows 的 `st_ctime` 是创建时间，不能冒充
  change time。跨平台还应在最终闭包门通过同一稳定 handle 复读 manifest/asset 并比较内容摘要，覆盖同尺寸改写后
  恢复 mtime 的情况。

## 2026-08-19 已公开异常仍是不可信输入

- 捕获到同类型的 public error 也不能直接透传：其 diagnostics、cause/context 可能由恶意调用者构造。
  只能从精确类型和 allow-list code 恢复最小边界类别，再在原 handler 外重建静态公开错误。
- `mkstemp` 的 fd close、candidate replace 和 tmp unlink 必须纳入同一生命周期；失败时应再次尝试 close 并
  始终尝试 unlink。若操作系统同时拒绝两种清理，只能保证隐藏 tmp 从未 publish，不能虚假承诺无残留。

## 2026-08-19 Public build error 与 publish terminal boundary

- `raise PublicError(...) from private_error` 虽然公开错误文本稳定，仍会通过 `__cause__` 和格式化 traceback
  泄露私密异常。`from None` 只隐藏展示链但仍保留 `__context__`；严格公开边界要先离开原异常 handler，再
  抛出新的公开错误，确保 cause/context 均为空。
- 原子 `os.replace` 之后不能再 hash/read/stat，也不应让临时目录 cleanup 成为潜在失败点。候选归档应先
  完成重开、哈希、大小计算与 staging，清理构建目录后再 publish；成功后仅用已知值构造返回合同。

## 2026-08-19 ZIP 重开门必须验证成员文件类型

- ZIP 的路径闭包、CRC 和内容哈希全部正确，仍不能证明成员是普通文件；Unix `external_attr` 可把同名声明
  成 symlink 或特殊文件。发布前重开门必须同时检查 `create_system` 与 mode file type，只接受普通文件或
  未声明 file type 的兼容成员。
- 原子发布的候选 ZIP 必须留在临时目录并在所有重开门之后才 `os.replace`；故障注入应覆盖 XML、目录写入、
  目录重开、ZIP 写入、归档重开和 publish 六个边界，并证明旧产物及无关文件不变。

## 2026-08-19 FairyGUI group 坐标与 XML file-closure gate

- Manifest 对象保存 parent-local 几何，但 FairyGUI component XML 的 group 成员坐标是 component-local；
  序列化时必须沿 canonical preorder 累加祖先平移，并把 group 放在其成员之后。直接原样写 child
  `xy` 会让嵌套容器内容整体错位。
- 独立 XML gate 不能只做安全 reparse：package 声明必须反推出唯一期望文件集，并同时校验 Windows
  NFC/casefold 路径碰撞、全局 typed target ID 唯一、component/image/loader 引用、mask source 顺序和
  canonical decimal；否则语法合法的 XML 仍可能覆盖文件、悬空引用或在 Editor 中产生不同工程。
- FairyGUI 保存语料中 display object 的 `size` 可以为 `0,0`；component 根 size 需保持正数，但普通
  display object 只能要求非负，不能机械套用 Task1 component size 的正数规则。
- Desktop capture 对 Unity/FairyGUI 窗口可能在边框捕获层返回 `0x80004002`。无法观察 modal 和 save
  结果时不能把 serializer golden 描述成 Editor-approved；应保留格式/XML gate 结果并明确列出
  待补的真实 open/save/reopen gate。

## 2026-08-19 Canonical gate 的 coercion 与二次序列化边界

- Pydantic `model_copy` 可绕过字段验证，而 `model_dump(mode="json")`/`model_validate`
  又可能将 `bool` 当成整数版本。合同 header 必须先从 raw runtime attrs 以
  `type(value) is builtin` 检查，dump 后的 raw payload 也要在 model validation 前重复检查。
- Canonical serializer 先调 validator 不足以防住状态型/自定义 `model_dump`；它自己的
  每一次 dump 都必须重做 exact-header 和 public-data closure gate，才能防止第二次
  dump 注入本地路径或 secret marker。
- 全字符串公开数据扫描应以精确结构路径定义豁免；仅豁免 Manifest object
  中的 visible text content 和 run content，不能因任意 provenance 也使用 `text/content`
  key 就被误豁免。

## 2026-08-19 Manifest 图的命名空间与深度边界

- raster mask 的被消费后代只保留在 `MaskPlan` 的 UIR ref 中，而 emitted object 的
  `sourceNodeRef` 是 Plan node ID。Manifest 必须另保留 emitted object 的公开 `uirNodeRef`，
  validator 才能在同一命名空间发现“既被 raster 消费又被发射”。
- Manifest component graph 比 Plan definition graph 多一层消费定义的 root component；因此
  Plan 合法的 256 层定义链在 Manifest 中是 257 个 component。深度限制需保持跨层一致，
  不能机械地对两张图使用相同节点数。
- 目标 ID 唯一不等于与逻辑键一致；Manifest gate 还必须利用公开来源事实重算
  package/component/object/resource 的 typed logical key，防止任意但格式正确的 8 位 ID 通过。

## 2026-08-19 Pillow 输入验证的跨线程隔离

- Pillow 的解压炸弹阈值、截断图开关和 warning filter 都是进程全局状态；私锁加“保存/恢复”仍会与
  不受该锁约束的调用者线程竞争，并可能覆盖其更新。需要严格 policy 时，应在受控子进程内解码，
  让父进程只接收固定、公开的格式和尺寸结果。
- 子进程探测的 bytes 只可经 stdin 传入，stderr 必须丢弃，stdout 只允许结构化公开结果；超时、
  异常退出或非法响应均应 fail closed，且不得将 payload 落盘或写入诊断。
- 除真实子进程的成功路径外，还应以受控 fake Popen 覆盖 timeout 回收、启动失败、非零退出和
  非法公开响应；每条错误路径都要证明 raw marker 未进入异常文本、repr 或诊断。

## 2026-08-19 Writer payload 输入门的安全边界

- 资源字节必须只在通过 hash、Pillow 实测格式/MIME/尺寸和 nine-slice 约束后传给序列化器；
  报错应只保留稳定的 resource ID 和静态公开说明，不能回显 bytes、解析异常或文件内容。
- Pillow 的解压炸弹警告默认不是异常。输入门需要在受控范围将其提升为异常、关闭截断图加载，
  并在验证后恢复全局设置；SVG 不应因 MIME 伪装而被当成安全栅格图。

## 2026-08-19 MaskPlan 必须闭包到实际 emitted target

- `consumed_uir_nodes` 只能证明被 raster/component owner 吞并，不能证明未消费节点最终可达并被发射；
  blocked raster root、definition missing 或不可发射祖先都会让后代 target 未进入 Plan。
- mask reconciliation 必须在节点编译后以实际 emitted UIR target 再收口；target 不存在时撤销
  MaskPlan/引用。资源继续由真实 consumer 驱动，不能为清理 orphan mask 全局删除共享 asset。

## 2026-08-19 外层 raster ownership 与内层 mask reconciliation

- raster mask 的初步 reconciliation 早于最终 raster-root 后代消费时，必须在所有权确定后再做一次
  emission reconciliation；若 mask target 或完整 scope 已被外层 raster root 消费，内层 MaskPlan
  及其专属 consumer 必须一并抑制，否则会留下 orphan mask 或 resource missing。
- 资源应继续由实际 consumer 驱动发射；抑制内层 mask 不应全局删除共享 asset 的 reason/consumer，
  以免误伤范围外仍独立使用该资源的节点。

## 2026-08-19 Plan v2 深度与 reviewed fallback 评审修复

- DAG/树深度不能与按 ID 排序的全局 DFS black visited 共用：先访问叶节点会把后续真实 root
  路径截短。应从实际 roots 计算可达子图，并用迭代拓扑最长路径独立计算深度；cycle 单独诊断。
- 后代消费必须依据最终 resolved capability decision，而不能只看源 UIR conversion mode；但放宽时
  要限定到合法来源角色，避免改变 mask reconciliation 等既有原子失败语义。

## 2026-08-19 自包含组件契约与旧 Plan 迁移

- 可复用组件定义必须同时校验定义局部树和跨定义引用图；节点 ID 单一所有权、定义可达性、
  悬空引用、未使用定义、引用深度和递归环缺一不可，且深树/图必须迭代遍历以避免递归栈风险。
- schema v1 的 candidate-only `componentReference` 不具备生成依据，不能在迁移时补猜
  `definitionRef`；只有完全不含组件引用的严格 v1 才能纯结构升级到 v2。
- UIR 中“verified mapping”只证明候选语义，不证明存在可生成组件树；若缺少自包含定义，
  编译必须使用已明确批准的 PNG fallback 或输出可行动的 unsupported 诊断。

## 2026-08-19 FairyGUI 虚拟路径与可选元数据

- FairyGUI package resource 的 leading `/` 表示包内虚拟根；输入验证不能直接套用主机路径的
  “leading slash 即绝对路径”规则，而应按方言只剥离一个 `/` 后再做严格 containment 校验。
- Characterization parser 只应强制真实证据中的必需结构。组件 XML `name` 可选，身份来自
  package resource；`publish` 属性语义未锁定时只验证已观察的唯一空元素形态，避免把猜测写成方言。

## 2026-08-19 方言夹具解析的文件边界

- XML 安全 parser 只能阻止实体/网络加载，不能替代资源路径验证；必须先拒绝绝对路径、
  traversal、drive/UNC、控制字符和目录型文件名，再解析资源文件。
- `resolve().relative_to()` 不能单独承担边界安全：读取前还要逐级 `lstat` 拒绝
  symlink/Windows reparse point，并用负向测试证明夹具外 XML 未被解析。

## 2026-08-18 Windows pytest 临时路径

- 受限 Windows 环境中，pytest 默认的 `%TEMP%/pytest-of-<user>` 可能拒绝访问；应显式指定
  `--basetemp` 到可写工作区。
- 打包集成测试对 Windows 路径长度敏感；工作树内的深层 `--basetemp` 会导致打包阶段失败，
  改用工作区根下的短路径后全套恢复通过。

## 2026-08-18 新建工程组件边界

- 通用组件候选映射中的包名、组件名、路径和 Controller 页面不能替代可生成组件定义；没有 XML、资源或节点树时，Writer 无法据此创建真实组件。
- 新建工程可通过 Plan 自包含组件定义生成内部引用；该临时目标 ID 分配属于新工程构建清单，不是扫描旧工程的 Project Binding。
- Plan 只保存资源事实和哈希，资源字节必须通过独立、逐项校验的载荷集合交给 Writer。

## 2026-08-18 主流程边界纠正

- Project Binding 不是 Figma → FairyGUI 新建工程的必经步骤；把它放在 XML Writer 前会给用户造成“转换为何先需要 FGUI 工程”的合理困惑。
- 正确做法是先从已验证 Plan 确定性生成新工程；只有更新旧工程、复用既有资源或绑定公共组件时才扫描目标工程。

## 2026-08-18 跨层完整性收口

- 单测某一编译层通过并不等于生产链路安全；插件、规范化、UIR、Plan、旧生成入口和发布产物必须使用同一套 fail-closed 规则。
- 插件 manifest 实际加载 checked-in `dist/code.js`，修改 TypeScript 后必须重建并做 fresh-build byte parity，否则源码正确也可能运行旧代码。
- 资源不能只按 Figma image hash 去重；相同源图片经过不同节点渲染后可能视觉不同，必须纳入导出身份。
- 遮罩必须保留明确的 source/content 角色、几何和资源证据；不能只靠节点类型猜测。
- 不可表示的视觉、行为、文本特性和变换必须阻断，不能生成“能打开但不一致”的工程。

## 2026-08-18 通用性约束

- “村庄升阶”用于回归与视觉比对，不是领域模型；所有修复都应由通用节点类型、资源规则或映射契约驱动。
- 通用映射只描述 `Figma → UIR 语义 → FairyGUI 逻辑组件`，真实 package/component ID 必须由具体目标工程阶段产生。

## 2026-08-19 Manifest 深度边界纠正

- 本文件前文关于 Manifest 允许 257 个 component 的结论已被 strict review 推翻；Writer v1 的
  component graph 总深度上限是 256，不能因为外层 root 消费定义而隐式扩大公开契约。
- 跨层深度校验应对照各层公开限制的同一计数语义写边界反例，不能只从图结构“多一层”推导放宽。
# 2026-08-21 — Actionable review metadata must close over the source transform

- A review button is not an adjustment implementation. The server must author an issue kind from a stable
  diagnostic code, declare a closed strategy set, retain the public source-node bridge, persist the typed
  decision, and pass it into normalization/Plan generation; E2E must prove output facts change.
- Selection-level previews and generated resources have different identity domains. Never associate them by
  array position; omit the source preview until a stable resource/source ID join exists.

# 2026-08-21 — Windows staging depth is part of Writer correctness

- API artifact roots are materially deeper than direct unit-test outputs. Stage deterministic project trees
  beside the final build directory on the same volume, not beneath the build-ID directory, so Windows path
  expansion does not turn valid manifests into `directory-write_failed` while atomic publication is retained.

# 2026-08-21 — Review evidence must share identity and access domains

- A stable source-resource URL is not evidence until the plugin middleware authorizes that exact route,
  ownership is checked, the client whitelist accepts only its bounded shape, and integration reads bytes.
- Plan node IDs and compiled manifest object IDs are different domains. Validate parent/child topology in
  manifest ID space; use source-node mappings only for facts that remain keyed by Plan nodes.
## 2026-08-21 — Async Writer operations need one invalidation token

- Candidate creation, adjustment, regeneration, and approval must all compare the same monotonically
  increasing operation token after every await and inside stage callbacks, catches, and finalizers.
- Selection drift and cancel must increment the token before aborting and reject any already-known
  server candidate; abort alone does not prevent a promise implementation from resolving late.
- Recovery queries must use the identical active-stage set in SELECT and conditional UPDATE, and return
  affected-row counts rather than the number initially observed.
- When polling or stage callbacks reveal a replacement server identity, update the imperative candidate
  ref synchronously before scheduling UI state; invalidation events can arrive before React commits.
