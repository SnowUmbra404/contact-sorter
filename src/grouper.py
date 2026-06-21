from __future__ import annotations

import re
from .vcards import Contact
from .normalize import phone_suffix


def name_key(name: str) -> str:
    if not name:
        return ""
    key = name.lower().strip()
    key = re.sub(r'[^a-z0-9 ]', ' ', key)
    key = re.sub(r'\s+', ' ', key).strip()
    return key


def group_by_name(contacts: list[Contact]) -> list[list[Contact]]:
    buckets: dict[str, list[int]] = {}
    for i, c in enumerate(contacts):
        key = name_key(c.full_name)
        if key:
            buckets.setdefault(key, []).append(i)
    return [
        [contacts[i] for i in idxs]
        for idxs in buckets.values()
        if len(idxs) >= 2
    ]


class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.p[ry] = rx


def group_by_phone(contacts: list[Contact]) -> list[list[Contact]]:
    n = len(contacts)
    uf = _UF(n)
    phone_to_idx: dict[str, int] = {}

    for i, c in enumerate(contacts):
        for p in c.phones:
            key = phone_suffix(p.number)
            if not key or len(key) < 7:
                continue
            if key in phone_to_idx:
                uf.union(i, phone_to_idx[key])
            else:
                phone_to_idx[key] = i

    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        groups.setdefault(root, []).append(i)

    return [
        [contacts[i] for i in idxs]
        for idxs in groups.values()
        if len(idxs) >= 2
    ]
