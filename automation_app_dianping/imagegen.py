"""Review-photo generation through the image gateway's OpenAI-compatible endpoint.

Generation goes through the user's new-api station (``api.mangoqwq.com/v1``);
the documented model is ``gpt-image-2`` (respects the 1024x1024 size, returns
``b64_json``). The old CPA gateway (``cpa.mangoqwq.com``) is retired here:
its 2026-11-08 live runs failed with 503 ``auth_not_found`` (no upstream
codex auth for the model). Generation is strictly best-effort: with no key
configured or any network failure it returns ``None`` and the caller falls
through to the default photo. It must never block or fail a publish.
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

GEN_BASE_URL = "https://api.mangoqwq.com/v1"
GEN_IMAGE_MODEL = "gpt-image-2"
_GEN_TIMEOUT_S = 150.0
_GEN_RETRIES = 2
# Hard ceiling over the whole generation sequence: three full-length attempts
# would hold a live publish for ~7.5 minutes on a degraded gateway (the
# documented 524 lands at ~126 s), so the retries share one deadline budget.
_GEN_TOTAL_BUDGET_S = 240.0
# The gateway sits behind Cloudflare, which returns 1010 ("your browser's
# signature") for the default urllib UA -- so every request must carry a
# browser-like User-Agent or the probe never reaches the API.
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


def _safe_prompt(dish_hint: str = "") -> str:
    """Food-photo prompt tuned for diner-plausibility on dianping.

    2026-11-09 A/B on the station (辣肉面 + 烤羊肉串, 1024x1024): the old
    "写实美食摄影/浅景深/家常餐馆摆盘" template produced glossy menu-shot
    images -- pretty but obviously commercial, not what a review photo
    looks like. The winning template describes a customer's casual phone
    photo (wooden table, chopsticks, tissue box, window light); the model
    picks a plausible serving vessel from the dish name on its own. The
    shop name deliberately stays out of the prompt: the model cannot know
    the shop, and naming it only risks rendering it as signage text.
    """
    subject = dish_hint.strip() or "招牌菜品"
    return (
        "%s，刚端上桌热气腾腾，手机随手拍摄的真实用餐照片，小餐馆木餐桌上"
        "配着筷子和纸巾，窗边自然光，色彩自然不夸张，像顾客写点评时拍的"
        "照片，画面干净无文字无水印，竖构图" % subject
    )


def _fetchable_url(url: str) -> bool:
    """False for gateway answers that only make sense on its own host.

    grok-style backends return a media URL on the origin's loopback
    (``http://127.0.0.1:18000/...``) — fetching it here fails with
    connection-refused and used to burn a full retry cycle as a vague
    "no image". Skip the fetch outright; those models are only usable
    with ``response_format=b64_json``.
    """
    import ipaddress
    from urllib.parse import urlparse

    try:
        host = (urlparse(str(url)).hostname or "").lower()
    except ValueError:
        return False
    if not host or host == "localhost":
        return False
    try:
        return not ipaddress.ip_address(host).is_private
    except ValueError:
        return True  # a domain name, not an IP literal: fetchable


def _decode_image(payload: Any, url_timeout: Optional[float] = None) -> Optional[bytes]:
    """Extract image bytes from the /images/generations JSON response.

    ``url_timeout`` bounds the media-URL download; the caller passes the
    retry budget's remaining time so a slow public-URL channel cannot push
    the whole generation past ``_GEN_TOTAL_BUDGET_S`` (2MB+ media pulls
    have measured >200s on this gateway's uplink)."""
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
    if url and _fetchable_url(url):
        try:
            timeout = url_timeout if url_timeout is not None else _GEN_TIMEOUT_S
            with urllib.request.urlopen(urllib.request.Request(str(url), headers=_HEADERS), timeout=timeout) as resp:
                return resp.read()
        except (OSError, urllib.error.URLError):
            return None
    return None


def _decode_image_bytes(raw: Optional[Any], url_timeout: Optional[float] = None) -> Optional[bytes]:
    """Salvage image bytes from a raw response body.

    The gateway can answer 524 (Cloudflare marks the origin late) *with the
    finished image already in the body* -- so before treating a response as
    failed, try it as raw image, then as the JSON envelope. See the gateway ops
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
        return _decode_image(payload, url_timeout=url_timeout)
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
    """Generate one review dish photo via ``/images/generations``.

    Returns the host path of the saved PNG, or ``None`` when the key is not
    configured or generation fails. Retries share one total time budget and
    client errors (4xx) are not retried; the file lands in ``out_dir`` so
    the next resolution sees it as a staged photo.
    """
    key = _env_value(env, "DIANPING_GEN_API_KEY")
    if not key:
        print(
            "[dianping-photos] image generation skipped: DIANPING_GEN_API_KEY"
            " not set (falling back to default photo)",
            flush=True,
        )
        return None
    base = (_env_value(env, "DIANPING_GEN_BASE_URL") or GEN_BASE_URL).rstrip("/")
    model = _env_value(env, "DIANPING_GEN_IMAGE_MODEL") or GEN_IMAGE_MODEL
    endpoint = "%s/images/generations" % base
    body = json.dumps(
        {
            "model": model,
            "prompt": _safe_prompt(dish_hint),
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
                image_bytes = _decode_image_bytes(raw, url_timeout=remaining)
                if image_bytes:
                    return _save_image(image_bytes, out_dir=out_dir, shop_name=shop_name)
                last_error = exc
                if 400 <= exc.code < 500:
                    # Client errors (bad key, bad model, bad request) cannot
                    # change on a retry -- fail fast instead of burning the
                    # budget while a publish waits on a photo.
                    break
                continue
            image_bytes = _decode_image_bytes(raw, url_timeout=remaining)
            if not image_bytes:
                last_error = RuntimeError("generation response carried no image")
                continue
            return _save_image(image_bytes, out_dir=out_dir, shop_name=shop_name)
        except Exception as exc:  # noqa: BLE001 -- best-effort by contract
            # Timeouts, TLS drops and unexpected response shapes must never
            # escape this helper, or a publish would break for want of a photo.
            last_error = exc
    if last_error is not None:
        # Include the HTTP status when the gateway answered -- "HTTPError"
        # alone made the 2026-11-08 live failures (Cloudflare 1010, then a
        # 503 auth_not_found) undiagnosable from the console output alone.
        detail = type(last_error).__name__
        code = getattr(last_error, "code", None)
        if isinstance(code, int):
            detail = "%s %d" % (detail, code)
        print(
            "[dianping-photos] image generation failed after %d attempt(s): %s"
            % (attempts, detail),
            flush=True,
        )
    return None


def dish_hint_from_content(content: str) -> str:
    """Pull a dish hint for the photo prompt out of the review content.

    The review body names what was eaten, but no upstream field carries a
    clean dish name (draft ``recommendedDishes`` was never populated). A
    regex over free prose is too fragile (real drafts yield
    "肉套餐性价比"/"对肉食爱好者"), so match against a dish-word lexicon:
    the longest dish term appearing in the text wins. Metaphor mentions
    (像/如/似 before the term, e.g. "环境像咖啡馆") are dropped -- without
    the filter a simile attaches the wrong dish to a published review's
    photo. Best-effort: no usable match keeps the generic signature-dish
    prompt instead of forcing a wrong subject into the generated image.
    """
    _DISH_WORDS = (
        # noodles & rice
        "拌面", "汤面", "炒面", "拉面", "牛肉面", "辣肉面", "麻酱面", "葱油拌面",
        "盖浇饭", "煲仔饭", "叉烧饭", "烧鹅饭", "鳗鱼饭", "石锅拌饭",
        # shanghai classics
        "生煎", "小笼", "锅贴", "烧卖", "汤包", "粢饭糕", "粢饭团", "油条",
        "大馄饨", "小馄饨", "蟹粉小笼", "鲜肉生煎", "春卷", "八宝饭",
        # meat & hotpot
        "烤串", "羊肉串", "烤肉", "烧肉", "红烧肉", "东坡肉", "叉烧", "烤鸭",
        "白斩鸡", "口水鸡", "辣子鸡", "火锅", "麻辣烫", "冒菜", "串串香",
        # seafood
        "小龙虾", "香辣蟹", "蟹粉", "三文鱼", "刺身", "寿司",
        # sweets & drinks
        "双皮奶", "杨枝甘露", "红豆沙", "绿豆汤", "蛋糕", "泡芙", "蛋挞",
        "奶茶", "咖啡",
    )
    if not content:
        return ""
    found = []
    for word in _DISH_WORDS:
        idx = content.find(word)
        if idx < 0:
            continue
        # 像/如/似 within the two characters before the term marks a simile
        # ("像咖啡馆一样安静"), not the dish being reviewed.
        if any(ch in content[max(0, idx - 2):idx] for ch in "像如似"):
            continue
        found.append(word)
    if not found:
        return ""
    return max(found, key=len)


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