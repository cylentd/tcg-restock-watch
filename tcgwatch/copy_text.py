"""The one reader of templates/copy.json, so the alert path and the status page share one copy file.

User-facing prose lives in copy.json under a key; code references the key (architecture rules: copy is
data). The page fills `{{key}}` placeholders from it (site.render); alerts fill `{name}` format fields
(notify.raffle_alert). Pure apart from reading that one file.
"""

from __future__ import annotations

import json
from pathlib import Path

COPY_PATH = Path(__file__).resolve().parent / "templates" / "copy.json"


def load() -> dict[str, str]:
    """Every copy key and its text."""
    return json.loads(COPY_PATH.read_text(encoding="utf-8"))


def words(key: str) -> str:
    """The text for one key; a missing key raises KeyError."""
    return load()[key]
