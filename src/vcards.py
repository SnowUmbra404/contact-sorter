"""VCF file parsing — handles vCard 2.1/3.0/4.0 with Samsung quirks."""

from __future__ import annotations

import vobject
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PhoneEntry:
    number: str
    type: str = "HOME"


@dataclass
class EmailEntry:
    address: str
    type: str = "HOME"


@dataclass
class Contact:
    uid: str
    full_name: str = ""
    given_name: str = ""
    family_name: str = ""
    phones: list[PhoneEntry] = field(default_factory=list)
    emails: list[EmailEntry] = field(default_factory=list)
    org: str = ""
    title: str = ""
    note: str = ""
    source_file: str = ""

    @property
    def all_phone_strings(self) -> list[str]:
        return [p.number for p in self.phones]

    @property
    def all_email_strings(self) -> list[str]:
        return [e.address for e in self.emails]


def _extract_tel(tel_prop) -> PhoneEntry:
    number = str(tel_prop.value) if tel_prop.value else ""
    tel_type = "OTHER"
    if hasattr(tel_prop, "params"):
        type_params = tel_prop.params.get("TYPE", tel_prop.params.get("type", []))
        if isinstance(type_params, list):
            for t in type_params:
                upper = t.upper().replace("-", "")
                if "CELL" in upper or "MOBILE" in upper:
                    tel_type = "CELL"
                elif "HOME" in upper:
                    tel_type = "HOME"
                elif "WORK" in upper:
                    tel_type = "WORK"
                elif "FAX" in upper:
                    tel_type = "FAX"
    return PhoneEntry(number=number, type=tel_type)


def _extract_email(email_prop) -> EmailEntry:
    address = str(email_prop.value) if email_prop.value else ""
    email_type = "OTHER"
    if hasattr(email_prop, "params"):
        type_params = email_prop.params.get("TYPE", email_prop.params.get("type", []))
        if isinstance(type_params, list):
            for t in type_params:
                upper = t.upper()
                if "HOME" in upper or "INTERNET" in upper:
                    email_type = "HOME"
                elif "WORK" in upper:
                    email_type = "WORK"
    return EmailEntry(address=address, type=email_type)


def parse_vcf(file_path: str | Path) -> list[Contact]:
    path = Path(file_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    contacts: list[Contact] = []

    for component in vobject.readComponents(text):
        if component.name.lower() != "vcard":
            continue

        uid = ""
        if hasattr(component, "uid") and component.uid:
            uid = str(component.uid.value)

        full_name = ""
        if hasattr(component, "fn") and component.fn:
            full_name = str(component.fn.value)

        given_name = ""
        family_name = ""
        if hasattr(component, "n") and component.n:
            n_val = component.n.value
            if isinstance(n_val, vobject.vcard.Name):
                family_name = n_val.family or ""
                given_name = n_val.given or ""
            elif isinstance(n_val, tuple) and len(n_val) >= 2:
                family_name = str(n_val[0]) if n_val[0] else ""
                given_name = str(n_val[1]) if n_val[1] else ""

        if not full_name and given_name:
            parts = [p for p in [given_name, family_name] if p]
            full_name = " ".join(parts)

        phones: list[PhoneEntry] = []
        if hasattr(component, "tel_list"):
            for tel in component.tel_list:
                phones.append(_extract_tel(tel))

        emails: list[EmailEntry] = []
        if hasattr(component, "email_list"):
            for email in component.email_list:
                emails.append(_extract_email(email))

        org = ""
        if hasattr(component, "org") and component.org:
            org_val = component.org.value
            if isinstance(org_val, (list, tuple)):
                org = " ".join(str(x) for x in org_val if x)
            else:
                org = str(org_val)

        title = ""
        if hasattr(component, "title") and component.title:
            title = str(component.title.value)

        note = ""
        if hasattr(component, "note") and component.note:
            note = str(component.note.value)

        contacts.append(Contact(
            uid=uid,
            full_name=full_name,
            given_name=given_name,
            family_name=family_name,
            phones=phones,
            emails=emails,
            org=org,
            title=title,
            note=note,
            source_file=path.name,
        ))

    return contacts


def load_all(file_paths: list[str | Path]) -> list[Contact]:
    all_contacts: list[Contact] = []
    for fp in file_paths:
        all_contacts.extend(parse_vcf(fp))
    return all_contacts
