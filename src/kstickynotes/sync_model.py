"""Immutable per-note revision graph; concurrent heads produce durable copies."""
import hashlib
import json
import re
import uuid


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def revision(note, parents, payload, nonce=None):
    value = {'v': 1, 'note': note, 'parents': sorted(parents), 'payload': payload,
             'nonce': nonce if nonce is not None else uuid.uuid4().hex}
    value['id'] = hashlib.sha256(canonical(value).encode()).hexdigest()
    return value


def validate(records):
    """Reject corruption, missing ancestors and cycles before any local mutation."""
    found = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {'id', 'v', 'note', 'parents', 'payload', 'nonce'}:
            raise ValueError('同步记录格式无效')
        rid = record['id']
        if not isinstance(rid, str) or not re.fullmatch('[0-9a-f]{64}', rid):
            raise ValueError('同步版本标识无效')
        if record['v'] != 1 or not isinstance(record['note'], str) or not re.fullmatch('[0-9a-f]{32}', record['note']):
            raise ValueError('同步版本或便签标识无效')
        parents, payload = record['parents'], record['payload']
        if not isinstance(parents, list) or any(not isinstance(p, str) or not re.fullmatch('[0-9a-f]{64}', p) for p in parents):
            raise ValueError('同步父版本格式无效')
        if len(set(parents)) != len(parents) or len(parents) > 2000:
            raise ValueError('同步父版本数量无效')
        if not isinstance(payload, dict) or set(payload) != {'title', 'body', 'deleted'}:
            raise ValueError('同步便签格式无效')
        if type(payload['deleted']) is not bool or not all(isinstance(payload[k], str) for k in ('title', 'body')):
            raise ValueError('同步便签内容无效')
        if not isinstance(record['nonce'], str) or len(record['nonce']) > 64:
            raise ValueError('同步记录随机标识无效')
        if len(canonical(record).encode()) > 4 * 1024 * 1024:
            raise ValueError('单条同步版本超过 4 MiB')
        value = {k: v for k, v in record.items() if k != 'id'}
        if hashlib.sha256(canonical(value).encode()).hexdigest() != rid:
            raise ValueError('同步记录校验失败')
        if rid in found and found[rid] != record:
            raise ValueError('同步记录标识冲突')
        found[rid] = record
    children = {}
    remaining = {}
    for rid, record in found.items():
        remaining[rid] = len(record['parents'])
        for parent in record['parents']:
            if parent not in found or found[parent]['note'] != record['note']:
                raise ValueError('同步版本不完整；稍后将自动重试')
            children.setdefault(parent, []).append(rid)
    queue = [rid for rid, count in remaining.items() if not count]
    ordered = []
    while queue:
        rid = queue.pop()
        ordered.append(found[rid])
        for child in children.get(rid, []):
            remaining[child] -= 1
            if remaining[child] == 0:
                queue.append(child)
    if len(ordered) != len(found):
        raise ValueError('同步版本图含有循环')
    return ordered


def heads(records):
    parents = {p for record in records for p in record['parents']}
    return sorted((r for r in records if r['id'] not in parents), key=lambda r: r['id'])


def resolve(records):
    """Deterministic merge: keep a live head and retain distinct competing texts."""
    grouped = {}
    for record in records:
        grouped.setdefault(record['note'], []).append(record)
    known_notes = set(grouped)
    additions = []
    conflicts = 0
    for note, history in grouped.items():
        leaves = heads(history)
        if len(leaves) < 2:
            continue
        leaves.sort(key=lambda r: (r['payload']['deleted'], r['id']))
        winner = leaves[0]
        seen = {canonical(winner['payload'])}
        for loser in leaves[1:]:
            payload = loser['payload']
            if payload['deleted'] or canonical(payload) in seen:
                continue
            seen.add(canonical(payload))
            copy_id = hashlib.sha256(('conflict:' + note + ':' + canonical(payload)).encode()).hexdigest()[:32]
            if copy_id not in known_notes:
                copy_payload = dict(payload, title=payload['title'] + ' (冲突副本)')
                additions.append(revision(copy_id, [], copy_payload, nonce='conflict'))
                known_notes.add(copy_id)
                conflicts += 1
        # Concurrent deletion never silently discards an edit.
        if any(r['payload']['deleted'] != winner['payload']['deleted'] for r in leaves):
            conflicts += 1
        additions.append(revision(note, [r['id'] for r in leaves], winner['payload'], nonce='merge'))
    return additions, conflicts
