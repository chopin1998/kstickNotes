pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents

Item {
    id: shell
    required property var controller
    required property var backend
    property bool reloading: false
    property string loadError: ""
    property int activeSlot: -1
    property int generation: 0
    property var savedState: null
    readonly property var item: activeSlot === 0 ? first.item : (activeSlot === 1 ? second.item : null)
    signal reloaded

    implicitWidth: controller.settings.popupWidth
    implicitHeight: controller.settings.popupHeight
    Layout.minimumWidth: Kirigami.Units.gridUnit * 20
    Layout.minimumHeight: Kirigami.Units.gridUnit * 14
    Layout.preferredWidth: controller.settings.popupWidth
    Layout.preferredHeight: controller.settings.popupHeight

    function reloadView() {
        if (reloading)
            return;
        savedState = item && item.captureViewState ? item.captureViewState() : null;
        reloading = true;
        loadError = "";
        const attempt = ++generation;
        // Backend.dispatch drains edits before this request. The service only
        // publishes a snapshot after committing every pending note transaction.
        backend.enqueue({
            op: "prepare-ui"
        }, reply => {
            if (!shell.reloading || attempt !== shell.generation)
                return;
            const candidate = shell.activeSlot === 0 ? second : first;
            candidate.setSource(reply.ui_url, {
                controller: shell.controller,
                backend: shell.backend
            });
        });
    }

    function cancelReload(message) {
        if (!reloading)
            return;
        ++generation;
        reloading = false;
        loadError = "重载失败，已保留原编辑器：" + message;
        const candidate = activeSlot === 0 ? second : first;
        candidate.source = "";
    }

    function finishLoad(candidate, slot) {
        if (!reloading)
            return;
        const previous = activeSlot === 0 ? first : second;
        activeSlot = slot;
        reloading = false;
        loadError = "";
        if (previous !== candidate)
            previous.source = "";
        const state = savedState;
        Qt.callLater(() => {
            shell.controller.focusEditor();
            if (shell.item && state && shell.item.restoreViewState)
                shell.item.restoreViewState(state);
            shell.reloaded();
        });
    }

    Loader {
        id: first
        anchors.fill: parent
        visible: shell.activeSlot === 0
        enabled: visible && !shell.reloading
        onLoaded: shell.finishLoad(first, 0)
        onStatusChanged: if (status === Loader.Error)
            shell.cancelReload("新版界面无法加载，请检查 QML 文件后重试。")
    }
    Loader {
        id: second
        anchors.fill: parent
        visible: shell.activeSlot === 1
        enabled: visible && !shell.reloading
        onLoaded: shell.finishLoad(second, 1)
        onStatusChanged: if (status === Loader.Error)
            shell.cancelReload("新版界面无法加载，请检查 QML 文件后重试。")
    }
    Connections {
        target: shell.backend
        function onFailed() {
            shell.cancelReload(shell.backend.error);
        }
    }
    PlasmaComponents.Label {
        anchors.centerIn: parent
        visible: shell.item === null && !shell.reloading
        text: "等待加载便签界面…"
    }
    Controls.BusyIndicator {
        anchors.centerIn: parent
        running: shell.reloading
        visible: running
    }
    Kirigami.InlineMessage {
        anchors {
            top: parent.top
            left: parent.left
            right: parent.right
        }
        z: 10
        visible: shell.loadError !== ""
        type: Kirigami.MessageType.Error
        text: shell.loadError
        actions: Kirigami.Action {
            text: "重试重载"
            onTriggered: shell.reloadView()
        }
    }
    Component.onCompleted: reloadView()
}
