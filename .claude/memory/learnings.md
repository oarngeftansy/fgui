# Learnings — 过程经验（只追加）

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
