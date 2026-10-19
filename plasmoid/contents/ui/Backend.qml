import QtQuick
import org.kde.plasma.workspace.dbus as DBus

Item {
    id: backend
    visible: false
    property var notes: []
    property var drafts: ({})
    property var acknowledged: ({})
    property var queue: []
    property bool busy: false
    property bool ready: false
    property bool pending: false
    property string error: ""
    property bool localChanges: Object.keys(drafts).length > 0
    signal failed
    signal created(int noteId)
    signal loaded

    function applySnapshot(snapshot) {
        if (snapshot.notes !== undefined) {
            notes = snapshot.notes;
            // Keep acknowledged text for optimistic conflict detection. Never
            // replace local drafts or editor text with background save results.
            if (!localChanges) {
                let bodies = {};
                for (const note of notes)
                    bodies[note.id] = note.body;
                acknowledged = bodies;
            }
            ready = true;
        }
        pending = snapshot.pending || false;
        error = snapshot.error || "";
        if (error)
            failed();
    }

    function body(noteId) {
        if (drafts[noteId] !== undefined)
            return drafts[noteId];
        if (acknowledged[noteId] !== undefined)
            return acknowledged[noteId];
        const note = notes.find(n => n.id === noteId);
        return note ? note.body : "";
    }

    function edit(noteId, text) {
        let next = Object.assign({}, drafts);
        next[noteId] = text;
        drafts = next;
        error = "";
        pending = true;
        pumpEdits();
    }

    function pumpEdits() {
        if (busy || queue.length || !ready || error)
            return;
        const ids = Object.keys(drafts);
        if (!ids.length)
            return;
        const id = Number(ids[0]);
        const body = drafts[id];
        const expected = acknowledged[id] === undefined ? "" : acknowledged[id];
        call({
            op: "edit",
            id: id,
            body: body,
            expected: expected
        }, reply => {
            let bodies = Object.assign({}, acknowledged);
            bodies[id] = reply.accepted;
            acknowledged = bodies;
            let next = Object.assign({}, drafts);
            if (next[id] === body)
                delete next[id];
            drafts = next;
        });
    }

    function enqueue(request, callback) {
        let next = queue.slice();
        next.push({
            request: request,
            callback: callback
        });
        queue = next;
        dispatch();
    }

    function dispatch() {
        if (busy)
            return;
        // Commands such as switching/deleting must first deliver all edits.
        if (localChanges && ready && !error) {
            const commands = queue;
            queue = [];
            pumpEdits();
            queue = commands;
            if (busy)
                return;
        }
        if (queue.length) {
            const next = queue[0];
            queue = queue.slice(1);
            call(next.request, next.callback);
        } else
            pumpEdits();
    }

    function call(request, callback) {
        busy = true;
        DBus.SessionBus.asyncCall({
            service: "org.kstickynotes.Service",
            path: "/Notes",
            iface: "org.kstickynotes.Notes1",
            member: "Request",
            signature: "(s)",
            arguments: [new DBus.string(JSON.stringify(request))]
        }, result => {
            try {
                const reply = JSON.parse(result.value);
                if (!reply.ok)
                    throw new Error(reply.error);
                error = "";
                if (callback)
                    callback(reply);
                if (reply.snapshot)
                    applySnapshot(reply.snapshot);
            } catch (problem) {
                error = String(problem);
                queue = [];
                failed();
            }
            busy = false;
            if (!error)
                dispatch();
        }, result => {
            error = "无法连接便签服务：" + result.error.message + "。请确认已安装服务后重试。";
            busy = false;
            queue = [];
            failed();
        });
    }

    function load() {
        if (busy)
            return;
        error = "";
        enqueue({
            op: "snapshot"
        }, () => loaded());
    }

    function reloadAfterConfirmation() {
        if (busy)
            return;
        drafts = ({});
        acknowledged = ({});
        queue = [];
        ready = false;
        load();
    }

    function flush() {
        error = "";
        enqueue({
            op: "flush"
        });
    }

    function createNote() {
        enqueue({
            op: "create"
        }, reply => created(reply.created));
    }

    function renameNote(id, title) {
        enqueue({
            op: "rename",
            id: id,
            title: title
        });
    }
    function deleteNote(id) {
        enqueue({
            op: "delete",
            id: id
        });
    }

    DBus.SignalWatcher {
        busType: DBus.BusType.Session
        service: "org.kstickynotes.Service"
        path: "/Notes"
        iface: "org.kstickynotes.Notes1"
        function dbusEvent(payload) {
            try {
                backend.applySnapshot(JSON.parse(payload));
            } catch (problem) {
                backend.error = String(problem);
                backend.failed();
            }
        }
    }
    Component.onCompleted: load()
}
