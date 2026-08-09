"""Saved column choices for report printing/exporting.

When a user picks which columns to include in a printout, they can save that
selection as a named preset (per report). Presets are stored as a small JSON
file in the data directory so they persist across sessions and users on this PC.

Shape: { "<report_key>": { "<preset name>": ["col_key", ...] } }
"""
from __future__ import annotations

import json
from pathlib import Path


class ColumnPresetStore:
    def __init__(self, data_root) -> None:
        self._file = Path(data_root) / "report_columns.json"

    def _load(self) -> dict:
        try:
            return json.loads(self._file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_all(self, data: dict) -> None:
        try:
            self._file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def presets(self, report_key: str) -> dict[str, list[str]]:
        """All saved presets for one report: {name: [column keys]}."""
        return self._load().get(report_key, {})

    def save(self, report_key: str, name: str, keys: list[str]) -> None:
        data = self._load()
        data.setdefault(report_key, {})[name] = list(keys)
        self._save_all(data)

    def delete(self, report_key: str, name: str) -> None:
        data = self._load()
        if report_key in data and name in data[report_key]:
            del data[report_key][name]
            self._save_all(data)
