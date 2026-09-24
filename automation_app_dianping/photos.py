"""Review-photo resolution with a strict priority chain.

1. The newest staged photo under ``data/photos/<slug>/`` — the most recent
   scraped/captured shot wins by mtime (never the fixed default first).
2. A freshly generated dish photo via CPA ``gpt-image-2`` (best-effort; a
   missing key or network failure falls through, never blocks a publish).
3. The fixed default reference photo (``artifacts/gni2_pulled.jpg``).

Generated photos are written into the same ``data/photos/<slug>/`` tree, so
the next resolution sees them as the latest staged photo and the chain
repeats without re-generating.

This module never touches the device gallery: the picker-side staging into
``Pictures/DianpingAuto`` stays the only path that puts a photo on the
phone, and it only ever receives the resolved host paths.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from automation_app_dianping.config import default_review_photos
from automation_app_dianping.imagegen import generate_review_photo

_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"})

# ``data/photos/<slug>/`` holds scraped best-shots and generated photos. The
# directory is also where imagegen writes, so mtime ordering is the whole
# "newest wins" contract.
_STAGED_PHOTO_SUBDIR = "photos"


def _slug_from_shop_name(shop_name: str) -> str:
    """Derive the staged-photo subdirectory key from a shop name.

    Mirrors imagegen's file-slug so manual and generated photos for the
    same shop land in one directory. Drafts carry an explicit ``shop_slug``
    (e.g. ``weixiangzhai-yandanglu``); this is only the fallback when no
    draft slug is available.
    """
    from automation_app_dianping.imagegen import _sanitize_slug

    return _sanitize_slug(shop_name) or "review"


def _mtime(path: Path) -> float:
    """mtime for ordering, 0.0 when the file vanished mid-scan.

    A concurrent delete must not raise out of ``resolve_review_photos`` and
    abort a publish — the chain stays best-effort.
    """
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _latest_staged_photos(data_dir: str, slug: str, limit: int) -> List[str]:
    """Newest image files under ``data/photos/<slug>/`` by mtime, descending."""
    root = Path(data_dir) / _STAGED_PHOTO_SUBDIR / slug
    if not root.is_dir():
        return []
    files = [
        path
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
    ]
    files.sort(key=_mtime, reverse=True)
    return [str(path) for path in files[: max(limit, 0)]]


def resolve_review_photos(
    *,
    slug: str = "",
    shop_name: str,
    data_dir: str = "data",
    limit: int = 1,
    dish_hint: str = "",
    env: Optional[Dict[str, str]] = None,
    allow_generate: bool = True,
) -> List[str]:
    """Resolve review photos by the documented priority chain.

    ``slug`` is the draft's shop slug and doubles as the staged-photo
    subdirectory (``data/photos/<slug>/``); when omitted it is derived from
    ``shop_name`` the same way imagegen names generated files, so manual and
    generated photos share one directory. The key is sanitized so a stored
    draft field can never escape ``data/photos/`` (traversal or absolute
    path). Returns host paths ready for the publish ``photos`` parameter;
    never touches the device gallery.
    """
    directory_key = _slug_from_shop_name(slug or shop_name)
    staged = _latest_staged_photos(data_dir, directory_key, limit)
    if staged:
        print(
            "[dianping-photos] using newest staged photo(s) for %s: %s"
            % (directory_key, staged),
            flush=True,
        )
        return staged
    if allow_generate:
        out_dir = str(Path(data_dir) / _STAGED_PHOTO_SUBDIR / directory_key)
        generated = generate_review_photo(
            shop_name=shop_name,
            dish_hint=dish_hint,
            out_dir=out_dir,
            env=env,
        )
        if generated:
            print(
                "[dianping-photos] using generated photo for %s: %s"
                % (directory_key, generated),
                flush=True,
            )
            return [str(generated)]
    return default_review_photos()


def resolve_review_photos_enabled(env: Optional[Dict[str, str]] = None) -> bool:
    """Opt-out switch for the photo-resolution chain.

    Defaults on; set ``DIANPING_PHOTO_RESOLVE=0`` to pin the fixed default
    photo (e.g. deterministic keepsake runs). Any other value keeps the
    chain enabled.
    """
    source = env if env is not None else os.environ
    value = str(source.get("DIANPING_PHOTO_RESOLVE", "")).strip().lower()
    return value not in {"0", "false", "no", "off"}