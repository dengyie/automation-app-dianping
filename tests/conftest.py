"""Shared pytest fixtures.

The default review photo is a real-device artifact: ``artifacts/`` is
gitignored, so ``artifacts/gni2_pulled.jpg`` exists on a developer's machine
but never in CI. Tests that exercise the default photo slot materialise the
file under ``tmp_path`` and repoint ``config.DEFAULT_REVIEW_PHOTO`` at it,
rather than asserting on a file only a local working copy happens to have.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_app_dianping import config

# Smallest valid JPEG (SOI + APP0/JFIF + EOI): enough for ``is_file`` and for
# the staging helpers that merely read bytes.
_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


@pytest.fixture
def default_photo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``config.DEFAULT_REVIEW_PHOTO`` at a real file under tmp_path."""
    path = tmp_path / "artifacts" / "gni2_pulled.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_JPEG)
    monkeypatch.setattr(config, "DEFAULT_REVIEW_PHOTO", path)
    return path
