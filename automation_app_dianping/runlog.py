"""Per-run JSONL event log for post-run analysis.

The live run's decisions used to be observable only in the ephemeral stdout
stream and the failure artifacts, so every post-mortem meant re-deriving
what happened from raw dumps. This log records the decisions themselves:
which dialog candidates were on screen, what the editor-chrome filter
skipped, where the slider handle was found and how far the drag went,
whether the overall star row was located. One JSON object per line, written
next to the run's screenshots and page dumps.

Discipline:

- Best-effort, always. A logging failure must never break a live run, and
  must never retry-spam: the first write failure parks the logger.
- No secrets. Events carry selectors, coordinates, labels and messages --
  never environment values, API keys or token material.
- Bounded fields. Messages and selector labels are truncated so one weird
  dump cannot turn a log line into a megabyte.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

# Per-field cap: messages/labels stay inspectable without ever growing
# unbounded on a hostile dump.
_FIELD_LIMIT = 400


def _safe(value: Any) -> Any:
    """Coerce one event field into JSON-safe form (never raises)."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value[:32]]
    if isinstance(value, dict):
        return {str(key)[:64]: _safe(value[key]) for key in list(value)[:32]}
    return str(value)[:_FIELD_LIMIT]


class RunEventLog:
    """Append-only JSONL event log; the first write failure parks it."""

    def __init__(self, path: Any):
        self.path = Path(path)
        self._parked = False

    def event(self, kind: str, **fields: Any) -> None:
        if self._parked:
            return
        record = {"ts": round(time.time(), 3), "kind": str(kind)[:64]}
        for key, value in fields.items():
            if isinstance(value, str) and len(value) > _FIELD_LIMIT:
                value = value[:_FIELD_LIMIT]
            record[str(key)[:64]] = _safe(value)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(record, ensure_ascii=False, default=str) + "\n"
                )
        except Exception:
            # One strike: a wedged log channel must never break the run nor
            # retry-spam on every action.
            self._parked = True

    def describe(self) -> str:
        """The log location for the operator (best-effort absolute)."""
        try:
            return str(self.path.resolve())
        except Exception:
            return str(self.path)


def emit(log: Optional[RunEventLog], kind: str, **fields: Any) -> None:
    """Log one event when a log is wired (None is the offline no-op)."""
    if log is None:
        return
    log.event(kind, **fields)


def run_log_path(artifact_root: Any, stamp: Optional[str] = None) -> Path:
    """Deterministic per-run log path under the run's artifact root."""
    mark = stamp or time.strftime("%Y%m%d-%H%M%S")
    return Path(artifact_root) / "logs" / ("run-%s.jsonl" % mark)
