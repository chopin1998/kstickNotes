import json
from pathlib import Path
from urllib.parse import unquote, urlparse
import pytest
from kstickynotes.ui_snapshot import prepare_ui
from kstickynotes.service import NotesService


def test_source_change_gets_new_url_and_old_snapshot_stays_valid(tmp_path):
    source = tmp_path/'source'
    source.mkdir()
    view = source/'NotesView.qml'
    view.write_text('import QtQuick\nItem { property int revision: 1 }')
    (source/'Helper.qml').write_text('import QtQuick\nItem {}')
    first = prepare_ui(source, tmp_path/'cache')
    assert prepare_ui(source, tmp_path/'cache') == first
    view.write_text('import QtQuick\nItem { property int revision: 2 }')
    second = prepare_ui(source, tmp_path/'cache')
    assert first != second
    assert 'revision: 1' in first.read_text()
    assert 'revision: 2' in second.read_text()
    assert (second.parent/'Helper.qml').exists()


def test_missing_view_does_not_create_snapshot(tmp_path):
    with pytest.raises(RuntimeError):
        prepare_ui(tmp_path/'missing',tmp_path/'cache')
    assert not (tmp_path/'cache').exists()


def test_prepare_ui_commits_pending_edits(qt_application, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'data'))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path/'cache'))
    source = tmp_path/'data/plasma/plasmoids/org.marco.kstickynotes/contents/ui'
    source.mkdir(parents=True)
    (source/'NotesView.qml').write_text('import QtQuick\nItem {}')
    service = NotesService(tmp_path/'notes')
    try:
        def request(**payload):
            return json.loads(service.Request(json.dumps(payload)))
        note = request(op='snapshot')['snapshot']['notes'][0]
        assert request(op='edit',id=note['id'],body='重载前未落盘',expected='')['ok']
        result = request(op='prepare-ui')
        assert result['ok'] and not service.pending
        assert service.store.notes()[0].body == '重载前未落盘'
        assert Path(unquote(urlparse(result['ui_url']).path)).exists()
    finally:
        service.close()


def test_prepare_ui_does_not_proceed_after_save_failure(qt_application, tmp_path, monkeypatch):
    service = NotesService(tmp_path/'notes')
    try:
        snapshot = json.loads(service.Request('{"op":"snapshot"}'))
        note = snapshot['snapshot']['notes'][0]
        service.Request(json.dumps({'op':'edit','id':note['id'],'body':'保留草稿','expected':''}))
        def fail(_): raise OSError('disk full')
        monkeypatch.setattr(service.store,'save',fail)
        result = json.loads(service.Request('{"op":"prepare-ui"}'))
        assert not result['ok']
        assert service.pending[note['id']] == '保留草稿'
    finally:
        service.close()
