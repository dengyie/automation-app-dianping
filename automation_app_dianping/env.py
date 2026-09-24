"""Minimal ``.env`` loader (no third-party dependency).

The project ships ``.env.example`` and gitignores ``.env``, but nothing read
it -- so settings like the CPA image key never reached the app. Loading is
explicit (the CLI entry calls it) rather than an import side effect, and it
never overrides variables already present in the real environment, so a
shell export and CI configuration always win.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

DEFAULT_ENV_FILE = ".env"


def _default_env_file() -> str:
    """Prefer the checkout's own ``.env`` (repo root, the package's parent)
    over whatever directory the process happens to be started from."""
    candidate = Path(__file__).resolve().parent.parent / DEFAULT_ENV_FILE
    return str(candidate) if candidate.is_file() else DEFAULT_ENV_FILE


def _parse_value(value: str) -> str:
    """Strip one layer of quotes, then an inline ``#`` comment.

    Quoted values keep ``#`` inside the quotes; unquoted values drop a
    comment only when it is preceded by whitespace (``A=1 #c`` -> ``1``,
    ``A=a#b`` stays ``a#b``), matching python-dotenv's convention.
    """
    if value[:1] in ('"', "'"):
        end = value.find(value[0], 1)
        if end != -1:
            return value[1:end]
    for idx, ch in enumerate(value):
        if ch == "#" and idx and value[idx - 1].isspace():
            return value[:idx].rstrip()
    return value


def parse_env_file(path: str = DEFAULT_ENV_FILE) -> Dict[str, str]:
    """Parse ``KEY=VALUE`` lines; blank lines, comments and junk are skipped."""
    values: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read()
    except OSError:
        return values
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            continue
        values[key] = _parse_value(value.strip())
    return values


def load_dotenv(path: Optional[str] = None) -> Dict[str, str]:
    """Load ``path`` (default: the checkout's ``.env``) into ``os.environ``;
    existing variables are kept."""
    values = parse_env_file(path or _default_env_file())
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return values
