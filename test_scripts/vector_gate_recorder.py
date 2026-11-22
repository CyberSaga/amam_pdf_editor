"""Run-time provenance recorder for the vector gate table (H12, D24).

A measuring script wraps the function it measures with ``record_call``; the wrapper records the
qualified name of the function ACTUALLY invoked (``fn.__module__ + "." + fn.__qualname__``) and a call
count.  ``gate_row`` builds a measured row from the wrapper, so a row cannot name a label other than
the function that ran.  ``write_gate_table`` writes ``test_scripts/data/vector_gate_table.json`` and
refuses any string that carries a machine path, the host name or the user name (device-guard rule).
"""

from __future__ import annotations

import getpass
import json
import logging
import math
import re
import socket
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TABLE_PATH = Path(__file__).resolve().parent / "data" / "vector_gate_table.json"
SCHEMA = 1
_MIN_NAME = 4  # shorter names are too common to match as words
_PATH_LIKE = re.compile(r"[A-Za-z]:[\\/]|\\\\|/Users/|/home/|\\Users\\")


class RecordedCall:
    """A callable that forwards to ``fn`` and counts the calls; ``name`` is the function that runs."""

    def __init__(self, fn: Callable[..., Any]) -> None:
        self._fn = fn
        self.name = f"{fn.__module__}.{fn.__qualname__}"
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        return self._fn(*args, **kwargs)


def record_call(fn: Callable[..., Any]) -> RecordedCall:
    return RecordedCall(fn)


def gate_row(number: float, unit: str, recorded: RecordedCall, commit: str, sample_digest: str) -> dict[str, object]:
    """A measured row; ``callable`` and ``calls`` come from the recorder, never from the caller."""
    return {
        "number": number,
        "unit": unit,
        "callable": recorded.name,
        "calls": recorded.calls,
        "commit": commit,
        "sample_digest": sample_digest,
    }


def _machine_strings() -> list[str]:
    out = []
    for fn in (socket.gethostname, getpass.getuser):
        try:
            value = fn()
        except Exception:  # noqa: BLE001 - an unknown user or host cannot leak
            continue
        if len(value) >= _MIN_NAME:
            out.append(value.lower())
    return out


def mentions_machine_name(text: str, machine: list[str]) -> bool:
    """A user or host name as a whole token (not inside a longer alphanumeric run): a short name such as
    ``mod`` must not reject ``model``."""
    low = text.lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(m)}(?![a-z0-9])", low) for m in machine)


def _check_strings(value: object, machine: list[str], where: str) -> None:
    if isinstance(value, str):
        if _PATH_LIKE.search(value) or mentions_machine_name(value, machine):
            raise ValueError(f"{where}: a machine path, host name or user name must not be written")
    elif isinstance(value, Mapping):
        for k, v in value.items():
            _check_strings(k, machine, where)
            _check_strings(v, machine, f"{where}.{k}")
    elif isinstance(value, (list, tuple)):
        for v in value:
            _check_strings(v, machine, where)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{where}: {value!r} is not finite")


def write_gate_table(rows: Mapping[str, Mapping[str, object]], path: Path | None = None) -> Path:
    """Write ``{"schema": 1, "gates": rows}`` as JSON (NaN and infinity refused)."""
    machine = _machine_strings()
    _check_strings(rows, machine, "gates")
    target = TABLE_PATH if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"schema": SCHEMA, "gates": rows}, indent=2, sort_keys=True, allow_nan=False) + "\n"
    target.write_text(text, encoding="utf-8", newline="\n")
    return target
