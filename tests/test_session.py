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

