import argparse
import os
import signal
import sys
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from .desktop import configure_desktop
from .instance import Instance
from .storage import Store, config_file, data_directory
from .ui import Window, dialog


def main():
    parser = argparse.ArgumentParser(description="KStickyNotes — KDE 桌面便签")
    parser.add_argument("--tray", action="store_true", help="启动时仅显示托盘图标")
    args = parser.parse_args()
    # Respect explicit overrides (including offscreen for tests).
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
    configure_desktop()
    app = QApplication([sys.argv[0]])
    app.setApplicationName("kstickynotes")
    app.setApplicationDisplayName("KStickyNotes")
    app.setOrganizationName("KStickyNotes")
    app.setDesktopFileName("org.kstickynotes.KStickyNotes")
    app.setQuitOnLastWindowClosed(False)
    instance = None
    store = None
    try:
        instance = Instance(data_directory())
        if not instance.primary:
            if instance.wake():
                return 0
            dialog(None, "KStickyNotes", "已有实例占用数据库，但暂时无法响应。请稍后重试。")
            return 1
        path = config_file()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        store = Store(data_directory() / "notes.sqlite3")
        settings = QSettings(str(path), QSettings.Format.IniFormat)
        window = Window(store, settings)
        instance.activated.connect(window.show_notes)
        # Keep Python able to dispatch SIGINT/SIGTERM while Qt owns the event loop.
        signal_timer = QTimer()
        signal_timer.start(250)
        signal_timer.timeout.connect(lambda: None)
        previous = {sig: signal.signal(sig, lambda *_: window.request_quit())
                    for sig in (signal.SIGINT, signal.SIGTERM)}
        app.commitDataRequest.connect(lambda manager: manager.cancel() if not window.flush() else None)
        app.aboutToQuit.connect(window.flush)
        if not args.tray or not QSystemTrayIcon.isSystemTrayAvailable():
            window.show_notes()
        try:
            return app.exec()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    except Exception as error:
        dialog(None, "KStickyNotes 启动失败", f"无法打开便签：{error}\n现有数据库未被替换。")
        return 1
    finally:
        if store is not None:
            store.close()
        if instance is not None:
            instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
