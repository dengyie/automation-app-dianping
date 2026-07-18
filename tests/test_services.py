from pathlib import Path

import pytest

from automation_app_dianping.config import DianpingAppConfig, DianpingPublishPolicy
from automation_app_dianping.services import (
    PublishGateError,
    assert_publish_allowed,
    draft_to_publish_parameters,
    mark_draft_published,
    prepare_publish_checklist,
)
from automation_app_dianping.storage import DraftRecord, DraftReview, DraftStore, ReviewRatings


def _draft(content=None, status="edited", published_at=None):
    text = content or ("红烧肉肥而不腻，响油鳝丝很香，环境有烟火气，服务利落，值得再来。" * 4)
    return DraftRecord(
        id="gate-1",
        shop_url="https://www.dianping.com/shop/gate1",
        shop_name="闸门店",
        shop_slug="gate1",
        draft=DraftReview(
            content=text,
            ratings=ReviewRatings(taste=5, environment=4, service=4),
            photos=["p.jpg"],
            status=status,
        ),
        published_at=published_at,
    )


def test_prepare_publish_checklist_and_parameters(tmp_path: Path):
    DraftStore(tmp_path).save(_draft())
    result = prepare_publish_checklist(data_dir=tmp_path, as_json=True)
    assert result["count"] == 1
    params = draft_to_publish_parameters(result["items"][0] and DraftStore(tmp_path).load("gate-1"))
    assert params["mode"] == "publish"
    assert params["shop_name"] == "闸门店"


def test_assert_publish_allowed_and_mark_published(tmp_path: Path):
    draft = _draft()
    DraftStore(tmp_path).save(draft)
    config = DianpingAppConfig(city="shanghai", publish=DianpingPublishPolicy(max_per_day=2, min_interval_minutes=0))
    assert_publish_allowed(draft=draft, config=config, data_dir=tmp_path)
    marked = mark_draft_published(draft=draft, data_dir=tmp_path)
    assert marked.draft.status == "published"
    with pytest.raises(PublishGateError, match="already published"):
        assert_publish_allowed(draft=marked, config=config, data_dir=tmp_path)


def test_assert_publish_allowed_rejects_short_content(tmp_path: Path):
    draft = _draft(content="太短")
    config = DianpingAppConfig(city="shanghai")
    with pytest.raises(PublishGateError):
        assert_publish_allowed(draft=draft, config=config, data_dir=tmp_path)
