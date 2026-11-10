from pathlib import Path

import pytest

from automation_app_dianping.config import DianpingAppConfig, DianpingPublishPolicy
from automation_app_dianping.services import (
    PublishGateError,
    assert_publish_allowed,
    assert_rate_limits,
    assert_review_allowed,
    draft_to_publish_parameters,
    mark_draft_published,
    prepare_publish_checklist,
    record_publish,
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


def test_assert_publish_allowed_no_submit_skips_bookkeeping_gates(tmp_path: Path):
    """no_submit rehearsal: an already-published draft passes the gate —
    the rehearsal stops before the submit tap, so published-at / quota /
    interval bookkeeping is irrelevant. Content validation still applies."""
    published = _draft(status="published", published_at="2026-11-01T00:00:00Z")
    config = DianpingAppConfig(city="shanghai")
    with pytest.raises(PublishGateError, match="already published"):
        assert_publish_allowed(draft=published, config=config, data_dir=tmp_path)
    # same draft, rehearsal mode → allowed
    assert_publish_allowed(
        draft=published, config=config, data_dir=tmp_path, no_submit=True
    )
    # short content is still rejected even in rehearsal mode
    short = _draft(content="太短", status="published", published_at="2026-11-01T00:00:00Z")
    with pytest.raises(PublishGateError):
        assert_publish_allowed(
            draft=short, config=config, data_dir=tmp_path, no_submit=True
        )


def test_record_publish_advances_quota_and_interval(tmp_path: Path):
    """A direct (no-draft) publish still advances the shared bookkeeping."""
    config = DianpingAppConfig(
        city="shanghai",
        publish=DianpingPublishPolicy(max_per_day=1, min_interval_minutes=60),
    )
    assert_rate_limits(config=config, data_dir=tmp_path)

    record_publish(data_dir=tmp_path)

    with pytest.raises(PublishGateError, match="quota"):
        assert_rate_limits(config=config, data_dir=tmp_path)


def test_record_publish_counts_toward_the_interval_gate(tmp_path: Path):
    config = DianpingAppConfig(
        city="shanghai",
        publish=DianpingPublishPolicy(max_per_day=5, min_interval_minutes=60),
    )
    record_publish(data_dir=tmp_path)

    with pytest.raises(PublishGateError, match="interval"):
        assert_rate_limits(config=config, data_dir=tmp_path)


def test_assert_review_allowed_rejects_all_five_ratings():
    """The all-five pattern is the low-quality spam signal the project's
    own review-writing guide warns about."""
    config = DianpingAppConfig(city="shanghai")
    body = ("红烧肉肥而不腻，响油鳝丝很香，环境有烟火气，服务利落，值得再来。" * 4)
    with pytest.raises(PublishGateError, match="all-five"):
        assert_review_allowed(
            content=body,
            ratings={"taste": 5, "environment": 5, "service": 5},
            config=config,
        )
    # a mixed pattern passes
    assert_review_allowed(
        content=body,
        ratings={"taste": 5, "environment": 5, "service": 4},
        config=config,
    )
