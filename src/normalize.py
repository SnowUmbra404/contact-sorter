"""Phone number and name normalization for matching."""

from __future__ import annotations

import re
import unicodedata

_PREFIXES = {"mr", "mrs", "ms", "dr", "smt", "shri", "smt.", "shri.", "prof", "sr", "sri"}
_INDIAN_MOBILE_RE = re.compile(r"^(?:\+?91)?0?([6-9]\d{9})$")
_GENERAL_RE = re.compile(r"^[+]?(\d{7,15})$")


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"[^\d+]", "", raw)
    if not digits or digits == "+":
        return ""

    if digits.startswith("+"):
        return "+" + re.sub(r"\D", "", digits[1:])

    m = _INDIAN_MOBILE_RE.match(digits)
    if m:
        return "+91" + m.group(1)

    m = _GENERAL_RE.match(digits)
    if m:
        return "+" + m.group(1)

    return "+" + re.sub(r"\D", "", digits)


def phone_suffix(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 10:
        return digits[-10:]
    return digits


def normalize_name(raw: str) -> str:
    if not raw:
        return ""
    name = unicodedata.normalize("NFKC", raw).lower().strip()
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    tokens = name.split()
    tokens = [t for t in tokens if t not in _PREFIXES]
    return " ".join(tokens)


def normalize_email(raw: str) -> str:
    return raw.strip().lower() if raw else ""


def name_tokens(name: str) -> set[str]:
    normalized = normalize_name(name)
    return set(normalized.split()) if normalized else set()
