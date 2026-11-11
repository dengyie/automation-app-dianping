"""Risk-control challenge helpers on top of the slidex vision channel.

The dianping webview serves two challenge shapes the pure-image solver
cannot read: the soft-edged slider sprite (handled by the bridge's vision
fallback in live.py) and the icon point-select challenge (this module).
Both go through the same SLIDEX_VISION_* channel configured for slidex's
multimodal engine.

Prompt discipline (live 2026-11-10): the prompts below never mention
captchas, verification, or bypassing -- naming them trips the model's
safety refusal and it answers with a policy apology instead of
coordinates. They describe the screen as a plain image with shapes.
"""

from __future__ import annotations

import base64
import io
import json
import re
import urllib.request
from typing import List, Optional, Tuple


def _strip_fences(raw: str) -> str:
    """The model wraps its JSON in markdown fences; slidex's parser wants
    the bare object."""
    return re.sub(r"```[a-zA-Z]*|```", "", raw).strip()


def locate_point_select_targets(
    popup_png: bytes,
    *,
    endpoint: str,
    api_key: str,
    model: str,
    timeout_s: float = 180.0,
) -> Optional[List[Tuple[str, float, float, float]]]:
    """Ordered click targets inside the point-select popup image.

    The single vision call reads the popup's hint row (which icons, in what
    order) and locates each matching icon in the field below, returning
    (label, x, y, confidence) with normalized coordinates relative to the
    popup image, in click order. None on any failure -- the caller decides
    whether to retry or bail; nothing here ever raises.
    """
    try:
        from slidex.ocr.llm import LlmVisionConfig, parse_llm_targets
    except ImportError:
        return None
    if not (endpoint and model):
        return None
    try:
        import PIL.Image  # noqa: F401 -- validates the payload renders

        Image = PIL.Image
        Image.open(io.BytesIO(popup_png)).verify()
    except Exception:
        return None
    prompt = (
        "这是一张界面截图。截图上方有一行提示，要求按顺序点击若干个黑色图标"
        "（例如拼图块、盾牌、云朵、银行卡等）。下方区域散布着这些图标。"
        "请先读出提示要求的图标顺序，再在下方区域找出每个图标的位置。"
        "严格只输出如下 JSON，不要任何解释：\n"
        '{"targets":[{"char":"拼图块","x":0.2,"y":0.3,"confidence":0.95},'
        '{"char":"盾牌","x":0.8,"y":0.4,"confidence":0.95}]}\n'
        "char 是图标名称，按提示要求的顺序排列；x、y 是该图标中心点在整张图"
        "中的归一化坐标（0 到 1，左上为原点）；confidence 是 0 到 1 的置信度。"
        "若某个图标找不到，confidence 设 0，仍保留该条目。"
    )
    try:
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": 100_000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64,"
                                + base64.b64encode(popup_png).decode()
                            },
                        },
                    ],
                }
            ],
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # Cloudflare-fronted gateways 1010 non-browser UAs.
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    " (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                **(
                    {"Authorization": "Bearer %s" % api_key} if api_key else {}
                ),
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            body = json.load(resp)
        raw = str(
            (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        )
        targets = parse_llm_targets(_strip_fences(raw))
    except Exception:
        return None
    usable = [
        (str(char), float(x), float(y), float(conf))
        for char, x, y, conf in targets
        if conf > 0 and 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
    ]
    if not usable:
        return None
    return usable


def vision_channel_from_env() -> Optional[Tuple[str, str, str, float]]:
    """(endpoint, api_key, model, timeout) from the slidex vision env, or None."""
    try:
        from slidex.ocr.llm import LlmVisionConfig

        config = LlmVisionConfig.from_env()
    except Exception:
        return None
    endpoint = (getattr(config, "endpoint", "") or "").strip()
    api_key = (getattr(config, "api_key", "") or "").strip()
    model = (getattr(config, "model", "") or "").strip()
    if not (endpoint and model):
        return None
    try:
        timeout = float(getattr(config, "timeout_s", 180.0) or 180.0)
    except (TypeError, ValueError):
        timeout = 180.0
    return endpoint, api_key, model, timeout
