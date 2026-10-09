"""Page-data providers: drop a module in this folder and its data reaches the status page.

A provider is `tcgwatch/site_data/<name>.py` exposing `provide(cfg, state, groups) -> dict`.
`groups` is the page's product groups (read-only by convention). The returned keys are merged into
the data the page embeds as `D`. A key that the core page already uses, or that another provider
returned, fails the build rather than silently overwriting it. Names starting with `_` are skipped.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Iterable

PROVIDER_DIR = Path(__file__).resolve().parent


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"tcgwatch.site_data.{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "provide", None)):
        raise ValueError(f"site_data provider {path.name} has no provide(cfg, state, groups)")
    return module


def provide_all(cfg, state, groups: list[dict], reserved: Iterable[str] = ()) -> dict:
    """Run every provider in name order and return their merged data."""
    taken = set(reserved)
    merged: dict = {}
    for path in sorted(PROVIDER_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        extra = _load(path).provide(cfg, state, groups)
        clash = sorted(set(extra) & taken)
        if clash:
            raise ValueError(f"site_data provider {path.name} reuses page data keys: {', '.join(clash)}")
        taken.update(extra)
        merged.update(extra)
    return merged
