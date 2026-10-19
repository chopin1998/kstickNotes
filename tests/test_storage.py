import sqlite3
import pytest
from kstickynotes.storage import Store


def test_persistence_and_crud(tmp_path):
    path = tmp_path / "notes.sqlite3"
    store = Store(path)
    first = store.create("中文 / Markdown")
    second = store.create()
    store.save({first.id: "# 标题\n\n你好 📝"})
    store.rename(first.id, "改名")
    store.delete(second.id)
    store.close()
    store = Store(path)
    assert [(n.title, n.body) for n in store.notes()] == [("改名", "# 标题\n\n你好 📝")]
    store.close()


def test_transaction_rolls_back_entire_batch(tmp_path):
    store = Store(tmp_path / "db")
    note = store.create()
    with pytest.raises(RuntimeError):
        store.save({note.id: "must roll back", 9999: "missing"})
    assert store.notes()[0].body == ""
    store.close()


def test_locked_database_keeps_original(tmp_path):
    path = tmp_path / "db"
    store = Store(path)
    note = store.create()
    blocker = sqlite3.connect(path)
    blocker.execute("BEGIN EXCLUSIVE")
    with pytest.raises(sqlite3.OperationalError):
        store.save({note.id: "new"})
    blocker.rollback()
    store.save({note.id: "new"})
    assert store.notes()[0].body == "new"
    blocker.close()
    store.close()
