# KStickyNotes

**xfce4-notes 的 KDE Plasma 6 实现：轻量级托盘便签，支持多标签、Markdown 和自动保存，优先适配原生 Wayland。**

参考 xfce4-notes 的笔记本操作习惯独立实现，使用 Python / PySide6 / SQLite；不是 Xfce 项目的官方移植，也不依赖 Xfce。

**当前默认采用普通窗口＋系统托盘模式。面板使用“自适应内容”时，窗口不随面板或图标移动。Plasma 小部件代码保留在 `plasmoid/`，作为可选实验实现；说明见 [README-widget.md](README-widget.md)。**

面向 Debian sid / KDE Plasma 6 的轻量便签，Python 3.11+、PySide6、SQLite、uv。使用 Qt Widgets、系统字体、调色板、图标主题和普通顶层窗口，保留原生窗口装饰，不覆盖系统样式。不是 Plasma Widget，也不依赖 KDE Frameworks。

## 启动

```sh
git clone https://github.com/chopin1998/kstickNotes.git
cd kstickNotes
uv sync --frozen
uv run --frozen kstickynotes
```

首次启动显示一个空白便签。`uv run --frozen kstickynotes --tray` 仅驻留托盘；若当前桌面没有托盘则显示窗口，避免无法找回。再次启动会显示已有窗口。

安装到 KDE 应用菜单（用户级，不需要 root）：

```sh
./install-desktop.sh
```

安装器生成 `~/.local/bin/kstickynotes`、XDG 数据目录下的 `.desktop` 和图标，不自动启动应用，也不默认启用开机自启。安装后请保留项目目录及其 `.venv`。如需登录时启动，可通过 KDE 系统设置的“自动启动”添加应用，参数可加 `--tray`。

## 操作

- 托盘左键：显示／隐藏；右键：显示便签、新建便签、退出。
- 关闭窗口、Ctrl+W 或 Esc：保存后隐藏到托盘；无托盘时最小化。退出菜单或 Ctrl+Q 才结束进程。
- Ctrl＋滚轮调整编辑区与 Markdown 预览字号，每格 10%，范围 50%–300%，退出后记忆；普通滚轮滚动正文。
- 顶部工具按钮与便签标签共用一行，中间用间距和分隔线区分；标签过多时仍可滚动。
- Ctrl+N 新建；F2 或双击当前标签重命名；Ctrl+Shift+D 删除（需要确认）。
- Ctrl+Tab / Ctrl+Shift+Tab 切换便签；过多标签使用两端滚动按钮。
- 直接编辑 Markdown 源码；Ctrl+Shift+M 打开／关闭并排预览。不是富文本所见即所得编辑器。
- 内容停止变化 400ms 后自动保存。Ctrl+S 可立即重试保存；不需要手动保存。
- 记住窗口大小、字号、预览开关和上次便签。删除最后一条后可以新建；下次启动会生成空白便签。

## 数据与错误处理

正文和标签：`${XDG_DATA_HOME:-~/.local/share}/kstickynotes/notes.sqlite3`。
配置：`${XDG_CONFIG_HOME:-~/.config}/kstickynotes/settings.ini`。
相对的 XDG 路径按规范忽略。数据库旁的 `instance.lock` 是进程锁文件，退出后留下空文件是正常的，不应手动删除运行中的锁。

SQLite 所有写入都使用事务；保存一批正文失败会回滚整批。编辑只更新内存和计时器，不逐键写盘。新建／删除／重命名立即提交事务。退出、隐藏、SIGINT、SIGTERM 前提交待保存内容。保存失败时显示持续错误栏，保留未保存正文，提供重试，并阻止主动退出和隐藏；新建或删除失败不先修改界面。配置错误也会提示。

数据库使用 SQLite 默认回滚日志和 FULL 同步。备份请先退出程序，再复制整个数据目录；没有内置备份／历史版本。强制杀死进程或断电可能丢失最后 400ms 尚未提交的输入，无法保证 SIGKILL 保存。系统会话关闭时尝试提交；强制结束会话同样不能保证保存。

## 位置记忆

原生 Wayland 不提供普通应用按系统托盘全局坐标定位窗口的标准接口。此模式不计算或跟踪托盘偏移。

可通过 KDE 系统设置 → 窗口管理 → 窗口规则，为 `org.kstickynotes.KStickyNotes` 的普通窗口单独添加“位置：记住”。位置由 KWin 记忆，窗口打开后不随面板移动。规则不锁定坐标，仍可随时拖动窗口。首次启用规则后，拖动窗口到希望的位置，让 KWin 记录初始位置；以后拖动会更新记忆。这里记忆的是屏幕上的位置。

如需隐藏任务栏条目，在同一条 KWin 规则中设置“跳过任务栏：强制，是”（`skiptaskbar=true`、`skiptaskbarrule=2`），便签窗口打开时也不显示任务栏条目；通过系统托盘显示或隐藏窗口。此项由 KDE 窗口规则管理，迁移到其他机器时需重新配置。

## KDE / Wayland

Wayland 会话默认请求 Qt 原生 `wayland` 后端，尊重显式的 `QT_QPA_PLATFORM` 覆盖。完全交给合成器放置窗口，不设置精确坐标，不使用置顶、X11 接口、KWin Script 或私有 Wayland 协议。通过 Qt 的标准显示／激活请求唤醒窗口；是否授予焦点取决于 KWin 的防焦点窃取策略。

托盘使用 QSystemTrayIcon 的 StatusNotifierItem 集成。遵循 KDE 常用的原生控件和快捷键习惯，但这不是 KDE 认证应用。uv 的 PySide6 包自带 Qt。在 KDE 下通过 `qtpaths6` 发现系统插件目录，仅在系统与应用 Qt 主／次版本一致时启用 KDE 平台集成，尊重用户指定的平台主题；版本不一致时使用 Qt 默认样式。不硬编码系统插件路径。当系统 Qt 与 PySide6 自带 Qt 版本不同，界面可能使用 Fusion 样式；要获得完整 Breeze 集成，需将 PySide6 Essentials 与系统 Qt 主／次版本匹配后重新锁定依赖。

若缺少系统共享库，Debian 通常需要 `libegl1`、`libgl1`、`libxkbcommon0`、`libwayland-client0`、`libwayland-cursor0`；使用 xcb 后端时还需 Qt xcb 插件依赖。按实际报错安装缺少的系统库。

## 验证

```sh
uv run --frozen pytest -q
```

测试使用 Qt offscreen，不操作当前桌面。覆盖正文持久化、事务回滚、数据库锁冲突、debounce、退出提交、失败保留和重试、删除确认、关闭到托盘及实例唤醒。

桌面验收：在 Plasma Wayland 启动，确认托盘左右键；输入中文和 Markdown、切换标签；调整大小后退出重启；两次启动确认只剩一个实例；验证窗口关闭后可从托盘恢复。offscreen 测试无法证明真实托盘、主题、输入法或 KWin 焦点行为。

实现参考：[Qt 系统托盘](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html)、[Qt 插件部署](https://doc.qt.io/qt-6/deployment-plugins.html)。
