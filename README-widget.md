# KStickyNotes — Plasma 面板小部件

**当前默认已切回普通窗口＋托盘模式，见 [README.md](README.md)。本小部件保留为可选实现。标准 Plasma 弹出区会锚定面板图标，因此会随“自适应内容”面板的位置变化移动，图钉不能解除这个锚定。**

此实现是 Plasma 原生小部件：面板上只有一个图标，点击弹出便签，再次点击收起。弹出区不使用普通应用窗口的标题栏，颜色、字体、图标和控件跟随 Plasma。支持固定弹出区，避免切换其他窗口时收起。

## 安装与使用

```sh
cd kstickNotes
uv sync --frozen
python3 install-widget.py
```

右键面板 → **添加小部件** → 搜索 **KStickyNotes** → 拖到面板。也可以在系统托盘配置的“小部件”中启用它（若当前 Plasma 托盘支持该入口）。安装器不会改写现有面板布局，也不会重启桌面。

不需要启动普通窗口版。若原来的 `uv run kstickynotes` 仍在运行，请从其托盘菜单退出；小部件会提示数据库占用，退出旧版后点击“重试”。保留普通窗口版作为备用入口，二者通过同一文件锁互斥，避免两套编辑器同时覆盖正文。

## 操作

- 面板图标左键显示／收起；右键菜单提供显示、新建、立即保存、重新加载界面，以及 Plasma 自己的设置和移除操作。
- 顶部按钮：新建、重命名、删除、Markdown 并排预览、固定弹出、收起。
- 标签可以横向滚动，两端按钮可翻动；Ctrl+Tab 切换，F2 重命名，Ctrl+N 新建。
- Ctrl+Shift+D 删除（需要确认）；Ctrl+Shift+M 切换预览；Esc 收起。
- 在编辑区或预览区按住 Ctrl 滚动滚轮调整字号：向上放大、向下缩小，每格 10%，范围 50%–300%。两边同步，大小保存在小部件配置中。普通滚轮仍滚动正文。
- 停止输入 400ms 自动保存；收起前额外请求立即保存。Ctrl+S 用于立即保存或重试。
- Plasma 记录当前标签、预览开关和弹出区大小；弹出区边缘可否直接调整大小由当前 Plasma 容器决定。面板位置和弹出位置由 Plasma 管理。
- 小部件由 Plasma 管理生命周期，没有“退出整个桌面”的操作；收起即可。移除小部件不会删除数据库。后台按需启动，闲置时无数据库轮询；仍保留一个 Python 服务进程。

## 开发时重载

修改编辑区 QML 后，先运行 `python3 install-widget.py` 更新已安装的文件，再右键面板上的 KStickyNotes 图标 → **重新加载界面**。

重载前先等待所有本地草稿送达后台并提交数据库；保留当前标签、字号、预览、固定弹出状态和编辑器的选择范围及滚动位置。保存失败时取消重载。新版 QML 编译失败时保留旧编辑器，修正并安装后可再次重试。

保存服务将已安装的界面代码复制到 `${XDG_CACHE_HOME:-~/.cache}/kstickynotes/ui/<内容哈希>/`；新版代码使用新的完整路径，避开 Plasma 的 QML 组件缓存，也不清空其他小部件的引擎。重复重载相同代码会复用已有副本。

重载范围是编辑区 `NotesView.qml` 及其局部 QML/JS 依赖。`main.qml`（面板菜单入口）、`ReloadableView.qml`（重载外壳）、根 `Backend.qml` 或配置结构修改，仍可能需要重新添加小部件；Python 后端代码修改需要保存后重启服务。首次安装这个菜单入口也需要重新添加一次，之后常规编辑区修改可使用菜单重载。

## 数据与稳定性

继续使用原窗口版的 SQLite 数据，无需转换：
`${XDG_DATA_HOME:-~/.local/share}/kstickynotes/notes.sqlite3`。

小部件配置由 Plasma 保存于 XDG 配置目录的 `plasma-org.kde.plasma.desktop-appletsrc`，而不是正文数据库。原窗口版的 `settings.ini` 仅供备用窗口使用。

Plasma QML 前端通过用户会话 D-Bus 与 uv 管理的 Python 服务通信。每次输入只把草稿送进后端内存，后端以 400ms debounce 合并事务写入；不逐键写磁盘。连续编辑已经有待保存正文的便签时不重复查询 SQLite。服务在独立进程中，使用 QCoreApplication，不加载另一个 GUI Qt 平台插件，因此前端直接使用系统 Plasma 组件，避免 uv Qt 与 Breeze 插件混用。

新增、改名、删除先提交已有草稿，再立即事务保存。删除需前端确认。磁盘错误会显示持续错误栏，保留后端和本地草稿，提供重试与复制草稿；发生冲突时不会静默覆盖，重新加载前需要确认放弃本地草稿。正常 SIGINT/SIGTERM 和服务主动停止会提交待保存内容；失败时保持服务运行。数据库锁与原窗口版一致，异常退出后可重新取得锁。

保存完成前强杀后端、强制结束会话或掉电仍可能丢失最后的未提交输入；前端输入尚未送达服务时强杀 Plasma 也无法保证恢复。备份前请先保存并停止服务，然后复制数据目录。

手动停止后台（已保存内容保留，下次打开小部件会再次按需启动）：

```sh
qdbus6 org.kstickynotes.Service /Notes org.kstickynotes.Notes1.Request '{"op":"stop"}'
```

## 依赖与测试

目标为 Debian sid / Plasma 6；已在本机 Plasma 6.6、系统 Qt 6.10 实测加载。需要 `kpackagetool6`、Plasma Components、Kirigami，以及 `org.kde.plasma.workspace.dbus` 模块中的 SessionBus 和 SignalWatcher。Debian 的该模块由 `qml6-module-org-kde-plasma-workspace` 提供；不同发行版可能整合在 plasma-workspace 中。Python 依赖仍由 uv.lock 管理。

```sh
uv run --frozen pytest -q
# 以下使用独立 D-Bus、临时配置和临时数据库，不操作现有面板
uv run --frozen python tests/run_qml_tests.py
uv run --frozen python tests/run_activation_test.py
```

原生界面测试额外需要 `qt6-declarative-dev-tools`、`qml6-module-qttest`、`qtpaths6` 与 `dbus-run-session`。测试覆盖快速输入、debounce 前后切换标签、Markdown、增删改、删除取消、收起保存；后端覆盖事务失败后的草稿保留、重试和冲突拒绝。真实面板点击、桌面输入法、KWin 焦点和容器大小调整仍需在实际面板中验收。

实现参考：[Plasma 6 小部件接口](https://develop.kde.org/docs/plasma/widget/porting_kf6/)、[KDE D-Bus 组件](https://github.com/KDE/plasma-workspace/tree/master/components/dbus)。
