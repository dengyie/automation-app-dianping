"""Opt-in live execution helpers for authorized device runs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Optional

from automation_app_dianping.config import DianpingDeviceConfig

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
) -> list:
    """Choose the publish photo list by the documented priority chain.

    An explicitly authored photo list (any non-default path) is kept as-is.
    An empty or default-filled list is resolved: newest staged photo under
    ``data/photos/<slug>/`` → CPA ``gpt-image-2`` generation → the fixed
    default photo. ``DIANPING_PHOTO_RESOLVE=0`` pins the default photo.
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
    ratings: Optional[dict] = None,
    photos: Optional[list] = None,
    device: Optional[DianpingDeviceConfig] = None,
    env: Optional[dict] = None,
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
        assert_publish_allowed(draft=draft, config=config, data_dir=Path(data_dir))
        parameters = draft_to_publish_parameters(draft)
        parameters["photos"] = _resolve_publish_photos(
            parameters.get("photos"),
            shop_name=parameters.get("shop_name") or draft.shop_name,
            slug=draft.shop_slug,
            data_dir=data_dir,
            env=env,
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
            ),
        }

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
    ratings: Optional[dict] = None,
    photos: Optional[list] = None,
    session_factory: Optional[Callable[[], Any]] = None,
    device: Optional[DianpingDeviceConfig] = None,
    env: Optional[dict] = None,
    mark_published: bool = False,
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
        ratings=ratings,
        photos=photos,
        device=device,
        env=env,
    ).run()
    if mark_published and result.success and draft_id:
        from automation_app_dianping.services import mark_draft_published
        from automation_app_dianping.storage import DraftStore

        draft = DraftStore(Path(data_dir)).load(draft_id)
        if draft is not None:
            mark_draft_published(draft=draft, data_dir=Path(data_dir))
    return result
