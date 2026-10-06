"""Nickname checks. A child profile stores a nickname, never a real name."""

import re
from pathlib import Path

from apps.kidsplay import conf
from apps.kidsplay.models import Family

_WORDS = None


def _blocked() -> set[str]:
    global _WORDS
    if _WORDS is None:
        path = Path(__file__).resolve().parent.parent / "data" / "blocked_words.txt"
        _WORDS = {line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    return _WORDS


def clean_nickname(raw: str) -> tuple[str, str]:
    """Return (nickname, error). Error is empty when the name is usable."""
    name = re.sub(r"\s+", " ", (raw or "").strip())
    if len(name) < 2 or len(name) > 20:
        return "", "bad_length"
    if not re.fullmatch(r"[\w .'-]+", name, flags=re.UNICODE):
        return "", "bad_chars"
    folded = name.casefold()
    if any(word in folded for word in _blocked()):
        return "", "blocked"
    return name, ""


def can_add_kid(family: Family) -> bool:
    return family.kids.count() < conf.get("MAX_KIDS_PER_FAMILY")
