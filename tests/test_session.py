from pathlib import Path
import pytest
from automation_app_dianping.session import (
    DianpingAppiumSession,
    build_session_factory,
    device_config_from_env,
    parse_locator,
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
    assert session.execute_action(
        "pick_photos",
        photos=["a.jpg"],
        fallback_steps=[{"action": "tap", "selector": "~add"}],
    ).success
    assert Path(session.capture_artifact("screenshot", "s.png").path).exists()
    session.stop()
    assert driver.closed


def test_build_session_factory_injected():
    factory = build_session_factory(driver_factory=FakeDriver)
    assert isinstance(factory(), DianpingAppiumSession)

def test_more_session_paths(tmp_path):
    driver = FakeDriver()
    session = DianpingAppiumSession(driver=driver, artifact_root=tmp_path)
    assert session.execute_action('launch_app').success is False
    assert session.execute_action('tap').success is False
    assert session.execute_action('type_text', selector='~a').success is False
    assert session.execute_action('wait_for_element', selector='uiautomator:missing', timeout=0.2).success is False
    assert session.execute_action('rate').success is False
    assert session.execute_action('pick_photos', photos=['a.jpg'], add_selector='~add', thumbnail_selector='~t', confirm_selector='~c').success
    assert session.execute_action('unknown_action').success is False
    assert Path(session.capture_artifact('page_source','u.xml').path).exists()



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
    # Star center y = label bottom (433) + 65 gap; x = label center (916)
    # lands on the star's right half for a full 5-star rating.
    assert driver.swipes == [(916, 498, 916, 498, 80)]


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
    # x = label right (140) + 115 gap + 143.5 pitch * 4 = 829; y = label
    # center (653).
    assert driver.swipes == [(829, 653, 829, 653, 80)]
