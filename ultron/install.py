"""Ustvari model `ultron` v Ollami: prenese odprti model in mu vgradi Ultronovo osebnost."""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from typing import Callable, Optional

from .brain import DEFAULT_NUM_CTX
from .ollama import Ollama
from .persona import ULTRON_SYSTEM_PROMPT

MODEL_NAME = "ultron"
MODEL_PARAMETERS = {"temperature": 0.8, "num_ctx": DEFAULT_NUM_CTX}


@dataclass(frozen=True)
class Tier:
    name: str
    base: str
    download: str
    needs: str
    min_ram_gb: int


TIERS = {
    "mini": Tier("mini", "qwen3.5:4b", "3,4 GB", "8 GB RAM", 0),
    "standard": Tier("standard", "gemma4:12b", "7,6 GB", "16 GB RAM ali GPU z 8+ GB", 14),
    "max": Tier("max", "gemma4:26b", "19 GB", "32 GB RAM ali GPU z 24+ GB", 30),
}


def total_ram_gb() -> Optional[float]:
    """Best-effort physical memory size, used to suggest a tier."""
    try:
        if sys.platform == "win32":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (n, ctypes.c_ulonglong)
                    for n in ("total", "avail", "total_page", "avail_page", "total_virtual", "avail_virtual", "ext")
                ]

            status = MemoryStatus(length=ctypes.sizeof(MemoryStatus))
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.total / 1024**3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (AttributeError, ValueError, OSError):
        return None


def suggest_tier(ram_gb: Optional[float]) -> Tier:
    if ram_gb is None:
        return TIERS["standard"]
    fitting = [t for t in TIERS.values() if ram_gb >= t.min_ram_gb]
    return max(fitting, key=lambda t: t.min_ram_gb)


def modelfile(base: str) -> str:
    lines = [
        "# Ultron - lokalni AI model brez API ključa.",
        "# Ustvari ga z: ollama create ultron -f Modelfile   (ali: ultron install)",
        f"FROM {base}",
    ]
    lines += [f"PARAMETER {key} {value}" for key, value in MODEL_PARAMETERS.items()]
    lines.append(f'SYSTEM """{ULTRON_SYSTEM_PROMPT}"""')
    return "\n".join(lines) + "\n"


def install(
    client: Ollama,
    base: str,
    name: str = MODEL_NAME,
    progress: Callable[[str, Optional[float]], None] = lambda status, fraction: None,
) -> None:
    """Pull `base` if needed and create the `name` model with Ultron's persona baked in."""
    if base not in client.models() and f"{base}:latest" not in client.models():
        for chunk in client.pull(base):
            total, done = chunk.get("total"), chunk.get("completed")
            fraction = done / total if total and done is not None else None
            progress(chunk.get("status", ""), fraction)
    for chunk in client.create(name, base, ULTRON_SYSTEM_PROMPT, MODEL_PARAMETERS):
        progress(chunk.get("status", ""), None)
