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
