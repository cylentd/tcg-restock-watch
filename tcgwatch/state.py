"""Persist last-known stock status per product so alerts fire only on a flip."""

from __future__ import annotations

import json
import time
from pathlib import Path


class State:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, dict] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._data = {}

    def get(self, key: str) -> dict:
        return self._data.get(key, {})

    def update(self, key: str, **fields) -> None:
        entry = self._data.setdefault(key, {})
        entry.update(fields)
        entry["updated"] = time.time()
        self.save()

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self.path)
