import json
import sqlite3
import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest
from kstickynotes.service import NotesService


@pytest.fixture
def service(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    service = NotesService(tmp_path)
    yield service
    service.close()


def request(service, **message):
    return json.loads(service.Request(json.dumps(message)))


def test_service_debounce_and_conflicts(service):
    note = request(service, op='snapshot')['snapshot']['notes'][0]
    assert request(service, op='edit', id=note['id'], body='第一稿', expected='')['ok']
    assert service.store.notes()[0].body == ''
    assert not request(service, op='edit', id=note['id'], body='覆盖', expected='')['ok']
    assert request(service, op='edit', id=note['id'], body='第二稿', expected='第一稿')['ok']
    QTest.qWait(550)
    assert service.store.notes()[0].body == '第二稿'
    assert not service.pending


def test_failed_save_keeps_pending_and_retries(service, monkeypatch):
    note = request(service, op='snapshot')['snapshot']['notes'][0]
    request(service, op='edit', id=note['id'], body='不能丢', expected='')
    original = service.store.save
    def fail(_):
        raise OSError('disk full')
    monkeypatch.setattr(service.store, 'save', fail)
    assert not request(service, op='flush')['ok']
    assert service.pending[note['id']] == '不能丢'
    assert not request(service, op='delete', id=note['id'])['ok']
    monkeypatch.setattr(service.store, 'save', original)
    assert request(service, op='flush')['ok']
    assert service.store.notes()[0].body == '不能丢'


def test_existing_schema_and_crud(service):
    first = request(service, op='snapshot')['snapshot']['notes'][0]
    assert request(service, op='rename', id=first['id'], title='原生小部件')['ok']
    assert request(service, op='create')['ok']
    assert request(service, op='delete', id=first['id'])['ok']
    assert len(service.store.notes()) == 1
    assert not request(service, op='rename', id=999, title='bad')['ok']
    assert not request(service, op='edit', id=999, body='bad', expected='')['ok']


def test_single_writer_lock(service):
    request(service, op='snapshot')
    other = NotesService(service.directory)
    try:
        assert not request(other, op='snapshot')['ok']
    finally:
        other.close()
