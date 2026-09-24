from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

SelectorValue = Union[str, Sequence[str]]

# Canonical review photo. Staged into Pictures/DianpingAuto; never pick
# Camera / 最近项目 tiles (those lead with private family photos).
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REVIEW_PHOTO = _PACKAGE_ROOT / "artifacts" / "gni2_pulled.jpg"


def default_review_photos() -> List[str]:
    """Host paths attached when publish does not pass ``photos``.

    Missing file → no photos (workflow still runs); live pick_photos then
    refuses rather than grabbing a private gallery tile.
    """
    if DEFAULT_REVIEW_PHOTO.is_file():
        return [str(DEFAULT_REVIEW_PHOTO)]
    return []



def as_selector_list(value: SelectorValue) -> List[str]:
    if isinstance(value, str):
        return [value]
    return [item for item in value if isinstance(item, str) and item.strip()]


@dataclass(frozen=True)
class DianpingSelectors:
    search_bar: SelectorValue = (
        # 2026-09 real device (OnePlus 7T, dianping 12.x): the home search
        # bar is title_search_bar with content-desc 搜索; the legacy
        # search_bar id stays as a fallback for older versions.
        "id:com.dianping.v1:id/title_search_bar",
        "~搜索",
        "id:com.dianping.v1:id/search_bar",
        'uiautomator:new UiSelector().resourceId("com.dianping.v1:id/search_bar")',
    )
    search_input: SelectorValue = (
        # 2026-09 real device: the search page input is search_keyword_edit;
        # a generic EditText stays as fallback for other versions/pages.
        "id:com.dianping.v1:id/search_keyword_edit",
        'uiautomator:new UiSelector().className("android.widget.EditText")',
    )
    search_confirm: SelectorValue = (
        # 2026-09 real device: the suggestion page's orange button is
        # search_button; description/text candidates trail for other pages.
        "id:com.dianping.v1:id/search_button",
        "~搜索",
        'uiautomator:new UiSelector().text("搜索")',
        'uiautomator:new UiSelector().description("搜索")',
        'uiautomator:new UiSelector().textContains("搜索")',
    )
    # The results page exposes tab/desc markers the suggestion page lacks;
    # wait for one before matching shop entries (a suggestion row also
    # contains the shop name text).
    search_results_marker: SelectorValue = (
        'uiautomator:new UiSelector().description("SearchPagerViewPager")',
        'uiautomator:new UiSelector().text("商户")',
        'uiautomator:new UiSelector().descriptionContains("SearchPager")',
    )
    shop_result: SelectorValue = (
        'uiautomator:new UiSelector().className("android.widget.RelativeLayout").descriptionContains("店铺")',
    )
    write_review: SelectorValue = (
        # Same-day draft card on the shop page (2026-09-21 细记港九):
        # 「完善评价」 continues the saved draft. Prefer it over 写评价 so
        # we do not start a second review on top of the draft banner.
        'uiautomator:new UiSelector().text("完善评价")',
        'uiautomator:new UiSelector().textContains("完善评价")',
        "~写评价",
        'uiautomator:new UiSelector().text("写评价")',
        # Same-day shop revisit opens the existing review as 编辑评价
        # (2026-09-21 细记港九); tapping 写评价 is absent on that chrome.
        'uiautomator:new UiSelector().text("编辑评价")',
        'uiautomator:new UiSelector().textContains("写点评")',
        'uiautomator:new UiSelector().textContains("编辑评价")',
    )
    review_input: SelectorValue = (
        "id:com.dianping.v1:id/review_content",
        # The 2026-09 Picasso editor renders the review box with no
        # resource-id; the class-only UiSelector stays the stable fallback.
        'uiautomator:new UiSelector().className("android.widget.EditText")',
    )
    rating_panel: SelectorValue = ('uiautomator:new UiSelector().text("口味")',)
    add_photo: SelectorValue = (
        "~添加图/视频",
        'uiautomator:new UiSelector().textContains("添加图")',
        'uiautomator:new UiSelector().text("添加图/视频")',
    )
    # 2026-09 Picasso picker: 最近项目 mixes videos and photos and does
    # not follow MediaStore datetaken (live 2026-09-21: first checkbox was
    # a downloads lab photo). Camera tile 0 is a private family photo.
    # Production stages into Pictures/DianpingAuto and switches album
    # before any checkbox tap. Video thumbnails are
    # ugc_album_item_video_thumbnail_image and have no checkbox. Photos
    # expose ugc_album_item_select_layout. Tapping photo_imageView opens a
    # preview sheet instead of selecting, so 下一步 can close with 0 photos.
    photo_thumbnail: SelectorValue = (
        'uiautomator:new UiSelector().resourceId("com.dianping.v1:id/ugc_album_item_select_layout")',
        'uiautomator:new UiSelector().resourceId("com.dianping.v1:id/ugc_album_item_photo_imageView")',
    )
    # Confirm is a two-page chain: the picker uses 下一步, the dish-edit
    # page uses 确定; 完成 stays as a fallback for older versions.
    photo_confirm: SelectorValue = (
        'uiautomator:new UiSelector().text("下一步")',
        'uiautomator:new UiSelector().textContains("下一步")',
        'uiautomator:new UiSelector().text("确定")',
        "~完成",
        'uiautomator:new UiSelector().text("完成")',
    )
    submit: SelectorValue = ("~发布", 'uiautomator:new UiSelector().text("发布")')
    success: SelectorValue = (
        'uiautomator:new UiSelector().textContains("发布成功")',
        'uiautomator:new UiSelector().textContains("评价成功")',
        'uiautomator:new UiSelector().textContains("审核中")',
    )
    dialog_dismiss: SelectorValue = (
        'uiautomator:new UiSelector().text("我知道了")',
        'uiautomator:new UiSelector().text("同意")',
        'uiautomator:new UiSelector().text("确定")',
        'uiautomator:new UiSelector().text("关闭")',
        'uiautomator:new UiSelector().text("取消")',
        "~关闭",
    )
    rating_stars: Dict[str, Dict[int, str]] = field(default_factory=dict)

    # 2026-09 editor geometry (OnePlus 7T, 1080px width). The overall row
    # stacks each star under its emoji+label (y anchors on the label bottom,
    # x on the measured star strip); dimension rows place the label left of
    # the star strip (y anchors on the label center). Measured split between
    # the half-star and the full star sits at ~0.8 of the star width, so the
    # tap lands at 0.85 to select the integer value deterministically.
    rating_overall_labels: Dict[int, str] = field(
        default_factory=lambda: {
            1: "很糟糕",
            2: "较差",
            3: "一般",
            4: "还可以",
            # 2026-09-23 live editor (dianping 12.x): the fifth overall label
            # is 很棒. The older 超预期 label stays as a fallback candidate
            # for previous builds (2026-09-21 measurement).
            5: "很棒",
        }
    )
    # Extra label candidates tried after the primary one for a given value.
    rating_overall_label_fallbacks: Dict[int, Tuple[str, ...]] = field(
        default_factory=lambda: {5: ("超预期",)}
    )
    rating_overall_star_origin_px: float = 144.0
    rating_overall_star_pitch_px: float = 176.0
    rating_overall_star_gap_px: float = 65.0
    # Dimension rows: first star centre x=236, pitch=144 (measured 2026-09).
    rating_dim_star_origin_px: float = 236.0
    rating_dim_star_pitch_px: float = 144.0
    rating_star_width_px: float = 89.0
    rating_star_tap_fraction: float = 0.85

    def overall_rating_selector(self, value: int) -> SelectorValue:
        label = self.rating_overall_labels.get(int(value))
        if not label:
            raise ValueError("overall rating value must be 1-5")
        candidates = ['uiautomator:new UiSelector().text("%s")' % label]
        # 2026-09-23 live editor: the 5th overall label is 很棒 (the older
        # 超预期 label belongs to a prior build / the dimension picker).
        for fallback in self.rating_overall_label_fallbacks.get(int(value), ()):
            candidates.append('uiautomator:new UiSelector().text("%s")' % fallback)
        return tuple(candidates)

    def rating_row_label_selector(self, dimension: str) -> SelectorValue:
        labels = {"taste": "口味", "environment": "环境", "service": "服务"}
        label = labels.get(dimension, dimension)
        return ('uiautomator:new UiSelector().text("%s")' % label,)

    def rating_star(self, dimension: str, value: int) -> Optional[str]:
        return (self.rating_stars.get(dimension) or {}).get(value)

    def shop_name_selector(self, shop_name: str) -> str:
        cleaned = (shop_name or "").strip()
        if not cleaned:
            raise ValueError("shop_name is required")
        safe = cleaned.replace("\\", "\\\\").replace('"', '\\"')
        return 'uiautomator:new UiSelector().textContains("%s")' % safe

    def rating_selector(self, dimension: str, value: int) -> SelectorValue:
        labels = {"taste": "口味", "environment": "环境", "service": "服务"}
        label = labels.get(dimension, dimension)
        # Prefer stars associated with the dimension label text; fall back to configured map.
        primary = [
            'uiautomator:new UiSelector().text("%s").fromParent(new UiSelector().className("android.widget.ImageView").instance(%s))' % (label, int(value) - 1),
            'uiautomator:new UiSelector().descriptionContains("%s").childSelector(new UiSelector().className("android.widget.ImageView").instance(%s))' % (label, int(value) - 1),
        ]
        fallback = self.rating_star(dimension, value)
        if fallback:
            primary.append(fallback)
        return tuple(primary)

    def photo_thumbnail_at(self, index: int) -> str:
        return (
            'uiautomator:new UiSelector().resourceId('
            '"com.dianping.v1:id/ugc_album_item_select_layout")'
            '.instance(%s)' % int(index)
        )


@dataclass(frozen=True)
class DianpingPublishPolicy:
    max_per_day: int = 2
    min_interval_minutes: int = 60
    min_chinese_chars: int = 100


@dataclass(frozen=True)
class DianpingDeviceConfig:
    app_id: str = "com.dianping.v1"
    # 2026-09 real device: the launcher activity is NovaMainActivity; the
    # legacy SplashScreenActivity no longer exists and fails cold starts.
    activity: str = "com.dianping.v1.NovaMainActivity"
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
    # Seconds to keep retrying a blocked action while a human solves a
    # risk-control challenge on the device (0 disables the window).
    captcha_window_seconds: float = 0.0


@dataclass(frozen=True)
class DianpingAppConfig:
    city: str
    app_id: str = "com.dianping.v1"
    # 2026-09 real device: the launcher activity is NovaMainActivity; the
    # legacy SplashScreenActivity no longer exists and fails cold starts.
    activity: str = "com.dianping.v1.NovaMainActivity"
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
