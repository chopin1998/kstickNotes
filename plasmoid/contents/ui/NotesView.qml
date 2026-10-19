pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents

Item {
    id: popup
    required property var controller
    required property var backend
    readonly property var root: popup.controller
    readonly property int textZoom: Math.max(50, Math.min(300, popup.root.settings.textZoom || 100))
    readonly property real noteFontSize: (Kirigami.Theme.defaultFont.pointSize > 0 ? Kirigami.Theme.defaultFont.pointSize : 10) * textZoom / 100
    property real wheelSteps: 0

    function captureViewState() {
        return {
            noteId: popup.root.currentNote,
            cursor: editor.cursorPosition,
            selectionStart: editor.selectionStart,
            selectionEnd: editor.selectionEnd,
            scrollY: noteScroll.contentItem.contentY,
            previewY: previewScroll.contentItem.contentY
        };
    }
    function restoreViewState(state) {
        if (state.noteId !== popup.root.currentNote)
            return;
        editor.cursorPosition = Math.min(state.cursor, editor.length);
        if (state.selectionStart !== state.selectionEnd)
            editor.select(Math.min(state.selectionStart, editor.length), Math.min(state.selectionEnd, editor.length));
        noteScroll.contentItem.contentY = Math.max(0, Math.min(state.scrollY, noteScroll.contentItem.contentHeight - noteScroll.contentItem.height));
        previewScroll.contentItem.contentY = Math.max(0, Math.min(state.previewY, previewScroll.contentItem.contentHeight - previewScroll.contentItem.height));
    }

    function changeFontZoom(steps) {
        popup.root.settings.textZoom = Math.max(50, Math.min(300, popup.textZoom + steps * 10));
    }

    function zoomWheel(event) {
        const delta = event.angleDelta.y ? event.angleDelta.y / 120 : event.pixelDelta.y / 40;
        if (!delta) {
            event.accepted = false;
            return;
        }
        popup.wheelSteps += delta;
        const steps = Math.trunc(popup.wheelSteps);
        if (steps) {
            popup.changeFontZoom(steps);
            popup.wheelSteps -= steps;
        }
        event.accepted = true;
    }
    Connections {
        target: popup.root
        function onRequestRename() {
            renameInput.text = popup.root.current.title;
            renameDialog.targetId = popup.root.currentNote;
            renameDialog.open();
            renameInput.selectAll();
            renameInput.forceActiveFocus();
        }
        function onRequestDelete() {
            deleteDialog.targetId = popup.root.currentNote;
            deleteLabel.text = "确定永久删除“" + popup.root.current.title + "”及其内容？";
            deleteDialog.open();
        }
    }
    objectName: "notesPopup"
    // Plasma may query implicit size when the panel adapts to its contents.
    // Derive it from the saved popup size, never from transient status text.
    implicitWidth: popup.root.settings.popupWidth
    implicitHeight: popup.root.settings.popupHeight
    Layout.minimumWidth: Kirigami.Units.gridUnit * 20
    Layout.minimumHeight: Kirigami.Units.gridUnit * 14
    Layout.preferredWidth: popup.root.settings.popupWidth
    Layout.preferredHeight: popup.root.settings.popupHeight
    onWidthChanged: sizeTimer.restart()
    onHeightChanged: sizeTimer.restart()
    Timer {
        id: sizeTimer
        interval: 400
        onTriggered: {
            if (popup.width >= popup.Layout.minimumWidth && popup.height >= popup.Layout.minimumHeight) {
                popup.root.settings.popupWidth = Math.round(popup.width);
                popup.root.settings.popupHeight = Math.round(popup.height);
            }
        }
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing
        RowLayout {
            Layout.fillWidth: true
            PlasmaComponents.Label {
                text: "KStickyNotes"
                font.bold: true
                Layout.fillWidth: true
            }
            PlasmaComponents.ToolButton {
                objectName: "newNoteButton"
                icon.name: "document-new"
                display: Controls.AbstractButton.IconOnly
                text: "新建便签"
                enabled: popup.backend.ready && !popup.backend.error
                onClicked: popup.root.newNote()
                Controls.ToolTip.text: text
                Controls.ToolTip.visible: hovered
            }
            PlasmaComponents.ToolButton {
                icon.name: "edit-rename"
                display: Controls.AbstractButton.IconOnly
                text: "重命名"
                enabled: popup.root.hasNote && !popup.backend.error
                onClicked: popup.root.renameNote()
                Controls.ToolTip.text: text
                Controls.ToolTip.visible: hovered
            }
            PlasmaComponents.ToolButton {
                icon.name: "edit-delete"
                display: Controls.AbstractButton.IconOnly
                text: "删除便签"
                enabled: popup.root.hasNote && !popup.backend.error
                onClicked: popup.root.deleteNote()
                Controls.ToolTip.text: text
                Controls.ToolTip.visible: hovered
            }
            PlasmaComponents.ToolButton {
                icon.name: "document-preview"
                display: Controls.AbstractButton.IconOnly
                text: "Markdown 预览"
                checkable: true
                checked: popup.root.preview
                onClicked: popup.root.preview = !popup.root.preview
                Controls.ToolTip.text: text
                Controls.ToolTip.visible: hovered
            }
            PlasmaComponents.ToolButton {
                icon.name: "window-pin"
                display: Controls.AbstractButton.IconOnly
                text: "保持弹出"
                checkable: true
                checked: popup.root.pinned
                onClicked: popup.root.pinned = !popup.root.pinned
                Controls.ToolTip.text: text
                Controls.ToolTip.visible: hovered
            }
            PlasmaComponents.ToolButton {
                icon.name: "window-close"
                display: Controls.AbstractButton.IconOnly
                text: "收起便签"
                onClicked: popup.root.hidePopup()
                Controls.ToolTip.text: text
                Controls.ToolTip.visible: hovered
            }
        }
        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: popup.backend.error !== ""
            type: Kirigami.MessageType.Error
            text: popup.backend.error
            actions: [
                Kirigami.Action {
                    text: "重试"
                    onTriggered: popup.backend.ready ? popup.backend.flush() : popup.backend.load()
                },
                Kirigami.Action {
                    text: "复制草稿"
                    onTriggered: {
                        editor.selectAll();
                        editor.copy();
                        editor.deselect();
                    }
                },
                Kirigami.Action {
                    text: "重新加载"
                    enabled: !popup.backend.busy
                    onTriggered: reloadDialog.open()
                }
            ]
        }
        RowLayout {
            Layout.fillWidth: true
            visible: popup.backend.notes.length > 0
            PlasmaComponents.ToolButton {
                icon.name: "go-previous"
                display: Controls.AbstractButton.IconOnly
                text: "上一条便签"
                enabled: tabList.contentX > 0
                onClicked: tabList.contentX = Math.max(0, tabList.contentX - tabList.width / 2)
            }
            ListView {
                id: tabList
                objectName: "noteTabs"
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 2
                orientation: ListView.Horizontal
                clip: true
                spacing: Kirigami.Units.smallSpacing
                model: popup.backend.notes
                currentIndex: popup.backend.notes.findIndex(note => note.id === popup.root.currentNote)
                onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
                boundsBehavior: Flickable.StopAtBounds
                delegate: PlasmaComponents.ToolButton {
                    required property var modelData
                    height: tabList.height
                    text: modelData.title
                    checkable: true
                    checked: modelData.id === popup.root.currentNote
                    onClicked: popup.root.selectNote(modelData.id)
                    onDoubleClicked: popup.root.renameNote()
                }
            }
            PlasmaComponents.ToolButton {
                icon.name: "go-next"
                display: Controls.AbstractButton.IconOnly
                text: "下一条便签"
                enabled: tabList.contentX < tabList.contentWidth - tabList.width
                onClicked: tabList.contentX = Math.min(tabList.contentWidth - tabList.width, tabList.contentX + tabList.width / 2)
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: popup.root.hasNote
            Controls.ScrollView {
                id: noteScroll
                objectName: "noteScroll"
                Layout.preferredWidth: 1
                Layout.fillWidth: true
                Layout.fillHeight: true
                PlasmaComponents.TextArea {
                    id: editor
                    WheelHandler {
                        target: null
                        acceptedModifiers: Qt.ControlModifier
                        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                        onWheel: event => popup.zoomWheel(event)
                    }
                    font.pointSize: popup.noteFontSize
                    objectName: "noteEditor"
                    property bool loading: false
                    wrapMode: TextEdit.Wrap
                    textFormat: TextEdit.PlainText
                    placeholderText: "直接输入便签，支持 Markdown…"
                    selectByMouse: true
                    Accessible.name: "便签正文"
                    function loadText() {
                        loading = true;
                        text = popup.backend.body(popup.root.currentNote);
                        loading = false;
                    }
                    onTextChanged: {
                        if (!loading && popup.root.hasNote && text !== popup.backend.body(popup.root.currentNote))
                            popup.backend.edit(popup.root.currentNote, text);
                    }
                    Component.onCompleted: loadText()
                    Connections {
                        target: popup.root
                        function onCurrentNoteChanged() {
                            editor.loadText();
                        }
                        function onFocusEditor() {
                            if (popup.root.expanded)
                                editor.forceActiveFocus();
                        }
                    }
                    Connections {
                        target: popup.backend
                        function onNotesChanged() {
                            if (!editor.activeFocus && !popup.backend.localChanges)
                                editor.loadText();
                        }
                    }
                }
            }
            Controls.ScrollView {
                id: previewScroll
                objectName: "previewScroll"
                Layout.preferredWidth: 1
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: popup.root.preview
                PlasmaComponents.TextArea {
                    id: markdown
                    WheelHandler {
                        target: null
                        acceptedModifiers: Qt.ControlModifier
                        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                        onWheel: event => popup.zoomWheel(event)
                    }
                    font.pointSize: popup.noteFontSize
                    objectName: "markdownPreview"
                    text: editor.text
                    textFormat: TextEdit.MarkdownText
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    onLinkActivated: link => {
                        if (/^(https?:|mailto:)/i.test(link))
                            Qt.openUrlExternally(link);
                    }
                    Accessible.name: "Markdown 预览"
                }
            }
        }
        PlasmaComponents.Label {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !popup.root.hasNote
            text: popup.backend.ready ? "没有便签，点击右上角新建。" : "正在连接便签服务…"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        Item {
            id: statusRow
            objectName: "statusRow"
            // Anchored text does not contribute its changing implicit width or
            // glyph-dependent height to ColumnLayout or the popup's size hints.
            implicitWidth: 0
            Layout.fillWidth: true
            Layout.minimumHeight: Math.ceil(statusMetrics.height) + Kirigami.Units.smallSpacing
            Layout.preferredHeight: Layout.minimumHeight
            Layout.maximumHeight: Layout.minimumHeight
            FontMetrics {
                id: statusMetrics
                font: Kirigami.Theme.defaultFont
            }
            PlasmaComponents.Label {
                objectName: "saveStatus"
                anchors.fill: parent
                font: Kirigami.Theme.defaultFont
                textFormat: Text.PlainText
                wrapMode: Text.NoWrap
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
                text: popup.backend.error ? "保存失败 · 草稿仍保留，请勿强制结束服务" : (popup.backend.pending || popup.backend.localChanges ? "正在自动保存…" : "已保存")
                opacity: 0.75
            }
        }
    }
    Controls.Dialog {
        id: renameDialog
        objectName: "renameDialog"
        property int targetId: -1
        title: "重命名便签"
        anchors.centerIn: parent
        width: Math.min(popup.width - 20, Kirigami.Units.gridUnit * 20)
        modal: true
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel
        contentItem: PlasmaComponents.TextField {
            id: renameInput
            objectName: "renameInput"
            Accessible.name: "便签名称"
            onAccepted: {
                if (text.trim())
                    renameDialog.accept();
            }
        }
        onAccepted: {
            if (renameInput.text.trim())
                popup.backend.renameNote(targetId, renameInput.text);
        }
    }
    Controls.Dialog {
        id: deleteDialog
        objectName: "deleteDialog"
        property int targetId: -1
        title: "删除便签"
        anchors.centerIn: parent
        width: Math.min(popup.width - 20, Kirigami.Units.gridUnit * 20)
        modal: true
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel
        contentItem: PlasmaComponents.Label {
            id: deleteLabel
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
        }
        onAccepted: popup.backend.deleteNote(targetId)
        onOpened: standardButton(Controls.Dialog.Cancel).forceActiveFocus()
    }
    Controls.Dialog {
        id: reloadDialog
        title: "重新加载便签"
        anchors.centerIn: parent
        width: Math.min(popup.width - 20, Kirigami.Units.gridUnit * 20)
        modal: true
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel
        contentItem: PlasmaComponents.Label {
            text: "这会放弃尚未送达保存服务的本地草稿。请先复制需要保留的文字。确定重新加载？"
            wrapMode: Text.Wrap
        }
        onAccepted: {
            popup.backend.reloadAfterConfirmation();
            popup.forceActiveFocus();
        }
        onOpened: standardButton(Controls.Dialog.Cancel).forceActiveFocus()
    }
    Shortcut {
        sequence: "Ctrl+N"
        enabled: popup.root.expanded
        onActivated: popup.root.newNote()
    }
    Shortcut {
        sequence: "F2"
        enabled: popup.root.expanded
        onActivated: popup.root.renameNote()
    }
    Shortcut {
        sequence: "Ctrl+Shift+D"
        enabled: popup.root.expanded
        onActivated: popup.root.deleteNote()
    }
    Shortcut {
        sequence: "Ctrl+S"
        enabled: popup.root.expanded
        onActivated: popup.backend.flush()
    }
    Shortcut {
        sequence: "Ctrl+Tab"
        enabled: popup.root.expanded
        onActivated: popup.root.cycle(1)
    }
    Shortcut {
        sequence: "Ctrl+Shift+Tab"
        enabled: popup.root.expanded
        onActivated: popup.root.cycle(-1)
    }
    Shortcut {
        sequence: "Ctrl+Shift+M"
        enabled: popup.root.expanded
        onActivated: popup.root.preview = !popup.root.preview
    }
    Shortcut {
        sequence: "Escape"
        enabled: popup.root.expanded
        onActivated: popup.root.hidePopup()
    }
}
