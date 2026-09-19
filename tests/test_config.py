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


def test_search_bar_prefers_current_version_title_bar():
    """2026-09 real device: the home search bar id is title_search_bar."""
    from automation_app_dianping.config import DianpingSelectors

    selectors = DianpingSelectors()

    assert selectors.search_bar[0] == "id:com.dianping.v1:id/title_search_bar"
    assert "~搜索" in selectors.search_bar
    # Legacy id stays as fallback for older app versions.
    assert "id:com.dianping.v1:id/search_bar" in selectors.search_bar


def test_search_input_prefers_search_page_edit_id():
    """2026-09 real device: the search page input id is search_keyword_edit."""
    from automation_app_dianping.config import DianpingSelectors

    selectors = DianpingSelectors()

    assert selectors.search_input[0] == "id:com.dianping.v1:id/search_keyword_edit"
    assert len(selectors.search_input) == 2


def test_search_input_prefers_search_page_edit_id():
    """2026-09 real device: the search page input id is search_keyword_edit."""
    from automation_app_dianping.config import DianpingSelectors

    selectors = DianpingSelectors()

    assert selectors.search_input[0] == "id:com.dianping.v1:id/search_keyword_edit"
    assert len(selectors.search_input) == 2


def test_device_activity_is_current_launcher():
    """2026-09 real device: SplashScreenActivity no longer exists; the
    launcher activity is NovaMainActivity (verified via resolve-activity)."""
    from automation_app_dianping.config import DianpingAppConfig, DianpingDeviceConfig

    assert DianpingDeviceConfig.activity == "com.dianping.v1.NovaMainActivity"
    assert DianpingAppConfig.activity == "com.dianping.v1.NovaMainActivity"


def test_search_confirm_prefers_results_button_and_marker_exists():
    """2026-09 real device: the suggestion page button is search_button and
    the results page exposes SearchPagerViewPager/商户 markers."""
    from automation_app_dianping.config import DianpingSelectors

    selectors = DianpingSelectors()

    assert selectors.search_confirm[0] == "id:com.dianping.v1:id/search_button"
    assert any("SearchPagerViewPager" in c for c in selectors.search_results_marker)
