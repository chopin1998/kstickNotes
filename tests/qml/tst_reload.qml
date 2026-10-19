import QtQuick
import QtTest
import "../../plasmoid/contents/ui" as Notes

Item {
    id: canvas
    width: 580
    height: 420
    QtObject {
        id: testSettings
        property int popupWidth: 580
        property int popupHeight: 420
    }
    Item {
        id: controller
        property var settings: testSettings
        signal focusEditor
    }
    Item {
        id: backend
        property string error: ""
        property bool failSave: false
        property url nextUrl: Qt.resolvedUrl("probes/First.qml")
        signal failed
        function enqueue(request, callback) {
            Qt.callLater(() => {
                if (backend.failSave) {
                    backend.error = "模拟保存失败";
                    backend.failed();
                } else
                    callback({
                        ui_url: backend.nextUrl
                    });
            });
        }
    }
    Component {
        id: factory
        Notes.ReloadableView {}
    }
    TestCase {
        name: "ReloadSafety"
        when: windowShown
        property var shell: null
        function initTestCase() {
            shell = factory.createObject(canvas, {
                controller: controller,
                backend: backend,
                width: 580,
                height: 420
            });
            verify(shell !== null);
            tryVerify(() => shell.item !== null && !shell.reloading, 5000, shell.loadError);
        }
        function test_01_loads_updated_code() {
            compare(shell.item.revision, "first");
            backend.nextUrl = Qt.resolvedUrl("probes/Second.qml");
            shell.reloadView();
            tryVerify(() => !shell.reloading, 5000);
            compare(shell.item.revision, "second");
            compare(shell.loadError, "");
        }
        function test_02_save_failure_keeps_old_editor() {
            const previous = shell.item;
            backend.failSave = true;
            shell.reloadView();
            tryVerify(() => !shell.reloading, 5000);
            compare(shell.item, previous);
            verify(shell.item.enabled);
            verify(shell.loadError.indexOf("模拟保存失败") >= 0);
            backend.failSave = false;
            backend.error = "";
        }
        function test_03_broken_qml_keeps_old_editor_and_can_retry() {
            const previous = shell.item;
            backend.nextUrl = Qt.resolvedUrl("probes/Broken.qml");
            shell.reloadView();
            tryVerify(() => !shell.reloading, 5000);
            compare(shell.item, previous);
            verify(shell.item.enabled);
            verify(shell.loadError !== "");
            backend.nextUrl = Qt.resolvedUrl("probes/First.qml");
            shell.reloadView();
            tryVerify(() => !shell.reloading, 5000);
            compare(shell.item.revision, "first");
            compare(shell.loadError, "");
        }
        function cleanupTestCase() {
            if (shell)
                shell.destroy();
        }
    }
}
