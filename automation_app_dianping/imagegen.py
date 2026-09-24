"""Review-photo generation through the CPA gateway's image endpoint.

The CPA gateway (openai-compatible, `https://cpa.mangoqwq.com/v1`) serves
``/images/*``; the documented model is ``gpt-image-2`` (CPA rejects
``gpt-image-1``, and the gpt-5.5/5.6 series' chat image tool is disabled
upstream — generation must go through ``/images/generations``, never the
chat/response path).

Generation is strictly best-effort: with no key configured or any network
failure it returns ``None`` and the caller falls through to the default
photo. It must never block or fail a publish.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

CPA_BASE_URL = "https://cpa.mangoqwq.com/v1"
CPA_IMAGE_MODEL = "gpt-image-2"
_GEN_TIMEOUT_S = 150.0
_GEN_RETRIES = 2
# Hard ceiling over the whole generation sequence: three full-length attempts
# would hold a live publish for ~7.5 minutes on a degraded gateway (the
# documented 524 lands at ~126 s), so the retries share one deadline budget.
_GEN_TOTAL_BUDGET_S = 240.0
# The gateway sits behind Cloudflare, which returns 1010 ("your browser's
# signature") for the default urllib UA -- so every request must carry a
# browser-like User-Agent or the probe never reaches CPA.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _env_value(env: Optional[Dict[str, str]], key: str, default: str = "") -> str:
    # ``env=None`` means "read the process environment" -- same fallback
    # semantics as photos.resolve_review_photos_enabled, so a caller using
    # the documented defaults still finds a key loaded into os.environ.
    source = os.environ if env is None else env
    return str(source.get(key) or default).strip()


def _safe_prompt(shop_name: str, dish_hint: str = "") -> str:
    """Food-photo prompt grounded in the shop so generations look plausible
    for the actual review and never name a brand/member.
    """
    subject = dish_hint.strip() or "%s 的招牌菜品" % shop_name
    return (
        "写实美食摄影照片，%s，刚出锅热气腾腾，诱人的油光，家常餐馆摆盘，"
        "暖色自然光线，浅景深，画面干净，无文字无水印，竖构图" % subject
    )


def _decode_image(payload: Any) -> Optional[bytes]:
    """Extract image bytes from the /images/generations JSON response."""
    if not isinstance(payload, dict):
        return None
    items = payload.get("data") or []
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    b64 = first.get("b64_json")
    if b64:
        try:
            return base64.b64decode(b64)
        except (TypeError, ValueError):
            return None
    url = first.get("url")
    if url:
        try:
            with urllib.request.urlopen(urllib.request.Request(str(url), headers=_HEADERS), timeout=_GEN_TIMEOUT_S) as resp:
                return resp.read()
        except (OSError, urllib.error.URLError):
            return None
    return None


def _decode_image_bytes(raw: Optional[Any]) -> Optional[bytes]:
    """Salvage image bytes from a raw response body.

    The gateway can answer 524 (Cloudflare marks the origin late) *with the
    finished image already in the body* -- so before treating a response as
    failed, try it as raw image, then as the JSON envelope. See the CPA ops
    note's "524 + 有图按成功处理" salvage rule.
    """
    if not raw:
        return None
    if isinstance(raw, bytes):
        if raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:3] == b"\xff\xd8\xff":
            return raw
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except (ValueError, TypeError):
            return None
        return _decode_image(payload)
    return None


def _save_image(image_bytes: bytes, *, out_dir: str, shop_name: str) -> str:
    slug = _sanitize_slug(shop_name) or "review"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / ("%s-%s.png" % (slug, stamp))
    serial = 2
    while path.exists():
        path = target_dir / ("%s-%s-%d.png" % (slug, stamp, serial))
        serial += 1
    path.write_bytes(image_bytes)
    print(
        "[dianping-photos] generated review photo -> %s" % path,
        flush=True,
    )
    return str(path)


def generate_review_photo(
    *,
    shop_name: str,
    dish_hint: str = "",
    out_dir: str = "data/photos",
    env: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Generate one review dish photo via CPA ``/images/generations``.

    Returns the host path of the saved PNG, or ``None`` when the key is not
    configured or generation fails. Retries share one total time budget and
    client errors (4xx) are not retried; the file lands in ``out_dir`` so
    the next resolution sees it as a staged photo.
    """
    key = _env_value(env, "DIANPING_CPA_API_KEY")
    if not key:
        print(
            "[dianping-photos] image generation skipped: DIANPING_CPA_API_KEY"
            " not set (falling back to default photo)",
            flush=True,
        )
        return None
    base = _env_value(env, "DIANPING_CPA_BASE_URL", CPA_BASE_URL).rstrip("/")
    model = _env_value(env, "DIANPING_CPA_IMAGE_MODEL", CPA_IMAGE_MODEL)
    endpoint = "%s/images/generations" % base
    body = json.dumps(
        {
            "model": model,
            "prompt": _safe_prompt(shop_name, dish_hint),
            "size": "1024x1024",
            "n": 1,
        }
    ).encode("utf-8")

    last_error: Optional[Exception] = None
    attempts = 0
    deadline = time.monotonic() + _GEN_TOTAL_BUDGET_S
    for attempt in range(_GEN_RETRIES + 1):
        if attempt:
            time.sleep(1.5)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        attempts += 1
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": "Bearer %s" % key,
                "Content-Type": "application/json",
                **_HEADERS,
            },
            method="POST",
        )
        try:
            try:
                with urllib.request.urlopen(
                    request, timeout=min(_GEN_TIMEOUT_S, remaining)
                ) as resp:
                    raw = resp.read()
            except urllib.error.HTTPError as exc:
                # The gateway can answer 524/5xx *with the finished image in
                # the body* (Cloudflare marks the origin late); salvage before
                # treating the attempt as failed.
                raw = None
                try:
                    raw = exc.read()
                except Exception:
                    raw = None
                image_bytes = _decode_image_bytes(raw)
                if image_bytes:
                    return _save_image(image_bytes, out_dir=out_dir, shop_name=shop_name)
                last_error = exc
                if 400 <= exc.code < 500:
                    # Client errors (bad key, bad model, bad request) cannot
                    # change on a retry -- fail fast instead of burning the
                    # budget while a publish waits on a photo.
                    break
                continue
            image_bytes = _decode_image_bytes(raw)
            if not image_bytes:
                last_error = RuntimeError("generation response carried no image")
                continue
            return _save_image(image_bytes, out_dir=out_dir, shop_name=shop_name)
        except Exception as exc:  # noqa: BLE001 -- best-effort by contract
            # Timeouts, TLS drops and unexpected response shapes must never
            # escape this helper, or a publish would break for want of a photo.
            last_error = exc
    if last_error is not None:
        print(
            "[dianping-photos] image generation failed after %d attempt(s): %s"
            % (attempts, type(last_error).__name__),
            flush=True,
        )
    return None


def _sanitize_slug(name: str) -> str:
    cleaned = []
    for ch in name:
        if ch.isalnum() or ch in "-_":
            cleaned.append(ch)
        else:
            cleaned.append("-")
    slug = "".join(cleaned)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-").lower()[:60] or "image"