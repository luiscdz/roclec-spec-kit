"""Identifiers and causal ordering for branch-authored records."""
from __future__ import annotations

from collections import defaultdict
import os
from threading import Lock
import time

from .model import need, strings

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_lock = Lock()
_last_time, _last_random, _last_pid = -1, 0, None


def record_id(prefix):
    global _last_time, _last_random, _last_pid
    with _lock:
        now = time.time_ns() // 1_000_000
        pid = os.getpid()
        if pid != _last_pid or now > _last_time:
            _last_time, _last_random, _last_pid = now, int.from_bytes(os.urandom(10), "big"), pid
        else:
            _last_random += 1
            if _last_random == 1 << 80:
                _last_time += 1
                _last_random = 0
        value = (_last_time << 80) | _last_random
    return prefix + "-" + "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


def scoped_heads(records, scopes):
    """Return heads independently for each scope shared by a supersession."""
    ids = {record["id"]: record for record in records}
    need(len(ids) == len(records), "ID_COLLISION", "Duplicate record identity")
    memberships = {key: set(scopes(value)) for key, value in ids.items()}
    heads = defaultdict(set)
    descendants = defaultdict(list)
    remaining = {}
    for key, record in ids.items():
        for scope in memberships[key]:
            heads[scope].add(key)
        supersedes = strings(record["supersedes"])
        remaining[key] = len(supersedes)
        for previous in supersedes:
            overlap = memberships[key] & memberships.get(previous, set())
            need(overlap, "INVALID_REFERENCE", "Superseded record must exist in a common scope",
                 entity=key, actual=previous)
            descendants[previous].append(key)
    ready = [key for key, count in remaining.items() if not count]
    while ready:
        key = ready.pop()
        for child in descendants[key]:
            for scope in memberships[key] & memberships[child]:
                heads[scope].discard(key)
            remaining[child] -= 1
            if not remaining[child]:
                ready.append(child)
    need(not any(remaining.values()), "INVALID_REFERENCE", "Cyclic supersession",
         actual=sorted(key for key, count in remaining.items() if count))
    return {scope: [ids[key] for key in sorted(keys)] for scope, keys in heads.items()}


def one_head(heads, scope):
    records = heads.get(scope, [])
    need(len(records) <= 1, "AMBIGUOUS_EVIDENCE", "Concurrent records need explicit reconciliation",
         entity=str(scope), actual=[record["id"] for record in records],
         remediation="Record a new result in this scope to supersede all its current heads.")
    return records[0] if records else None
