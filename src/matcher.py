"""Duplicate detection via multi-signal matching and union-find clustering."""

from __future__ import annotations

from dataclasses import dataclass, field
from rapidfuzz.distance import JaroWinkler

from .normalize import normalize_phone, phone_suffix, normalize_name, normalize_email, is_case_variant
from .vcards import Contact


@dataclass
class MatchSignal:
    kind: str
    detail: str
    confidence: float


@dataclass
class DuplicateCluster:
    contacts: list[Contact] = field(default_factory=list)
    signals: list[MatchSignal] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        if not self.signals:
            return 0.0
        return max(s.confidence for s in self.signals)

    @property
    def display_name(self) -> str:
        for c in self.contacts:
            if c.full_name:
                return c.full_name
        return self.contacts[0].uid if self.contacts else "Unknown"


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


def _match_phones(c1: Contact, c2: Contact) -> MatchSignal | None:
    norm1 = {normalize_phone(p) for p in c1.all_phone_strings if p}
    norm2 = {normalize_phone(p) for p in c2.all_phone_strings if p}
    exact = norm1 & norm2
    if exact:
        return MatchSignal("phone_exact", f"shared phone(s): {', '.join(exact)}", 0.99)

    suf1 = {phone_suffix(p) for p in c1.all_phone_strings if p}
    suf2 = {phone_suffix(p) for p in c2.all_phone_strings if p}
    suffix_match = suf1 & suf2
    suffix_match.discard("")
    if suffix_match:
        return MatchSignal("phone_suffix", f"shared last-10: {', '.join(suffix_match)}", 0.90)

    return None


def _match_emails(c1: Contact, c2: Contact) -> MatchSignal | None:
    emails1 = {normalize_email(e) for e in c1.all_email_strings if e}
    emails2 = {normalize_email(e) for e in c2.all_email_strings if e}
    shared = emails1 & emails2
    shared.discard("")
    if shared:
        return MatchSignal("email_exact", f"shared email(s): {', '.join(shared)}", 0.99)
    return None


def _match_names(c1: Contact, c2: Contact) -> MatchSignal | None:
    n1 = normalize_name(c1.full_name)
    n2 = normalize_name(c2.full_name)
    if not n1 or not n2:
        return None
    score = JaroWinkler.similarity(n1, n2)
    if score >= 0.92:
        return MatchSignal("name_fuzzy", f'"{c1.full_name}" ~ "{c2.full_name}" ({score:.2f})', score)

    return None


def _match_org_name(c1: Contact, c2: Contact) -> MatchSignal | None:
    if not c1.org or not c2.org:
        return None
    if c1.org.lower().strip() != c2.org.lower().strip():
        return None

    n1 = normalize_name(c1.full_name)
    n2 = normalize_name(c2.full_name)
    if not n1 or not n2:
        return None

    score = JaroWinkler.similarity(n1, n2)
    if score >= 0.70:
        return MatchSignal("org_name", f'same org "{c1.org}", name score {score:.2f}', 0.80)

    return None


def _match_case(c1: Contact, c2: Contact) -> MatchSignal | None:
    n1 = c1.full_name.strip()
    n2 = c2.full_name.strip()
    if not n1 or not n2:
        return None
    if is_case_variant(n1, n2):
        return MatchSignal("name_case", f'"{n1}" vs "{n2}" (case only)', 0.98)
    return None

def find_duplicates(contacts: list[Contact]) -> list[DuplicateCluster]:
    n = len(contacts)
    uf = UnionFind(n)
    all_signals: dict[tuple[int, int], list[MatchSignal]] = {}

    for i in range(n):
        for j in range(i + 1, n):
            pair_signals: list[MatchSignal] = []
            for matcher in [_match_phones, _match_emails, _match_case, _match_names, _match_org_name]:
                sig = matcher(contacts[i], contacts[j])
                if sig:
                    pair_signals.append(sig)

            if pair_signals:
                uf.union(i, j)
                key = (min(i, j), max(i, j))
                all_signals[key] = pair_signals

    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        groups.setdefault(root, []).append(i)

    clusters: list[DuplicateCluster] = []
    for indices in groups.values():
        if len(indices) < 2:
            continue
        cluster = DuplicateCluster(contacts=[contacts[i] for i in indices])
        seen_pairs: set[tuple[int, int]] = set()
        for i in indices:
            for j in indices:
                if i >= j:
                    continue
                key = (i, j)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                if key in all_signals:
                    cluster.signals.extend(all_signals[key])
        clusters.append(cluster)

    clusters.sort(key=lambda c: c.confidence, reverse=True)
    return clusters
