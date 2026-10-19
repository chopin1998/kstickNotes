"""WebDAV immutable-object transport; no live SQLite files leave this machine."""
import base64
import json
import re
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler, ProxyHandler
import xml.etree.ElementTree as ET
from .sync_model import canonical, validate

DEFAULT_URL = 'https://app.koofr.net/dav/Koofr/KStickyNotes/'
LIMIT = 4 * 1024 * 1024


def normalize_url(url):
    parts = urlsplit(url.strip())
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or any(ord(c) < 33 for c in url.strip())):
        raise ValueError('同步地址须为不含账号、查询参数的 HTTPS 文件夹地址')
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/') + '/', '', ''))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward credentials or notes to an unexpected destination.
        return None


class WebDAV:
    def __init__(self, url, username, password, proxy='', cancel=None):
        self.url = normalize_url(url)
        self.cancel = cancel
        if proxy:
            p = urlsplit(proxy)
            if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
                raise ValueError('代理地址须为 http://主机:端口 或 https://主机:端口')
        handlers = [NoRedirect(), HTTPSHandler(context=ssl.create_default_context())]
        if proxy:
            handlers.append(ProxyHandler({'http': proxy, 'https': proxy}))
        self.opener = build_opener(*handlers)
        self.auth = 'Basic ' + base64.b64encode(f'{username}:{password}'.encode()).decode()

    def request(self, method, suffix='', body=None, headers=None, allowed=(), limit=LIMIT):
        if self.cancel is not None and self.cancel.is_set():
            raise RuntimeError('同步已取消')
        request = Request(self.url + suffix, data=body, method=method,
                          headers=dict({'Authorization': self.auth}, **(headers or {})))
        try:
            response = self.opener.open(request, timeout=15)
        except HTTPError as error:
            if error.code not in allowed:
                error.close()
                if error.code in (401, 403):
                    raise RuntimeError('WebDAV 登录失败或权限不足，请检查账号和应用密码') from None
                raise RuntimeError(f'WebDAV 返回 HTTP {error.code}；本地便签仍已保存') from None
            response = error
        except (URLError, OSError, ssl.SSLError, socket.timeout):
            raise RuntimeError('无法连接 WebDAV，请检查网络、代理和 HTTPS 证书') from None
        try:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise RuntimeError('同步响应超过大小限制，已停止本轮同步')
            return response.code, data
        finally:
            response.close()

    def list_ids(self):
        body = b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>'
        headers = {'Depth': '1', 'Content-Type': 'application/xml; charset=utf-8'}
        code, data = self.request('PROPFIND', body=body, headers=headers, allowed=(404,), limit=8*LIMIT)
        if code == 404:
            self.request('MKCOL', allowed=(405,))
            code, data = self.request('PROPFIND', body=body, headers=headers, limit=8*LIMIT)
        if code != 207:
            raise RuntimeError('WebDAV 未返回有效的文件夹列表')
        try:
            if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                raise ValueError()
            tree = ET.fromstring(data)
        except (ET.ParseError, ValueError):
            raise RuntimeError('WebDAV 文件夹列表格式无效') from None
        base = unquote(urlsplit(self.url).path)
        result = set()
        for entry in tree.findall('{DAV:}response'):
            href = entry.findtext('{DAV:}href', '')
            path = unquote(urlsplit(href).path)
            if not path.startswith(base):
                continue
            filename = path[len(base):]
            if re.fullmatch(r'[0-9a-f]{64}\.json', filename):
                result.add(filename[:-5])
        if len(result) > 20000:
            raise RuntimeError('云端版本记录超过 20000 条，请先备份并整理同步目录')
        return result

    def exchange(self, local):
        # Validate the whole graph before uploading or touching the local database.
        validate(local)
        local_by_id = {r['id']: r for r in local}
        remote_ids = self.list_ids()
        incoming = []
        size = 0
        for rid in sorted(remote_ids - local_by_id.keys()):
            _, body = self.request('GET', rid + '.json')
            size += len(body)
            if size > 64 * 1024 * 1024:
                raise RuntimeError('单轮下载超过 64 MiB，已停止同步')
            try:
                record = json.loads(body)
            except (ValueError, UnicodeError):
                raise RuntimeError('云端同步文件不是有效 JSON') from None
            if not isinstance(record, dict) or record.get('id') != rid:
                raise RuntimeError('云端文件名与版本记录不一致')
            incoming.append(record)
        ordered = validate(local + incoming)
        # Parents first: an interrupted upload can be retried without broken ancestry.
        for record in ordered:
            if record['id'] in local_by_id and record['id'] not in remote_ids:
                payload = canonical(record).encode()
                code, _ = self.request('PUT', record['id'] + '.json', payload,
                                       {'Content-Type': 'application/json; charset=utf-8',
                                        'If-None-Match': '*'}, allowed=(412,))
                if code == 412:
                    _, existing = self.request('GET', record['id'] + '.json')
                    try:
                        same = json.loads(existing) == record
                    except (ValueError, UnicodeError):
                        same = False
                    if not same:
                        raise RuntimeError('云端版本文件不一致，已停止同步以保留本地数据')
        return incoming
