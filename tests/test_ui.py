import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from kstickynotes.storage import Store
from kstickynotes.instance import Instance
from kstickynotes.ui import Window
import kstickynotes.ui as ui


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    store = Store(tmp_path / "notes.db")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = Window(store, settings)
    yield window
    window.timer.stop()
    window.tray.hide()
    window.quitting = True
    window.close()
    window.deleteLater()
    app.processEvents()
    store.close()


def test_debounce_and_quit_flush(window, monkeypatch):
    page = window.tabs.currentWidget()
    for text in ("a", "ab", "abc"):
        page.editor.setPlainText(text)
    assert window.store.notes()[0].body == ""
    QTest.qWait(550)
    assert window.store.notes()[0].body == "abc"
    page.editor.setPlainText("pending at exit")
    monkeypatch.setattr(QApplication, "quit", lambda *_: None)
    window.request_quit()
    assert window.store.notes()[0].body == "pending at exit"
    assert window.quitting


def test_failed_save_preserves_dirty_and_prevents_exit(window, monkeypatch):
    page = window.tabs.currentWidget()
    page.editor.setPlainText("do not lose")
    original = window.store.save
    def fail(_):
        raise OSError("disk full")
    monkeypatch.setattr(window.store, "save", fail)
    window.request_quit()
    assert not window.quitting
    assert window.dirty[page.note_id] == "do not lose"
    assert not window.error_row.isHidden()
    monkeypatch.setattr(window.store, "save", original)
    assert window.flush()
    assert not window.dirty
    assert window.store.notes()[0].body == "do not lose"


def test_delete_confirm_rename_and_selection(window, monkeypatch):
    window.new_note()
    selected = window.tabs.currentWidget().note_id
    monkeypatch.setattr(ui, "dialog", lambda *a, **k: "改名")
    window.rename_note()
    assert window.store.notes()[-1].title == "改名"
    assert window.flush()
    assert window.settings.value("notes/current", type=int) == selected
    monkeypatch.setattr(ui, "dialog", lambda *a, **k: False)
    window.delete_note()
    assert window.tabs.count() == 2
    monkeypatch.setattr(ui, "dialog", lambda *a, **k: True)
    window.delete_note()
    assert window.tabs.count() == 1
    assert len(window.store.notes()) == 1


def test_close_hides_without_exiting(window, monkeypatch):
    monkeypatch.setattr(ui.QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    window.show()
    window.close()
    assert not window.isVisible()
    assert not window.quitting
    window.show_notes()
    assert window.isVisible()


def test_single_instance_wakes_primary(app, tmp_path):
    primary = Instance(tmp_path)
    secondary = Instance(tmp_path)
    assert primary.primary and not secondary.primary
    activations = []
    primary.activated.connect(lambda: activations.append(True))
    assert secondary.wake()
    QTest.qWait(100)
    assert activations == [True]
    primary.close()
    third = Instance(tmp_path)
    assert third.primary
    third.close()


def test_restart_restores_size_selection_and_text(window):
    window.resize(740, 510)
    window.new_note()
    page = window.tabs.currentWidget()
    page.editor.setPlainText("# Markdown\n\n- 中文")
    window.preview_action.setChecked(True)
    window.toggle_preview()
    assert "Markdown" in page.preview.toPlainText()
    assert window.flush()
    restored = Window(window.store, window.settings)
    assert restored.size() == window.size()
    assert restored.tabs.currentWidget().note_id == page.note_id
    assert restored.tabs.currentWidget().editor.toPlainText() == page.editor.toPlainText()
    restored.timer.stop()
    restored.tray.hide()
    restored.quitting = True
    restored.close()
    restored.deleteLater()


def send_wheel(widget, delta, modifiers=Qt.KeyboardModifier.NoModifier):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    event = QWheelEvent(QPointF(20, 20), QPointF(widget.mapToGlobal(QPoint(20, 20))),
                        QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                        modifiers, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


def test_window_ctrl_wheel_syncs_and_persists(window):
    page = window.tabs.currentWidget()
    original_text = page.editor.toPlainText()
    original_size = page.editor.font().pointSizeF()
    send_wheel(page.editor.viewport(), 120, Qt.KeyboardModifier.ControlModifier)
    assert window.zoom_percent == 110
    assert page.editor.font().pointSizeF() > original_size
    assert page.preview.font().pointSizeF() == page.editor.font().pointSizeF()
    assert not window.dirty
    send_wheel(page.preview.viewport(), -120, Qt.KeyboardModifier.ControlModifier)
    assert window.zoom_percent == 100
    assert page.editor.toPlainText() == original_text
    window.change_zoom(3)
    window.new_note()
    assert window.tabs.currentWidget().editor.font().pointSizeF() == page.editor.font().pointSizeF()
    window.preview_action.setChecked(True)
    window.toggle_preview()
    assert window.flush()
    restored = Window(window.store, window.settings)
    assert restored.zoom_percent == 130
    assert restored.preview_action.isChecked()
    restored.timer.stop()
    restored.tray.hide()
    restored.quitting = True
    restored.close()
    restored.deleteLater()


def test_window_zoom_limits_normal_scroll_and_focus_loss(window, app):
    from PySide6.QtCore import QEvent
    page = window.tabs.currentWidget()
    window.show_notes()
    page.editor.setPlainText('\n'.join('普通滚动测试' for _ in range(100)))
    page.editor.moveCursor(page.editor.textCursor().MoveOperation.Start)
    QTest.qWait(100)
    scroll = page.editor.verticalScrollBar()
    scroll.setValue(0)
    send_wheel(page.editor.viewport(), -120)
    assert scroll.value() > 0
    assert window.zoom_percent == 100
    window.change_zoom(100)
    assert window.zoom_percent == 300
    window.change_zoom(-100)
    assert window.zoom_percent == 50
    QApplication.sendEvent(window, QEvent(QEvent.Type.WindowDeactivate))
    assert window.isVisible()
    assert window.windowType() == Qt.WindowType.Window
    assert window.windowHandle().transientParent() is None


def test_tools_share_tab_row_and_tabs_still_scroll(window, app):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QToolButton
    for index in range(20):
        window.add_page(window.store.create(f'较长的标签 {index}'))
    window.resize(680, 440)
    window.show_notes()
    QTest.qWait(80)
    assert window.tabs.cornerWidget(Qt.Corner.TopLeftCorner) is window.note_tools
    bar = window.tabs.tabBar()
    buttons = window.note_tools.findChildren(QToolButton)
    assert len(buttons) == 4
    bar_center = bar.mapTo(window, bar.rect().center()).y()
    for button in buttons:
        center = button.mapTo(window, button.rect().center()).y()
        assert abs(center - bar_center) <= 3
    assert any(button.isVisible() for button in bar.findChildren(QToolButton))
    window.tabs.setCurrentIndex(window.tabs.count()-1)
    assert window.flush()
    assert window.settings.value('notes/current', type=int) == window.tabs.currentWidget().note_id
