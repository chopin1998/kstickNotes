"""Headless session-bus backend for the Plasma widget (no GUI Qt plugins)."""
from dataclasses import asdict
import fcntl
import json
from pathlib import Path
import signal
import sys

from PySide6.QtCore import ClassInfo, QCoreApplication, QObject, QTimer, Signal, Slot
from PySide6.QtDBus import QDBusConnection
from .storage import Store, data_directory, xdg_path
from .ui_snapshot import prepare_ui

SERVICE = "org.kstickynotes.Service"
INTERFACE = "org.kstickynotes.Notes1"
OBJECT_PATH = "/Notes"


@ClassInfo(**{"D-Bus Interface": INTERFACE})
class NotesService(QObject):
    Event = Signal(str)

    def __init__(self, directory: Path):
        super().__init__()
        self.directory = directory
        self.store = None
        self.lock = None
        self.pending = {}
        self.error = ""
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.flush)

    def ensure_store(self):
        if self.store is not None:
            return
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = open(self.directory / "instance.lock", "a+")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise RuntimeError("独立窗口版正在使用便签。请从其托盘菜单退出，再点击重试。")
        try:
            store = Store(self.directory / "notes.sqlite3")
            if not store.notes():
                store.create()
        except Exception:
            lock.close()
            raise
        self.lock, self.store = lock, store

    def snapshot(self):
        self.ensure_store()
        notes = [asdict(note) for note in self.store.notes()]
        for note in notes:
            note["body"] = self.pending.get(note["id"], note["body"])
        return {"notes": notes, "pending": bool(self.pending), "error": self.error}

    def publish(self):
        self.Event.emit(json.dumps(self.snapshot(), ensure_ascii=False))

    def flush(self):
        self.timer.stop()
        try:
            self.ensure_store()
            if self.pending:
                self.store.save(self.pending)
                self.pending.clear()
            self.error = ""
        except Exception as error:
            self.error = f"保存失败：{error}。修改仍保留在内存中，请修复后重试。"
            self.Event.emit(json.dumps({"error": self.error, "pending": bool(self.pending)}))
            return False
        self.publish()
        return True

    @Slot(str, result=str)
    def Request(self, payload):
        try:
            request = json.loads(payload)
            operation = request["op"]
            self.ensure_store()
            if operation == "snapshot":
                return json.dumps({"ok": True, "snapshot": self.snapshot()}, ensure_ascii=False)
            if operation == "edit":
                note_id = int(request["id"])
                body, expected = request["body"], request["expected"]
                if not isinstance(body, str) or not isinstance(expected, str):
                    raise ValueError("正文格式错误")
                if note_id in self.pending:
                    current = self.pending[note_id]
                else:
                    note = self.store.note(note_id)
                    if note is None:
                        raise ValueError("便签已被删除，当前修改未提交。")
                    current = note.body
                if current != expected:
                    raise ValueError("此便签已被另一小部件修改。当前草稿仍保留；请复制草稿后重新加载。")
                self.pending[note_id] = body
                self.timer.start()
                return json.dumps({"ok": True, "accepted": body}, ensure_ascii=False)
            if operation not in ("flush", "create", "rename", "delete", "stop", "prepare-ui"):
                raise ValueError("未知操作")
            if not self.flush():
                raise RuntimeError(self.error)
            if operation == "prepare-ui":
                source = xdg_path("XDG_DATA_HOME", ".local/share") / "plasma/plasmoids/org.marco.kstickynotes/contents/ui"
                cache = xdg_path("XDG_CACHE_HOME", ".cache") / "kstickynotes/ui"
                view = prepare_ui(source, cache)
                return json.dumps({"ok": True, "ui_url": view.as_uri(), "snapshot": self.snapshot()}, ensure_ascii=False)
            if operation == "create":
                created = self.store.create()
                self.publish()
                return json.dumps({"ok": True, "created": created.id, "snapshot": self.snapshot()}, ensure_ascii=False)
            if operation in ("rename", "delete"):
                note_id = int(request["id"])
                if not any(note.id == note_id for note in self.store.notes()):
                    raise ValueError("便签不存在")
                if operation == "rename":
                    title = request["title"].strip()
                    if not title:
                        raise ValueError("名称不能为空")
                    self.store.rename(note_id, title)
                else:
                    self.store.delete(note_id)
                self.publish()
            if operation == "stop":
                QTimer.singleShot(0, QCoreApplication.instance().quit)
            return json.dumps({"ok": True, "snapshot": self.snapshot()}, ensure_ascii=False)
        except Exception as error:
            return json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False)

    def shutdown(self):
        if self.flush():
            QCoreApplication.instance().quit()

    def close(self):
        self.timer.stop()
        if self.store is not None:
            self.store.close()
            self.store = None
        if self.lock is not None:
            self.lock.close()
            self.lock = None


def main():
    app = QCoreApplication([sys.argv[0]])
    app.setApplicationName("kstickynotes-service")
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        print("无法连接用户会话 D-Bus", file=sys.stderr)
        return 1
    if not bus.registerService(SERVICE):
        # Another service owns the name; never open a second database writer.
        return 0
    service = NotesService(data_directory())
    if not bus.registerObject(OBJECT_PATH, service, QDBusConnection.RegisterOption.ExportAllSlots |
                              QDBusConnection.RegisterOption.ExportAllSignals):
        print(bus.lastError().message(), file=sys.stderr)
        return 1
    timer = QTimer()
    timer.start(250)
    timer.timeout.connect(lambda: None)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: service.shutdown())
    app.aboutToQuit.connect(service.flush)
    try:
        return app.exec()
    finally:
        bus.unregisterObject(OBJECT_PATH)
        bus.unregisterService(SERVICE)
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
