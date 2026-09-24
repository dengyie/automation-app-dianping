from pathlib import Path
import pytest
from automation_core.drivers import ActionResult, ArtifactHandle, SessionInfo
from automation_app_dianping.session import (
    DianpingAppiumSession,
    DianpingUia2Session,
    build_session_factory,
    device_config_from_env,
    editor_has_dimension_rows,
    device_geometry_scale,
    dimension_star_row_rects,
    overall_star_row_rects,
    parse_locator,
    preferred_tap_rect,
    shop_result_candidates,
    shop_row_tap_rect,
)


class FakeElement:
    def __init__(self):
        self.clicked = False
        self.keys = []
    def click(self):
        self.clicked = True
    def clear(self):
        return None
    def send_keys(self, text):
        self.keys.append(text)


class FakeDriver:
    def __init__(self):
        self.activated = []
        self.closed = False
        self.element = FakeElement()
        self.page_source = "<hierarchy/>"
    def activate_app(self, app_id):
        self.activated.append(app_id)
    def find_element(self, by, value):
        if "missing" in str(value):
            raise LookupError("not found")
        return self.element
    def save_screenshot(self, path):
        Path(path).write_text("img", encoding="utf-8")
        return True
    def quit(self):
        self.closed = True
    def press_keycode(self, code):
        self.activated.append(("keycode", code))
        return True


def test_parse_locator_variants():
    assert parse_locator("~x")[1] == "x"
    assert "search_bar" in parse_locator("id:com.dianping.v1:id/search_bar")[1]
    assert "UiSelector" in parse_locator('uiautomator:new UiSelector().text("a")')[1]
    with pytest.raises(ValueError):
        parse_locator(" ")


def test_device_config_from_env_overrides():
    cfg = device_config_from_env({
        "DIANPING_DEVICE_UDID": "emulator-5554",
        "DIANPING_APPIUM_PORT": "4725",
    })
    assert cfg.udid == "emulator-5554"
    assert cfg.port == 4725
    with pytest.raises(ValueError):
        device_config_from_env({"DIANPING_APPIUM_PORT": "x"})


def test_session_actions(tmp_path):
    driver = FakeDriver()
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)
    session.start()
    assert session.execute_action("launch_app", app_id="com.dianping.v1", settle_seconds=0).success
    assert session.execute_action("tap", selector=["uiautomator:missing", "~ok"]).success
    assert session.execute_action("type_text", selector="id:a", text="hi").success
    assert session.execute_action("wait_for_element", selector="~ok", timeout=0.2).success
    assert session.execute_action("rate", selector="~star").success
    # appium pick_photos stays a tap-expansion shim (uia2 does gallery prep)
    assert session.execute_action(
        "pick_photos",
        photos=["a.jpg"],
        fallback_steps=[{"action": "tap", "selector": "~add"}],
    ).success
    assert Path(session.capture_artifact("screenshot", "s.png").path).exists()
    session.stop()
    assert driver.closed


def test_build_session_factory_injected():
    factory = build_session_factory(driver="appium", driver_factory=FakeDriver)
    assert isinstance(factory(), DianpingAppiumSession)

def test_more_session_paths(tmp_path):
    driver = FakeDriver()
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)
    assert session.execute_action('launch_app').success is False
    assert session.execute_action('tap').success is False
    assert session.execute_action('type_text', selector='~a').success is False
    assert session.execute_action('wait_for_element', selector='uiautomator:missing', timeout=0.2).success is False
    assert session.execute_action('rate').success is False
    # appium pick_photos stays a tap-expansion shim (uia2 does gallery prep)
    assert session.execute_action(
        'pick_photos', photos=['a.jpg'], add_selector='~add',
        thumbnail_selector='~t', confirm_selector='~c',
    ).success
    assert session.execute_action('unknown_action').success is False
    assert Path(session.capture_artifact('page_source','u.xml').path).exists()



def test_appium_navigate_uses_restored_shop_page(tmp_path):
    driver = FakeDriver()
    driver.page_source = (
        "<hierarchy><node text='细记港九宵夜大牌档(虹桥南丰城店)' />"
        "<node text='完善评价' /></hierarchy>"
    )
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="细记港九宵夜大牌档(虹桥南丰城店)",
        write_selector=('uiautomator:new UiSelector().text("完善评价")',),
        search_bar=("~搜索",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
    )

    assert result.success
    assert "restored shop page" in result.message
    assert driver.element.clicked is True
    assert driver.element.keys == []


def test_appium_navigate_searches_from_home(tmp_path):
    driver = FakeDriver()
    driver.page_source = "<hierarchy/>"
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="细记港九宵夜大牌档(虹桥南丰城店)",
        write_selector=('uiautomator:new UiSelector().text("写评价")',),
        search_bar=("~搜索",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
        search_confirm=("~搜索",),
        search_results_marker=('uiautomator:new UiSelector().text("商户")',),
        shop_result=('uiautomator:new UiSelector().textContains("细记港九")',),
    )

    assert result.success
    assert "via search" in result.message
    assert "细记港九宵夜大牌档(虹桥南丰城店)" in driver.element.keys


def test_appium_navigate_fails_when_the_editor_never_opens(tmp_path, monkeypatch):
    """The write CTA tap alone is not proof: the editor must show up."""
    import automation_app_dianping.session as session_module

    monkeypatch.setattr(session_module, "_EDITOR_OPEN_TIMEOUT_SECONDS", 0.1)

    class StuckDriver(FakeDriver):
        def find_element(self, by, value):
            if "添加图" in str(value) or "发布" in str(value):
                raise LookupError("editor never opened")
            return super().find_element(by, value)

    driver = StuckDriver()
    driver.page_source = "<hierarchy/>"
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="细记港九宵夜大牌档(虹桥南丰城店)",
        write_selector=('uiautomator:new UiSelector().text("写评价")',),
        search_bar=("~搜索",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
        search_confirm=("~搜索",),
        search_results_marker=('uiautomator:new UiSelector().text("商户")',),
        shop_result=('uiautomator:new UiSelector().textContains("细记港九")',),
    )

    assert not result.success
    assert "did not open the editor" in result.message


def test_appium_navigate_skips_when_editor_already_open(tmp_path):
    driver = FakeDriver()
    driver.page_source = (
        "<hierarchy><node text='添加图/视频' /><node text='已写81个字' /></hierarchy>"
    )
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="细记港九宵夜大牌档(虹桥南丰城店)",
        write_selector=('uiautomator:new UiSelector().text("完善评价")',),
        search_bar=("~搜索",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
    )

    assert result.success
    assert "already in review editor" in result.message
    assert driver.element.clicked is False
    assert driver.element.keys == []


def test_appium_navigate_skips_when_dish_edit_open(tmp_path):
    driver = FakeDriver()
    driver.page_source = (
        "<hierarchy><node text='识别菜品' /><node text='确定' /></hierarchy>"
    )
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="细记港九宵夜大牌档(虹桥南丰城店)",
        write_selector=('uiautomator:new UiSelector().text("完善评价")',),
        search_bar=("~搜索",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
    )

    assert result.success
    assert "dish-edit" in result.message
    assert driver.element.clicked is False
    assert driver.element.keys == []


def test_appium_hide_keyboard_taps_done(tmp_path):
    driver = FakeDriver()
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)

    result = session.execute_action("hide_keyboard")

    assert result.success
    assert "完成" in result.message
    assert driver.element.clicked is True


def test_appium_hide_keyboard_falls_back_to_back(tmp_path):
    driver = FakeDriver()

    def missing(by, value):
        raise LookupError("not found")

    driver.find_element = missing
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)

    result = session.execute_action("hide_keyboard")

    assert result.success
    assert "BACK" in result.message
    assert ("keycode", 4) in driver.activated


def test_appium_hide_keyboard_falls_back_to_driver_hide(tmp_path):
    driver = FakeDriver()
    driver.press_keycode = None
    driver.hide_calls = []

    def missing(by, value):
        raise LookupError("not found")

    def hide():
        driver.hide_calls.append(True)

    driver.find_element = missing
    driver.hide_keyboard = hide
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)

    result = session.execute_action("hide_keyboard")

    assert result.success
    assert "driver" in result.message
    assert driver.hide_calls == [True]


def test_appium_hide_keyboard_skips_when_publish_chrome_visible(tmp_path):
    driver = FakeDriver()
    driver.page_source = (
        "<hierarchy><node text='添加图/视频' /><node text='发布' /></hierarchy>"
    )
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)

    result = session.execute_action("hide_keyboard")

    assert result.success
    assert "chrome visible" in result.message
    assert driver.element.clicked is False


def test_appium_rate_skips_when_overwrite_chrome_has_no_overall_bar(tmp_path):
    driver = FakeDriver()
    driver.page_source = (
        "<hierarchy><node text='添加图/视频' /><node text='发布' /></hierarchy>"
    )
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)

    result = session.execute_action(
        "rate",
        dimension="overall",
        value=5,
        selector=('uiautomator:new UiSelector().text("超预期")',),
        anchor="overall",
    )

    assert result.success
    assert "skipped" in result.message
    assert driver.element.clicked is False


def test_confirm_search_and_dismiss(tmp_path):
    driver = FakeDriver()
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)
    # button path
    ok = session.execute_action("confirm_search", selector="~搜索")
    assert ok.success
    # keycode path when selectors missing
    ok2 = session.execute_action("confirm_search", selector="uiautomator:missing", keycode=66)
    assert ok2.success
    dismissed = session.execute_action("dismiss_dialogs", selector="~ok", max_attempts=2)
    assert dismissed.success
    assert dismissed.data["dismissed"] >= 1
    # failure dumps artifact
    bad = session.execute_action("wait_for_element", selector="uiautomator:missing", timeout=0.2)
    assert bad.success is False
    dumps = list(Path(tmp_path).glob("fail-*.png")) + list(Path(tmp_path).glob("fail-*.xml"))
    assert dumps


def test_appium_driver_caps_include_coloros_workarounds():
    pytest.importorskip("appium")
    import appium.webdriver as appium_webdriver

    from automation_app_dianping.config import DianpingDeviceConfig
    from automation_app_dianping.session import create_appium_driver

    captured = {}

    class FakeRemote:
        def __init__(self, command_executor, options):
            captured["executor"] = command_executor
            captured["capabilities"] = options.to_capabilities()

    original_remote = appium_webdriver.Remote
    appium_webdriver.Remote = FakeRemote
    try:
        create_appium_driver(DianpingDeviceConfig())
    finally:
        appium_webdriver.Remote = original_remote

    caps = captured["capabilities"]
    assert caps["appium:ignoreHiddenApiPolicyError"] is True
    assert caps["appium:autoGrantPermissions"] is True
    assert caps["appium:automationName"] == "UiAutomator2"


# --- slider guard -------------------------------------------------------------

_SLIDER_PAGE = (
    '<hierarchy><node bounds="[40,800][120,880]" content-desc="滑块" class='
    '"android.widget.ImageView"/><node resource-id="com.dianping.v1:id/nc_1_wrapper" '
    'class="android.view.View"/></hierarchy>'
)
_CLEAN_PAGE = (
    "<hierarchy><node text='点评' class='android.widget.TextView'/>"
    "<node class='android.webkit.WebView' text='banner slider widget'/></hierarchy>"
)


def test_page_source_indicates_slider():
    from automation_app_dianping.session import page_source_indicates_slider

    assert page_source_indicates_slider(_SLIDER_PAGE)
    verify_page = (
        "<hierarchy><node text='安全验证' class='android.widget.TextView'/></hierarchy>"
    )
    assert page_source_indicates_slider(verify_page)
    # H5 copy mentioning "slider" must not trip the structural markers.
    assert not page_source_indicates_slider(_CLEAN_PAGE)


def test_locate_slider_handle_parses_bounds_center():
    from automation_app_dianping.session import locate_slider_handle

    assert locate_slider_handle(_SLIDER_PAGE) == (80, 840)
    assert locate_slider_handle(_CLEAN_PAGE) is None
    assert locate_slider_handle("not xml") is None


class FakeSliderDriver(FakeDriver):
    def __init__(self):
        super().__init__()
        self.page_source = _SLIDER_PAGE
        self.swipes = []

    def get_screenshot_as_base64(self):
        import base64 as _b64

        return _b64.b64encode(b"img").decode("ascii")

    def swipe(self, start_x, start_y, end_x, end_y, duration=None):
        self.swipes.append((start_x, start_y, end_x, end_y, duration))


def test_slider_guard_solves_and_retries_action():
    from automation_app_dianping.session import DianpingAppiumSession

    driver = FakeSliderDriver()
    calls = []

    def solver(image_bytes):
        calls.append(image_bytes)
        return {"gap_offset_px": 137}

    session = DianpingAppiumSession(driver, artifact_root="artifacts/test-slider", slider_solver=solver)

    result = session.execute_action("tap", selector="~写评价")

    assert result.success
    assert "slider solved" in result.message
    assert len(calls) == 1
    assert driver.swipes == [(80, 840, 217, 840, 600)]


def test_slider_guard_bridges_async_solver():
    import asyncio

    from automation_app_dianping.session import DianpingAppiumSession

    driver = FakeSliderDriver()

    async def solver(image_bytes):
        return {"gap_offset_px": 100}

    session = DianpingAppiumSession(driver, artifact_root="artifacts/test-slider", slider_solver=solver)

    result = session.execute_action("tap", selector="~写评价")

    assert result.success
    assert driver.swipes == [(80, 840, 180, 840, 600)]


def test_slider_guard_without_solver_fails_with_guidance():
    from automation_app_dianping.session import DianpingAppiumSession

    driver = FakeSliderDriver()
    session = DianpingAppiumSession(driver, artifact_root="artifacts/test-slider")

    result = session.execute_action("tap", selector="~写评价")

    assert not result.success
    assert "slider challenge detected" in result.message
    assert "--enable-slidex" in result.message


def test_slider_guard_skips_clean_pages():
    from automation_app_dianping.session import DianpingAppiumSession

    driver = FakeSliderDriver()
    driver.page_source = _CLEAN_PAGE
    calls = []

    session = DianpingAppiumSession(
        driver,
        artifact_root="artifacts/test-slider",
        slider_solver=lambda image: calls.append(image) or {"gap_offset_px": 10},
    )

    result = session.execute_action("tap", selector="~写评价")

    assert result.success
    assert calls == []
    assert driver.swipes == []


def test_slider_guard_absolute_gap_x_subtracts_handle_start():
    from automation_app_dianping.session import DianpingAppiumSession

    # slidex pure-image solve returns gap_x (gap's left edge in screenshot
    # px). The handle in _SLIDER_PAGE is at center x=80, so the drag must be
    # gap_x - 80, not gap_x itself.
    driver = FakeSliderDriver()
    session = DianpingAppiumSession(
        driver,
        artifact_root="artifacts/test-slider",
        slider_solver=lambda image: {"gap_x": 363},
    )

    result = session.execute_action("tap", selector="~写评价")

    assert result.success
    assert driver.swipes == [(80, 840, 363, 840, 600)]


def test_slider_guard_gap_x_with_distance_scale():
    from automation_app_dianping.session import DianpingAppiumSession

    driver = FakeSliderDriver()
    session = DianpingAppiumSession(
        driver,
        artifact_root="artifacts/test-slider",
        slider_solver=lambda image: {"gap_x": 300, "distance_scale": 0.5},
    )

    result = session.execute_action("tap", selector="~写评价")

    assert result.success
    # (300 - 80) * 0.5 = 110
    assert driver.swipes == [(80, 840, 190, 840, 600)]


def test_slider_guard_gap_x_left_of_handle_fails_deterministically():
    from automation_app_dianping.session import DianpingAppiumSession

    driver = FakeSliderDriver()
    session = DianpingAppiumSession(
        driver,
        artifact_root="artifacts/test-slider",
        slider_solver=lambda image: {"gap_x": 50},
    )

    result = session.execute_action("tap", selector="~写评价")

    assert not result.success
    assert "at or left of handle" in result.message
    assert driver.swipes == []


def test_slider_guard_invalid_gap_x_fails():
    from automation_app_dianping.session import DianpingAppiumSession

    driver = FakeSliderDriver()
    session = DianpingAppiumSession(
        driver,
        artifact_root="artifacts/test-slider",
        slider_solver=lambda image: {"gap_x": "not-a-number"},
    )

    result = session.execute_action("tap", selector="~写评价")

    assert not result.success
    assert "invalid gap_x" in result.message
    assert driver.swipes == []


def test_slider_guard_invalid_distance_scale_fails():
    from automation_app_dianping.session import DianpingAppiumSession

    driver = FakeSliderDriver()
    session = DianpingAppiumSession(
        driver,
        artifact_root="artifacts/test-slider",
        slider_solver=lambda image: {"gap_x": 300, "distance_scale": -1},
    )

    result = session.execute_action("tap", selector="~写评价")

    assert not result.success
    assert "distance_scale" in result.message
    assert driver.swipes == []


def test_rate_by_label_anchor_taps_right_half_star():
    from automation_app_dianping.session import DianpingAppiumSession

    class FakeLabelElement:
        def __init__(self, x, y, width, height):
            self.rect = {"x": x, "y": y, "width": width, "height": height}

    class FakeRatingDriver(FakeSliderDriver):
        def __init__(self):
            super().__init__()
            self.page_source = _CLEAN_PAGE

        def find_element(self, by, value):
            return FakeLabelElement(883, 394, 66, 39)

    driver = FakeRatingDriver()
    session = DianpingAppiumSession(driver, artifact_root="artifacts/test-slider")

    result = session.execute_action(
        "rate",
        dimension="overall",
        value=5,
        selector=('uiautomator:new UiSelector().text("很棒")',),
        anchor="overall",
    )

    assert result.success
    # x = star strip origin (144) + pitch (176) * 4 + 0.85 * star width (89)
    # lands past the half-star split for a full 5-star rating; y anchors on
    # the label bottom (433) + 65 gap.
    assert driver.swipes == [(923, 498, 923, 498, 80)]


def test_rate_by_label_anchor_dimension_row():
    from automation_app_dianping.session import DianpingAppiumSession

    class FakeLabelElement:
        def __init__(self, x, y, width, height):
            self.rect = {"x": x, "y": y, "width": width, "height": height}

    class FakeRatingDriver(FakeSliderDriver):
        def __init__(self):
            super().__init__()
            self.page_source = _CLEAN_PAGE

        def find_element(self, by, value):
            return FakeLabelElement(68, 632, 72, 42)

    driver = FakeRatingDriver()
    session = DianpingAppiumSession(driver, artifact_root="artifacts/test-slider")

    result = session.execute_action(
        "rate",
        dimension="taste",
        value=5,
        selector=('uiautomator:new UiSelector().text("口味")',),
        anchor="dimension_row",
    )

    assert result.success
    # 2026-09 measured strip: 5th star x = 236 + 144*4 = 812; y = label
    # center (653).
    assert driver.swipes == [(812, 653, 812, 653, 80)]


def test_manual_captcha_window_recovers_blocked_action():
    from automation_app_dianping.session import DianpingAppiumSession

    class FlakyBlockedDriver(FakeSliderDriver):
        def __init__(self):
            super().__init__()
            self.page_source = _CLEAN_PAGE
            self.attempts = 0

        def find_element(self, by, value):
            self.attempts += 1
            if self.attempts < 3:
                raise LookupError("blocked by challenge")
            return self.element

    driver = FlakyBlockedDriver()
    session = DianpingAppiumSession(
        driver,
        artifact_root="artifacts/test-slider",
        captcha_window_seconds=6,
    )

    result = session.execute_action("wait_for_element", selector="~写评价", timeout=0.5)

    assert result.success
    assert "manual captcha window" in result.message
    assert driver.attempts == 3


def test_manual_captcha_window_disabled_by_default():
    from automation_app_dianping.session import DianpingAppiumSession

    driver = FakeSliderDriver()
    driver.page_source = _CLEAN_PAGE
    session = DianpingAppiumSession(driver, artifact_root="artifacts/test-slider")

    result = session.execute_action(
        "wait_for_element", selector="~missing", timeout=0.5
    )

    assert not result.success


# --- uia2 slider guard --------------------------------------------------------

class _FakeUia2Driver:
    """Stand-in for a uiautomator2 device: hierarchy dump, screenshot, swipe."""

    def __init__(self, hierarchy=_SLIDER_PAGE):
        self.hierarchy = hierarchy
        self.swipes = []

    def dump_hierarchy(self):
        return self.hierarchy

    def screenshot(self):
        return b"fake-png-bytes"

    def swipe(self, start_x, start_y, end_x, end_y, duration=None):
        self.swipes.append((start_x, start_y, end_x, end_y, duration))


class _FakeUia2Kit:
    """Minimal kit adapters.uia2 session stand-in backed by a fake device."""

    def __init__(self, driver):
        self.driver = driver
        self.info = SessionInfo(driver_name="uia2", platform="android", identifier="uia2-test")
        self.calls = []

    def start(self):
        return None

    def stop(self):
        return None

    def execute_action(self, action_name, **kwargs):
        self.calls.append((action_name, kwargs))
        return ActionResult(True, action_name)

    def capture_artifact(self, artifact_type, name):
        return ArtifactHandle(artifact_type=artifact_type, path=Path(name))


def test_uia2_slider_guard_solves_and_retries_action():
    from automation_app_dianping.session import DianpingUia2Session

    kit = _FakeUia2Kit(_FakeUia2Driver())
    calls = []

    def solver(image_bytes):
        calls.append(image_bytes)
        return {"gap_offset_px": 137}

    session = DianpingUia2Session(kit, slider_solver=solver)
    result = session.execute_action("tap", selector="~写评价")

    assert result.success
    assert "slider solved" in result.message
    assert len(calls) == 1
    # u2 swipe duration is in seconds, unlike Appium's milliseconds.
    assert kit.driver.swipes == [(80, 840, 217, 840, 0.6)]


def test_uia2_slider_guard_absolute_gap_x_subtracts_handle_start():
    from automation_app_dianping.session import DianpingUia2Session

    kit = _FakeUia2Kit(_FakeUia2Driver())
    session = DianpingUia2Session(
        kit, slider_solver=lambda image: {"gap_x": 363}
    )

    result = session.execute_action("tap", selector="~写评价")

    assert result.success
    assert "slider solved" in result.message
    # gap left edge 363, handle starts at x=80: drag = 363 - 80 = 283.
    assert kit.driver.swipes == [(80, 840, 363, 840, 0.6)]


def test_uia2_slider_guard_without_solver_fails_with_guidance():
    from automation_app_dianping.session import DianpingUia2Session

    kit = _FakeUia2Kit(_FakeUia2Driver())
    session = DianpingUia2Session(kit)

    result = session.execute_action("tap", selector="~写评价")

    assert not result.success
    assert "slider challenge detected" in result.message
    assert "--enable-slidex" in result.message


def test_uia2_slider_guard_skips_clean_pages():
    from automation_app_dianping.session import DianpingUia2Session

    kit = _FakeUia2Kit(_FakeUia2Driver(hierarchy=_CLEAN_PAGE))
    calls = []
    session = DianpingUia2Session(
        kit,
        slider_solver=lambda image: calls.append(image) or {"gap_offset_px": 10},
    )

    result = session.execute_action("tap", selector="~写评价")

    assert result.success
    assert calls == []
    assert kit.driver.swipes == []


def test_uia2_session_factory_wires_slider_solver(monkeypatch):
    import automation_app_dianping.session as session_mod
    from automation_app_dianping.config import DianpingDeviceConfig
    from automation_app_dianping.session import build_uia2_session_factory

    def fake_kit_cls(driver, *, identifier, artifact_root):
        return _FakeUia2Kit(driver)

    monkeypatch.setattr(session_mod, "_import_kit_uia2_session", lambda: fake_kit_cls)
    monkeypatch.setattr(session_mod, "_connect_uia2", lambda udid: _FakeUia2Driver())

    solver = lambda image: {"gap_offset_px": 1}
    factory = build_uia2_session_factory(
        DianpingDeviceConfig(udid="uia2-test-udid"),
        slider_solver=solver,
    )

    session = factory()

    assert session.slider_solver is solver


def test_build_session_factory_passes_slider_solver_to_uia2(monkeypatch):
    import automation_app_dianping.session as session_mod
    from automation_app_dianping.session import build_session_factory

    received = []

    def fake_builder(config, *, slider_solver=None):
        received.append(slider_solver)
        return lambda: None

    monkeypatch.setattr(session_mod, "build_uia2_session_factory", fake_builder)

    factory = build_session_factory(
        env={"DIANPING_DRIVER": "uia2", "DIANPING_DEVICE_UDID": "uia2-test-udid"},
        slider_solver="solver-sentinel",
    )

    assert callable(factory)
    assert received == ["solver-sentinel"]


_PADDED_APP_BAR_XML = (
    '<hierarchy>'
    '<node resource-id="com.dianping.v1:id/app_bar" class="android.widget.FrameLayout"'
    ' clickable="true" bounds="[0,0][1080,303]"/>'
    '<node resource-id="com.dianping.v1:id/title_search_bar" class="android.widget.TextView"'
    ' text="" clickable="false" bounds="[25,186][1055,286]"/>'
    '</hierarchy>'
)


def test_preferred_tap_rect_uses_wide_label_inside_padded_app_bar():
    """A wide label is the control; the padded app-bar centre is dead chrome."""
    rect = preferred_tap_rect(
        _PADDED_APP_BAR_XML, "id", "com.dianping.v1:id/title_search_bar"
    )
    assert rect == {"x": 25, "y": 186, "width": 1030, "height": 100}


def test_preferred_tap_rect_keeps_ancestor_for_narrow_button_label():
    """A narrow caption still taps its clickable button ancestor."""
    xml = (
        '<hierarchy>'
        '<node class="android.widget.FrameLayout" clickable="true" bounds="[191,2179][287,2292]">'
        '<node text="写评价" class="android.widget.TextView" clickable="false" bounds="[194,2255][284,2292]"/>'
        '</node>'
        '</hierarchy>'
    )
    rect = preferred_tap_rect(xml, "text", "写评价")
    assert rect == {"x": 191, "y": 2179, "width": 96, "height": 113}


def test_shop_result_candidates_anchor_on_shop_name_first():
    configured = ("uiautomator:new UiSelector().className(\"android.widget.RelativeLayout\")"
                  '.descriptionContains("店铺")',)
    candidates = shop_result_candidates("小杨生煎(百盛优客天山店)", configured)
    assert candidates[0] == (
        'uiautomator:new UiSelector().textContains("小杨生煎(百盛优客天山店)")'
    )
    assert candidates[1:] == configured


def test_shop_result_candidates_without_name_keep_configured_only():
    configured = ('uiautomator:new UiSelector().textContains("x")',)
    assert shop_result_candidates("", configured) == configured
    assert shop_result_candidates(None, configured) == configured


_ROW_WITH_HEADER_XML = (
    "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n"
    "<hierarchy>\n"
    '  <node resource-id="com.dianping.v1:id/search_header" class="android.widget.FrameLayout"'
    ' clickable="false" bounds="[0,68][1080,212]">\n'
    '    <node text="小杨生煎(百盛优客天山店)" class="android.widget.EditText"'
    ' clickable="true" bounds="[168,90][772,190]" />\n'
    "  </node>\n"
    '  <node class="android.widget.FrameLayout" clickable="true" bounds="[42,437][1038,530]">\n'
    '    <node text="小杨生煎(百盛优客天山店)" class="android.widget.TextView"'
    ' clickable="false" bounds="[309,437][801,486]" />\n'
    "  </node>\n"
    "</hierarchy>\n"
)


def test_shop_row_tap_rect_skips_header_query_box():
    """The header shows the typed query, so the first text match is the
    toolbar; the tap must land on the result row's name label below it."""
    rect = shop_row_tap_rect(_ROW_WITH_HEADER_XML, "小杨生煎(百盛优客天山店)")
    assert rect == {"x": 309, "y": 437, "width": 492, "height": 49}


def test_shop_row_tap_rect_prefers_label_over_card():
    """The card spans the whole entry; tapping its centre hits a deal tile.
    The resolver returns the name label rect, the proven shop-page entry."""
    xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n"
        "<hierarchy>\n"
        '  <node class="android.widget.FrameLayout" clickable="true"'
        ' bounds="[0,437][1080,1213]">\n'
        '    <node text="小杨生煎(百盛优客天山店)" class="android.widget.TextView"'
        ' clickable="false" bounds="[309,437][801,486]" />\n'
        "  </node>\n"
        "</hierarchy>\n"
    )
    assert shop_row_tap_rect(xml, "小杨生煎(百盛优客天山店)") == {
        "x": 309, "y": 437, "width": 492, "height": 49
    }


def test_shop_row_tap_rect_ignores_edittext_without_row():
    xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n"
        "<hierarchy>\n"
        '  <node resource-id="com.dianping.v1:id/search_header" class="android.widget.FrameLayout"'
        ' clickable="false" bounds="[0,68][1080,212]">\n'
        '    <node text="小杨先生天山店" class="android.widget.EditText"'
        ' clickable="true" bounds="[168,90][772,190]" />\n'
        "  </node>\n"
        "</hierarchy>\n"
    )
    assert shop_row_tap_rect(xml, "小杨生煎(百盛优客天山店)") is None


def test_shop_row_tap_rect_prefers_exact_name():
    xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n"
        "<hierarchy>\n"
        '  <node class="android.widget.TextView" clickable="true"'
        ' bounds="[42,212][1038,325]" text="小杨生煎天山百盛店" />\n'
        '  <node class="android.widget.TextView" clickable="true"'
        ' bounds="[42,437][1038,530]" text="小杨生煎(百盛优客天山店)" />\n'
        "</hierarchy>\n"
    )
    rect = shop_row_tap_rect(xml, "小杨生煎(百盛优客天山店)")
    assert rect == {"x": 42, "y": 437, "width": 996, "height": 93}


def _marker_session(sources):
    """uia2 session whose hierarchy dumps walk a fixed sequence."""
    frame = {"i": 0}

    class _Driver:
        def dump_hierarchy(self_inner):
            idx = min(frame["i"], len(sources) - 1)
            frame["i"] += 1
            return sources[idx]

    class _Kit:
        def __init__(self_inner):
            self_inner.driver = _Driver()
            self_inner.info = SessionInfo("uia2", "android", "marker-test")

    return DianpingUia2Session(_Kit())


def test_uia2_wait_for_marker_polls_until_node_appears(monkeypatch):
    monkeypatch.setattr("automation_app_dianping.session.time.sleep", lambda *_: None)
    session = _marker_session(
        [
            "<hierarchy><node text='首页'/></hierarchy>",
            "<hierarchy><node text='首页'/></hierarchy>",
            "<hierarchy><node text='商户'/></hierarchy>",
        ]
    )
    result = session._wait_for_marker(
        ('uiautomator:new UiSelector().text("商户")',), 5.0
    )
    assert result.success


def test_uia2_wait_for_marker_times_out_without_node(monkeypatch):
    monkeypatch.setattr("automation_app_dianping.session.time.sleep", lambda *_: None)
    ticks = iter([0.0, 1.0, 2.0, 9.0, 9.0, 9.0])
    monkeypatch.setattr(
        "automation_app_dianping.session.time.time", lambda: next(ticks)
    )
    session = _marker_session(["<hierarchy><node text='首页'/></hierarchy>"])
    result = session._wait_for_marker(
        ('uiautomator:new UiSelector().text("商户")',), 2.0
    )
    assert not result.success
    assert "marker" in result.message


# --- editor rating shape (2026-09-23 live build) ------------------------------

class _NoBoundsKit:
    """Kit stand-in whose element_bounds never resolves."""

    def __init__(self, source):
        class _Driver:
            def dump_hierarchy(self_inner):
                return source

        self.driver = _Driver()
        self.info = SessionInfo("uia2", "android", "rate-test")

    def execute_action(self, action_name, **kwargs):
        return ActionResult(False, "no bounds for %s" % kwargs.get("selector"))


def test_editor_has_dimension_rows_detects_absent_rows():
    # 环境 inside review prose must not count as a dimension row
    assert not editor_has_dimension_rows(
        "<hierarchy><node text='很棒' /><node text='我的环境很好'/></hierarchy>"
    )
    assert editor_has_dimension_rows("<hierarchy><node text='口味'/></hierarchy>")


def test_uia2_rate_skips_when_editor_has_no_dimension_rows():
    """The 2026-09-23 live editor only renders the overall bar; a dimension
    rate has nothing to anchor on and must not fail the publish."""
    source = "<hierarchy><node text='很糟糕' /><node text='很棒' /></hierarchy>"
    session = DianpingUia2Session(_NoBoundsKit(source), captcha_window_seconds=0)

    result = session.execute_action(
        "rate",
        dimension="taste",
        value=5,
        selector=('uiautomator:new UiSelector().text("口味")',),
        anchor="dimension_row",
    )

    assert result.success
    assert "skipped" in result.message


def test_uia2_rate_fails_when_dimension_rows_exist_but_label_missing():
    source = "<hierarchy><node text='口味' /><node text='环境' /></hierarchy>"
    session = DianpingUia2Session(_NoBoundsKit(source), captcha_window_seconds=0)

    result = session.execute_action(
        "rate",
        dimension="service",
        value=5,
        selector=('uiautomator:new UiSelector().text("服务")',),
        anchor="dimension_row",
    )

    assert not result.success
    assert "dimension rating label not found" in result.message


def test_overall_rating_selector_fifth_label_is_bang_with_fallback():
    from automation_app_dianping.config import default_selectors

    candidates = default_selectors().overall_rating_selector(5)
    assert candidates[0] == 'uiautomator:new UiSelector().text("很棒")'
    assert 'uiautomator:new UiSelector().text("超预期")' in candidates


_STAR_ROW_XML = """<hierarchy>
  <node text="很棒" class="android.widget.TextView" bounds="[883,253][949,292]" />
  <node class="android.widget.ImageView" bounds="[835,252][874,291]" />
  <node class="android.widget.ImageView" bounds="[144,313][233,402]" />
  <node class="android.widget.ImageView" bounds="[320,313][409,402]" />
  <node class="android.widget.ImageView" bounds="[496,313][585,402]" />
  <node class="android.widget.ImageView" bounds="[671,313][760,402]" />
  <node class="android.widget.ImageView" bounds="[847,313][936,402]" />
  <node class="android.widget.ImageView" bounds="[762,715][851,804]" />
</hierarchy>"""


def test_overall_star_row_rects_picks_strip_below_captions():
    # The caption line carries its own ImageView icons (y 252-291), so a row
    # of five images sits ON the captions and another BELOW them. Only the
    # row below (y 313-402) is the control; a lone 服务 star (y 715-804) is
    # not a row of five.
    assert overall_star_row_rects(_STAR_ROW_XML) == (
        (188, 357),
        (364, 357),
        (540, 357),
        (715, 357),
        (891, 357),
    )
    assert overall_star_row_rects("") == ()
    assert overall_star_row_rects("<hierarchy><node text='很棒'/></hierarchy>") == ()
    # Star images without any caption in the dump give no anchor at all.
    assert overall_star_row_rects("<hierarchy><node class='android.widget.ImageView' bounds='[1,2][3,4]'/></hierarchy>") == ()


_DIMENSION_ROW_XML = """<hierarchy>
  <node class="android.widget.ImageView" bounds="[144,313][233,402]" />
  <node text="口味" class="android.widget.TextView" bounds="[68,491][140,533]" />
  <node class="android.widget.ImageView" bounds="[189,467][276,556]" />
  <node class="android.widget.ImageView" bounds="[332,467][419,556]" />
  <node class="android.widget.ImageView" bounds="[476,467][563,556]" />
  <node class="android.widget.ImageView" bounds="[620,467][707,556]" />
  <node class="android.widget.ImageView" bounds="[763,467][850,556]" />
</hierarchy>"""


def test_dimension_star_row_rects_use_the_row_label_line():
    # 口味's stars are centred on its text line (cy 511); the overall star
    # band two rows up (cy 357) must not leak into the dimension strip.
    rects = dimension_star_row_rects(
        _DIMENSION_ROW_XML, {"x": 68, "y": 491, "width": 72, "height": 42}
    )
    assert rects == (
        (232, 511),
        (375, 511),
        (519, 511),
        (663, 511),
        (806, 511),
    )
    assert dimension_star_row_rects(_DIMENSION_ROW_XML, {}) == ()
    assert dimension_star_row_rects("", {"x": 68, "y": 491, "width": 72, "height": 42}) == ()


def test_uia2_rate_overall_taps_nth_star_without_kit_bounds():
    """Live 2026-09-23: the 很棒..很糟糕 captions are dead text; the star row
    below them is the control, and kit element_bounds is unusable on uia2."""
    source = _STAR_ROW_XML

    class _Kit:
        def __init__(self):
            class _Driver:
                def dump_hierarchy(self_inner):
                    return source

            self.driver = _Driver()
            self.info = SessionInfo("uia2", "android", "rate-overall")
            self.calls = []

        def execute_action(self, action_name, **kwargs):
            self.calls.append((action_name, kwargs))
            if action_name == "element_bounds":
                return ActionResult(False, "element info unavailable")
            return ActionResult(True, action_name)

    kit = _Kit()
    session = DianpingUia2Session(kit, captcha_window_seconds=0)

    result = session.execute_action(
        "rate",
        dimension="overall",
        value=4,
        selector=('uiautomator:new UiSelector().text("还可以")',),
        anchor="overall",
    )

    assert result.success, result.message
    assert all(name != "element_bounds" for name, _ in kit.calls)
    swipe = kit.calls[-1][1]
    # stars = ((188,357),(364,357),(540,357),(715,357),(891,357)) → 4th star.
    assert (swipe["start_x"], swipe["start_y"]) == (715, 357)


def test_uia2_rate_dimension_reads_star_strip_from_dump(monkeypatch):
    """The dimension strip geometry comes from the hierarchy dump itself.

    Live 2026-09-23 the editor renders the strip as five ImageViews on the
    row-label line; this is the production path. The kit element_bounds
    fallback must stay untouched, so the test makes it fail loudly.
    """
    source = _DIMENSION_ROW_XML

    class _Kit:
        def __init__(self):
            class _Driver:
                def dump_hierarchy(self_inner):
                    return source

            self.driver = _Driver()
            self.info = SessionInfo("uia2", "android", "rate-dimension")
            self.calls = []

        def execute_action(self, action_name, **kwargs):
            self.calls.append((action_name, kwargs))
            if action_name == "element_bounds":
                return ActionResult(False, "element bounds unavailable")
            return ActionResult(True, action_name)

    kit = _Kit()
    session = DianpingUia2Session(kit, captcha_window_seconds=0)

    result = session.execute_action(
        "rate",
        dimension="taste",
        value=5,
        selector=('uiautomator:new UiSelector().text("口味")',),
        anchor="dimension_row",
    )

    assert result.success, result.message
    assert all(name != "element_bounds" for name, _ in kit.calls)
    swipe = kit.calls[-1][1]
    # label 口味 at y 491..533 → strip midpoints (232,511)..(806,511) → 5th.
    assert (swipe["start_x"], swipe["start_y"]) == (806, 511)


def _rate_session_for_source(source):
    """DianpingUia2Session around a fake kit that dumps ``source``."""

    class _Kit:
        def __init__(self):
            class _Driver:
                def dump_hierarchy(self_inner):
                    return source

            self.driver = _Driver()
            self.info = SessionInfo("uia2", "android", "rate-scale")
            self.calls = []

        def execute_action(self, action_name, **kwargs):
            self.calls.append((action_name, kwargs))
            if action_name == "element_bounds":
                return ActionResult(False, "element bounds unavailable")
            return ActionResult(True, action_name)

    kit = _Kit()
    return DianpingUia2Session(kit, captcha_window_seconds=0), kit


def test_geometry_scale_follows_the_dump_screen_width():
    assert device_geometry_scale("") == 1.0
    assert device_geometry_scale("<hierarchy />") == 1.0
    assert device_geometry_scale('<hierarchy width="1080" height="2287" />') == 1.0
    assert device_geometry_scale('<hierarchy width="1440" height="3200" />') == pytest.approx(
        1440 / 1080
    )


def _dense_star_row_xml(width_attr: str, star_cy: int) -> str:
    """Captions at y 380..440 plus five stars centred on ``star_cy``."""
    stars = "\n".join(
        '  <node class="android.widget.ImageView" bounds="[%d,%d][%d,%d]" />'
        % (100 + 180 * index, star_cy - 20, 180 + 180 * index, star_cy + 20)
        for index in range(5)
    )
    return (
        "<hierarchy%s>\n"
        '  <node text="一般" class="android.widget.TextView" bounds="[0,380][100,440]" />\n'
        "%s\n</hierarchy>"
    ) % (width_attr, stars)


def test_overall_star_row_scale_allows_a_wider_dump():
    # Star row 260px under the captions: past the 1080px band (200px) but
    # inside the 1440px one (267px).
    dense = _dense_star_row_xml(' width="1440" height="3200"', 700)
    narrow = _dense_star_row_xml("", 700)

    assert overall_star_row_rects(dense) == (
        (140, 700),
        (320, 700),
        (500, 700),
        (680, 700),
        (860, 700),
    )
    assert overall_star_row_rects(narrow) == ()


def test_uia2_rate_dimension_fallback_scales_to_the_dump_width():
    source = (
        '<hierarchy width="1440" height="3200">\n'
        '  <node text="口味" class="android.widget.TextView" bounds="[68,491][140,533]" />\n'
        "</hierarchy>"
    )
    session, kit = _rate_session_for_source(source)

    result = session.execute_action(
        "rate",
        dimension="taste",
        value=5,
        selector=('uiautomator:new UiSelector().text("口味")',),
        anchor="dimension_row",
    )

    assert result.success, result.message
    swipe = kit.calls[-1][1]
    # measured strip 236 + 144*4 = 812, scaled by 1440/1080.
    assert (swipe["start_x"], swipe["start_y"]) == (1082, 512)



def test_appium_wait_for_element_rejects_a_bad_timeout(tmp_path):
    driver = FakeDriver()
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)

    result = session.execute_action(
        "wait_for_element", selector=("~ok",), timeout="soon"
    )

    assert not result.success
    assert "timeout must be a number" in result.message
    assert "'soon'" in result.message


def test_appium_dismiss_dialogs_rejects_a_bad_max_attempts(tmp_path):
    driver = FakeDriver()
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)

    result = session.execute_action(
        "dismiss_dialogs", selector=("~ok",), max_attempts="many"
    )

    assert not result.success
    assert "max_attempts must be a number" in result.message


def test_appium_rejects_a_negative_or_garbage_captcha_window(tmp_path):
    driver = FakeDriver()
    with pytest.raises(ValueError, match="captcha_window_seconds must be >= 0"):
        DianpingAppiumSession(driver=driver, artifact_root=tmp_path, captcha_window_seconds=-1)
    with pytest.raises(ValueError, match="captcha_window_seconds must be a number"):
        DianpingAppiumSession(driver=driver, artifact_root=tmp_path, captcha_window_seconds="later")
