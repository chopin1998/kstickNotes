"""Nonblocking window-mode sync controller and credential settings dialog."""
import queue
import threading
from PySide6.QtCore import QObject, QTimer, QSignalBlocker, QSettings
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
                              QCheckBox, QLabel, QVBoxLayout)
from .webdav import DEFAULT_URL, WebDAV, normalize_url
from .wallet import wallet_password


def settings_dialog(parent, current):
    box = QDialog(parent)
    box.setWindowTitle('Koofr / WebDAV 双向同步')
    box.resize(550, 280)
    layout = QVBoxLayout(box)
    help_text = QLabel('两台电脑使用相同文件夹和账号。首次同步会合并双方便签；同时修改会保留冲突副本。\n'
                       '请使用 Koofr 单独生成的应用密码，密码仅保存到 KDE 钱包。')
    help_text.setWordWrap(True)
    layout.addWidget(help_text)
    form = QFormLayout()
    url = QLineEdit(current.get('url', DEFAULT_URL))
    user = QLineEdit(current.get('user', ''))
    password = QLineEdit()
    password.setEchoMode(QLineEdit.EchoMode.Password)
    password.setPlaceholderText('留空以使用此账号已保存的钱包密码')
    proxy = QLineEdit(current.get('proxy', ''))
    proxy.setPlaceholderText('可留空，或填写 http://127.0.0.1:7890')
    enabled = QCheckBox('自动同步（编辑后约 3 秒，空闲时每 60 秒）')
    enabled.setChecked(current.get('enabled', True))
    for label, field in [('同步文件夹', url), ('账号邮箱', user), ('应用密码', password), ('网络代理', proxy)]:
        form.addRow(label, field)
    form.addRow(enabled)
    layout.addLayout(form)
    error = QLabel()
    error.setWordWrap(True)
    layout.addWidget(error)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存并同步')
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
    layout.addWidget(buttons)
    def accept():
        try:
            normalize_url(url.text())
            if not user.text().strip() or ':' in user.text():
                raise ValueError('请填写有效账号邮箱')
        except ValueError as issue:
            error.setText(str(issue))
            return
        box.accept()
    buttons.accepted.connect(accept)
    buttons.rejected.connect(box.reject)
    if box.exec() != QDialog.DialogCode.Accepted:
        return None
    config = {'url': normalize_url(url.text()), 'user': user.text().strip(),
              'proxy': proxy.text().strip(), 'enabled': enabled.isChecked()}
    secret = password.text() or None
    password.clear()
    return config, secret


class SyncController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.busy = False
        self.closed = False
        self.again = False
        self.cancel = threading.Event()
        self.results = queue.Queue()
        self._secrets = {}
        self.label = QLabel('同步未设置')
        window.statusBar().addPermanentWidget(self.label)
        self.poll = QTimer(self)
        self.poll.setInterval(200)
        self.poll.timeout.connect(self.finish)
        self.periodic = QTimer(self)
        self.periodic.setInterval(60000)
        self.periodic.timeout.connect(self.automatic)
        self.periodic.start()
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(3000)
        self.debounce.timeout.connect(self.automatic)
        window.tray_menu.insertSeparator(window.tray_menu.actions()[-1])
        before = window.tray_menu.actions()[-1]
        self.now_action = window.tray_menu.addAction('立即同步', self.manual)
        self.setup_action = window.tray_menu.addAction('同步设置…', self.configure)
        # Keep Quit last, preserving the familiar tray menu.
        for action in (self.now_action, self.setup_action):
            window.tray_menu.removeAction(action)
            window.tray_menu.insertAction(before, action)
        from PySide6.QtWidgets import QApplication
        QApplication.instance().aboutToQuit.connect(self.close)
        if self.config().get('user'):
            self.label.setText('等待同步' if self.config()['enabled'] else '自动同步已关闭')
            QTimer.singleShot(1500, self.automatic)

    def config(self):
        settings = self.window.settings
        return {'url': settings.value('sync/url', DEFAULT_URL),
                'user': settings.value('sync/user', ''), 'proxy': settings.value('sync/proxy', ''),
                'enabled': settings.value('sync/enabled', False, type=bool)}

    def configure(self):
        if self.busy:
            self.label.setToolTip('请等待当前同步完成后修改设置')
            return
        current = self.config()
        if not current['user']:
            current['enabled'] = True
        result = settings_dialog(self.window, current)
        if result:
            self.start(*result)

    def manual(self):
        if not self.config()['user']:
            self.configure()
        else:
            self.start()

    def defer(self):
        config = self.config()
        if config['user'] and config['enabled']:
            self.debounce.start()

    def automatic(self):
        config = self.config()
        if config['user'] and config['enabled']:
            self.start()

    def start(self, config=None, password=None):
        if self.closed:
            return
        if self.busy:
            self.again = True
            return
        if not self.window.flush():
            self.label.setText('同步暂停：请先保存本地修改')
            return
        config = config or self.config()
        if not config['user']:
            return
        try:
            config = dict(config, url=normalize_url(config['url']))
            records = self.window.store.revisions()
        except Exception:
            self.label.setText('无法读取同步数据')
            return
        self.busy = True
        self.now_action.setEnabled(False)
        self.setup_action.setEnabled(False)
        self.label.setText('正在同步…')
        self.label.setToolTip('如 KDE 钱包提示，请解锁并允许 KStickyNotes 访问')
        results, cancel, cache = self.results, self.cancel, self._secrets
        def work():
            ready = False
            try:
                key = (config['url'], config['user'])
                secret = cache.get(key) if password is None else None
                if secret is None:
                    secret = wallet_password(config['url'], config['user'], password)
                    if cancel.is_set():
                        raise RuntimeError('同步已取消')
                    cache[key] = secret
                ready = True
                remote = WebDAV(config['url'], config['user'], secret, config['proxy'], cancel)
                incoming = remote.exchange(records)
                results.put((config, incoming, None))
            except Exception as error:
                # Transport/wallet errors are sanitized and do not contain passwords or note text.
                message = str(error) if isinstance(error, (ValueError, RuntimeError)) else '同步失败，请检查网络和钱包后重试'
                results.put((config if ready else None, None, message))
        threading.Thread(target=work, daemon=True, name='kstickynotes-webdav').start()
        self.poll.start()

    def finish(self):
        try:
            config, incoming, error = self.results.get_nowait()
        except queue.Empty:
            return
        self.poll.stop()
        self.busy = False
        self.now_action.setEnabled(True)
        self.setup_action.setEnabled(True)
        if self.closed:
            return
        if config is not None:
            for key, value in config.items():
                self.window.settings.setValue('sync/' + key, value)
            self.window.settings.sync()
            if self.window.settings.status() != QSettings.Status.NoError:
                error = '无法保存同步配置，请检查配置目录权限'
        if error is None:
            if not self.window.flush():
                error = '本地修改尚未保存，已暂停合并云端数据'
            else:
                try:
                    conflicts = self.window.store.merge(incoming)
                    self.refresh_pages()
                    self.label.setText(f'已同步 · {conflicts} 处冲突已保留' if conflicts else '已同步')
                    self.label.setToolTip('新增、修改和删除已合并；本轮产生的冲突记录将在下一轮上传')
                    if incoming or conflicts:
                        QTimer.singleShot(0, self.start)
                except Exception as issue:
                    error = str(issue) if isinstance(issue, ValueError) else '同步合并失败，本地修改仍在，请检查磁盘后重试'
        if error:
            self.label.setText('同步失败（悬停查看）')
            self.label.setToolTip(error)
        if self.again and not error:
            self.again = False
            self.debounce.start()
        else:
            self.again = False

    def refresh_pages(self):
        window = self.window
        notes = {n.id: n for n in window.store.notes()}
        selected = window.tabs.currentWidget()
        focused = selected.editor.hasFocus() if selected else False
        with QSignalBlocker(window.tabs):
            for index in range(window.tabs.count()-1, -1, -1):
                page = window.tabs.widget(index)
                note = notes.pop(page.note_id, None)
                if note is None:
                    window.tabs.removeTab(index)
                    page.deleteLater()
                    continue
                window.tabs.setTabText(index, note.title)
                if page.editor.toPlainText() != note.body:
                    position = page.editor.textCursor().position()
                    scroll = page.editor.verticalScrollBar().value()
                    with QSignalBlocker(page.editor):
                        page.editor.setPlainText(note.body)
                        cursor = page.editor.textCursor()
                        cursor.setPosition(min(position, page.editor.document().characterCount()-1))
                        page.editor.setTextCursor(cursor)
                        page.editor.verticalScrollBar().setValue(scroll)
                    page.render()
            for note in notes.values():
                window.add_page(note)
        # Avoid changing focus while the window is hidden or another control is active.
        page = window.tabs.currentWidget()
        for action in (window.rename_action, window.delete_action, window.preview_action):
            action.setEnabled(page is not None)
        if page and focused:
            page.editor.setFocus()
        window.save_settings()

    def close(self):
        self.closed = True
        self.cancel.set()
        self._secrets.clear()
        for timer in (self.poll, self.periodic, self.debounce):
            timer.stop()
