import QtQuick
import QtTest
import org.kde.kirigami as Kirigami
import "../../plasmoid/contents/ui" as Notes

Rectangle {
    id: captureCanvas
    color: Kirigami.Theme.backgroundColor
    width: 950
    height: 600
    Notes.Backend {
        id: testBackend
        onNotesChanged: {
            if (!notes.some(n => n.id === testController.currentNote))
                testController.selectNote(notes.length ? notes[0].id : -1);
        }
        onCreated: noteId => testController.selectNote(noteId)
    }
    QtObject {
        id: testSettings
        property int popupWidth: 580
        property int popupHeight: 420
        property int textZoom: 100
    }
    Item {
        id: testController
        property int currentNote: -1
        property bool expanded: true
        property bool preview: false
        property bool pinned: false
        property var settings: testSettings
        readonly property var current: testBackend.notes.find(n => n.id === currentNote)
        readonly property bool hasNote: current !== undefined
        signal focusEditor
        signal requestRename
        signal requestDelete
        function selectNote(id) {
            currentNote = id;
            focusEditor();
        }
        function newNote() {
            testBackend.createNote();
        }
        function renameNote() {
            requestRename();
        }
        function deleteNote() {
            requestDelete();
        }
        function hidePopup() {
            testBackend.flush();
            expanded = false;
        }
        function cycle(direction) {
            const index = testBackend.notes.findIndex(n => n.id === currentNote);
            selectNote(testBackend.notes[(index + direction + testBackend.notes.length) % testBackend.notes.length].id);
        }
    }
    Notes.NotesView {
        id: view
        anchors.fill: parent
        controller: testController
        backend: testBackend
    }
    Component {
        id: reloadableComponent
        Notes.ReloadableView {}
    }
    TestCase {
        name: "NativeNotes"
        when: windowShown
        function initTestCase() {
            tryVerify(() => testBackend.ready, 8000, testBackend.error);
            compare(testBackend.error, "");
        }
        function test_01_edit_markdown_and_save() {
            const editor = findChild(view, "noteEditor");
            verify(editor !== null);
            editor.forceActiveFocus();
            editor.text = "# 中文便签\n\n**原生 Plasma**";
            testController.preview = true;
            tryVerify(() => !testBackend.pending && !testBackend.localChanges && !testBackend.busy, 5000, testBackend.error);
            compare(testBackend.error, "");
            compare(testBackend.notes[0].body, editor.text);
            verify(findChild(view, "markdownPreview").visible);
            // Fast edits while an IPC reply is in flight must keep the final text.
            editor.text = "a";
            editor.text = "ab";
            editor.text = "最后一次输入";
            tryVerify(() => !testBackend.pending && !testBackend.localChanges && !testBackend.busy, 5000, testBackend.error);
            compare(testBackend.notes[0].body, "最后一次输入");
        }
        function test_02_new_and_switch_preserves_text() {
            mouseClick(findChild(view, "newNoteButton"));
            tryVerify(() => testBackend.notes.length === 2 && !testBackend.busy, 5000, testBackend.error);
            const editor = findChild(view, "noteEditor");
            compare(editor.text, "");
            editor.text = "第二页";
            testController.cycle(-1);
            compare(editor.text, "最后一次输入");
            testController.cycle(1);
            compare(editor.text, "第二页");
            tryVerify(() => !testBackend.busy && !testBackend.localChanges, 5000, testBackend.error);
            // The backend has accepted the text but its 400ms save may still be pending.
            testController.cycle(-1);
            testController.cycle(1);
            compare(editor.text, "第二页");
            tryVerify(() => !testBackend.pending && !testBackend.localChanges && !testBackend.busy, 5000, testBackend.error);
        }
        function test_03_rename_and_delete_confirmation() {
            testController.renameNote();
            const input = findChild(view, "renameInput");
            input.text = "工作记录";
            findChild(view, "renameDialog").accept();
            tryVerify(() => testBackend.notes.some(n => n.title === "工作记录") && !testBackend.busy, 5000, testBackend.error);
            testController.deleteNote();
            const dialog = findChild(view, "deleteDialog");
            verify(dialog.opened);
            dialog.reject();
            compare(testBackend.notes.length, 2);
            testController.deleteNote();
            dialog.accept();
            tryVerify(() => testBackend.notes.length === 1 && !testBackend.busy, 5000, testBackend.error);
            compare(findChild(view, "noteEditor").text, "最后一次输入");
        }
        function test_04_collapse_does_not_drop_final_edit() {
            const editor = findChild(view, "noteEditor");
            editor.text = "收起前的输入";
            testController.hidePopup();
            tryVerify(() => !testBackend.pending && !testBackend.localChanges && !testBackend.busy, 5000, testBackend.error);
            compare(testBackend.notes[0].body, "收起前的输入");
            compare(testBackend.error, "");
        }
        function test_05_preview_capture() {
            testController.expanded = true;
            const editor = findChild(view, "noteEditor");
            editor.text = "# 今天的计划\n\n- [x] 使用 KDE 原生小部件\n- [ ] 整理工作笔记\n- [ ] 记录灵感\n\n**输入会自动保存。**";
            testController.preview = true;
            wait(250);
            let saved = false;
            captureCanvas.grabToImage(result => {
                saved = result.saveToFile(Qt.resolvedUrl("../widget-preview.png").toString().replace("file://", ""));
            });
            tryVerify(() => saved, 3000);
            testBackend.flush();
            tryVerify(() => !testBackend.pending && !testBackend.localChanges && !testBackend.busy, 5000);
        }
        function test_06_ctrl_wheel_changes_both_fonts() {
            const editor = findChild(view, "noteEditor");
            const preview = findChild(view, "markdownPreview");
            const originalText = editor.text;
            testController.preview = true;
            testSettings.textZoom = 100;
            const originalSize = editor.font.pointSize;
            mouseWheel(editor, 30, 30, 0, 120, Qt.NoButton, Qt.ControlModifier);
            tryCompare(view, "textZoom", 110);
            verify(editor.font.pointSize > originalSize);
            compare(preview.font.pointSize, editor.font.pointSize);
            mouseWheel(preview, 30, 30, 0, -120, Qt.NoButton, Qt.ControlModifier);
            tryCompare(view, "textZoom", 100);
            fuzzyCompare(editor.font.pointSize, originalSize, 0.01);
            mouseWheel(editor, 30, 30, 0, 120, Qt.NoButton, Qt.NoModifier);
            compare(view.textZoom, 100);
            compare(editor.text, originalText);
            compare(testSettings.textZoom, 100);
            // Unmodified wheel events still reach the underlying ScrollView.
            editor.text = Array(100).fill("普通滚动测试").join("\n");
            editor.cursorPosition = 0;
            const scroll = findChild(view, "noteScroll").contentItem;
            tryVerify(() => scroll.contentHeight > scroll.height);
            wait(100);
            scroll.contentY = 0;
            mouseWheel(editor, 30, 30, 0, -120, Qt.NoButton, Qt.NoModifier);
            tryVerify(() => scroll.contentY > 0);
            compare(view.textZoom, 100);
            editor.text = originalText;
            testBackend.flush();
            tryVerify(() => !testBackend.pending && !testBackend.localChanges && !testBackend.busy, 5000);
        }
        function test_07_zoom_limits_and_recreation() {
            const editor = findChild(view, "noteEditor");
            mouseWheel(editor, 30, 30, 0, 120 * 100, Qt.NoButton, Qt.ControlModifier);
            tryCompare(view, "textZoom", 300);
            mouseWheel(editor, 30, 30, 0, -120 * 100, Qt.NoButton, Qt.ControlModifier);
            tryCompare(view, "textZoom", 50);
            testSettings.textZoom = 130;
            // A freshly created popup must read the saved widget configuration.
            const component = Qt.createComponent("../../plasmoid/contents/ui/NotesView.qml");
            compare(component.status, Component.Ready, component.errorString());
            const restored = component.createObject(captureCanvas, {
                controller: testController,
                backend: testBackend,
                visible: false
            });
            verify(restored !== null);
            compare(restored.textZoom, 130);
            fuzzyCompare(findChild(restored, "noteEditor").font.pointSize, editor.font.pointSize, 0.01);
            restored.destroy();
            testSettings.textZoom = 100;
        }
        function test_08_save_status_keeps_editor_geometry() {
            tryVerify(() => !testBackend.pending && !testBackend.busy && !testBackend.localChanges, 5000);
            const scroll = findChild(view, "noteScroll");
            const preview = findChild(view, "previewScroll");
            const row = findChild(view, "statusRow");
            const editor = findChild(view, "noteEditor");
            // Exercise the popup's preferred dimensions, as an adaptive host does.
            testSettings.popupWidth = 580;
            testSettings.popupHeight = 420;
            captureCanvas.width = view.implicitWidth;
            captureCanvas.height = view.implicitHeight;
            testController.preview = true;
            wait(100);
            function geometry() {
                const top = scroll.mapToItem(view, 0, 0);
                return {
                    x: top.x,
                    y: top.y,
                    width: scroll.width,
                    height: scroll.height,
                    previewWidth: preview.width,
                    previewHeight: preview.height,
                    footerHeight: row.height,
                    implicitWidth: view.implicitWidth,
                    implicitHeight: view.implicitHeight
                };
            }
            const saved = geometry();
            for (let i = 0; i < 6; ++i) {
                testBackend.pending = !testBackend.pending;
                wait(20);
                compare(geometry(), saved, "Status changes must not move or resize the editor");
            }
            compare(row.implicitWidth, 0);
            // A real save also refreshes the notebook model; geometry stays fixed.
            editor.forceActiveFocus();
            const original = editor.text;
            editor.text = original + "\n保存状态布局测试";
            wait(20);
            compare(geometry(), saved);
            tryVerify(() => !testBackend.pending && !testBackend.busy && !testBackend.localChanges, 5000);
            compare(geometry(), saved);
            editor.text = original;
            testBackend.flush();
            tryVerify(() => !testBackend.pending && !testBackend.busy && !testBackend.localChanges, 5000);
            compare(geometry(), saved);
        }
        function test_09_reload_flushes_edits_and_keeps_view_state() {
            view.visible = false;
            const reloader = reloadableComponent.createObject(captureCanvas, {
                controller: testController,
                backend: testBackend,
                width: captureCanvas.width,
                height: captureCanvas.height
            });
            verify(reloader !== null);
            tryVerify(() => reloader.item !== null && !reloader.reloading, 8000, reloader.loadError);
            const oldView = reloader.item;
            const editor = findChild(oldView, "noteEditor");
            const original = editor.text;
            testController.preview = true;
            testController.pinned = true;
            testSettings.textZoom = 140;
            editor.text = "重载前最后一次输入";
            editor.select(1, 4);
            const selectionStart = editor.selectionStart;
            const selectionEnd = editor.selectionEnd;
            const noteId = testController.currentNote;
            reloader.reloadView();
            tryVerify(() => !reloader.reloading, 8000, reloader.loadError);
            compare(reloader.loadError, "");
            verify(reloader.item !== oldView);
            const restored = findChild(reloader.item, "noteEditor");
            tryCompare(restored, "text", "重载前最后一次输入");
            tryCompare(restored, "selectionStart", selectionStart);
            compare(restored.selectionEnd, selectionEnd);
            compare(testController.currentNote, noteId);
            compare(reloader.item.textZoom, 140);
            verify(testController.preview && testController.pinned);
            tryVerify(() => !testBackend.pending && !testBackend.localChanges && !testBackend.busy, 5000);
            compare(testBackend.notes.find(n => n.id === noteId).body, "重载前最后一次输入");
            restored.text = original;
            testBackend.flush();
            tryVerify(() => !testBackend.pending && !testBackend.localChanges && !testBackend.busy, 5000);
            reloader.destroy();
            testSettings.textZoom = 100;
            view.visible = true;
        }
    }
}
