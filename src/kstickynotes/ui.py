from PySide6.QtCore import QEvent, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QPlainTextEdit, QPushButton, QSplitter, QStyle,
    QSystemTrayIcon, QTabWidget, QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)
from .storage import Note, Store


def dialog(parent, title, message, *, value=None, confirm=False):
    """Small native-widget dialogs; no nested QMessageBox dependency."""
    box = QDialog(parent)
    box.setWindowTitle(title)
    layout = QVBoxLayout(box)
    label = QLabel(message)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    layout.addWidget(label)
    entry = None
    if value is not None:
        entry = QLineEdit(value)
        entry.selectAll()
        layout.addWidget(entry)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    if entry is not None or confirm:
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
    buttons.accepted.connect(box.accept)
    buttons.rejected.connect(box.reject)
    layout.addWidget(buttons)
    if entry is not None:
        entry.setFocus()
    accepted = box.exec() == QDialog.DialogCode.Accepted
    return entry.text().strip() if accepted and entry is not None else accepted


class NotePage(QSplitter):
    zoom_requested = Signal(int)

    def __init__(self, note: Note, changed):
        super().__init__(Qt.Orientation.Horizontal)
        self.note_id = note.id
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(note.body)
        self.editor.setPlaceholderText("直接输入便签，支持 Markdown…")
        self.editor.setAccessibleName("便签内容")
        self.editor.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.base_font = QFont(self.editor.font())
        self.wheel_steps = 0.0
        self.preview = QTextBrowser()
        self.editor.viewport().installEventFilter(self)
        self.preview.viewport().installEventFilter(self)
        self.preview.setOpenLinks(False)
        self.preview.anchorClicked.connect(self.open_link)
        self.addWidget(self.editor)
        self.addWidget(self.preview)
        self.preview.hide()
        self.editor.textChanged.connect(lambda: changed(self))
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(200)
        self.preview_timer.timeout.connect(self.render)
        self.editor.textChanged.connect(self.preview_timer.start)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y() / 120 if event.angleDelta().y() else event.pixelDelta().y() / 40
            if delta:
                self.wheel_steps += delta
                steps = int(self.wheel_steps)
                if steps:
                    self.wheel_steps -= steps
                    self.zoom_requested.emit(steps)
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def set_zoom(self, percent):
        font = QFont(self.base_font)
        base = font.pointSizeF() if font.pointSizeF() > 0 else 10.0
        font.setPointSizeF(base * percent / 100)
        self.editor.setFont(font)
        self.preview.setFont(font)

    @staticmethod
    def open_link(url: QUrl):
        if url.scheme() in ("https", "http", "mailto"):
            QDesktopServices.openUrl(url)

    def render(self):
        if not self.preview.isHidden():
            self.preview.setMarkdown(self.editor.toPlainText())

    def set_preview(self, visible):
        self.preview.setVisible(visible)
        if visible:
            self.preview.setMarkdown(self.editor.toPlainText())


class Window(QMainWindow):
    def __init__(self, store: Store, settings: QSettings):
        super().__init__()
        self.store, self.settings = store, settings
        self.dirty = {}
        self.quitting = False
        self.zoom_percent = max(50, min(300, settings.value("editor/zoom", 100, type=int)))
        self.setWindowTitle("KStickyNotes")
        self.resize(settings.value("window/size", QSize(600, 420), type=QSize))
        self.setMinimumSize(320, 220)
        icon = QIcon.fromTheme("kstickynotes", QIcon.fromTheme("accessories-text-editor"))
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        self.setWindowIcon(icon)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        self.error_row = QWidget()
        error_layout = QHBoxLayout(self.error_row)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        error_layout.addWidget(self.error_label, 1)
        retry = QPushButton("重试保存")
        retry.clicked.connect(self.flush)
        error_layout.addWidget(retry)
        self.error_row.hide()
        layout.addWidget(self.error_row)
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBarDoubleClicked.connect(lambda index: self.rename_note() if index >= 0 else None)
        layout.addWidget(self.tabs)
        self.setCentralWidget(root)
        self.new_action = self.action("新建", "document-new", "Ctrl+N", self.new_note)
        self.rename_action = self.action("重命名", "edit-rename", "F2", self.rename_note)
        self.delete_action = self.action("删除", "edit-delete", "Ctrl+Shift+D", self.delete_note)
        self.preview_action = self.action("Markdown 预览", "document-preview", "Ctrl+Shift+M", self.toggle_preview)
        self.preview_action.setCheckable(True)
        self.preview_action.setChecked(settings.value("editor/preview", False, type=bool))
        self.note_tools = QWidget(self.tabs)
        self.note_tools.setObjectName("noteTools")
        tools_layout = QHBoxLayout(self.note_tools)
        tools_layout.setContentsMargins(4, 0, 12, 0)
        tools_layout.setSpacing(2)
        for action in (self.new_action, self.rename_action, self.delete_action, self.preview_action):
            button = QToolButton(self.note_tools)
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setIconSize(QSize(18, 18))
            button.setAutoRaise(True)
            tools_layout.addWidget(button)
        tools_layout.addSpacing(6)
        separator = QFrame(self.note_tools)
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        tools_layout.addWidget(separator)
        self.tabs.setCornerWidget(self.note_tools, Qt.Corner.TopLeftCorner)
        self.action("下一条便签", "", "Ctrl+Tab", lambda: self.cycle(1))
        self.action("上一条便签", "", "Ctrl+Shift+Tab", lambda: self.cycle(-1))
        self.action("隐藏窗口", "", "Escape", self.hide_to_tray)
        self.action("关闭到托盘", "", "Ctrl+W", self.hide_to_tray)
        self.action("保存", "", "Ctrl+S", self.flush)
        self.action("退出", "", "Ctrl+Q", self.request_quit)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.flush)
        notes = store.notes()
        if not notes:
            notes = [store.create()]
        for note in notes:
            self.add_page(note)
        selected = settings.value("notes/current", -1, type=int)
        for index in range(self.tabs.count()):
            if self.tabs.widget(index).note_id == selected:
                self.tabs.setCurrentIndex(index)
        self.tabs.currentChanged.connect(self.tab_changed)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("KStickyNotes")
        self.tray_menu = QMenu(self)
        self.tray_menu.addAction("显示便签", self.show_notes)
        self.tray_menu.addAction("新建便签", self.new_note)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("退出", self.request_quit)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()
        self.tab_changed()

    def action(self, text, icon, shortcut, callback):
        action = QAction(QIcon.fromTheme(icon), text, self)
        action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        self.addAction(action)
        return action

    def add_page(self, note):
        page = NotePage(note, self.changed)
        page.set_zoom(self.zoom_percent)
        page.zoom_requested.connect(self.change_zoom)
        page.set_preview(self.preview_action.isChecked())
        self.tabs.addTab(page, note.title)
        return page

    def change_zoom(self, steps):
        percent = max(50, min(300, self.zoom_percent + steps * 10))
        if percent == self.zoom_percent:
            return
        self.zoom_percent = percent
        for index in range(self.tabs.count()):
            self.tabs.widget(index).set_zoom(percent)
        self.statusBar().showMessage(f"字号 {percent}%", 1500)
        self.timer.start()

    def changed(self, page):
        self.dirty[page.note_id] = page.editor.toPlainText()
        self.statusBar().showMessage("尚未保存…")
        self.timer.start()

    def report_error(self, message):
        self.error_label.setText(message)
        self.error_row.show()
        self.statusBar().showMessage("保存失败，修改仍保留在内存中")
        self.show_notes()

    def flush(self):
        self.timer.stop()
        try:
            if self.dirty:
                self.store.save(self.dirty)
                self.dirty.clear()
            self.save_settings()
        except Exception as error:
            self.report_error(f"保存失败：{error}\n请修复磁盘空间或目录权限后重试。")
            return False
        self.error_row.hide()
        self.statusBar().showMessage("已保存", 2000)
        return True

    def save_settings(self):
        self.settings.setValue("window/size", self.size())
        self.settings.setValue("editor/zoom", self.zoom_percent)
        self.settings.setValue("editor/preview", self.preview_action.isChecked())
        page = self.tabs.currentWidget()
        if page:
            self.settings.setValue("notes/current", page.note_id)
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            raise OSError("无法写入应用配置；便签正文已提交的部分仍在数据库中。")

    def new_note(self):
        try:
            page = self.add_page(self.store.create())
        except Exception as error:
            self.report_error(f"新建便签失败：{error}")
            return
        self.tabs.setCurrentWidget(page)
        self.show_notes()

    def rename_note(self):
        index = self.tabs.currentIndex()
        if index < 0:
            return
        title = dialog(self, "重命名便签", "便签名称：", value=self.tabs.tabText(index))
        if not title:
            return
        try:
            self.store.rename(self.tabs.currentWidget().note_id, title)
        except Exception as error:
            self.report_error(f"重命名失败：{error}")
            return
        self.tabs.setTabText(index, title)

    def delete_note(self):
        index = self.tabs.currentIndex()
        if index < 0:
            return
        if not dialog(self, "删除便签", f"确定永久删除“{self.tabs.tabText(index)}”及其内容？", confirm=True):
            return
        if not self.flush():
            return
        page = self.tabs.currentWidget()
        try:
            self.store.delete(page.note_id)
        except Exception as error:
            self.report_error(f"删除失败：{error}")
            return
        self.tabs.removeTab(index)
        page.deleteLater()
        # An empty notebook remains usable; startup creates a blank page.
        self.flush()

    def cycle(self, direction):
        if self.tabs.count():
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + direction) % self.tabs.count())

    def tab_changed(self, *_):
        page = self.tabs.currentWidget()
        for action in (self.rename_action, self.delete_action, self.preview_action):
            action.setEnabled(page is not None)
        if page:
            page.set_preview(self.preview_action.isChecked())
            page.editor.setFocus()
        self.timer.start()

    def toggle_preview(self):
        self.timer.start()
        page = self.tabs.currentWidget()
        if page:
            page.set_preview(self.preview_action.isChecked())
            page.editor.setFocus()

    def show_notes(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        page = self.tabs.currentWidget()
        if page:
            page.editor.setFocus()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible() and not self.isMinimized():
                self.hide_to_tray()
            else:
                self.show_notes()

    def hide_to_tray(self):
        if self.flush():
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.hide()
            else:
                self.showMinimized()

    def closeEvent(self, event):
        if self.quitting:
            event.accept()
        else:
            event.ignore()
            self.hide_to_tray()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "timer"):
            self.timer.start()

    def request_quit(self):
        if self.flush():
            self.quitting = True
            self.tray.hide()
            QApplication.instance().quit()
