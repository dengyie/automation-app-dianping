"""Opt-in live execution helpers.

Default tests must never enable this path. Live runs require an explicit
environment flag and an injected session factory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


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


@dataclass(frozen=True)
class LiveRunRequest:
    draft_id: str
    app_id: str = "com.dianping.v1"
    city: str = "shanghai"
    enable_slidex: bool = False


def build_live_workflow(
    *,
    session_factory: Callable[[], Any],
    draft_id: str,
    data_dir: str = "data",
    city: str = "shanghai",
    app_id: str = "com.dianping.v1",
    enable_slidex: bool = False,
    env: Optional[dict] = None,
):
    """Build a publish workflow from a stored draft after business gate checks."""
    require_live_enabled(env)

    from automation_runner import WorkflowContext, WorkflowOptions

    from automation_app_dianping.composition import (
        build_composition,
        create_workflow_from_composition,
    )
    from automation_app_dianping.config import DianpingAppConfig
    from automation_app_dianping.services import (
        assert_publish_allowed,
        draft_to_publish_parameters,
    )
    from automation_app_dianping.storage import DraftStore

    draft = DraftStore(Path(data_dir)).load(draft_id)
    if draft is None:
        raise FileNotFoundError("draft not found: %s" % draft_id)

    config = DianpingAppConfig(city=city, app_id=app_id)
    assert_publish_allowed(draft=draft, config=config, data_dir=Path(data_dir))

    composition = build_composition(enable_slidex=enable_slidex)
    options = WorkflowOptions(
        app_id=config.app_id,
        parameters=draft_to_publish_parameters(draft),
    )
    return create_workflow_from_composition(
        composition,
        session_factory=session_factory,
        context=WorkflowContext(workflow_name="dianping-publish", live=True),
        options=options,
    )
