from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Union

SelectorValue = Union[str, Sequence[str]]


def as_selector_list(value: SelectorValue) -> List[str]:
    if isinstance(value, str):
        return [value]
    return [item for item in value if isinstance(item, str) and item.strip()]


@dataclass(frozen=True)
class DianpingSelectors:
    search_bar: SelectorValue = (
        "id:com.dianping.v1:id/search_bar",
        'uiautomator:new UiSelector().resourceId("com.dianping.v1:id/search_bar")',
        "~搜索",
    )
    search_input: SelectorValue = (
        'uiautomator:new UiSelector().className("android.widget.EditText")',
    )
    shop_result: SelectorValue = (
        'uiautomator:new UiSelector().className("android.widget.RelativeLayout").descriptionContains("店铺")',
    )
    write_review: SelectorValue = (
        "~写评价",
        'uiautomator:new UiSelector().text("写评价")',
        'uiautomator:new UiSelector().textContains("写点评")',
    )
    review_input: SelectorValue = (
        "id:com.dianping.v1:id/review_content",
        'uiautomator:new UiSelector().className("android.widget.EditText").instance(0)',
    )
    rating_panel: SelectorValue = ('uiautomator:new UiSelector().text("口味")',)
    add_photo: SelectorValue = ("~添加图片", 'uiautomator:new UiSelector().textContains("添加图片")')
    photo_thumbnail: SelectorValue = (
        'uiautomator:new UiSelector().className("android.widget.ImageView").instance(0)',
    )
    photo_confirm: SelectorValue = ("~完成", 'uiautomator:new UiSelector().text("完成")')
    submit: SelectorValue = ("~发布", 'uiautomator:new UiSelector().text("发布")')
    success: SelectorValue = (
        'uiautomator:new UiSelector().textContains("发布成功")',
        'uiautomator:new UiSelector().textContains("评价成功")',
    )
    rating_stars: Dict[str, Dict[int, str]] = field(default_factory=dict)

    def rating_star(self, dimension: str, value: int) -> Optional[str]:
        return (self.rating_stars.get(dimension) or {}).get(value)

    def shop_name_selector(self, shop_name: str) -> str:
        cleaned = (shop_name or "").strip()
        if not cleaned:
            raise ValueError("shop_name is required")
        safe = cleaned.replace("\\", "\\\\").replace('"', '\\"')
        return 'uiautomator:new UiSelector().textContains("%s")' % safe

    def photo_thumbnail_at(self, index: int) -> str:
        return 'uiautomator:new UiSelector().className("android.widget.ImageView").instance(%s)' % int(index)


@dataclass(frozen=True)
class DianpingPublishPolicy:
    max_per_day: int = 2
    min_interval_minutes: int = 60
    min_chinese_chars: int = 100


@dataclass(frozen=True)
class DianpingDeviceConfig:
    app_id: str = "com.dianping.v1"
    activity: str = "com.dianping.main.guide.SplashScreenActivity"
    host: str = "127.0.0.1"
    port: int = 4723
    path: str = "/"
    udid: Optional[str] = None
    device_name: str = "Android"
    platform_version: Optional[str] = None
    no_reset: bool = True
    auto_grant_permissions: bool = True
    new_command_timeout: int = 300
    artifact_root: str = "artifacts/dianping-live"


@dataclass(frozen=True)
class DianpingAppConfig:
    city: str
    app_id: str = "com.dianping.v1"
    activity: str = "com.dianping.main.guide.SplashScreenActivity"
    selectors: DianpingSelectors = field(default_factory=lambda: default_selectors())
    publish: DianpingPublishPolicy = field(default_factory=DianpingPublishPolicy)
    device: DianpingDeviceConfig = field(default_factory=DianpingDeviceConfig)

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
    def stars(start: int):
        return {
            i: 'uiautomator:new UiSelector().className("android.widget.ImageView").instance(%s)'
            % (start + i - 1)
            for i in range(1, 6)
        }

    return DianpingSelectors(
        rating_stars={
            "taste": stars(0),
            "environment": stars(5),
            "service": stars(10),
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
