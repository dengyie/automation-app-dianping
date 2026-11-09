"""Opt-in live execution helpers for authorized device runs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Optional

from automation_app_dianping.config import DianpingDeviceConfig
from automation_app_dianping.imagegen import dish_hint_from_content

LIVE_FLAG = "DIANPING_LIVE_E2E"


def live_enabled(env: Optional[dict] = None) -> bool:
    source = env if env is not None else os.environ
    value = str(source.get(LIVE_FLAG, "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def require_live_enabled(env: Optional[dict] = None) -> None:
    if not live_enabled(env):
        raise RuntimeError(
            "live E2E disabled; set %s=1 to enable authorized live runs" % LIVE_FLAG
        )


def require_uia2_publish(
    env: Optional[dict] = None,
    session_factory: Optional[Callable[[], Any]] = None,
) -> None:
    """Publish fails closed on a non-uia2 driver.

    README: production publish runs ``DIANPING_DRIVER=uia2``; the Appium flow
    wedges UiAutomation on publish, so an explicit Appium publish is refused
    rather than silently driven. An injected ``session_factory`` (tests,
    dry-run) is left alone — the caller supplied a concrete driver already.
    """
    if session_factory is not None:
        return
    source = env if env is not None else os.environ
    selected = str(source.get("DIANPING_DRIVER") or "uia2").strip().lower()
    if selected != "uia2":
        raise ValueError(
            "publish requires DIANPING_DRIVER=uia2 (got %r); the Appium flow "
            "wedges UiAutomation" % selected
        )


def resolve_session_factory(
    *,
    session_factory: Optional[Callable[[], Any]] = None,
    device: Optional[DianpingDeviceConfig] = None,
    env: Optional[dict] = None,
    slider_solver: Optional[Callable[[Any], Any]] = None,
) -> Callable[[], Any]:
    if session_factory is not None:
        return session_factory
    from automation_app_dianping.session import build_session_factory

    return build_session_factory(device=device, env=env, slider_solver=slider_solver)


def _vision_gap_left_edge(image_bytes: bytes) -> Optional[int]:
    """Locate the puzzle sprite's left edge via the slidex vision channel.

    slidex's pure-image detectors miss dianping's soft-edged, semi-transparent
    jigsaw sprite (live 2026-11-10: two puzzles, zero detections) while the
    multimodal model reads it fine. The prompt is deliberately neutral about
    what the sprite is FOR -- naming captchas trips safety refusals (the
    model answers with a policy apology instead of coordinates). Markdown
    fences are stripped before parsing. Returns the sprite's left edge in
    full-screenshot pixels, or None when the channel is unconfigured/misses.
    """
    try:
        from slidex.ocr.llm import LlmVisionConfig, parse_llm_targets
    except ImportError:
        return None
    config = LlmVisionConfig.from_env()
    if not getattr(config, "configured", False):
        return None
    try:
        import base64
        import json as _json
        import re as _re
        import urllib.request

        from PIL import Image
        import io

        shot = Image.open(io.BytesIO(image_bytes))
        width, height = shot.size
        # The puzzle renders centered on dianping's webview; crop the central
        # band so the model sees the sprite large instead of a busy full shot.
        cx0, cy0, cx1, cy1 = (
            int(width * 0.08), int(height * 0.22), int(width * 0.92), int(height * 0.72),
        )
        crop = shot.crop((cx0, cy0, cx1, cy1))
        buffer = io.BytesIO()
        crop.save(buffer, format="PNG")
        prompt = (
            "这是一张照片。图中有一个深色的拼图形状（半透明深色阴影块）。"
            "请找出这个深色拼图形状的左边缘中点。严格只输出如下 JSON：\n"
            '{"targets":[{"char":"拼图形状","x":0.70,"y":0.35,"confidence":0.9}]}\n'
            "x、y 是该左边缘中点在整张图中的归一化坐标（0 到 1，左上为原点）。"
        )
        payload = {
            "model": config.model,
            "temperature": 0,
            "max_tokens": config.max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64,"
                                + base64.b64encode(buffer.getvalue()).decode()
                            },
                        },
                    ],
                }
            ],
        }
        request = urllib.request.Request(
            config.endpoint,
            data=_json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": config.user_agent,
                "Accept": "application/json",
                **(
                    {"Authorization": "Bearer %s" % config.api_key}
                    if config.api_key
                    else {}
                ),
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=config.timeout_s) as resp:
            body = _json.load(resp)
        raw = str(
            (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        )
        # The model wraps the JSON in markdown fences; slidex's parser wants
        # the bare object.
        raw = _re.sub(r"```[a-zA-Z]*|```", "", raw).strip()
        targets = parse_llm_targets(raw)
        if not targets or targets[0][3] <= 0:
            return None
        return int(round(targets[0][1] * (cx1 - cx0)) + cx0)
    except Exception:
        return None


def _build_slider_solver(composition) -> Callable[[Any], Any]:
    """Build the session-level slider solver on top of the visual capability.

    Returns an async callable (screenshot bytes -> {"gap_x": int} or
    {"gap_offset_px": int}); the session bridges the awaitable onto a worker
    thread because actions run inside the runtime event loop.

    slidex's pure-image path (android_screenshot_bytes) reports ``gap_x`` /
    ``distance_px`` — the gap's left edge in screenshot pixels — while older
    providers reported a ready-made ``gap_offset_px``. Both are passed
    through; the session picks the one it got.
    """
    from automation_core.capabilities import CapabilityRequest
    from automation_core.execution import ExecutionContext

    executor = composition.capability_executor

    async def solve(image_bytes: bytes):
        request = CapabilityRequest(
            capability="visual.challenge",
            operation="solve",
            parameters={
                "challenge_type": "slider_captcha",
                "context": "android_screenshot_bytes",
                "image_bytes": image_bytes,
                "provider": "auto",
                "metadata": {},
            },
            metadata={},
        )
        context = ExecutionContext(
            run_id="dianping-slider",
            task_id="slider-solve",
            workflow_name="dianping-live",
        )
        result = await executor.execute(request, context)
        if not getattr(result, "success", False):
            raise RuntimeError(
                "slidex slider solve failed: %s"
                % (getattr(result, "error_code", None) or "unknown")
            )
        data = dict(getattr(result, "data", {}) or {})
        metadata = dict(data.get("metadata") or {})

        def _first(*keys):
            for source in (data, metadata):
                for key in keys:
                    if source.get(key) is not None:
                        return source[key]
            return None

        offset = _first("gap_offset_px")
        if offset is not None:
            return {"gap_offset_px": int(offset)}
        gap_x = _first("gap_x", "distance_px")
        if gap_x is None:
            # slidex's pure-image path missed (soft-edged sprite); the vision
            # channel is the second slidex leg before giving up.
            gap_x = _vision_gap_left_edge(image_bytes)
            if gap_x is None:
                raise RuntimeError(
                    "slidex slider solve returned no gap_x/gap_offset_px"
                )
        return {"gap_x": int(gap_x)}

    return solve


def build_live_smoke_workflow(
    *,
    session_factory: Optional[Callable[[], Any]] = None,
    city: str = "shanghai",
    app_id: str = "com.dianping.v1",
    enable_slidex: bool = False,
    device: Optional[DianpingDeviceConfig] = None,
    env: Optional[dict] = None,
):
    del city
    require_live_enabled(env)
    from automation_runner import WorkflowContext, WorkflowOptions
    from automation_app_dianping.composition import (
        build_composition,
        create_workflow_from_composition,
    )

    composition = build_composition(enable_slidex=enable_slidex)
    factory = resolve_session_factory(
        session_factory=session_factory,
        device=device,
        env=env,
        slider_solver=_build_slider_solver(composition) if enable_slidex else None,
    )
    return create_workflow_from_composition(
        composition,
        session_factory=factory,
        context=WorkflowContext(workflow_name="dianping-smoke", live=True),
        options=WorkflowOptions(app_id=app_id, parameters={"mode": "smoke"}),
    )


def _resolve_publish_photos(
    photos,
    *,
    shop_name: str,
    slug: str = "",
    data_dir: str = "data",
    env: Optional[dict] = None,
    dish_hint: str = "",
) -> list:
    """Choose the publish photo list by the documented priority chain.

    An explicitly authored photo list (any non-default path) is kept as-is.
    An empty or default-filled list is resolved: newest staged photo under
    ``data/photos/<slug>/`` → gateway ``gpt-image-2`` generation → the fixed
    default photo. ``DIANPING_PHOTO_RESOLVE=0`` pins the default photo.
    ``dish_hint`` grounds the generation prompt in what the review actually
    eats (falls back to the shop's signature-dish prompt when empty).
    """
    from automation_app_dianping.config import default_review_photos
    from automation_app_dianping.photos import (
        resolve_review_photos,
        resolve_review_photos_enabled,
    )

    if photos:
        canonical = set(default_review_photos())
        if any(str(path) not in canonical for path in photos):
            return list(photos)
    if not resolve_review_photos_enabled(env):
        return default_review_photos()
    return resolve_review_photos(
        slug=slug,
        shop_name=shop_name,
        data_dir=data_dir,
        env=env,
        dish_hint=dish_hint,
    )


def build_live_workflow(
    *,
    session_factory: Optional[Callable[[], Any]] = None,
    draft_id: Optional[str] = None,
    data_dir: str = "data",
    city: str = "shanghai",
    app_id: str = "com.dianping.v1",
    enable_slidex: bool = False,
    shop_name: Optional[str] = None,
    content: Optional[str] = None,
    dish_hint: str = "",
    ratings: Optional[dict] = None,
    photos: Optional[list] = None,
    device: Optional[DianpingDeviceConfig] = None,
    env: Optional[dict] = None,
    no_submit: bool = False,
):
    require_live_enabled(env)
    require_uia2_publish(env, session_factory=session_factory)
    from automation_runner import WorkflowContext, WorkflowOptions
    from automation_app_dianping.composition import (
        build_composition,
        create_workflow_from_composition,
    )
    from automation_app_dianping.config import DianpingAppConfig
    from automation_app_dianping.services import assert_publish_allowed, draft_to_publish_parameters
    from automation_app_dianping.storage import DraftStore

    config = DianpingAppConfig(city=city, app_id=app_id)
    if draft_id:
        draft = DraftStore(Path(data_dir)).load(draft_id)
        if draft is None:
            raise FileNotFoundError("draft not found: %s" % draft_id)
        assert_publish_allowed(
            draft=draft, config=config, data_dir=Path(data_dir), no_submit=bool(no_submit)
        )
        parameters = draft_to_publish_parameters(draft)
        parameters["photos"] = _resolve_publish_photos(
            parameters.get("photos"),
            shop_name=parameters.get("shop_name") or draft.shop_name,
            slug=draft.shop_slug,
            data_dir=data_dir,
            env=env,
            dish_hint=dish_hint_from_content(draft.draft.content),
        )
    else:
        if not shop_name or not content:
            raise ValueError("live publish requires draft_id or shop_name+content")

        parameters = {
            "mode": "publish",
            "shop_name": shop_name,
            "content": content,
            # All-5 default: the 2026-09 editor derives the overall stars
            # from these values, and a positive review at 4 stars reads
            # incoherently on the public page.
            "ratings": ratings or {"taste": 5, "environment": 5, "service": 5},
            "photos": _resolve_publish_photos(
                photos,
                shop_name=shop_name,
                data_dir=data_dir,
                env=env,
                dish_hint=dish_hint or dish_hint_from_content(content),
            ),
        }

    # Authorized rehearsal (no_submit): the flag flows to the publish flow so
    # it stops right before the externally-visible submit tap.
    parameters["no_submit"] = bool(no_submit)

    composition = build_composition(enable_slidex=enable_slidex)
    factory = resolve_session_factory(
        session_factory=session_factory,
        device=device,
        env=env,
        slider_solver=_build_slider_solver(composition) if enable_slidex else None,
    )
    return create_workflow_from_composition(
        composition,
        session_factory=factory,
        context=WorkflowContext(workflow_name="dianping-publish", live=True),
        options=WorkflowOptions(app_id=config.app_id, parameters=parameters),
    )


def run_live(
    *,
    mode: str = "smoke",
    draft_id: Optional[str] = None,
    data_dir: str = "data",
    city: str = "shanghai",
    app_id: str = "com.dianping.v1",
    enable_slidex: bool = False,
    shop_name: Optional[str] = None,
    content: Optional[str] = None,
    dish_hint: str = "",
    ratings: Optional[dict] = None,
    photos: Optional[list] = None,
    session_factory: Optional[Callable[[], Any]] = None,
    device: Optional[DianpingDeviceConfig] = None,
    env: Optional[dict] = None,
    mark_published: bool = False,
    no_submit: bool = False,
):
    mode_normalized = (mode or "smoke").strip().lower()
    if mode_normalized == "smoke":
        return build_live_smoke_workflow(
            session_factory=session_factory,
            city=city,
            app_id=app_id,
            enable_slidex=enable_slidex,
            device=device,
            env=env,
        ).run()
    if mode_normalized != "publish":
        raise ValueError("unsupported live mode: %s" % mode)
    result = build_live_workflow(
        session_factory=session_factory,
        draft_id=draft_id,
        data_dir=data_dir,
        city=city,
        app_id=app_id,
        enable_slidex=enable_slidex,
        shop_name=shop_name,
        content=content,
        dish_hint=dish_hint,
        ratings=ratings,
        photos=photos,
        device=device,
        env=env,
        no_submit=no_submit,
    ).run()
    if mark_published and result.success and draft_id:
        from automation_app_dianping.services import mark_draft_published
        from automation_app_dianping.storage import DraftStore

        draft = DraftStore(Path(data_dir)).load(draft_id)
        if draft is not None:
            mark_draft_published(draft=draft, data_dir=Path(data_dir))
    return result
