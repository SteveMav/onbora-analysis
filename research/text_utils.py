"""Text cleanup for derived/search values while raw ARSP data stays intact."""

from __future__ import annotations

import re


EXCEL_ESCAPE_RE = re.compile(r"_x([0-9a-fA-F]{4})_", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")
LEGAL_SUFFIX_RE = re.compile(
    r"(?:[\s,.-]+(?:sarlu|sarl|sprl|sas|sa|scs|snc|ltd|limited))+$",
    re.IGNORECASE,
)


def clean_excel_text(value: str) -> str:
    """Decode Excel XML escapes such as ``_x000D_`` in a derived value."""
    decoded = EXCEL_ESCAPE_RE.sub(lambda match: chr(int(match.group(1), 16)), str(value or ""))
    return SPACE_RE.sub(" ", decoded).strip()


def company_name_variants(value: str) -> list[str]:
    """Return stable full-name and brand-like variants, most precise first."""
    full_name = clean_excel_text(value)
    if not full_name:
        return []
    base_name = LEGAL_SUFFIX_RE.sub("", full_name).strip(" ,.-")
    return list(dict.fromkeys(name for name in (full_name, base_name) if name))
