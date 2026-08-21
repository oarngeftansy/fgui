# Writer Task 1 报告：锁定 FairyGUI 6.1.4 工程方言

## 状态

完成。本任务只建立 Writer 的 6.1.4 格式证据层，未实现 Project Binding、
Writer 后续序列化任务或任何村庄特例。

## 格式证据

依照收缩后的执行要求，未新建 GUI 工程，而是从
`C:\Users\momoca\Downloads\FairyGUI-project3` 的已打开/保存 6.1.4 工程提炼：

- `isekaiUI.fairy` 提供 `projectDescription`、`type="Unity"` 和 `version="5.0"` 结构证据。
- `assets/MyVillage/package.xml` 提供 `packageDescription/resources/component/publish`
  元素及 `id/name/path` 属性证据。
- 同一 6.1.4 工程的 `assets/Common/Tips/Common_Tips_Layer.xml` 提供真实空组件
  `<component ...><displayList/></component>` 结构证据。
- 夹具只将工程/包/组件名中立化为 `Minimal/Generated/Root`，尺寸设为计划指定的
  `320x180`，不复制业务资源或业务节点。

## TDD 证据

### RED

命令：

```powershell
& 'C:\Users\momoca\Documents\figma转fgui\source\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_fgui_xml_dialect_614.py
```

输出摘要：

```text
ModuleNotFoundError: No module named 'figma_to_fgui.fgui_xml_dialect_614'
1 error in 0.13s
```

备注：直接执行 `python` 首先命中了不可用的 WindowsApps 别名；改用仓库既有 `.venv`
后取得上述真实 RED。

### GREEN

命令：

```powershell
& 'C:\Users\momoca\Documents\figma转fgui\source\.venv\Scripts\python.exe' -m pytest -q tests/unit/test_fgui_xml_dialect_614.py
```

输出：

```text
.                                                                        [100%]
1 passed in 0.11s
```

## 实现文件

- `tests/fixtures/fgui-editor-6.1.4/README.md`
- `tests/fixtures/fgui-editor-6.1.4/minimal/Minimal.fairy`
- `tests/fixtures/fgui-editor-6.1.4/minimal/assets/Generated/package.xml`
- `tests/fixtures/fgui-editor-6.1.4/minimal/assets/Generated/components/Root.xml`
- `tests/unit/test_fgui_xml_dialect_614.py`
- `src/figma_to_fgui/fgui_xml_dialect_614.py`
- `.claude/memory/wiki.md`
- `.claude/memory/learnings.md`
- `.superpowers/sdd/writer-task-1-report.md`

## 实现摘要

- 新增常量 `FAIRYGUI_VERSION="6.1.4"`、`PROJECT_SUFFIX=".fairy"`、
  `ASSETS_DIRECTORY="assets"`。
- 新增冻结模型 `EditorDialectFixture`。
- 新增严格解析入口 `parse_editor_fixture(root: Path)`：要求正好一个工程标记和一个包，
  使用禁用实体解析与网络的 lxml parser，并读取组件名和尺寸。

## 自检

- Focused pytest：`1 passed in 0.11s`。
- 全套 pytest：`750 passed, 2 skipped, 3 warnings in 17.05s`。
- Ruff：`All checks passed!`
- mypy：`Success: no issues found in 49 source files`。
- `git diff --check`：通过。
- 夹具内 3 个 XML 文件均由 lxml 成功解析。

全套 pytest 必须使用短且可写的 `--basetemp C:\Users\momoca\Documents\figma转fgui\.ptb-writer-task1`。
默认 `%TEMP%` 被拒绝访问；工作树内过深的 basetemp 又会让 5 个 Windows 打包集成测试因路径过长失败。

## 提交

- 提交信息：`test: lock FairyGUI 6.1.4 project dialect`
- 提交 hash：见任务最终回报（报告与实现同提交）。

## 关注点

- Computer Use 启动 FairyGUI 的调用被中断，未对中立化后的 `Minimal` 夹具再做一次单独 GUI
  打开/保存复验。根据收缩后的明确要求，这不阻塞本任务；当前证据来自已由 6.1.4
  打开/保存的 `FairyGUI-project3`。
- 夹具 ID 仅是方言证据；后续 Writer 仍必须确定性生成生产 ID，不得复用夹具 ID。
- `.claude/memory/memory.md` 无新的稳定偏好需回写。

---

## 2026-08-19 代码评审修复

### 当前状态

Task 1 的非 GUI 代码评审问题已修复。当前夹具仍来源于 FairyGUI Editor 6.1.4
打开并保存过的工程格式证据；中立化后的最终 `Minimal` 夹具尚未完成独立的 GUI
打开/保存/关闭重开往返，因此最终验收仍需 controller/user 执行 GUI gate。本修复不声明该
GUI gate 已完成。

### TDD 修复证据

RED focused 测试在旧实现上得到：

```text
25 failed, 3 passed, 1 skipped
```

失败覆盖 marker 未解析、根元素与必需结构未验证、资源 ID 未校验、路径逃逸、绝对路径、
名称目录注入、控制字符、组件结构缺失，以及 reparse point 未阻断。

GREEN 后 focused 测试：

```text
35 passed, 1 skipped
```

跳过项仅为当前 Windows 账户无创建文件符号链接权限；等价的 Windows reparse point
模拟测试已通过。

### 修复内容

- `.fairy` marker 现在会实际解析并严格验证 `projectDescription`、小写字母数字 ID、
  `type="Unity"` 与已观察到的工程文件版本 `version="5.0"`。
- `package.xml` 严格验证 `packageDescription` 根、合法包 ID、唯一且非空的资源 ID，
  以及恰好一个直接 `resources` 和 `publish` 元素。
- 组件 XML 严格验证 `component` 根、与资源文件名一致的非空 `name`、两个正整数构成的
  `size`，以及恰好一个直接 `displayList`。
- 资源 `path` 只允许安全的 POSIX 相对目录，`name` 只允许单个文件名；拒绝 `..`、
  绝对路径、drive/UNC、反斜杠、控制字符、目录型名称、越出 package root，以及路径链上的
  symlink/reparse point。
- 负向测试通过公共入口 `parse_editor_fixture` 验证 fail closed，并用外部 XML 读取 guard
  证明 traversal 在读取夹具外文件前被拒绝。
- 方言 fixture 中的资源路径调整为 `components/`，组件补上 `name="Root"`；README 明确
  标注最终中立 fixture 尚待 GUI gate。

### 完整验证

- Focused pytest：`35 passed, 1 skipped`。
- Full pytest：`784 passed, 3 skipped, 3 warnings`。
- Ruff：`All checks passed!`
- mypy：`Success: no issues found in 49 source files`。
- `git diff --check`：通过。

本修复提交 hash 见任务最终回报。

---

## 2026-08-19 Important 复审纠偏

### 当前状态

本节纠正上一节对 6.1.4 方言的两处过度约束。非 GUI 代码问题已修复；最终中立化
`Minimal` 仍未完成 FairyGUI 6.1.4 GUI open/save/reopen gate，本节不声明 GUI 验收完成。

### TDD 证据

恢复真实 fixture 方言并加入行为测试后，旧实现的 focused RED 为：

```text
17 failed, 28 passed, 1 skipped
```

GREEN 与完整验证：

- Focused pytest：`45 passed, 1 skipped in 0.43s`。
- Full pytest：`794 passed, 3 skipped, 3 warnings in 17.39s`。
- Ruff：`All checks passed!`
- mypy：`Success: no issues found in 49 source files`。
- `git diff --check`：通过。

### 方言纠偏

- FairyGUI package resource `path` 的单个 leading `/` 是包内虚拟根，不是主机绝对路径。
  解析器只剥离一个 leading slash，再验证 `..`、embedded empty segment、drive/UNC、
  backslash、控制字符、symlink/reparse 与 resolved containment；`//` 仍直接拒绝。
- `component` XML 的 `name` 属性是可选的；组件身份来自 package resource 的 `name`。
  XML 若提供 `name`，只验证其非空且路径安全，不再要求与资源文件名一致。真实 `Root.xml`
  fixture 已恢复为无 `name` 根。
- `publish` 只要求在 `packageDescription` 下唯一且保持已观察的空元素结构。现有
  `name/path/packageCount` 属性组合与无属性 `<publish/>` 均通过；不猜测属性语义或强制属性，
  但拒绝子元素和非空文本。
- 对应测试明确验证 `/components/` 映射到 `package_root/components`，以及 `//`、`/../`、
  `/C:/`、embedded empty segment、UNC 和 fixture 外读取攻击继续 fail closed。

本纠偏提交 hash 见任务最终回报。

---

## 2026-08-19 GUI gate 收口

### 实际往返

Controller 使用 FairyGUI Editor 6.1.4 直接启动中立 fixture 的 `Minimal.fairy`：

1. 唯一工程窗口标题为 `Minimal`，执行 `Ctrl+S` 保存并以 `Alt+F4` 关闭；窗口列表确认
   `Minimal` 消失。
2. 从同一路径再次启动，唯一工程窗口标题仍为 `Minimal`；再次执行 `Ctrl+S`，然后以
   `Alt+F4` 关闭。
3. 全过程没有额外 modal、repair 或 migration 窗口。

因此 Task 1 的真实 FairyGUI 6.1.4 open/save/close/reopen/save GUI gate 已完成。此证据只覆盖
Task 1 的方言 fixture，不代表尚未实现的后续 Writer 产物已经通过 GUI gate。

### 字节一致性

两次保存后，以下三个 tracked fixture 文件没有 git diff，SHA-256 为：

- `Minimal.fairy`：`273501ef00ee0a533aa8de2b383249eb93a9b69e431ff318837cc40921ef4d1b`
- `assets/Generated/package.xml`：
  `e374ff3c3a3c70613ee990e6e8bcb267ca984b6aaf0c4cec833171199bfd6534`
- `assets/Generated/components/Root.xml`：
  `97244573813d99e17263e6f0883cbb94fccd193d2df97bbead187a8a7c350c34`

Unity window capture 返回 `0x80004002`，因此本报告不把截图列为证据，也不声称取得截图。

### 缓存与验证

- Editor 生成的确切缓存目录
  `tests/fixtures/fgui-editor-6.1.4/minimal/.objs/` 已在 containment 校验后删除；它是可再生缓存。
- 新增 fixture-local `.gitignore`，仅忽略 `.objs/`。
- Focused pytest：`45 passed, 1 skipped in 0.46s`。
- 本次只修改文档、fixture-local ignore 和可再生缓存，不重跑 full pytest；上一轮实现提交的
  full pytest 结果为 `794 passed, 3 skipped, 3 warnings`。

本 GUI gate 收口提交 hash 见任务最终回报。
