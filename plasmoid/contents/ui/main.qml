pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.plasmoid

PlasmoidItem {
    id: root
    property int currentNote: Plasmoid.configuration.currentNote
    property bool pinned: false
    property bool preview: Plasmoid.configuration.preview
    readonly property var current: notesBackend.notes.find(note => note.id === currentNote)
    readonly property bool hasNote: current !== undefined
    property var settings: Plasmoid.configuration
    signal requestRename
    signal requestDelete
    signal focusEditor

    preferredRepresentation: compactRepresentation
    activationTogglesExpanded: true
    hideOnWindowDeactivate: !pinned && !notesBackend.error
    toolTipMainText: "KStickyNotes"
    toolTipSubText: notesBackend.error ? notesBackend.error : (notesBackend.pending || notesBackend.localChanges ? "有未保存修改" : "点击打开便签")
    Plasmoid.icon: "accessories-text-editor"
    Plasmoid.status: notesBackend.error ? PlasmaCore.Types.NeedsAttentionStatus : PlasmaCore.Types.ActiveStatus

    function reloadEditor() {
        expanded = true;
        Qt.callLater(() => {
            if (root.fullRepresentationItem)
                root.fullRepresentationItem.reloadView();
        });
    }

    function selectNote(noteId) {
        currentNote = noteId;
        Plasmoid.configuration.currentNote = noteId;
        focusEditor();
    }
    function cycle(direction) {
        if (!notesBackend.notes.length)
            return;
        const index = notesBackend.notes.findIndex(note => note.id === currentNote);
        selectNote(notesBackend.notes[(index + direction + notesBackend.notes.length) % notesBackend.notes.length].id);
    }
    function toggle() {
        expanded = !expanded;
    }
    function newNote() {
        expanded = true;
        notesBackend.createNote();
    }
    function renameNote() {
        if (hasNote)
            requestRename();
    }
    function deleteNote() {
        if (hasNote)
            requestDelete();
    }
    function hidePopup() {
        notesBackend.flush();
        if (!notesBackend.error)
            expanded = false;
    }
    onExpandedChanged: {
        if (expanded) {
            if (!notesBackend.ready && !notesBackend.busy)
                notesBackend.load();
            Qt.callLater(() => root.focusEditor());
        } else if (notesBackend.ready)
            notesBackend.flush();
    }
    onPreviewChanged: Plasmoid.configuration.preview = preview

    Backend {
        id: notesBackend
        onNotesChanged: {
            if (!notes.some(note => note.id === root.currentNote))
                root.selectNote(notes.length ? notes[0].id : -1);
        }
        onCreated: noteId => root.selectNote(noteId)
        onFailed: root.expanded = true
    }

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: "显示便签"
            icon.name: "accessories-text-editor"
            onTriggered: root.expanded = true
        },
        PlasmaCore.Action {
            text: "新建便签"
            icon.name: "document-new"
            enabled: notesBackend.ready && !notesBackend.error
            onTriggered: root.newNote()
        },
        PlasmaCore.Action {
            text: "立即保存"
            icon.name: "document-save"
            onTriggered: notesBackend.flush()
        },
        PlasmaCore.Action {
            text: "重新加载界面"
            icon.name: "view-refresh"
            enabled: !root.fullRepresentationItem || !root.fullRepresentationItem.reloading
            onTriggered: root.reloadEditor()
        }
    ]

    compactRepresentation: PlasmaComponents.ToolButton {
        objectName: "panelButton"
        icon.name: notesBackend.error ? "dialog-warning" : "accessories-text-editor"
        display: Controls.AbstractButton.IconOnly
        text: "KStickyNotes"
        checkable: true
        checked: root.expanded
        onClicked: root.toggle()
        Accessible.name: "打开或收起 KStickyNotes 便签"
    }

    fullRepresentation: ReloadableView {
        controller: root
        backend: notesBackend
    }
}
