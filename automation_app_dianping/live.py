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


def resolve_session_factory(
    *,
    session_factory: Optional[Callable[[], Any]] = None,
    device: Optional[DianpingDeviceConfig] = None,
    env: Optional[dict] = None,
) -> Callable[[], Any]:
    if session_factory is not None:
        return session_factory
    from automation_app_dianping.session import build_session_factory

    return build_session_factory(device=device, env=env)


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

    factory = resolve_session_factory(session_factory=session_factory, device=device, env=env)
    composition = build_composition(enable_slidex=enable_slidex)
    return create_workflow_from_composition(
        composition,
        session_factory=factory,
        context=WorkflowContext(workflow_name="dianping-smoke", live=True),
        options=WorkflowOptions(app_id=app_id, parameters={"mode": "smoke"}),
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
    else:
        if not shop_name or not content:
            raise ValueError("live publish requires draft_id or shop_name+content")
        parameters = {
            "mode": "publish",
            "shop_name": shop_name,
            "content": content,
            "ratings": ratings or {"taste": 5, "environment": 4, "service": 4},
            "photos": list(photos or []),
        }

    factory = resolve_session_factory(session_factory=session_factory, device=device, env=env)
    composition = build_composition(enable_slidex=enable_slidex)
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
