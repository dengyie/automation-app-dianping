"""Application services for Dianping business flows.

These helpers sit above storage/config and below live adapter execution.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

from automation_app_dianping.config import DianpingAppConfig, validate_review_content
from automation_app_dianping.storage import (
    DraftRecord,
    DraftStore,
    StateStore,
    build_publish_items,
    write_publish_checklist,
)


class PublishGateError(ValueError):
    pass


def prepare_publish_checklist(
    *,
    data_dir: Path = Path("data"),
    as_json: bool = False,
    output: Optional[Path] = None,
):
    store = DraftStore(data_dir)
    items = build_publish_items(store.list())
    path = write_publish_checklist(items, data_dir=data_dir, as_json=as_json, output=output)
    return {"count": len(items), "path": str(path), "items": items}


def draft_to_publish_parameters(draft: DraftRecord) -> Dict[str, Any]:
    return {
        "mode": "publish",
        "draft_id": draft.id,
        "shop_name": draft.shop_name,
        "shop_url": draft.shop_url,
        "content": draft.draft.content,
        "ratings": asdict(draft.draft.ratings),
        "photos": list(draft.draft.photos),
    }


def assert_publish_allowed(
    *,
    draft: DraftRecord,
    config: DianpingAppConfig,
    data_dir: Path = Path("data"),
) -> None:
    error = validate_review_content(
        draft.draft.content,
        asdict(draft.draft.ratings),
        min_chinese_chars=config.publish.min_chinese_chars,
    )
    if error:
        raise PublishGateError(error)
    if draft.published_at or draft.draft.status == "published":
        raise PublishGateError("draft already published: %s" % draft.id)

    state_store = StateStore(data_dir)
    state = state_store.load()
    if not state_store.can_publish_today(state, config.publish.max_per_day):
        raise PublishGateError(
            "daily publish quota exceeded (%s/%s)"
            % (state.today_published_count, config.publish.max_per_day)
        )
    minutes = state_store.minutes_since_last_publish(state)
    if minutes is not None and minutes < config.publish.min_interval_minutes:
        remaining = config.publish.min_interval_minutes - minutes
        raise PublishGateError("publish interval not met; wait %.1f more minutes" % remaining)


def mark_draft_published(
    *,
    draft: DraftRecord,
    data_dir: Path = Path("data"),
    published_at: Optional[str] = None,
) -> DraftRecord:
    from datetime import datetime, timezone

    stamp = published_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    draft.draft.status = "published"
    draft.published_at = stamp
    DraftStore(data_dir).save(draft)

    state_store = StateStore(data_dir)
    state = state_store.load()
    state_store.refresh(state)
    state.today_published_count += 1
    state.last_published_timestamp = stamp
    state_store.save(state)
    return draft
