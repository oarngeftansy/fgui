# Learnings — 过程经验（只追加）

## 2026-08-20 隔离子进程仍需要信任启动边界

- 仅把 Pillow 放进子进程不代表已隔离；`sys.executable -m package.module` 会让攻击者可控
  CWD/PYTHONPATH 参与模块解析，继承整个环境还会把秘密传入子进程。应使用绝对解释器与
  绝对 probe 脚本、`-I`、可信 cwd 和最小环境 allow-list，并用恶意 CWD shadow 回归证明。
- 图片解码像素限制不能代替编码字节限制。资源目录必须在分配/完整读取前检查
  单文件与合计大小，读取本身也必须有界；内存 API 边界还要独立复验，避免绕过 CLI。

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
