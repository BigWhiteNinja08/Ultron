"""Ultronov dolgoročni spomin: dejstva o človeku, ki preživijo ponovni zagon."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

MAX_FACTS = 200
MAX_FACT_CHARS = 500


def ultron_home() -> Path:
    return Path(os.environ.get("ULTRON_HOME") or Path.home() / ".ultron")


class Memory:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else ultron_home() / "memory.json"
        self.facts: list[str] = self._load()

    def _load(self) -> list[str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [str(f) for f in data.get("facts", [])][-MAX_FACTS:]
        except (OSError, ValueError, AttributeError):
            return []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"facts": self.facts}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, fact: str) -> bool:
        fact = " ".join(str(fact).split())[:MAX_FACT_CHARS]
        if not fact or fact.lower() in {f.lower() for f in self.facts}:
            return False
        self.facts = (self.facts + [fact])[-MAX_FACTS:]
        self._save()
        return True

    def clear(self) -> None:
        self.facts = []
        self._save()
