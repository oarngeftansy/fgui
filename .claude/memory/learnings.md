# Learnings — 过程经验（只追加）

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
