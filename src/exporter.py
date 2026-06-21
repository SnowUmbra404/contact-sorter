"""Export merged contacts as RFC 6350-compliant vCard 3.0."""

from __future__ import annotations

import vobject
from pathlib import Path

from .vcards import Contact


def _build_vcard(contact: Contact) -> vobject.vCard:
    card = vobject.vCard()

    card.add("version")
    card.version.value = "3.0"

    card.add("fn")
    card.fn.value = contact.full_name or contact.uid

    card.add("n")
    card.n.value = vobject.vcard.Name(
        family=contact.family_name,
        given=contact.given_name,
    )

    for phone in contact.phones:
        tel = card.add("tel")
        tel.value = phone.number
        tel.params["TYPE"] = [phone.type]

    for email in contact.emails:
        e = card.add("email")
        e.value = email.address
        e.params["TYPE"] = [email.type]

    if contact.org:
        card.add("org")
        card.org.value = [contact.org]

    if contact.title:
        card.add("title")
        card.title.value = contact.title

    if contact.note:
        card.add("note")
        card.note.value = contact.note

    if contact.uid:
        card.add("uid")
        card.uid.value = contact.uid

    return card


def export_vcf(contacts: list[Contact], output_path: str | Path) -> int:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for contact in contacts:
        card = _build_vcard(contact)
        serialized = card.serialize()
        lines.append(serialized)

    path.write_text("".join(lines), encoding="utf-8")
    return len(contacts)
