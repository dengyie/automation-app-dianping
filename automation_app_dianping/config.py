from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class DianpingSelectors:
    search_bar: str = "search_bar"
    search_input: str = "search_input"
    shop_result: str = "shop_result"
    write_review: str = "write_review"
    review_input: str = "review_input"
    rating_panel: str = "rating_panel"
    add_photo: str = "add_photo"
    photo_thumbnail: str = "photo_thumbnail"
    photo_confirm: str = "photo_confirm"
    submit: str = "submit"
    success: str = "publish_success"
    rating_stars: Dict[str, Dict[int, str]] = field(default_factory=dict)

    def rating_star(self, dimension: str, value: int) -> Optional[str]:
        stars = self.rating_stars.get(dimension) or {}
        return stars.get(value)


@dataclass(frozen=True)
class DianpingPublishPolicy:
    max_per_day: int = 2
    min_interval_minutes: int = 60
    min_chinese_chars: int = 100


@dataclass(frozen=True)
class DianpingAppConfig:
    city: str
    app_id: str = "com.dianping.v1"
    activity: str = "com.dianping.main.guide.SplashScreenActivity"
    selectors: DianpingSelectors = field(default_factory=DianpingSelectors)
    publish: DianpingPublishPolicy = field(default_factory=DianpingPublishPolicy)

    def __post_init__(self):
        if not isinstance(self.city, str) or not self.city.strip():
            raise ValueError("city must be a non-blank string")
        if not isinstance(self.app_id, str) or not self.app_id.strip():
            raise ValueError("app_id must be a non-blank string")
        if not isinstance(self.activity, str) or not self.activity.strip():
            raise ValueError("activity must be a non-blank string")
        if self.publish.max_per_day < 1:
            raise ValueError("publish.max_per_day must be >= 1")
        if self.publish.min_interval_minutes < 0:
            raise ValueError("publish.min_interval_minutes must be >= 0")
        if self.publish.min_chinese_chars < 1:
            raise ValueError("publish.min_chinese_chars must be >= 1")


def default_selectors() -> DianpingSelectors:
    return DianpingSelectors(
        rating_stars={
            "taste": {1: "taste_star_1", 2: "taste_star_2", 3: "taste_star_3", 4: "taste_star_4", 5: "taste_star_5"},
            "environment": {
                1: "environment_star_1",
                2: "environment_star_2",
                3: "environment_star_3",
                4: "environment_star_4",
                5: "environment_star_5",
            },
            "service": {
                1: "service_star_1",
                2: "service_star_2",
                3: "service_star_3",
                4: "service_star_4",
                5: "service_star_5",
            },
        }
    )


def count_chinese_chars(text: str) -> int:
    return sum(1 for ch in text if "一" <= ch <= "鿿")


def validate_review_content(
    content: str,
    ratings: Dict[str, int],
    *,
    min_chinese_chars: int = 100,
) -> Optional[str]:
    if not isinstance(content, str) or not content.strip():
        return "review content must be a non-blank string"
    chinese = count_chinese_chars(content)
    if chinese < min_chinese_chars:
        return "review content needs at least %s Chinese characters (got %s)" % (
            min_chinese_chars,
            chinese,
        )
    if not isinstance(ratings, dict):
        return "ratings must be an object"
    for key in ("taste", "environment", "service"):
        value = ratings.get(key)
        if not isinstance(value, int) or value < 1 or value > 5:
            return "ratings.%s must be an integer between 1 and 5" % key
    if (
        ratings.get("taste") == 5
        and ratings.get("environment") == 5
        and ratings.get("service") == 5
    ):
        return "all-five-star ratings are rejected as low-quality spam signal"
    return None
