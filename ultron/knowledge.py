"""Ultronovo znanje: študijski zapiski o temah, ki se jih nauči, in preživijo ponovni zagon."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Optional

from .memory import ultron_home

MAX_TOPICS = 300
MAX_NOTE_CHARS = 40000
MAX_SOURCES = 12


def _norm(topic: str) -> str:
    return " ".join(str(topic).lower().split())[:120]


class Knowledge:
    """A growing library of study notes, one entry per topic, stored on disk."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else ultron_home() / "knowledge.json"
        self.entries: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            entries = data.get("topics", {})
            return {k: v for k, v in entries.items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            return {}

    def _save(self) -> None:
        # Keep only the most recently updated topics if the library grows too large.
        if len(self.entries) > MAX_TOPICS:
            keep = sorted(self.entries.items(), key=lambda kv: kv[1].get("updated", ""), reverse=True)[:MAX_TOPICS]
            self.entries = dict(keep)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"topics": self.entries}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def learn(self, topic: str, notes: str, sources: Optional[list] = None, summary: str = "") -> str:
        topic = " ".join(str(topic).split())[:120]
        key = _norm(topic)
        if not key or not notes.strip():
            return ""
        entry = {
            "topic": topic,
            "notes": notes.strip()[:MAX_NOTE_CHARS],
            "summary": (summary or notes.strip().split("\n", 1)[0])[:280],
            "sources": [s for s in (sources or []) if isinstance(s, str)][:MAX_SOURCES],
            "updated": date.today().isoformat(),
        }
        # Merge with existing notes on the same topic rather than overwriting them.
        if key in self.entries:
            old = self.entries[key].get("notes", "")
            if entry["notes"] not in old:
                entry["notes"] = (old + "\n\n---\n\n" + entry["notes"])[-MAX_NOTE_CHARS:]
        self.entries[key] = entry
        self._save()
        return key

    def get(self, query: str) -> Optional[dict]:
        q = _norm(query)
        if not q:
            return None
        if q in self.entries:
            return self.entries[q]
        for key, entry in self.entries.items():
            if q in key or key in q:
                return entry
        words = set(q.split())
        best, best_score = None, 0
        for key, entry in self.entries.items():
            score = len(words & set(key.split()))
            if score > best_score:
                best, best_score = entry, score
        return best

    def search(self, query: str) -> list[dict]:
        q = _norm(query)
        words = set(q.split())
        hits = []
        for key, entry in self.entries.items():
            haystack = (key + " " + entry.get("notes", "")).lower()
            if q and (q in haystack or words & set(key.split())):
                hits.append(entry)
        return hits

    def topics(self) -> list[str]:
        return [e["topic"] for e in sorted(self.entries.values(), key=lambda e: e.get("updated", ""), reverse=True)]

    def forget(self, query: str) -> bool:
        entry = self.get(query)
        if not entry:
            return False
        key = next((k for k, v in self.entries.items() if v is entry), None)
        if key is not None:
            del self.entries[key]
            self._save()
            return True
        return False

    def clear(self) -> None:
        self.entries = {}
        self._save()


def extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"https?://[^\s)\]]+", text)))[:MAX_SOURCES]
