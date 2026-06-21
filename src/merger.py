"""Merge a cluster of duplicate contacts into one clean contact."""

from __future__ import annotations

from .vcards import Contact, PhoneEntry, EmailEntry
from .normalize import normalize_phone, normalize_name
from .matcher import DuplicateCluster

def preview_name(cluster: DuplicateCluster) -> str:
    return _best_name(cluster.contacts)


def merge_cluster(cluster: DuplicateCluster, chosen_name: str | None = None) -> Contact:
    contacts = cluster.contacts
    if not contacts:
        raise ValueError("Cannot merge empty cluster")

    full_name = chosen_name or _best_name(contacts)

    phones_seen: dict[str, PhoneEntry] = {}
    for c in contacts:
        for p in c.phones:
            norm = normalize_phone(p.number)
            if norm and norm not in phones_seen:
                phones_seen[norm] = p
    merged_phones = list(phones_seen.values())

    emails_seen: dict[str, EmailEntry] = {}
    for c in contacts:
        for e in c.emails:
            key = e.address.lower().strip()
            if key and key not in emails_seen:
                emails_seen[key] = e
    merged_emails = list(emails_seen.values())

    org = _best_field(contacts, "org")
    title = _best_field(contacts, "title")
    note = _best_field(contacts, "note")

    source_files = sorted(set(c.source_file for c in contacts if c.source_file))
    source_label = "+".join(source_files) if source_files else contacts[0].source_file

    return Contact(
        uid=contacts[0].uid,
        full_name=full_name,
        given_name=full_name.split()[0] if full_name else "",
        family_name=full_name.split()[-1] if full_name and len(full_name.split()) > 1 else "",
        phones=merged_phones,
        emails=merged_emails,
        org=org,
        title=title,
        note=note,
        source_file=source_label,
    )


def _best_name(contacts: list[Contact]) -> str:
    scored: list[tuple[int, str]] = []
    for c in contacts:
        name = c.full_name.strip()
        if not name:
            continue
        norm = normalize_name(name)
        score = len(norm) + (100 if c.full_name == c.full_name.strip() else 0)
        scored.append((score, name))
    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]
    return contacts[0].uid


def _best_field(contacts: list[Contact], field: str) -> str:
    values = [getattr(c, field) for c in contacts if getattr(c, field)]
    if not values:
        return ""
    return max(values, key=len)
