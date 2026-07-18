import pytest

from automation_app_dianping.config import (
    DianpingAppConfig,
    count_chinese_chars,
    default_selectors,
    validate_review_content,
)


def test_dianping_app_config_holds_domain_fields():
    config = DianpingAppConfig(city="shanghai", app_id="com.dianping.v1")

    assert config.city == "shanghai"
    assert config.app_id == "com.dianping.v1"
    assert config.activity
    assert config.publish.max_per_day == 2


def test_dianping_app_config_rejects_blank_city():
    with pytest.raises(ValueError, match="city"):
        DianpingAppConfig(city="   ")


def test_default_selectors_expose_rating_star_lookup():
    selectors = default_selectors()
    star = selectors.rating_star("taste", 4)
    assert isinstance(star, str) and "UiSelector" in star
    assert selectors.rating_star("taste", 9) is None


def test_validate_review_content_enforces_business_rules():
    short = "很好吃"
    assert validate_review_content(short, {"taste": 4, "environment": 4, "service": 3}) is not None

    content = "红烧肉肥而不腻，响油鳝丝很香，环境有烟火气，服务也利落，值得再来一次。" * 4
    assert count_chinese_chars(content) >= 100
    assert (
        validate_review_content(
            content,
            {"taste": 4, "environment": 4, "service": 3},
        )
        is None
    )
    assert (
        validate_review_content(
            content,
            {"taste": 5, "environment": 5, "service": 5},
        )
        is not None
    )


def test_dianping_app_config_rejects_invalid_publish_policy():
    from automation_app_dianping.config import DianpingPublishPolicy

    with pytest.raises(ValueError, match="app_id"):
        DianpingAppConfig(city="shanghai", app_id=" ")
    with pytest.raises(ValueError, match="activity"):
        DianpingAppConfig(city="shanghai", activity=" ")
    with pytest.raises(ValueError, match="max_per_day"):
        DianpingAppConfig(city="shanghai", publish=DianpingPublishPolicy(max_per_day=0))
    with pytest.raises(ValueError, match="min_interval_minutes"):
        DianpingAppConfig(city="shanghai", publish=DianpingPublishPolicy(min_interval_minutes=-1))
    with pytest.raises(ValueError, match="min_chinese_chars"):
        DianpingAppConfig(city="shanghai", publish=DianpingPublishPolicy(min_chinese_chars=0))


def test_validate_review_content_type_errors():
    assert validate_review_content("", {"taste": 4, "environment": 4, "service": 3}) is not None
    assert validate_review_content("内容" * 60, "bad") is not None
    assert validate_review_content("内容" * 60, {"taste": 0, "environment": 4, "service": 3}) is not None
