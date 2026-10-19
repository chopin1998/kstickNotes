import copy
from pathlib import Path
import json
import sqlite3
import threading
import uuid
from urllib.error import HTTPError, URLError
import pytest
from PySide6.QtCore import QSignalBlocker
from PySide6.QtTest import QTest
from kstickynotes.storage import Store
from kstickynotes.sync_model import revision, canonical, validate
from kstickynotes.webdav import WebDAV, normalize_url


def state(store):
    return sorted((n.title,n.body) for n in store.notes())


def settle(a,b):
    for _ in range(4):
        a.merge(b.revisions())
        b.merge(a.revisions())
    assert {r['id'] for r in a.revisions()} == {r['id'] for r in b.revisions()}
    assert state(a)==state(b)


def pair(tmp_path):
    a,b=Store(tmp_path/'a'),Store(tmp_path/'b')
    n=a.create('计划')
    a.save({n.id:'原文'})
    b.merge(a.revisions())
    return a,b,n.id,b.notes()[0].id


def test_offline_edits_converge_with_durable_conflict_copy(tmp_path):
    a,b,aid,bid=pair(tmp_path)
    a.save({aid:'电脑 A'})
    b.save({bid:'电脑 B'})
    settle(a,b)
    assert {n.body for n in a.notes()}=={'电脑 A','电脑 B'}
    assert sum('冲突副本' in n.title for n in a.notes())==1
    original=next(n for n in a.notes() if '冲突副本' not in n.title)
    a.save({original.id:'合并后继续编辑'})
    settle(a,b)
    assert len(a.notes())==2
    # Deleting the copy remains a deletion, including on a previously offline replica.
    old=Store(tmp_path/'old')
    old.merge(b.revisions())
    conflict=next(n for n in a.notes() if '冲突副本' in n.title)
    a.delete(conflict.id)
    settle(a,b)
    settle(a,old)
    assert len(a.notes())==1
    for store in (a,b,old):store.close()


def test_delete_edit_conflict_keeps_edited_text(tmp_path):
    a,b,aid,bid=pair(tmp_path)
    a.delete(aid)
    b.save({bid:'删除时另一台未同步的修改'})
    settle(a,b)
    assert state(a)==[('计划','删除时另一台未同步的修改')]
    a.delete(a.notes()[0].id)
    settle(a,b)
    assert not a.notes()
    a.close();b.close()


def test_same_text_concurrent_edits_do_not_duplicate(tmp_path):
    a,b,aid,bid=pair(tmp_path)
    a.save({aid:'一样'})
    b.save({bid:'一样'})
    settle(a,b)
    assert len(a.notes())==1
    a.close();b.close()


def test_three_way_conflict_converges(tmp_path):
    a,b,aid,bid=pair(tmp_path)
    c=Store(tmp_path/'c');c.merge(a.revisions())
    a.save({aid:'A'});b.save({bid:'B'});c.save({c.notes()[0].id:'C'})
    # Different partial merges arrive in opposite orders.
    a.merge(b.revisions());c.merge(b.revisions())
    settle(a,c);settle(a,b);settle(b,c)
    assert {'A','B','C'} <= {n.body for n in a.notes()}
    for store in (a,b,c):store.close()


def test_bad_remote_graph_is_atomic_and_missing_parent_retries(tmp_path):
    a,b,aid,bid=pair(tmp_path)
    b.save({bid:'新文本'})
    leaf=b.revisions()[-1]
    before=a.revisions()
    damaged=copy.deepcopy(leaf);damaged['payload']['body']='破坏校验'
    with pytest.raises(ValueError):a.merge([damaged])
    assert a.revisions()==before and a.note(aid).body=='原文'
    fresh=Store(tmp_path/'fresh')
    with pytest.raises(ValueError):fresh.merge([leaf])
    assert not fresh.notes() and not fresh.revisions()
    fresh.merge(b.revisions())
    assert fresh.notes()[0].body=='新文本'
    for store in (a,b,fresh):store.close()


def test_sync_merge_rolls_back_notes_and_history_on_sql_error(tmp_path):
    a,b,aid,bid=pair(tmp_path)
    b.save({bid:'远端'})
    a.db.execute("CREATE TRIGGER prevent_sync BEFORE UPDATE ON notes BEGIN SELECT RAISE(ABORT,'blocked'); END")
    before=a.revisions()
    with pytest.raises(sqlite3.IntegrityError):a.merge(b.revisions())
    assert a.revisions()==before and a.note(aid).body=='原文'
    a.close();b.close()


def test_v1_migration_preserves_ids_and_makes_private_backup(tmp_path):
    path=tmp_path/'notes.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE notes(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,body TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        db.execute("INSERT INTO notes(id,title,body) VALUES(12,'已有便签','原样内容\n中文')")
        db.execute('PRAGMA user_version=1')
    store=Store(path)
    assert store.note(12).body=='原样内容\n中文'
    backup,=list((tmp_path/'backups').glob('before-sync-*.sqlite3'))
    assert backup.stat().st_mode&0o777==0o600
    with sqlite3.connect(backup) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==1
        assert db.execute('SELECT body FROM notes').fetchone()[0]=='原样内容\n中文'
    store.close()


class Response:
    def __init__(self,code,data=b''):self.code,self.data=code,data
    def read(self,limit):return self.data[:limit]
    def close(self):pass


class DavServer:
    def __init__(self):self.files={};self.calls=[];self.exists=False;self.fail_after=None
    def open(self,request,timeout=15):
        method=request.method;name=request.full_url.rsplit('/',1)[-1]
        self.calls.append((method,name))
        if self.fail_after is not None and len(self.calls)>self.fail_after:
            raise URLError('offline')
        if method=='MKCOL':self.exists=True;return Response(201)
        if not self.exists:raise HTTPError(request.full_url,404,'missing',{},None)
        if method=='PROPFIND':
            data='<d:multistatus xmlns:d="DAV:">'+''.join('<d:response><d:href>/notes/'+name+'</d:href></d:response>' for name in self.files)+'</d:multistatus>'
            return Response(207,data.encode())
        if method=='GET':return Response(200,self.files[name])
        assert method=='PUT'
        assert request.get_header('If-none-match')=='*'
        if name in self.files:raise HTTPError(request.full_url,412,'exists',{},None)
        record=json.loads(request.data)
        assert all(parent+'.json' in self.files for parent in record['parents'])
        self.files[name]=request.data
        return Response(201)


def transport(server):
    client=WebDAV('https://example.test/notes/','account','private-password')
    client.opener=server
    return client


def test_webdav_roundtrip_and_interrupted_upload_retry(tmp_path):
    a,b,aid,bid=pair(tmp_path)
    server=DavServer();client=transport(server)
    client.exchange(a.revisions())
    assert server.calls[:3]==[('PROPFIND',''),('MKCOL',''),('PROPFIND','')]
    b.save({bid:'远端修改'})
    server.fail_after=len(server.calls)+1
    with pytest.raises(RuntimeError):client.exchange(b.revisions())
    assert len(server.files)==len(a.revisions())
    server.fail_after=None
    client.exchange(b.revisions())
    incoming=client.exchange(a.revisions())
    a.merge(incoming)
    assert a.note(aid).body=='远端修改'
    count=len(server.files)
    assert client.exchange(a.revisions())==[]
    assert len(server.files)==count
    a.close();b.close()


def test_url_security_and_redirect_credentials():
    for url in ('http://example.test/','https://user:secret@example.test/','https://example.test/?x=1'):
        with pytest.raises(ValueError):normalize_url(url)
    assert normalize_url('https://example.test/notes')=='https://example.test/notes/'
    client=WebDAV('https://example.test/notes/','user','sensitive')
    class Rejected:
        def open(self,request,timeout):raise HTTPError(request.full_url,302,'redirect',{'Location':'https://other.test'},None)
    client.opener=Rejected()
    with pytest.raises(RuntimeError,match='HTTP 302') as issue:client.exchange([])
    assert 'sensitive' not in str(issue.value)


def test_wallet_password_goes_through_stdin_only(monkeypatch):
    import kstickynotes.wallet as wallet
    from types import SimpleNamespace
    calls=[]
    monkeypatch.setattr(wallet.shutil,'which',lambda name:'/usr/bin/'+name)
    def run(command,**kwargs):
        calls.append((command,kwargs))
        return SimpleNamespace(returncode=0,stdout='kdewallet\n' if 'networkWallet' in command[-1] else '')
    monkeypatch.setattr(wallet.subprocess,'run',run)
    assert wallet.wallet_password('https://example.test/','user','keep secret spaces ')=='keep secret spaces '
    assert all('keep secret spaces ' not in ' '.join(args) for args,_ in calls)
    assert calls[-1][1]['input']=='keep secret spaces \n'


def test_ui_sync_preserves_edits_made_during_request(tmp_path,monkeypatch):
    from PySide6.QtCore import QSettings
    from kstickynotes.ui import Window
    import kstickynotes.sync_ui as sync_ui
    store=Store(tmp_path/'local')
    note=store.create('共享');store.save({note.id:'原文'})
    peer=Store(tmp_path/'peer');peer.merge(store.revisions())
    peer.save({peer.notes()[0].id:'网络请求期间的远端修改'})
    peer_records=peer.revisions()
    window=Window(store,QSettings(str(tmp_path/'settings.ini'),QSettings.IniFormat))
    controller=window.sync
    released=threading.Event()
    completed=threading.Event()
    monkeypatch.setattr(sync_ui,'wallet_password',lambda *args:'secret')
    class FakeDAV:
        def __init__(self,*args):pass
        def exchange(self,records):
            released.wait(2)
            completed.set()
            known={r['id'] for r in records}
            return [r for r in peer_records if r['id'] not in known]
    monkeypatch.setattr(sync_ui,'WebDAV',FakeDAV)
    try:
        controller.start({'url':'https://example.test/notes/','user':'user','proxy':'','enabled':False})
        assert controller.busy
        window.tabs.currentWidget().editor.setPlainText('网络请求期间的本地输入')
        released.set()
        assert completed.wait(2)
        for _ in range(40):
            QTest.qWait(50)
            if not controller.busy:
                break
        assert not controller.busy
        assert {'网络请求期间的本地输入','网络请求期间的远端修改'} <= {n.body for n in store.notes()}
        assert not window.dirty
        assert window.tabs.count()==len(store.notes())
        assert 'secret' not in Path(window.settings.fileName()).read_text()
    finally:
        controller.close();window.timer.stop();window.tray.hide();window.quitting=True;window.close()
        window.deleteLater()
        store.close();peer.close()


def test_sync_deleting_last_note_stays_empty_after_restart(tmp_path):
    from PySide6.QtCore import QSettings
    from kstickynotes.ui import Window
    path=tmp_path/'db'
    store=Store(path);note=store.create();store.delete(note.id);store.close()
    store=Store(path)
    window=Window(store,QSettings(str(tmp_path/'settings.ini'),QSettings.IniFormat))
    try:
        assert window.tabs.count()==0
        assert not store.notes()
    finally:
        window.sync.close();window.timer.stop();window.tray.hide();window.quitting=True;window.close()
        window.deleteLater();store.close()



def test_partial_upload_is_parent_complete_and_retryable(tmp_path):
    store=Store(tmp_path/'db')
    note=store.create('重试')
    store.save({note.id:'第一版'})
    store.save({note.id:'第二版'})
    server=DavServer();server.fail_after=4
    client=transport(server)
    with pytest.raises(RuntimeError):client.exchange(store.revisions())
    assert len(server.files)==1
    validate([json.loads(body) for body in server.files.values()])
    server.fail_after=None
    client.exchange(store.revisions())
    assert len(server.files)==len(store.revisions())
    store.close()


def test_conditional_put_race_verifies_existing_content(tmp_path):
    store=Store(tmp_path/'db');store.create('并发上传')
    class RacedServer(DavServer):
        def open(self,request,timeout=15):
            if request.method=='PUT':
                name=request.full_url.rsplit('/',1)[-1]
                self.files[name]=request.data
            return super().open(request,timeout)
    server=RacedServer()
    assert transport(server).exchange(store.revisions())==[]
    assert any(method=='GET' for method,_ in server.calls)
    store.close()
