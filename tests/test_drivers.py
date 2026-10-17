"""Driver dispatch and uia2 session tests (offline, fake devices only)."""
from pathlib import Path

import pytest

from automation_core.drivers import ActionResult, ArtifactHandle, SessionInfo

from automation_app_dianping.config import DianpingDeviceConfig
from automation_app_dianping.session import (
    DianpingAppiumSession,
    DianpingUia2Session,
    _media_display_name,
    _picker_header_album,
    _shell_text,
    build_session_factory,
    clickable_ancestor_rect,
    editor_attached_photo_rects,
    dish_edit_delete_confirm_rect,
    dish_edit_filmstrip_rects,
    dish_edit_is_open,
    dish_edit_trash_rect,
    preferred_tap_rect,
    review_editor_is_open,
    review_ime_toolbar_visible,
    review_publish_chrome_visible,
    overall_rating_bar_visible,
    should_skip_rating,
    shop_page_has_review_entry,
    translate_uiautomator_selector,
)


class FakeKitSession:
    """Duck-typed stand-in for the kit adapters.uia2 session."""

    def __init__(self, device, artifact_root=None, identifier="dianping-uia2"):
        self.device = device
        self.info = SessionInfo(
            driver_name="uia2",
            platform="android",
            identifier=identifier,
        )
        self.actions = []
        self.artifacts = []
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def execute_action(self, action_name, **kwargs):
        self.actions.append((action_name, kwargs))
        if action_name == "launch_app":
            return ActionResult(True, "launch_app")
        if action_name == "tap":
            return ActionResult(True, "tap")
        return ActionResult(True, action_name)

    def capture_artifact(self, artifact_type, name):
        self.artifacts.append((artifact_type, name))
        return ArtifactHandle(artifact_type=artifact_type, path=Path(name))


class FakeU2Device:
    """Duck-typed uiautomator2.Device recording app lifecycle calls."""


# --- selector translation ---------------------------------------------------


def test_translate_id_and_description_prefixes():
    assert translate_uiautomator_selector("id:com.dianping.v1:id/x") == (
        "id",
        "com.dianping.v1:id/x",
    )
    assert translate_uiautomator_selector("~搜索") == ("description", "搜索")


def test_translate_xpath_and_plain_text():
    assert translate_uiautomator_selector("//node") == ("xpath", "//node")
    assert translate_uiautomator_selector("xpath://node") == ("xpath", "//node")
    assert translate_uiautomator_selector("确定") == ("text", "确定")


def test_translate_single_method_uiselectors():
    cases = {
        'uiautomator:new UiSelector().text("确定")': ("text", "确定"),
        'uiautomator:new UiSelector().textContains("搜索")': ("text-contains", "搜索"),
        'uiautomator:new UiSelector().description("搜索")': ("description", "搜索"),
        'uiautomator:new UiSelector().resourceId("com.dianping.v1:id/x")': (
            "id",
            "com.dianping.v1:id/x",
        ),
    }
    for raw, expected in cases.items():
        assert translate_uiautomator_selector(raw) == expected


def test_translate_rejects_unsupported_uiautomator_constructs():
    unsupported = [
        'uiautomator:new UiSelector().text("x").instance(0)',
        'uiautomator:new UiSelector().text("x").fromParent(new UiSelector())',
        'uiautomator:new UiSelector().text("x").childSelector(new UiSelector())',
        'uiautomator:new UiSelector().className("a").text("b")',
        "uiautomator:not-a-selector",
    ]
    for raw in unsupported:
        assert translate_uiautomator_selector(raw) is None


def test_translate_rejects_blank_and_non_string():
    assert translate_uiautomator_selector("   ") is None
    assert translate_uiautomator_selector(None) is None
    assert translate_uiautomator_selector(123) is None


# --- factory dispatch -------------------------------------------------------


def test_build_session_factory_defaults_to_uia2(monkeypatch):
    import automation_app_dianping.session as session_module

    monkeypatch.setattr(session_module, "_import_kit_uia2_session", lambda: FakeKitSession)
    monkeypatch.setattr(session_module, "_connect_uia2", lambda udid: FakeU2Device())

    factory = build_session_factory(env={})

    assert isinstance(factory(), DianpingUia2Session)


def test_build_session_factory_dispatches_appium_when_asked():
    factory = build_session_factory(
        env={}, driver="appium", driver_factory=lambda: object()
    )

    session = factory()

    assert isinstance(session, DianpingAppiumSession)


def test_build_session_factory_dispatches_uia2_from_arg(monkeypatch):
    import automation_app_dianping.session as session_module

    monkeypatch.setattr(session_module, "_import_kit_uia2_session", lambda: FakeKitSession)
    monkeypatch.setattr(
        session_module, "_connect_uia2", lambda udid: FakeU2Device()
    )
    config = DianpingDeviceConfig(udid="1275cb0e", artifact_root="artifacts/test-uia2")

    factory = session_module.build_uia2_session_factory(config)
    session = factory()

    assert isinstance(session, DianpingUia2Session)
    assert session.info.driver_name == "uia2"
    assert session.info.identifier == "1275cb0e"


def test_build_session_factory_reads_driver_from_env(monkeypatch):
    import automation_app_dianping.session as session_module

    monkeypatch.setattr(session_module, "_import_kit_uia2_session", lambda: FakeKitSession)
    monkeypatch.setattr(session_module, "_connect_uia2", lambda udid: FakeU2Device())

    factory = build_session_factory(env={"DIANPING_DRIVER": "uia2"})

    assert isinstance(factory(), DianpingUia2Session)


def test_build_session_factory_rejects_unknown_driver():
    with pytest.raises(ValueError, match="unsupported dianping driver"):
        build_session_factory(env={"DIANPING_DRIVER": "adb"})


def test_build_session_factory_driver_arg_beats_env():
    factory = build_session_factory(
        env={"DIANPING_DRIVER": "uia2"},
        driver_factory=lambda: object(),
        driver="appium",
    )

    assert isinstance(factory(), DianpingAppiumSession)


# --- appium server URL -------------------------------------------------------


def _install_fake_appium(monkeypatch, captured):
    import sys
    from types import ModuleType

    class FakeUiAutomator2Options:
        def set_capability(self, name, value):
            captured.setdefault("caps", {})[name] = value

    def fake_remote(command_executor, options):
        captured["url"] = command_executor
        captured["options"] = options
        return object()

    appium_module = ModuleType("appium")
    webdriver_module = ModuleType("appium.webdriver")
    webdriver_module.Remote = fake_remote
    appium_module.webdriver = webdriver_module
    options_module = ModuleType("appium.options")
    android_options_module = ModuleType("appium.options.android")
    android_options_module.UiAutomator2Options = FakeUiAutomator2Options

    monkeypatch.setitem(sys.modules, "appium", appium_module)
    monkeypatch.setitem(sys.modules, "appium.webdriver", webdriver_module)
    monkeypatch.setitem(sys.modules, "appium.options", options_module)
    monkeypatch.setitem(sys.modules, "appium.options.android", android_options_module)


def test_create_appium_driver_strips_trailing_base_path(monkeypatch):
    from automation_app_dianping.session import create_appium_driver

    captured = {}
    _install_fake_appium(monkeypatch, captured)

    create_appium_driver(DianpingDeviceConfig(host="127.0.0.1", port=4723))

    # Selenium concatenates the base URL and "/session" verbatim; a trailing
    # slash would send POST //session, which 404s on Appium's router.
    assert captured["url"] == "http://127.0.0.1:4723"


def test_create_appium_driver_preserves_explicit_base_path(monkeypatch):
    from automation_app_dianping.session import create_appium_driver

    captured = {}
    _install_fake_appium(monkeypatch, captured)

    create_appium_driver(DianpingDeviceConfig(path="/wd/hub"))

    assert captured["url"] == "http://127.0.0.1:4723/wd/hub"


def test_uia2_launch_app_rejects_non_numeric_settle(monkeypatch):
    import automation_app_dianping.session as session_module

    monkeypatch.setattr(session_module, "_import_kit_uia2_session", lambda: FakeKitSession)
    monkeypatch.setattr(session_module, "_connect_uia2", lambda udid: FakeU2Device())

    session = session_module.build_uia2_session_factory(DianpingDeviceConfig())()

    result = session.execute_action("launch_app", app_id="com.dianping.v1", settle_seconds="soon")

    assert result.success is False
    assert "settle_seconds must be a number" in result.message


def test_build_live_workflow_allows_uia2_publish(monkeypatch):
    """uia2 publish parity landed (2026-09-20); the former guard is retired."""
    from automation_app_dianping.live import build_live_workflow

    monkeypatch.setenv("DIANPING_LIVE_E2E", "1")
    monkeypatch.setenv("DIANPING_DRIVER", "uia2")

    workflow = build_live_workflow(
        session_factory=lambda: object(),
        shop_name="店铺",
        content="内容",
    )

    assert workflow is not None


def test_build_live_workflow_smoke_allows_uia2(monkeypatch):
    from automation_app_dianping.live import build_live_smoke_workflow

    monkeypatch.setenv("DIANPING_LIVE_E2E", "1")
    monkeypatch.setenv("DIANPING_DRIVER", "uia2")

    workflow = build_live_smoke_workflow(
        session_factory=lambda: object(),
    )

    assert workflow.name == "dianping-smoke"


def test_uia2_factory_missing_kit_adapter_raises_import_error(monkeypatch):
    import automation_app_dianping.session as session_module

    def missing():
        raise ImportError("adapters.uia2")

    monkeypatch.setattr(session_module, "_import_kit_uia2_session", missing)

    factory = session_module.build_uia2_session_factory(DianpingDeviceConfig())

    with pytest.raises(ImportError):
        factory()


# --- DianpingUia2Session behavior -------------------------------------------


class _DelegatingKitStub(FakeKitSession):
    def __init__(self, device_map):
        super().__init__(device=None)
        self.device_map = device_map

    def execute_action(self, action_name, **kwargs):
        self.actions.append((action_name, kwargs))
        if action_name == "tap":
            if self.device_map.get("tap:" + str(kwargs.get("selector"))):
                return ActionResult(True, "tap")
            return ActionResult(False, "element lookup failed")
        if action_name == "launch_app":
            return ActionResult(True, "launch_app")
        return ActionResult(True, action_name)


def test_uia2_session_delegates_primitives_and_artifacts():
    inner = FakeKitSession(device=None)
    session = DianpingUia2Session(inner)

    session.start()
    launch = session.execute_action("launch_app", app_id="com.dianping.v1")
    handle = session.capture_artifact("screenshot", "startup.png")
    session.stop()

    assert launch.success is True
    assert ("launch_app", {"app_id": "com.dianping.v1"}) in inner.actions
    assert inner.artifacts == [("screenshot", "startup.png")]
    assert handle.artifact_type == "screenshot"
    assert inner.started is True and inner.stopped is True


def test_uia2_dismiss_dialogs_taps_translated_candidates(monkeypatch):
    device_map = {"tap:我知道了": True, "tap:同意": True}
    inner = _DelegatingKitStub(device_map)
    session = DianpingUia2Session(inner)

    result = session.execute_action(
        "dismiss_dialogs",
        selector=(
            'uiautomator:new UiSelector().text("我知道了")',
            "~同意",
        ),
        max_attempts=3,
    )

    assert result.success is True
    assert result.data == {"dismissed": 3}


def test_uia2_dismiss_dialogs_best_effort_without_dialogs():
    inner = _DelegatingKitStub({})
    session = DianpingUia2Session(inner)

    result = session.execute_action(
        "dismiss_dialogs",
        selector=('uiautomator:new UiSelector().text("关闭")',),
        max_attempts=2,
    )

    assert result.success is True
    assert result.data == {"dismissed": 0}


def test_uia2_dismiss_dialogs_skips_untranslatable_candidates():
    inner = _DelegatingKitStub({})
    session = DianpingUia2Session(inner)

    result = session.execute_action(
        "dismiss_dialogs",
        selector=(
            'uiautomator:new UiSelector().text("x").instance(0)',
            'uiautomator:new UiSelector().text("关闭")',
        ),
        max_attempts=1,
    )

    # The instance() candidate is skipped without failing the step.
    assert result.success is True
    assert result.data == {"dismissed": 0}


def test_uia2_smoke_flow_runs_green_offline(tmp_path, monkeypatch):
    """Smoke-equivalent steps against the uia2 session, mirroring the appium path."""
    import automation_app_dianping.session as session_module
    from automation_app_dianping.workflow import build_smoke_steps

    class FakeOptions:
        app_id = "com.dianping.v1"

    class RecordingKit(FakeKitSession):
        pass

    monkeypatch.setattr(session_module, "_import_kit_uia2_session", lambda: RecordingKit)
    monkeypatch.setattr(session_module, "_connect_uia2", lambda udid: FakeU2Device())

    config = DianpingDeviceConfig(artifact_root=str(tmp_path / "artifacts"))
    session = session_module.build_uia2_session_factory(config)()
    from automation_runner.runtime import WorkflowRuntime

    runtime = WorkflowRuntime(
        session_factory=lambda: session,
        workflow_name="dianping-uia2-smoke",
    )
    result = runtime.run(build_smoke_steps(FakeOptions()))

    assert result.status.value == "succeeded"
    kit = session._session
    assert ("launch_app", {"app_id": "com.dianping.v1"}) in kit.actions
    artifact_types = {
        step.artifact_result.artifact_type
        for step in result.steps
        if step.artifact_result
    }
    assert {"screenshot", "page_source"} <= artifact_types


# --- uia2 publish parity ------------------------------------------------------


class FakeKitUia2:
    """Records translated kit calls; publishes label bounds for rate."""

    def __init__(self):
        self.calls = []
        self.info = SessionInfo(driver_name="uia2", platform="android", identifier="fake")
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def execute_action(self, action_name, **kwargs):
        self.calls.append((action_name, kwargs))
        if action_name == "element_bounds":
            return ActionResult(
                True, "element_bounds", data={"x": 68, "y": 632, "width": 72, "height": 42}
            )
        return ActionResult(True, action_name)

    def capture_artifact(self, artifact_type, name):
        return ArtifactHandle(artifact_type=artifact_type, path=Path(name))


def _make_uia2_session(monkeypatch, kit=None):
    import automation_app_dianping.session as session_module

    kit = kit or FakeKitUia2()
    monkeypatch.setattr(session_module, "_import_kit_uia2_session", lambda: type("C", (), {"__call__": lambda self, *a, **k: kit}))
    return session_module.DianpingUia2Session(kit, captcha_window_seconds=0), kit


def test_uia2_confirm_search_translates_then_taps(monkeypatch):
    session, kit = _make_uia2_session(monkeypatch)

    result = session.execute_action(
        "confirm_search", selector=('uiautomator:new UiSelector().text("搜索")',), keycode=66
    )

    assert result.success
    assert kit.calls[0] == ("tap", {"selector": "搜索", "by": "text"})


def test_uia2_rate_falls_back_to_kit_bounds_without_dump(monkeypatch):
    """No hierarchy (offline fake): label geometry comes from kit bounds.

    The production path parses the dump; this covers the fallback that runs
    when the driver publishes no hierarchy at all, plus the measured-strip
    constants used when the dump has no star strip either.
    """
    session, kit = _make_uia2_session(monkeypatch)

    result = session.execute_action(
        "rate",
        dimension="taste",
        value=5,
        selector=('uiautomator:new UiSelector().text("口味")',),
        anchor="dimension_row",
    )

    assert result.success
    bounds_call, rate_swipe = kit.calls[0], kit.calls[-1]
    assert bounds_call[0] == "element_bounds"
    assert rate_swipe[0] == "swipe"
    # 2026-09 measured strip: first star centre 236, pitch 144 → 5th star
    # x = 236 + 144*4 = 812; y = label centre = 632+21 = 653.
    assert rate_swipe[1]["start_x"] == 812 and rate_swipe[1]["start_y"] == 653


def test_uia2_rate_requires_label_anchor(monkeypatch):
    session, _ = _make_uia2_session(monkeypatch)

    result = session.execute_action("rate", dimension="taste", value=5)

    assert not result.success
    assert "label anchor" in result.message


def test_uia2_failure_captures_screenshot_and_page_source(monkeypatch):
    """A failed action must leave the same evidence trail as the Appium path."""
    class ArtifactKit(FakeKitUia2):
        def __init__(self):
            super().__init__()
            self.artifacts = []

        def capture_artifact(self, artifact_type, name):
            self.artifacts.append((artifact_type, name))
            return super().capture_artifact(artifact_type, name)

    kit = ArtifactKit()
    session, _ = _make_uia2_session(monkeypatch, kit=kit)

    result = session.execute_action("rate", dimension="taste", value=5)

    assert not result.success
    assert [kind for kind, _ in kit.artifacts] == ["screenshot", "page_source"]
    assert all(name.startswith("fail-rate-") for _, name in kit.artifacts)


def test_uia2_pick_photos_refuses_without_gallery_prep(monkeypatch, tmp_path):
    """A host path that cannot be staged (missing file) must fail before
    any picker tap — never fall back to an arbitrary gallery tile."""
    session, kit = _make_uia2_session(monkeypatch)

    result = session.execute_action(
        "pick_photos",
        photos=["does-not-exist.jpg"],
        add_selector=("~添加图",),
    )

    assert not result.success
    # without an adb-capable driver there is no deterministic way to stage
    # the photo — refuse instead of selecting an arbitrary gallery tile
    assert "gallery prep failed" in result.message
    assert kit.calls == []  # no tap happened


# --- editor leftover-photo clearing ------------------------------------------


class _WidgetStub:
    def __init__(self, exists):
        self.exists = exists


def _editor_photo_xml(tiles: int) -> str:
    cards = []
    for index in range(tiles):
        left = 34 + 156 * index
        right = left + 120
        cards.append(
            '  <node class="android.widget.FrameLayout" clickable="true" '
            'bounds="[%d,1087][%d,1340]">\n'
            '    <node class="android.widget.ImageView" clickable="false" '
            'bounds="[%d,1087][%d,1340]" />\n'
            '    <node text="%d" class="android.widget.TextView" clickable="false" '
            'bounds="[%d,1095][%d,1134]" />\n'
            "  </node>" % (left, right, left, right, index + 1, right - 39, right - 20)
        )
    return (
        "<hierarchy>\n"
        + "\n".join(cards)
        + '\n  <node text="发布" class="android.widget.TextView" clickable="false" '
        'bounds="[900,2255][1000,2292]" />\n'
        "</hierarchy>"
    )


_PHOTO_PREVIEW_XML = (
    "<hierarchy>\n"
    '  <node text="删除" class="android.widget.TextView" clickable="false" '
    'bounds="[540,2155][620,2192]" />\n'
    '  <node class="android.widget.ImageView" clickable="false" bounds="[0,0][1080,2100]" />\n'
    "</hierarchy>"
)


class _PhotoEditorDriver:
    """Dumps an editor with ``tiles`` numbered thumbnails; a click on a tile
    opens the photo preview, a click there drops one tile and returns."""

    def __init__(self, tiles):
        self.tiles = tiles
        self.mode = "editor"
        self.clicks = []

    def dump_hierarchy(self):
        if self.mode == "preview":
            return _PHOTO_PREVIEW_XML
        return _editor_photo_xml(self.tiles)

    def __call__(self, **kwargs):
        # Only the photo preview exposes the delete labels.
        return _WidgetStub(self.mode == "preview")

    def click(self, x, y):
        self.clicks.append((int(x), int(y)))
        if self.mode == "editor":
            self.mode = "preview"
        else:
            self.tiles = max(self.tiles - 1, 0)
            self.mode = "editor"


def _session_with_photo_driver(monkeypatch, driver):
    kit = FakeKitUia2()
    kit.driver = driver
    return _make_uia2_session(monkeypatch, kit=kit)[0], kit


def test_clear_editor_photos_removes_leftover_via_preview(monkeypatch):
    driver = _PhotoEditorDriver(tiles=1)
    session, _ = _session_with_photo_driver(monkeypatch, driver)

    result = session._clear_existing_editor_photos()

    assert result.success, result.message
    assert "cleared 1" in result.message
    # tile tap (opens preview) then the 删除 label tap (drops the tile).
    assert len(driver.clicks) == 2


def test_clear_editor_photos_skips_delete_without_a_page_change(monkeypatch):
    class _StuckDriver:
        def __init__(self):
            self.clicks = []
            self.src = _editor_photo_xml(1)

        def dump_hierarchy(self):
            return self.src

        def __call__(self, **kwargs):
            # The sticker tap opens nothing: no delete labels exist.
            return _WidgetStub(False)

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))

    driver = _StuckDriver()
    session, _ = _session_with_photo_driver(monkeypatch, driver)

    result = session._clear_existing_editor_photos()

    assert not result.success
    assert "did not drop" in result.message
    # Never taps a delete control when the tile tap changed nothing: the
    # two clicks are the corner and centre fallback only, both on the tile.
    assert len(driver.clicks) == 2


def test_clear_editor_photos_stops_at_the_cap(monkeypatch):
    driver = _PhotoEditorDriver(tiles=7)
    session, _ = _session_with_photo_driver(monkeypatch, driver)

    result = session._clear_existing_editor_photos()

    assert not result.success
    assert "after the 6-photo cap" in result.message
    assert driver.tiles == 1

class _FakeShellResponse:
    """Mirrors uiautomator2.abstract.ShellResponse (NamedTuple with no strip)."""

    def __init__(self, output, exit_code=0):
        self.output = output
        self.exit_code = exit_code


_EDITOR_ADD_PHOTO_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[335,1519][588,1772]">
    <node index="1" text="添加图/视频" class="android.widget.TextView" clickable="false" bounds="[364,1665][559,1707]" />
  </node>
</hierarchy>
"""

_EDITOR_LEFTOVER_PHOTOS_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[34,1087][212,1340]">
    <node class="android.widget.ImageView" clickable="false" bounds="[34,1087][212,1340]" />
    <node text="1" class="android.widget.TextView" clickable="false" bounds="[173,1095][192,1134]" />
  </node>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[226,1087][479,1340]">
    <node class="android.widget.ImageView" clickable="false" bounds="[226,1087][479,1340]" />
    <node text="2" class="android.widget.TextView" clickable="false" bounds="[440,1095][459,1134]" />
  </node>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[493,1087][746,1340]">
    <node class="android.widget.ImageView" clickable="false" bounds="[581,1152][658,1228]" />
    <node text="添加图/视频" class="android.widget.TextView" clickable="false" bounds="[522,1233][717,1275]" />
  </node>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[760,1087][1013,1340]">
    <node text="说评价" class="android.widget.TextView" clickable="false" bounds="[833,1233][941,1275]" />
  </node>
</hierarchy>
"""

_EDITOR_ONE_LEFTOVER_PHOTO_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[34,1087][212,1340]">
    <node class="android.widget.ImageView" clickable="false" bounds="[34,1087][212,1340]" />
    <node text="1" class="android.widget.TextView" clickable="false" bounds="[173,1095][192,1134]" />
  </node>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[226,1087][479,1340]">
    <node class="android.widget.ImageView" clickable="false" bounds="[314,1152][391,1228]" />
    <node text="添加图/视频" class="android.widget.TextView" clickable="false" bounds="[255,1233][450,1275]" />
  </node>
</hierarchy>
"""

_SHOP_WRITE_REVIEW_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[191,2179][287,2292]">
    <node text="写评价" class="android.widget.TextView" clickable="false" bounds="[194,2255][284,2292]" />
  </node>
</hierarchy>
"""

_SHOP_DRAFT_COMPLETE_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node text="细记港九宵夜大牌档(虹桥南丰城店)" class="android.widget.TextView" clickable="false" bounds="[39,400][900,460]" />
  <node class="android.widget.FrameLayout" clickable="true" bounds="[0,1447][1080,1664]">
    <node text="完善评价" class="android.widget.TextView" clickable="false" bounds="[829,1522][1040,1592]" />
  </node>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[191,2179][287,2292]">
    <node text="写评价" class="android.widget.TextView" clickable="false" bounds="[194,2255][284,2292]" />
  </node>
</hierarchy>
"""

_HOME_SEARCH_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node resource-id="com.dianping.v1:id/title_search_bar" class="android.widget.FrameLayout" clickable="true" bounds="[48,88][900,172]" content-desc="搜索" />
</hierarchy>
"""

# Home page as it really renders (bottom tab bar present); used by the
# 我的→待评价 navigation tests where the tab must be tappable.
_HOME_WITH_TABS_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node resource-id="com.dianping.v1:id/title_search_bar" class="android.widget.FrameLayout" clickable="true" bounds="[48,88][900,172]" content-desc="搜索" />
  <node text="首页" class="android.widget.TextView" clickable="false" bounds="[0,2300][216,2380]" />
  <node text="我的" class="android.widget.TextView" clickable="false" bounds="[864,2300][1008,2380]" />
</hierarchy>
"""

# Staged hierarchies the home→search→shop→editor flow walks through. Each
# marker (keyword field, 商户 header, shop name, 写评价, 添加图/视频) only
# appears on its own page, so _wait_for_marker really has to poll the dump.
_SEARCH_BOX_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node resource-id="com.dianping.v1:id/search_keyword_edit" class="android.widget.EditText" clickable="true" bounds="[48,88][900,172]" />
</hierarchy>
"""

_RESULTS_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node text="商户" class="android.widget.TextView" clickable="false" bounds="[32,64][128,112]" />
  <node text="细记港九宵夜大牌档(虹桥南丰城店)" class="android.widget.TextView" clickable="true" bounds="[48,300][900,360]" />
</hierarchy>
"""

_PICKER_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[430,103][649,156]">
    <node text="最近项目" class="android.widget.TextView" clickable="false" bounds="[430,103][610,156]" />
  </node>
  <node resource-id="com.dianping.v1:id/ugc_album_item_photo_imageView" class="android.widget.ImageView" clickable="true" bounds="[0,80][200,280]" />
  <node resource-id="com.dianping.v1:id/ugc_album_item_select_layout" class="android.widget.FrameLayout" clickable="true" bounds="[120,80][200,160]">
    <node resource-id="com.dianping.v1:id/ugc_album_item_select" class="android.widget.TextView" clickable="false" bounds="[140,100][180,140]" />
  </node>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[833,2287][1036,2366]">
    <node text="下一步" class="android.widget.TextView" clickable="false" bounds="[885,2307][984,2346]" />
  </node>
</hierarchy>
"""

_ALBUM_DROPDOWN_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[430,103][649,156]">
    <node text="最近项目" class="android.widget.TextView" clickable="false" bounds="[430,103][610,156]" />
  </node>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[0,192][1080,451]">
    <node text="最近项目" class="android.widget.TextView" clickable="false" bounds="[293,268][461,317]" />
  </node>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[0,451][1080,710]">
    <node text="Camera" class="android.widget.TextView" clickable="false" bounds="[293,527][439,576]" />
  </node>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[0,1487][1080,1746]">
    <node text="downloads" class="android.widget.TextView" clickable="false" bounds="[293,1563][499,1612]" />
  </node>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[0,1746][1080,2005]">
    <node text="DianpingAuto" class="android.widget.TextView" clickable="false" bounds="[293,1822][540,1871]" />
  </node>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[833,2287][1036,2366]">
    <node text="下一步" class="android.widget.TextView" clickable="false" bounds="[885,2307][984,2346]" />
  </node>
</hierarchy>
"""

_STAGING_ALBUM_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[430,103][649,156]">
    <node text="DianpingAuto" class="android.widget.TextView" clickable="false" bounds="[430,103][610,156]" />
  </node>
  <node resource-id="com.dianping.v1:id/ugc_album_item_photo_imageView" class="android.widget.ImageView" clickable="true" bounds="[0,192][200,392]" />
  <node resource-id="com.dianping.v1:id/ugc_album_item_select_layout" class="android.widget.FrameLayout" clickable="true" bounds="[120,192][200,272]">
    <node resource-id="com.dianping.v1:id/ugc_album_item_select" class="android.widget.TextView" clickable="false" bounds="[140,212][180,252]" />
  </node>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[833,2287][1036,2366]">
    <node text="下一步" class="android.widget.TextView" clickable="false" bounds="[885,2307][984,2346]" />
  </node>
</hierarchy>
"""

_DISH_CONFIRM_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node text="识别菜品" class="android.widget.TextView" clickable="false" bounds="[0,0][200,40]" />
  <node class="android.widget.FrameLayout" clickable="true" bounds="[800,2200][1080,2360]">
    <node text="确定" class="android.widget.TextView" clickable="false" bounds="[880,2240][1000,2320]" />
  </node>
</hierarchy>
"""


def _dish_edit_xml(leftover_photos=3):
    thumbs = []
    for index in range(leftover_photos):
        x1 = 31 + index * 143
        x2 = x1 + 127
        thumbs.append(
            '  <node class="android.widget.FrameLayout" clickable="true" '
            'bounds="[%d,1964][%d,2091]">\n'
            '    <node class="android.widget.ImageView" clickable="false" '
            'bounds="[%d,1964][%d,2091]" />\n'
            "  </node>\n" % (x1, x2, x1, x2)
        )
    plus_x1 = 31 + leftover_photos * 143
    plus_x2 = plus_x1 + 127
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n"
        "<hierarchy>\n"
        '  <node text="识别菜品" class="android.widget.TextView" clickable="true" '
        'bounds="[37,1754][214,1816]" />\n'
        '  <node class="android.widget.ImageView" clickable="true" '
        'bounds="[951,1745][1044,1815]" />\n'
        "%s"
        '  <node class="android.widget.FrameLayout" clickable="true" '
        'bounds="[%d,1964][%d,2091]" content-desc="上传照片">\n'
        '    <node class="android.widget.ImageView" clickable="false" '
        'bounds="[%d,1964][%d,2091]" />\n'
        "  </node>\n"
        "</hierarchy>\n" % ("".join(thumbs), plus_x1, plus_x2, plus_x1, plus_x2)
    )


class _FakeGalleryDevice:
    """Records push/shell calls; shell() drives the index lifecycle.

    Mirrors a real uiautomator2 Device: ``push(src, dst)`` exists and ``sync``
    does not. Tests that used ``device.sync.push`` would hide the live failure
    ``'Device' object has no attribute 'sync'``. Starts on the editor (add-photo
    label is not clickable); photo tiles appear only after the parent card is
    tapped, matching 2026-09 Picasso chrome.
    """

    PHOTO_ID = "com.dianping.v1:id/ugc_album_item_photo_imageView"
    SELECT_ID = "com.dianping.v1:id/ugc_album_item_select_layout"
    BADGE_ID = "com.dianping.v1:id/ugc_album_item_select"
    ADD_PARENT_BOUNDS = (335, 1519, 588, 1772)
    HEADER_PARENT_BOUNDS = (430, 103, 649, 156)
    ALBUM_PARENT_BOUNDS = (0, 1746, 1080, 2005)
    NEXT_PARENT_BOUNDS = (833, 2287, 1036, 2366)
    DISH_PARENT_BOUNDS = (800, 2200, 1080, 2360)

    def __init__(
        self,
        name,
        tops_after=2,
        visible_texts=None,
        photo_count=8,
        picker_open=False,
        leftover_photos=0,
    ):
        self.pushed = []
        self.pushed_payloads = []
        self.shell_calls = []
        self.lookups = []
        self.clicks = []
        self.coordinate_clicks = []
        self.swipes = []
        self.selected = set()
        self._name = name
        self._tops_after = tops_after
        self.photo_count = photo_count
        self.picker_open = picker_open
        self.dropdown_open = False
        self.dish_edit_open = False
        self.album = "DianpingAuto" if picker_open else None
        self.leftover_photos = leftover_photos
        self.hierarchy = (
            _STAGING_ALBUM_XML
            if picker_open
            else self._editor_hierarchy()
        )
        self.picker_xml = _PICKER_XML
        self.delete_dialog = False
        if visible_texts is not None:
            self.visible_texts = list(visible_texts)
        elif picker_open:
            self.visible_texts = ["下一步", "确定", "DianpingAuto"]
        else:
            self.visible_texts = ["添加图/视频"]

    class _Widget:
        def __init__(self, exists, on_click=None, info=None):
            self.exists = exists
            self._on_click = on_click
            self.info = info or {}

        def click(self):
            if self._on_click:
                self._on_click()
            return True

    def _editor_hierarchy(self):
        if self.leftover_photos >= 2:
            return _EDITOR_LEFTOVER_PHOTOS_XML
        if self.leftover_photos == 1:
            return _EDITOR_ONE_LEFTOVER_PHOTO_XML
        return _EDITOR_ADD_PHOTO_XML

    def dump_hierarchy(self):
        if self.dish_edit_open and self.delete_dialog:
            return self.hierarchy.replace(
                "</hierarchy>",
                '  <node text="确认删除这张图片吗？" class="android.widget.TextView" '
                'clickable="false" bounds="[200,1080][880,1140]" />\n'
                '  <node class="android.widget.FrameLayout" clickable="true" '
                'bounds="[568,1211][872,1324]">\n'
                '    <node text="确认删除" class="android.widget.TextView" '
                'clickable="false" bounds="[600,1235][840,1300]" />\n'
                "  </node>\n"
                "</hierarchy>",
            )
        return self.hierarchy

    def click(self, x, y):
        self.coordinate_clicks.append((int(x), int(y)))
        if self.dish_edit_open and not self.picker_open:
            if self.delete_dialog and 568 <= x <= 872 and 1211 <= y <= 1324:
                self.delete_dialog = False
                if self.leftover_photos:
                    self.leftover_photos -= 1
                    self.hierarchy = _dish_edit_xml(self.leftover_photos)
                return
            if 951 <= x <= 1044 and 1745 <= y <= 1815:
                if self.leftover_photos:
                    self.delete_dialog = True
                return
            plus_x1 = 31 + self.leftover_photos * 143
            plus_x2 = plus_x1 + 127
            if plus_x1 <= x <= plus_x2 and 1964 <= y <= 2091:
                self.dish_edit_open = False
                self._open_picker()
                return
            return
        if not self.picker_open and self.leftover_photos:
            leftover_tiles = (
                (34, 1087, 212, 1340),
                (226, 1087, 479, 1340),
            )
            for left, top, right, bottom in leftover_tiles[: self.leftover_photos]:
                if left <= x <= right and top <= y <= bottom:
                    self.dish_edit_open = True
                    self.hierarchy = _dish_edit_xml(self.leftover_photos)
                    return
        left, top, right, bottom = self.ADD_PARENT_BOUNDS
        if not self.picker_open and left <= x <= right and top <= y <= bottom:
            self._open_picker()
            return
        hleft, htop, hright, hbottom = self.HEADER_PARENT_BOUNDS
        if (
            self.picker_open
            and not self.dropdown_open
            and self.album != "DianpingAuto"
            and hleft <= x <= hright
            and htop <= y <= hbottom
        ):
            self._open_dropdown()
            return
        aleft, atop, aright, abottom = self.ALBUM_PARENT_BOUNDS
        if (
            self.dropdown_open
            and aleft <= x <= aright
            and atop <= y <= abottom
        ):
            self._open_staging_album()
            return
        nleft, ntop, nright, nbottom = self.NEXT_PARENT_BOUNDS
        if (
            self.picker_open
            and not self.dropdown_open
            and "下一步" in self.visible_texts
            and nleft <= x <= nright
            and ntop <= y <= nbottom
        ):
            self._advance_to_dish()
            return
        dleft, dtop, dright, dbottom = self.DISH_PARENT_BOUNDS
        if (
            "确定" in self.visible_texts
            and dleft <= x <= dright
            and dtop <= y <= dbottom
        ):
            self._finish_confirm()

    def swipe(self, x1, y1, x2, y2, duration=0.3):
        self.swipes.append((int(x1), int(y1), int(x2), int(y2), float(duration)))

    def _open_picker(self):
        self.picker_open = True
        self.dropdown_open = False
        self.album = "最近项目"
        self.visible_texts = ["下一步", "最近项目"]
        self.hierarchy = self.picker_xml

    def _open_dropdown(self):
        self.dropdown_open = True
        self.visible_texts = [
            "下一步",
            "最近项目",
            "Camera",
            "downloads",
            "DianpingAuto",
        ]
        self.hierarchy = _ALBUM_DROPDOWN_XML

    def _open_staging_album(self):
        self.dropdown_open = False
        self.album = "DianpingAuto"
        self.visible_texts = ["下一步", "DianpingAuto"]
        self.hierarchy = _STAGING_ALBUM_XML

    def _advance_to_dish(self):
        self.clicks.append({"text": "下一步", "via": "parent"})
        self.visible_texts = ["确定"]
        self.picker_open = False
        self.hierarchy = _DISH_CONFIRM_XML

    def _finish_confirm(self):
        self.clicks.append({"text": "确定", "via": "parent"})
        self.visible_texts = []
        self.hierarchy = _EDITOR_ADD_PHOTO_XML

    def __call__(self, **kwargs):
        self.lookups.append(dict(kwargs))
        exists = True
        text = kwargs.get("text") or kwargs.get("textContains")
        if text is not None:
            exists = any(
                text == item or (kwargs.get("textContains") and text in item)
                for item in self.visible_texts
            )
            if (
                not exists
                and self.delete_dialog
                and text in {"确认删除", "确认删除这张图片吗？"}
            ):
                exists = True
        desc = kwargs.get("description") or kwargs.get("descriptionContains")
        if desc is not None:
            exists = any(
                desc == item or (kwargs.get("descriptionContains") and desc in item)
                for item in self.visible_texts
            )
        resource = kwargs.get("resourceId")
        instance = int(kwargs.get("instance", 0))
        info = {}
        if resource is not None:
            album_ready = (
                self.picker_open
                and not self.dropdown_open
                and self.album == "DianpingAuto"
            )
            if resource in {self.SELECT_ID, self.BADGE_ID}:
                exists = album_ready and instance < self.photo_count
            elif resource == self.PHOTO_ID:
                exists = self.picker_open and instance < self.photo_count
            else:
                exists = False
            if resource == self.BADGE_ID and instance in self.selected:
                info = {"text": str(instance + 1)}

        def on_click():
            # Photo tiles are real widgets; Picasso chrome labels are not.
            # Confirm/add must go through Device.click on the parent card.
            self.clicks.append(dict(kwargs))
            if (
                kwargs.get("resourceId") == self.SELECT_ID
                and self.album == "DianpingAuto"
                and not self.dropdown_open
            ):
                self.selected.add(int(kwargs.get("instance", 0)))

        return self._Widget(exists, on_click, info)

    def push(self, local, remote):
        payload = Path(local).read_bytes()
        self.pushed.append((local, remote))
        self.pushed_bytes = payload
        self.pushed_payloads.append(payload)
        self._name = remote.rsplit("/", 1)[-1]

    def shell(self, args):
        self.shell_calls.append(list(args))
        joined = " ".join(args)
        if "--where" in joined and self._name in joined:
            # index lifecycle: absent → present-but-NULL → real row
            n = len(
                [
                    c
                    for c in self.shell_calls
                    if "--where" in c and self._name in " ".join(c)
                ]
            )
            if n <= self._tops_after:
                return _FakeShellResponse("")
            if n <= self._tops_after + 1:
                return _FakeShellResponse(
                    "Row: 0 _display_name=%s, bucket_display_name=DianpingAuto, datetaken=NULL"
                    % self._name
                )
            return _FakeShellResponse(
                "Row: 0 _display_name=%s, bucket_display_name=DianpingAuto, datetaken=1789859011371"
                % self._name
            )
        if "--sort" in joined and "DESC" in joined:
            return _FakeShellResponse(
                "Row: 0 _display_name=%s, datetaken=1789859011371\n"
                "Row: 1 _display_name=other.jpg, datetaken=1" % self._name
            )
        return _FakeShellResponse(
            "Broadcasting: Intent { act=MEDIA_SCANNER_SCAN_FILE }"
        )


def _write_jpeg(tmp_path, name="gni.jpg"):
    from PIL import Image

    path = tmp_path / name
    Image.new("RGB", (4, 4)).save(path, "JPEG")
    return path


def _install_fast_clock(monkeypatch, start=1_700_000_000.0):
    """Advance session.time on sleep so gallery polls do not wait wall-clock."""
    import automation_app_dianping.session as session_module

    clock = {"now": start}

    def fake_time():
        return clock["now"]

    def fake_sleep(seconds):
        clock["now"] += float(seconds)

    monkeypatch.setattr(session_module.time, "time", fake_time)
    monkeypatch.setattr(session_module.time, "sleep", fake_sleep)
    return clock


class _PickerKit(FakeKitUia2):
    """Tap helper that only succeeds for currently visible picker labels."""

    def __init__(self, device):
        super().__init__()
        self.device = device

    def execute_action(self, action_name, **kwargs):
        self.calls.append((action_name, kwargs))
        if action_name == "tap":
            selector = str(kwargs.get("selector") or "")
            if selector in {"下一步", "确定", "完成", "确认删除"}:
                widget = self.device(text=selector)
                if not widget.exists:
                    return ActionResult(False, "not visible: %s" % selector)
                widget.click()
            return ActionResult(True, action_name)
        return super().execute_action(action_name, **kwargs)


def test_push_file_falls_back_to_sync_and_adb_device(tmp_path):
    staged = tmp_path / "staged.jpg"
    staged.write_bytes(b"jpeg")

    class SyncOnly:
        def __init__(self):
            self.pushed = []
            self.sync = self

        def push(self, local, remote):
            self.pushed.append((local, remote))

    sync_only = SyncOnly()
    DianpingUia2Session._push_file(sync_only, str(staged), "/sdcard/a.jpg")
    assert sync_only.pushed == [(str(staged), "/sdcard/a.jpg")]

    class AdbOnly:
        def __init__(self):
            self.pushed = []
            self.adb_device = type("Adb", (), {"sync": self})()

        def push(self, local, remote):
            self.pushed.append((local, remote))

    adb_only = AdbOnly()
    DianpingUia2Session._push_file(adb_only, str(staged), "/sdcard/b.jpg")
    assert adb_only.pushed == [(str(staged), "/sdcard/b.jpg")]

    class Empty:
        pass

    try:
        DianpingUia2Session._push_file(Empty(), str(staged), "/sdcard/c.jpg")
    except AttributeError as exc:
        assert "file push" in str(exc)
    else:
        raise AssertionError("expected AttributeError")


def test_uia2_gallery_push_uses_device_push_not_sync(monkeypatch, tmp_path):
    """Real u2 Device has push() and no sync; gallery prep must not AttributeError."""
    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    device = _FakeGalleryDevice("IMG99999999_gni.jpg")
    assert not hasattr(device, "sync")
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=('uiautomator:new UiSelector().text("添加图/视频")',),
        thumbnail_selector=(
            'uiautomator:new UiSelector().resourceId("%s")' % device.SELECT_ID,
        ),
        confirm_selector=(
            'uiautomator:new UiSelector().text("下一步")',
            'uiautomator:new UiSelector().text("确定")',
        ),
    )

    assert result.success, result.message
    assert device.pushed and device.pushed[0][1].endswith(
        "Pictures/DianpingAuto/IMG99999999_gni.jpg"
    )


def test_uia2_pick_photos_stages_then_selects(monkeypatch, tmp_path):
    import io

    from PIL import Image

    from automation_app_dianping.config import default_selectors

    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    name = "IMG99999999_gni.jpg"
    device = _FakeGalleryDevice(name)
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device
    selectors = default_selectors()

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=selectors.add_photo,
        thumbnail_selector=selectors.photo_thumbnail,
        confirm_selector=selectors.photo_confirm,
    )

    assert result.success, result.message
    assert len(device.pushed) == 1
    remote = device.pushed[0][1]
    assert remote.endswith("Pictures/DianpingAuto/" + name)
    assert any(c[:2] == ["mkdir", "-p"] for c in device.shell_calls)
    source_exif = Image.open(io.BytesIO(photo.read_bytes())).getexif()
    staged_exif = Image.open(io.BytesIO(device.pushed_bytes)).getexif()
    assert source_exif.get(36867) is None
    assert staged_exif.get(36867) is not None
    scan = [c for c in device.shell_calls if c[:1] == ["am"]][0]
    assert "MEDIA_SCANNER_SCAN_FILE" in " ".join(scan)
    assert len(device.coordinate_clicks) >= 5, device.coordinate_clicks
    ax, ay = device.coordinate_clicks[0]
    assert 335 <= ax <= 588 and 1519 <= ay <= 1772
    hx, hy = device.coordinate_clicks[1]
    assert 430 <= hx <= 649 and 103 <= hy <= 156
    alx, aly = device.coordinate_clicks[2]
    assert 0 <= alx <= 1080 and 1746 <= aly <= 2005
    nx, ny = device.coordinate_clicks[3]
    assert 833 <= nx <= 1036 and 2287 <= ny <= 2366
    dx, dy = device.coordinate_clicks[4]
    assert 800 <= dx <= 1080 and 2200 <= dy <= 2360
    assert [c.get("text") for c in device.clicks if c.get("text")] == ["下一步", "确定"]
    select_lookups = [
        c
        for c in device.lookups
        if c.get("resourceId") == device.SELECT_ID and "instance" in c
    ]
    assert select_lookups and select_lookups[0]["instance"] == 0
    assert 0 in device.selected
    assert device.album == "DianpingAuto"
    assert not any(c.get("className") == "android.widget.ImageView" for c in device.lookups)


def test_uia2_pick_photos_fails_when_not_indexed_first(monkeypatch, tmp_path):
    """Indexed but not topping the DESC order → refuse to select."""
    import automation_app_dianping.session as session_module

    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path, "late.jpg")
    name = "IMG99999999_late.jpg"
    device = _FakeGalleryDevice(name)
    # never let the DESC probe see the target on top
    real_shell = device.shell

    def shell(args):
        if "--sort" in " ".join(args):
            return _FakeShellResponse("Row: 0 _display_name=other.jpg, datetaken=9")
        return real_shell(args)

    device.shell = shell
    kit = FakeKitUia2()
    monkeypatch.setattr(
        session_module, "_import_kit_uia2_session",
        lambda: type("C", (), {"__call__": lambda self, *a, **k: kit}),
    )
    session = session_module.DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=("~添加图",),
    )

    assert not result.success
    assert "not indexed first" in result.message
    assert kit.calls == []


def test_shell_text_reads_uia2_namedtuple_without_strip():
    from collections import namedtuple

    ShellResponse = namedtuple("ShellResponse", ["output", "exit_code"])
    response = ShellResponse("  Row: 0 _display_name=a.jpg  ", 0)
    with pytest.raises(AttributeError):
        response.strip()
    assert _shell_text(response) == "Row: 0 _display_name=a.jpg"
    assert _shell_text(("  hello  ", 0)) == "hello"
    assert _shell_text(b"  bytes  ") == "bytes"
    assert _shell_text("  plain  ") == "plain"
    assert _shell_text(None) == ""


def test_media_display_name_is_exact_field():
    row = "Row: 0 _display_name=IMG99999999_gni.jpg, datetaken=1"
    assert _media_display_name(row) == "IMG99999999_gni.jpg"
    assert _media_display_name(
        "Row: 0 _display_name=IMG99999999_gni.jpg.bak, datetaken=1"
    ) != "IMG99999999_gni.jpg"
    assert _media_display_name("Row: 0 datetaken=1") == ""


def test_uia2_pick_photos_skips_video_imageviews(monkeypatch, tmp_path):
    """Class-only ImageView.instance(0) is a video tile on 2026-09 最近项目."""
    from automation_app_dianping.config import default_selectors

    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    device = _FakeGalleryDevice("IMG99999999_gni.jpg")
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device
    selectors = default_selectors()

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=selectors.add_photo,
        thumbnail_selector=(
            'uiautomator:new UiSelector().className("android.widget.ImageView")',
        )
        + tuple(selectors.photo_thumbnail),
        confirm_selector=selectors.photo_confirm,
    )

    assert result.success, result.message
    assert any(
        c.get("resourceId") == device.SELECT_ID and "instance" in c
        for c in device.lookups
    )
    assert not any(c.get("className") == "android.widget.ImageView" for c in device.lookups)


def test_uia2_pick_photos_imageview_tap_does_not_count_as_selected(
    monkeypatch, tmp_path
):
    """Tapping photo_imageView opens a preview; it must not confirm as selected."""
    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    device = _FakeGalleryDevice("IMG99999999_gni.jpg")
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=('uiautomator:new UiSelector().text("添加图/视频")',),
        thumbnail_selector=(
            'uiautomator:new UiSelector().resourceId("%s")' % device.PHOTO_ID,
        ),
        confirm_selector=('uiautomator:new UiSelector().text("下一步")',),
    )

    assert not result.success
    assert "was not selected" in result.message or "attached 0 of 1" in result.message
    assert device.selected == set()
    assert not any(c.get("text") == "下一步" for c in device.clicks)


def test_uia2_pick_photos_fails_when_photo_tile_missing(monkeypatch, tmp_path):
    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    device = _FakeGalleryDevice("IMG99999999_gni.jpg", photo_count=0)
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=('uiautomator:new UiSelector().text("添加图/视频")',),
        thumbnail_selector=(
            'uiautomator:new UiSelector().resourceId("%s")' % device.PHOTO_ID,
        ),
        confirm_selector=('uiautomator:new UiSelector().text("下一步")',),
    )

    assert not result.success
    assert "attached 0 of 1" in result.message
    assert not any(c.get("text") == "下一步" for c in device.clicks)


class _FlakyFirstTapDevice(_FakeGalleryDevice):
    """Swallows the first select_layout tap, like a grid still settling.

    Live 2026-10-16: the tile was visible in the dump yet the first click
    never produced the selection badge; the retry (same selector) must stick
    instead of giving up after one miss.
    """

    def __init__(self, name):
        super().__init__(name)
        self.tile_tap_count = 0

    def __call__(self, **kwargs):
        widget = super().__call__(**kwargs)
        if kwargs.get("resourceId") == self.SELECT_ID:
            original = widget._on_click

            def flaky_on_click():
                # Device-level count: each lookup returns a fresh widget, so
                # the "first tap swallowed" state must not live per-widget.
                self.tile_tap_count += 1
                if self.tile_tap_count >= 2 and original is not None:
                    original()

            widget._on_click = flaky_on_click
        return widget


def test_uia2_pick_photos_retries_tile_tap_that_does_not_stick(
    monkeypatch, tmp_path
):
    from automation_app_dianping.config import default_selectors

    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    device = _FlakyFirstTapDevice("IMG99999999_gni.jpg")
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device
    selectors = default_selectors()

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=selectors.add_photo,
        thumbnail_selector=selectors.photo_thumbnail,
        confirm_selector=selectors.photo_confirm,
    )

    assert result.success, result.message
    assert device.tile_tap_count == 2
    assert 0 in device.selected
    assert device.album == "DianpingAuto"


def test_uia2_pick_photos_reports_tile_reason_in_failure(monkeypatch, tmp_path):
    """The per-tile reason must survive into the step result message."""
    from automation_app_dianping.config import default_selectors

    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    device = _FakeGalleryDevice("IMG99999999_gni.jpg", photo_count=0)
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device
    selectors = default_selectors()

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=selectors.add_photo,
        thumbnail_selector=selectors.photo_thumbnail,
        confirm_selector=selectors.photo_confirm,
    )

    assert not result.success
    assert "attached 0 of 1" in result.message
    # Diagnostics tell the next live run whether the selector left the tree.
    assert "select_layout in dump" in result.message


def test_uia2_pick_photos_staggers_multi_photo_exif(monkeypatch, tmp_path):
    import io

    from PIL import Image

    from automation_app_dianping.config import default_selectors

    _install_fast_clock(monkeypatch)
    first = _write_jpeg(tmp_path, "alpha.jpg")
    second = _write_jpeg(tmp_path, "beta.jpg")
    device = _FakeGalleryDevice("IMG99999999_alpha.jpg")
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device
    selectors = default_selectors()

    result = session.execute_action(
        "pick_photos",
        photos=[str(first), str(second)],
        add_selector=selectors.add_photo,
        thumbnail_selector=selectors.photo_thumbnail,
        confirm_selector=selectors.photo_confirm,
    )

    assert result.success, result.message
    remotes = [remote for _local, remote in device.pushed]
    assert remotes[0].endswith("IMG99999999_beta.jpg")
    assert remotes[1].endswith("IMG99999999_alpha.jpg")
    older = Image.open(io.BytesIO(device.pushed_payloads[0])).getexif().get(36867)
    newer = Image.open(io.BytesIO(device.pushed_payloads[1])).getexif().get(36867)
    assert older and newer and older < newer
    select_lookups = [
        c
        for c in device.lookups
        if c.get("resourceId") == device.SELECT_ID and "instance" in c
    ]
    assert [c.get("instance") for c in select_lookups[:2]] == [0, 1]
    assert device.selected >= {0, 1}


def test_prepare_gallery_photo_flattens_alpha_png(monkeypatch, tmp_path):
    """A generated review photo may be an RGBA PNG; staging re-saves as JPEG,
    which cannot encode alpha. Without the RGB flatten the EXIF rewrite fails
    and the publish attaches nothing."""
    import io

    from PIL import Image

    _install_fast_clock(monkeypatch)
    png = tmp_path / "gen.png"
    Image.new("RGBA", (4, 4), (255, 0, 0, 128)).save(png, "PNG")

    device = _FakeGalleryDevice("IMG99999999_gen.png")
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session._prepare_gallery_photo(str(png))

    assert result.success, result.message
    staged = Image.open(io.BytesIO(device.pushed_payloads[0]))
    assert staged.format == "JPEG"
    assert staged.mode == "RGB"
    assert staged.getexif().get(36867)


def test_uia2_pick_photos_refuses_substring_top_row(monkeypatch, tmp_path):
    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    name = "IMG99999999_gni.jpg"
    device = _FakeGalleryDevice(name)
    real_shell = device.shell

    def shell(args):
        if "--sort" in " ".join(args):
            return _FakeShellResponse(
                "Row: 0 _display_name=%s.bak, datetaken=9" % name
            )
        return real_shell(args)

    device.shell = shell
    kit = FakeKitUia2()
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=("~添加图",),
    )

    assert not result.success
    assert "not indexed first" in result.message
    assert kit.calls == []


def test_dish_edit_helpers_read_filmstrip_and_trash():
    xml = _dish_edit_xml(3)
    assert dish_edit_is_open(xml)
    rects = dish_edit_filmstrip_rects(xml)
    assert [(item["x"], item["width"]) for item in rects] == [
        (31, 127),
        (174, 127),
        (317, 127),
    ]
    trash = dish_edit_trash_rect(xml)
    assert trash == {"x": 951, "y": 1745, "width": 93, "height": 70}
    plus = preferred_tap_rect(xml, "description", "上传照片")
    assert plus["x"] == 460
    assert not dish_edit_is_open(_EDITOR_ADD_PHOTO_XML)
    assert dish_edit_filmstrip_rects(_EDITOR_ADD_PHOTO_XML) == []
    assert dish_edit_trash_rect(_EDITOR_ADD_PHOTO_XML) is None
    assert dish_edit_trash_rect("<not-xml") is None
    assert dish_edit_filmstrip_rects("<not-xml") == []
    assert dish_edit_delete_confirm_rect(xml) is None
    assert dish_edit_delete_confirm_rect("<not-xml") is None
    title_only = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n"
        "<hierarchy>\n"
        '  <node text="确认删除这张图片吗？" class="android.widget.TextView" '
        'clickable="false" bounds="[305,1088][775,1144]" />\n'
        "</hierarchy>\n"
    )
    assert dish_edit_delete_confirm_rect(title_only) is None
    live_dialog = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n"
        "<hierarchy>\n"
        '  <node text="确认删除这张图片吗？" class="android.widget.TextView" '
        'clickable="false" bounds="[305,1088][775,1144]" />\n'
        '  <node text="考虑一下" class="android.widget.TextView" clickable="true" '
        'bounds="[207,1211][511,1324]" />\n'
        '  <node text="确认删除" class="android.widget.TextView" clickable="true" '
        'bounds="[568,1211][872,1324]" />\n'
        "</hierarchy>\n"
    )
    assert dish_edit_delete_confirm_rect(live_dialog) == {
        "x": 568,
        "y": 1211,
        "width": 304,
        "height": 113,
    }


def test_editor_attached_photo_rects_skips_add_and_voice_cards():
    rects = editor_attached_photo_rects(_EDITOR_LEFTOVER_PHOTOS_XML)
    assert [(item["x"], item["y"], item["width"], item["height"]) for item in rects] == [
        (34, 1087, 178, 253),
        (226, 1087, 253, 253),
    ]
    assert editor_attached_photo_rects(_EDITOR_ADD_PHOTO_XML) == []
    assert editor_attached_photo_rects(_EDITOR_ONE_LEFTOVER_PHOTO_XML) == [
        {"x": 34, "y": 1087, "width": 178, "height": 253}
    ]
    assert editor_attached_photo_rects("<not-xml") == []


def test_uia2_pick_photos_clears_leftover_editor_tiles(monkeypatch, tmp_path):
    from automation_app_dianping.config import default_selectors

    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    device = _FakeGalleryDevice("IMG99999999_gni.jpg", leftover_photos=2)
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device
    selectors = default_selectors()

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=selectors.add_photo,
        thumbnail_selector=selectors.photo_thumbnail,
        confirm_selector=selectors.photo_confirm,
    )

    assert result.success, result.message
    assert device.leftover_photos == 0
    assert device.album == "DianpingAuto"
    assert 0 in device.selected
    leftover_taps = [
        (x, y)
        for x, y in device.coordinate_clicks
        if 1087 <= y <= 1340 and x < 479
    ]
    assert leftover_taps
    trash_taps = [
        (x, y)
        for x, y in device.coordinate_clicks
        if 1745 <= y <= 1815 and x >= 951
    ]
    assert len(trash_taps) >= 2


def test_uia2_pick_photos_confirms_already_open_dish_edit_delete_dialog(
    monkeypatch, tmp_path
):
    """A leftover 确认删除 sheet is dismissed before any trash/filmstrip tap."""
    from automation_app_dianping.config import default_selectors

    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    device = _FakeGalleryDevice("IMG99999999_gni.jpg", leftover_photos=1)
    device.dish_edit_open = True
    device.delete_dialog = True
    device.hierarchy = _dish_edit_xml(1)
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device
    selectors = default_selectors()

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=selectors.add_photo,
        thumbnail_selector=selectors.photo_thumbnail,
        confirm_selector=selectors.photo_confirm,
    )

    assert result.success, result.message
    assert device.leftover_photos == 0
    assert device.album == "DianpingAuto"
    assert 0 in device.selected
    confirm_taps = [
        (x, y)
        for x, y in device.coordinate_clicks
        if 568 <= x <= 872 and 1211 <= y <= 1324
    ]
    assert confirm_taps
    trash_taps = [
        (x, y)
        for x, y in device.coordinate_clicks
        if 1745 <= y <= 1815 and x >= 951
    ]
    assert trash_taps == []


def test_uia2_pick_photos_fails_when_dish_edit_delete_dialog_stuck(monkeypatch, tmp_path):
    """Tapping 确认删除 three times without the sheet leaving is a hard fail."""
    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    device = _FakeGalleryDevice("IMG99999999_gni.jpg", leftover_photos=1)
    device.dish_edit_open = True
    device.delete_dialog = True
    device.hierarchy = _dish_edit_xml(1)

    def miss_confirm(x, y):
        device.coordinate_clicks.append((int(x), int(y)))

    device.click = miss_confirm
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=('uiautomator:new UiSelector().text("添加图/视频")',),
    )

    assert not result.success
    assert "stuck after confirm" in result.message
    assert device.leftover_photos == 1
    assert device.selected == set()
    assert not device.picker_open
    confirm_taps = [
        (x, y)
        for x, y in device.coordinate_clicks
        if 568 <= x <= 872 and 1211 <= y <= 1324
    ]
    assert len(confirm_taps) >= 3


def test_uia2_pick_photos_fails_when_leftover_tile_does_not_drop(monkeypatch, tmp_path):
    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    device = _FakeGalleryDevice("IMG99999999_gni.jpg", leftover_photos=1)

    def stuck(x, y):
        device.coordinate_clicks.append((int(x), int(y)))

    device.click = stuck
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=('uiautomator:new UiSelector().text("添加图/视频")',),
    )

    assert not result.success
    assert "did not drop" in result.message
    assert device.selected == set()
    assert not device.picker_open


def test_picker_header_album_reads_chrome_not_dropdown():
    assert _picker_header_album(_PICKER_XML) == "最近项目"
    assert _picker_header_album(_ALBUM_DROPDOWN_XML) == "最近项目"
    assert _picker_header_album(_STAGING_ALBUM_XML) == "DianpingAuto"
    assert _picker_header_album(_EDITOR_ADD_PHOTO_XML) is None
    assert _picker_header_album("<not-xml") is None


def test_uia2_pick_photos_refuses_tiles_outside_staging_album(monkeypatch, tmp_path):
    """最近项目 tile 0 is a private/downloads photo; refuse until DianpingAuto."""
    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    device = _FakeGalleryDevice("IMG99999999_gni.jpg")

    def no_album_switch(x, y):
        device.coordinate_clicks.append((int(x), int(y)))
        left, top, right, bottom = device.ADD_PARENT_BOUNDS
        if not device.picker_open and left <= x <= right and top <= y <= bottom:
            device._open_picker()

    device.click = no_album_switch
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=('uiautomator:new UiSelector().text("添加图/视频")',),
        thumbnail_selector=(
            'uiautomator:new UiSelector().resourceId("%s")' % device.SELECT_ID,
        ),
        confirm_selector=('uiautomator:new UiSelector().text("下一步")',),
    )

    assert not result.success
    assert (
        "could not switch" in result.message
        or "refused to select" in result.message
        or "album dropdown did not open" in result.message
    )
    assert device.selected == set()
    assert device.album == "最近项目"
    assert not any(c.get("resourceId") == device.SELECT_ID for c in device.clicks)


def test_clickable_ancestor_rect_uses_parent_card():
    add = clickable_ancestor_rect(_EDITOR_ADD_PHOTO_XML, "text", "添加图/视频")
    assert add == {"x": 335, "y": 1519, "width": 253, "height": 253}
    write = clickable_ancestor_rect(_SHOP_WRITE_REVIEW_XML, "text", "写评价")
    assert write == {"x": 191, "y": 2179, "width": 96, "height": 113}
    nxt = clickable_ancestor_rect(_PICKER_XML, "text", "下一步")
    assert nxt == {"x": 833, "y": 2287, "width": 203, "height": 79}
    dish = clickable_ancestor_rect(_DISH_CONFIRM_XML, "text", "确定")
    assert dish == {"x": 800, "y": 2200, "width": 280, "height": 160}
    missing = clickable_ancestor_rect(_EDITOR_ADD_PHOTO_XML, "text", "发布")
    assert missing is None
    assert clickable_ancestor_rect("<not-xml", "text", "写评价") is None
    xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[10,10][9,20]" resource-id="host">
    <node text="添加图" content-desc="加图入口" class="android.widget.TextView" clickable="false" bounds="[12,12][40,40]" />
  </node>
</hierarchy>
"""
    own = clickable_ancestor_rect(xml, "text-contains", "添加")
    assert own == {"x": 12, "y": 12, "width": 28, "height": 28}
    assert clickable_ancestor_rect(xml, "description", "加图入口") == own
    assert clickable_ancestor_rect(xml, "description-contains", "加图") == own
    assert clickable_ancestor_rect(xml, "id", "host") is None
    assert clickable_ancestor_rect(xml, "class", "android.widget.TextView") == own
    assert clickable_ancestor_rect(xml, "xpath", "n") is None
    assert clickable_ancestor_rect(xml, "text", "") is None


def test_preferred_tap_rect_shrinks_full_width_draft_card():
    card = clickable_ancestor_rect(_SHOP_DRAFT_COMPLETE_XML, "text", "完善评价")
    assert card == {"x": 0, "y": 1447, "width": 1080, "height": 217}
    button = preferred_tap_rect(_SHOP_DRAFT_COMPLETE_XML, "text", "完善评价")
    assert button == {"x": 829, "y": 1522, "width": 211, "height": 70}
    write = preferred_tap_rect(_SHOP_WRITE_REVIEW_XML, "text", "写评价")
    assert write == {"x": 191, "y": 2179, "width": 96, "height": 113}


def test_shop_page_has_review_entry_requires_shop_and_cta():
    shop = "细记港九宵夜大牌档(虹桥南丰城店)"
    assert shop_page_has_review_entry(_SHOP_DRAFT_COMPLETE_XML, shop)
    assert not shop_page_has_review_entry(_HOME_SEARCH_XML, shop)
    assert not shop_page_has_review_entry(_SHOP_WRITE_REVIEW_XML, shop)
    assert not shop_page_has_review_entry(_SHOP_DRAFT_COMPLETE_XML, "")


def test_review_editor_is_open_detects_add_photo_and_word_count():
    assert review_editor_is_open(_EDITOR_ADD_PHOTO_XML)
    assert review_editor_is_open(
        "<hierarchy><node text='已写81个字' /></hierarchy>"
    )
    assert not review_editor_is_open(_SHOP_DRAFT_COMPLETE_XML)
    assert not review_editor_is_open(_HOME_SEARCH_XML)
    assert not review_editor_is_open("")
    assert dish_edit_is_open(
        "<hierarchy><node text='确认删除这张图片吗？' /></hierarchy>"
    )


def test_should_skip_rating_on_overwrite_chrome_without_overall_bar():
    overwrite = (
        "<hierarchy><node text='添加图/视频' /><node text='发布' /></hierarchy>"
    )
    overall = "<hierarchy><node text='超预期' /></hierarchy>"
    assert should_skip_rating(overwrite)
    assert review_publish_chrome_visible(overwrite)
    assert not overall_rating_bar_visible(overwrite)
    assert not should_skip_rating(overall)
    assert overall_rating_bar_visible(overall)
    assert not should_skip_rating("")
    assert not should_skip_rating(_HOME_SEARCH_XML)
    assert should_skip_rating(_dish_edit_xml(2))
    assert not review_ime_toolbar_visible(overwrite)
    assert review_ime_toolbar_visible(
        "<hierarchy><node text='完成' /><node text='已写81个字' /></hierarchy>"
    )


def test_uia2_navigate_skips_search_on_restored_shop_page(monkeypatch):
    class Device:
        def __init__(self):
            self.clicks = []
            self.hierarchy = _SHOP_DRAFT_COMPLETE_XML

        def dump_hierarchy(self):
            return self.hierarchy

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))

    device = Device()
    kit = FakeKitUia2()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="细记港九宵夜大牌档(虹桥南丰城店)",
        write_selector=('uiautomator:new UiSelector().text("完善评价")',),
        search_bar=("~搜索",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
    )

    assert result.success, result.message
    assert "restored shop page" in result.message
    assert device.clicks == [(934, 1557)]
    assert kit.calls == []


def test_uia2_navigate_searches_from_home(monkeypatch):
    # The search flow now waits for a real page marker after every transition
    # (the kit wait resolves lazily and would otherwise race the next tap), so
    # the fake device must actually change page on each tap that leaves one.
    pages = [
        _HOME_SEARCH_XML,
        _SEARCH_BOX_XML,
        _RESULTS_XML,
        _SHOP_WRITE_REVIEW_XML,
        _EDITOR_ADD_PHOTO_XML,
    ]

    class Device:
        def __init__(self):
            self.clicks = []
            self.step = 0

        def dump_hierarchy(self):
            return pages[min(self.step, len(pages) - 1)]

        def advance(self):
            self.step = min(self.step + 1, len(pages) - 1)

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))
            self.advance()

    device = Device()

    class Kit(FakeKitUia2):
        def execute_action(self, action_name, **kwargs):
            result = super().execute_action(action_name, **kwargs)
            if result.success and action_name in ("tap", "press_key"):
                device.advance()
            return result

    kit = Kit()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="细记港九宵夜大牌档(虹桥南丰城店)",
        write_selector=('uiautomator:new UiSelector().text("写评价")',),
        search_bar=("id:com.dianping.v1:id/title_search_bar",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
        search_confirm=('uiautomator:new UiSelector().text("搜索")',),
        search_results_marker=('uiautomator:new UiSelector().text("商户")',),
        shop_result=('uiautomator:new UiSelector().textContains("细记港九")',),
    )

    assert result.success, result.message
    assert "via search" in result.message
    names = [name for name, _kwargs in kit.calls]
    # 2026-10-17: the on-home gate is now a real dump parse (the kit wait
    # fakes success for absent selectors), so wait_for_element is no longer
    # part of the navigate flow itself.
    assert "type_text" in names
    assert "tap" in names
    # home → search box → results → shop page → editor
    assert device.step == len(pages) - 1
    assert device.clicks[0] == (474, 130)


def test_uia2_navigate_continues_from_restored_results_page(monkeypatch):
    """A relaunch can restore the app mid-search on the results page, where
    the search-bar selectors do not exist. The flow must skip the search box
    and tap the result row straight away."""
    pages = [_RESULTS_XML, _SHOP_WRITE_REVIEW_XML, _EDITOR_ADD_PHOTO_XML]

    class Device:
        def __init__(self):
            self.clicks = []
            self.step = 0

        def dump_hierarchy(self):
            return pages[min(self.step, len(pages) - 1)]

        def advance(self):
            self.step = min(self.step + 1, len(pages) - 1)

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))
            self.advance()

    device = Device()

    class Kit(FakeKitUia2):
        def execute_action(self, action_name, **kwargs):
            result = super().execute_action(action_name, **kwargs)
            if result.success and action_name in ("tap", "press_key"):
                device.advance()
            return result

    kit = Kit()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="细记港九宵夜大牌档(虹桥南丰城店)",
        write_selector=('uiautomator:new UiSelector().text("写评价")',),
        search_bar=("id:com.dianping.v1:id/title_search_bar",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
        search_confirm=('uiautomator:new UiSelector().text("搜索")',),
        search_results_marker=('uiautomator:new UiSelector().text("商户")',),
        shop_result=('uiautomator:new UiSelector().textContains("细记港九")',),
    )

    assert result.success, result.message
    assert "via search" in result.message
    names = [name for name, _kwargs in kit.calls]
    assert "type_text" not in names
    assert "wait_for_element" not in names
    # rose row tap (474, 330) then the write-CTA tap (239, 2235)
    assert device.clicks == [(474, 330), (239, 2235)]
    assert device.step == len(pages) - 1


def test_uia2_navigate_skips_when_editor_already_open():
    class Device:
        def __init__(self):
            self.clicks = []
            self.hierarchy = _EDITOR_ADD_PHOTO_XML

        def dump_hierarchy(self):
            return self.hierarchy

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))

    device = Device()
    kit = FakeKitUia2()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="细记港九宵夜大牌档(虹桥南丰城店)",
        write_selector=('uiautomator:new UiSelector().text("完善评价")',),
        search_bar=("~搜索",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
    )

    assert result.success, result.message
    assert "already in review editor" in result.message
    assert device.clicks == []
    assert kit.calls == []


def test_uia2_navigate_skips_when_delete_dialog_already_open():
    xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n"
        "<hierarchy>\n"
        '  <node text="确认删除这张图片吗？" class="android.widget.TextView" '
        'clickable="false" bounds="[305,1088][775,1144]" />\n'
        '  <node text="确认删除" class="android.widget.TextView" clickable="true" '
        'bounds="[568,1211][872,1324]" />\n'
        "</hierarchy>\n"
    )

    class Device:
        def __init__(self):
            self.clicks = []
            self.hierarchy = xml

        def dump_hierarchy(self):
            return self.hierarchy

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))

    device = Device()
    kit = FakeKitUia2()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="细记港九宵夜大牌档(虹桥南丰城店)",
        write_selector=('uiautomator:new UiSelector().text("完善评价")',),
        search_bar=("~搜索",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
    )

    assert result.success, result.message
    assert "dish-edit" in result.message
    assert device.clicks == []
    assert kit.calls == []


def test_uia2_navigate_refuses_empty_hierarchy_after_wake(monkeypatch):
    class Device:
        def __init__(self):
            self.clicks = []
            self.screen_on_calls = 0
            self.info = {"displayOn": False}

        def dump_hierarchy(self):
            return ""

        def screen_on(self):
            self.screen_on_calls += 1
            self.info = {"displayOn": True}

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))

    _install_fast_clock(monkeypatch)
    device = Device()
    kit = FakeKitUia2()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="细记港九宵夜大牌档(虹桥南丰城店)",
        write_selector=('uiautomator:new UiSelector().text("完善评价")',),
        search_bar=("~搜索",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
    )

    assert not result.success
    assert "empty hierarchy" in result.message
    assert device.screen_on_calls >= 1
    assert device.clicks == []
    assert kit.calls == []


def test_uia2_launch_app_wakes_screen_when_off():
    class Device:
        def __init__(self):
            self.screen_on_calls = 0
            self.info = {"displayOn": False}

        def screen_on(self):
            self.screen_on_calls += 1
            self.info = {"displayOn": True}

    device = Device()
    kit = FakeKitSession(device)
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "launch_app", app_id="com.dianping.v1", settle_seconds=0
    )

    assert result.success, result.message
    assert device.screen_on_calls == 1


def test_uia2_launch_app_wakes_screen_via_keyevent_when_screen_on_missing():
    class Device:
        def __init__(self):
            self.shell_calls = []
            self.info = {"screenOn": False}

        def shell(self, args):
            self.shell_calls.append(args)

    device = Device()
    kit = FakeKitSession(device)
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "launch_app", app_id="com.dianping.v1", settle_seconds=0
    )

    assert result.success, result.message
    assert device.shell_calls == ["input keyevent 224"]


def test_uia2_navigate_skips_when_dish_edit_open():
    class Device:
        def __init__(self):
            self.clicks = []
            self.hierarchy = _dish_edit_xml(2)

        def dump_hierarchy(self):
            return self.hierarchy

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))

    device = Device()
    kit = FakeKitUia2()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="细记港九宵夜大牌档(虹桥南丰城店)",
        write_selector=('uiautomator:new UiSelector().text("完善评价")',),
        search_bar=("~搜索",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
    )

    assert result.success, result.message
    assert "dish-edit" in result.message
    assert device.clicks == []
    assert kit.calls == []


def test_uia2_type_text_and_hide_keyboard_skip_on_dish_edit():
    class Device:
        def __init__(self):
            self.clicks = []
            self.presses = []
            self.hierarchy = _dish_edit_xml(1)

        def dump_hierarchy(self):
            return self.hierarchy

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))

        def press(self, key):
            self.presses.append(key)

    device = Device()
    kit = FakeKitUia2()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    typed = session.execute_action(
        "type_text",
        selector=('uiautomator:new UiSelector().className("android.widget.EditText")',),
        text="should not type",
    )
    hidden = session.execute_action("hide_keyboard")
    dismissed = session.execute_action("dismiss_dialogs")

    assert typed.success and "dish-edit" in typed.message
    assert hidden.success and "chrome visible" in hidden.message
    assert dismissed.success and "dish-edit" in dismissed.message
    assert device.clicks == []
    assert device.presses == []
    assert kit.calls == []


def test_uia2_hide_keyboard_taps_done_label():
    xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[900,1400][1040,1480]">
    <node text="完成" class="android.widget.TextView" clickable="false" bounds="[920,1420][1020,1460]" />
  </node>
</hierarchy>
"""

    class Device:
        def __init__(self):
            self.clicks = []
            self.hierarchy = xml

        def dump_hierarchy(self):
            return self.hierarchy

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))

    device = Device()
    kit = FakeKitUia2()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action("hide_keyboard")

    assert result.success, result.message
    assert "完成" in result.message
    assert device.clicks == [(970, 1440)]


def test_uia2_hide_keyboard_falls_back_to_back():
    class Kit(FakeKitUia2):
        def execute_action(self, action_name, **kwargs):
            self.calls.append((action_name, kwargs))
            if action_name == "tap":
                return ActionResult(False, "not found")
            return super().execute_action(action_name, **kwargs)

    class Device:
        def __init__(self):
            self.clicks = []
            self.presses = []
            self.hierarchy = "<hierarchy/>"

        def dump_hierarchy(self):
            return self.hierarchy

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))

        def press(self, key):
            self.presses.append(key)

    device = Device()
    kit = Kit()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action("hide_keyboard")

    assert result.success, result.message
    assert "BACK" in result.message
    assert device.presses == ["back"]
    assert device.clicks == []


def test_uia2_rate_overall_taps_star_row_after_hiding_keyboard():
    """The overall bar is a row of 5 stars under dead caption labels.

    With the IME up the star row is not in the dump; rate must hide the
    keyboard once (Picasso 完成 toolbar button) and then tap the Nth star
    centre — never the caption text, which is not a touch target
    (live 2026-09-23).
    """
    covered = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[900,1400][1040,1480]">
    <node text="完成" class="android.widget.TextView" clickable="false" bounds="[920,1420][1020,1460]" />
  </node>
</hierarchy>
"""
    revealed = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node class="android.widget.FrameLayout" clickable="true" bounds="[34,209][1047,417]">
    <node text="很棒" class="android.widget.TextView" clickable="false" bounds="[883,253][949,292]" />
    <node class="android.widget.ImageView" bounds="[144,313][233,402]" />
    <node class="android.widget.ImageView" bounds="[320,313][409,402]" />
    <node class="android.widget.ImageView" bounds="[496,313][585,402]" />
    <node class="android.widget.ImageView" bounds="[671,313][760,402]" />
    <node class="android.widget.ImageView" bounds="[847,313][936,402]" />
  </node>
</hierarchy>
"""

    class Device:
        def __init__(self):
            self.clicks = []
            self.hierarchy = covered

        def dump_hierarchy(self):
            return self.hierarchy

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))
            # 完成 dismisses the IME; the star row is dumped from then on.
            self.hierarchy = revealed

    device = Device()
    kit = FakeKitUia2()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "rate",
        dimension="overall",
        value=5,
        selector=('uiautomator:new UiSelector().text("很棒")',),
        anchor="overall",
    )

    assert result.success, result.message
    # (970,1440) is the 完成 toolbar tap that hides the IME; the Nth star is
    # tapped via a kit swipe gesture at the star centre, never the caption.
    assert device.clicks == [(970, 1440)]
    assert kit.calls[-1][0] == "swipe"
    swipe = kit.calls[-1][1]
    # 5th star centre read from the dump row ((188,357)..(891,357)).
    assert (swipe["start_x"], swipe["start_y"]) == (891, 357)
    assert "bounds" not in [name for name, _ in kit.calls]


def test_uia2_rate_skips_when_overwrite_chrome_has_no_overall_bar():
    class Device:
        def dump_hierarchy(self):
            return (
                "<hierarchy><node text='添加图/视频' />"
                "<node text='发布' /></hierarchy>"
            )

        def click(self, x, y):
            raise AssertionError("rate must not tap overwrite chrome")

    device = Device()
    kit = FakeKitUia2()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "rate",
        dimension="overall",
        value=5,
        selector=('uiautomator:new UiSelector().text("超预期")',),
        anchor="overall",
    )

    assert result.success, result.message
    assert "skipped" in result.message
    assert kit.calls == []


def test_uia2_hide_keyboard_skips_when_publish_chrome_visible():
    class Device:
        def __init__(self):
            self.clicks = []
            self.presses = []

        def dump_hierarchy(self):
            return (
                "<hierarchy><node text='添加图/视频' />"
                "<node text='发布' /></hierarchy>"
            )

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))

        def press(self, key):
            self.presses.append(key)

    device = Device()
    kit = FakeKitUia2()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action("hide_keyboard")

    assert result.success, result.message
    assert "chrome visible" in result.message
    assert device.clicks == []
    assert device.presses == []


def test_uia2_tap_write_review_uses_clickable_parent():
    device = _FakeGalleryDevice("unused.jpg")
    device.hierarchy = _SHOP_WRITE_REVIEW_XML
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "tap",
        selector=('uiautomator:new UiSelector().text("写评价")',),
    )

    assert result.success, result.message
    assert device.coordinate_clicks
    x, y = device.coordinate_clicks[0]
    assert 191 <= x <= 287
    assert 2179 <= y <= 2292


def test_uia2_tap_falls_back_when_hierarchy_dump_fails():
    device = _FakeGalleryDevice("unused.jpg")

    def boom():
        raise RuntimeError("dump failed")

    device.dump_hierarchy = boom
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "tap",
        selector=('uiautomator:new UiSelector().text("添加图/视频")',),
    )

    assert result.success
    assert kit.calls and kit.calls[0][0] == "tap"
    assert device.coordinate_clicks == []


def test_uia2_clickable_parent_tap_reports_click_error():
    device = _FakeGalleryDevice("unused.jpg")

    def boom(x, y):
        raise RuntimeError("click failed")

    device.click = boom
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "tap",
        selector=('uiautomator:new UiSelector().text("添加图/视频")',),
    )

    assert not result.success
    assert "clickable-parent tap failed" in result.message


def test_uia2_pick_photos_confirm_requires_clickable_parent(monkeypatch, tmp_path):
    """Kit tap on the 下一步 label must not count as confirm (live miss)."""
    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    device = _FakeGalleryDevice("IMG99999999_gni.jpg")

    def miss_confirm(x, y):
        device.coordinate_clicks.append((int(x), int(y)))
        left, top, right, bottom = device.ADD_PARENT_BOUNDS
        if not device.picker_open and left <= x <= right and top <= y <= bottom:
            device._open_picker()
            return
        hleft, htop, hright, hbottom = device.HEADER_PARENT_BOUNDS
        if (
            device.picker_open
            and not device.dropdown_open
            and device.album != "DianpingAuto"
            and hleft <= x <= hright
            and htop <= y <= hbottom
        ):
            device._open_dropdown()
            return
        aleft, atop, aright, abottom = device.ALBUM_PARENT_BOUNDS
        if (
            device.dropdown_open
            and aleft <= x <= aright
            and atop <= y <= abottom
        ):
            device._open_staging_album()

    device.click = miss_confirm
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=('uiautomator:new UiSelector().text("添加图/视频")',),
        thumbnail_selector=(
            'uiautomator:new UiSelector().resourceId("%s")' % device.SELECT_ID,
        ),
        confirm_selector=(
            'uiautomator:new UiSelector().text("下一步")',
            'uiautomator:new UiSelector().text("确定")',
        ),
    )

    assert not result.success
    assert "confirm not found" in result.message
    assert device.picker_open
    assert "下一步" in device.visible_texts


def test_uia2_pick_photos_fails_when_picker_does_not_open(monkeypatch, tmp_path):
    _install_fast_clock(monkeypatch)
    photo = _write_jpeg(tmp_path)
    device = _FakeGalleryDevice("IMG99999999_gni.jpg")

    def miss(x, y):
        device.coordinate_clicks.append((int(x), int(y)))

    device.click = miss
    kit = _PickerKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "pick_photos",
        photos=[str(photo)],
        add_selector=('uiautomator:new UiSelector().text("添加图/视频")',),
        thumbnail_selector=(
            'uiautomator:new UiSelector().resourceId("%s")' % device.PHOTO_ID,
        ),
        confirm_selector=('uiautomator:new UiSelector().text("下一步")',),
    )

    assert not result.success
    assert "did not open picker" in result.message
    assert not any(
        c.get("resourceId") == device.PHOTO_ID and "instance" in c
        for c in device.lookups
    )


def test_uia2_manual_window_prints_guidance(monkeypatch, capsys):
    import automation_app_dianping.session as session_module

    class BlockedKit(FakeKitUia2):
        def execute_action(self, action_name, **kwargs):
            self.calls.append((action_name, kwargs))
            return ActionResult(False, "blocked")

    kit = BlockedKit()
    session = session_module.DianpingUia2Session(kit, captcha_window_seconds=2)

    result = session.execute_action("tap", selector="搜索", by="text")

    assert not result.success
    out = capsys.readouterr().out
    assert "solve the challenge" in out


def test_uia2_execute_action_logs_progress(monkeypatch, capsys):
    session, _ = _make_uia2_session(monkeypatch)

    session.execute_action("tap", selector="搜索", by="text")

    out = capsys.readouterr().out
    assert "[dianping-uia2] >> tap" in out
    assert "[dianping-uia2] << tap: ok" in out


def test_uia2_dismiss_dialogs_rejects_a_bad_max_attempts(monkeypatch):
    session, _kit = _make_uia2_session(monkeypatch)

    result = session.execute_action(
        "dismiss_dialogs", selector=("~ok",), max_attempts="many"
    )

    assert not result.success
    assert "max_attempts must be a number" in result.message


def test_uia2_widget_exists_fails_closed_when_driver_errors(monkeypatch, capsys):
    """A driver hiccup must not read as 'widget gone' (fail-closed)."""
    class _BadDriver:
        def __call__(self, **kwargs):
            raise RuntimeError("u2 transport lost")

    class _Kit(FakeKitUia2):
        @property
        def driver(self):
            return _BadDriver()

    session, _kit = _make_uia2_session(monkeypatch, _Kit())

    assert session._uia2_widget_exists("text", "Camera") is True
    assert "widget_exists" in capsys.readouterr().out


def test_log_swallowed_throttles_repeated_labels(monkeypatch, capsys):
    """A persistent device fault makes every poll raise; the log must not
    print one line per poll (spam), only the first and then after a pause."""
    import automation_app_dianping.session as session_mod

    monkeypatch.setattr(session_mod, "_SWALLOW_LOG_LAST", {})
    clock = {"now": 1000.0}
    monkeypatch.setattr(session_mod.time, "time", lambda: clock["now"])
    exc = RuntimeError("boom")

    session_mod._log_swallowed("throttle-probe", exc)
    assert "throttle-probe" in capsys.readouterr().out

    session_mod._log_swallowed("throttle-probe", exc)
    assert "throttle-probe" not in capsys.readouterr().out

    clock["now"] += session_mod._SWALLOW_LOG_INTERVAL_SECONDS
    session_mod._log_swallowed("throttle-probe", exc)
    assert "throttle-probe" in capsys.readouterr().out


def test_uia2_widget_exists_reports_absent_and_present(monkeypatch):
    class _NullDriver:
        def __call__(self, **kwargs):
            class _El:
                exists = False
            return _El()

    class _SetDriver:
        def __call__(self, **kwargs):
            class _El:
                exists = True
            return _El()

    class _Kit(FakeKitUia2):
        driver = _NullDriver()

    class _KitPresent(FakeKitUia2):
        driver = _SetDriver()

    session, _ = _make_uia2_session(monkeypatch, _Kit())
    assert session._uia2_widget_exists("text", "Camera") is False

    session_present, _ = _make_uia2_session(monkeypatch, _KitPresent())
    assert session_present._uia2_widget_exists("text", "Camera") is True


_PENDING_LIST_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node text="待评价(2)" class="android.widget.TextView" clickable="true" bounds="[60,300][400,380]" />
  <node text="赤上烧肉酒场(娄山关路店)" class="android.widget.TextView" clickable="false" bounds="[40,600][600,660]" />
  <node text="评价" class="android.widget.Button" clickable="true" bounds="[880,590][1040,670]" />
  <node text="细记港九宵夜大牌档(虹桥南丰城店)" class="android.widget.TextView" clickable="false" bounds="[40,900][600,960]" />
  <node text="评价" class="android.widget.Button" clickable="true" bounds="[880,890][1040,970]" />
</hierarchy>
"""

# Same pending list but the target shop is absent — the fallback path must
# back out of it instead of tapping an unrelated order's CTA.
_PENDING_LIST_OTHER_SHOP_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node text="待评价(1)" class="android.widget.TextView" clickable="true" bounds="[60,300][400,380]" />
  <node text="味香斋(雁荡路店)" class="android.widget.TextView" clickable="false" bounds="[40,600][600,660]" />
  <node text="评价" class="android.widget.Button" clickable="true" bounds="[880,590][1040,670]" />
</hierarchy>
"""

# A warm start on an unrelated inner page (消息): no 我的 tab, no search bar,
# no editor chrome — navigation must BACK-unwind to home before searching.
_OTHER_TAB_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node text="消息" class="android.widget.TextView" clickable="false" bounds="[480,120][600,180]" />
  <node text="系统通知" class="android.widget.TextView" clickable="false" bounds="[60,300][300,360]" />
  <node text="互动消息" class="android.widget.TextView" clickable="false" bounds="[60,420][300,480]" />
</hierarchy>
"""


def test_uia2_pending_review_row_rect_anchors_cta_to_shop_row():
    from automation_app_dianping.session import pending_review_row_rect

    rect = pending_review_row_rect(_PENDING_LIST_XML, "赤上烧肉酒场(娄山关路店)")
    assert rect == {"x": 880, "y": 590, "width": 160, "height": 80}

    # The second row's CTA must be returned for the other shop.
    other = pending_review_row_rect(_PENDING_LIST_XML, "细记港九宵夜大牌档(虹桥南丰城店)")
    assert other == {"x": 880, "y": 890, "width": 160, "height": 80}

    assert pending_review_row_rect(_PENDING_LIST_XML, "不存在的店") is None
    assert pending_review_row_rect("", "赤上烧肉酒场") is None


def test_uia2_navigate_prefers_pending_review_entry(monkeypatch):
    # 我的 tab → pending list → shop CTA → editor. The first dump is the
    # home page (has the 我的 tab label), each click advances the page.
    pages = [
        _HOME_WITH_TABS_XML,
        _PENDING_LIST_XML,
        _PENDING_LIST_XML,
        _EDITOR_ADD_PHOTO_XML,
        _EDITOR_ADD_PHOTO_XML,
    ]

    class Device:
        def __init__(self):
            self.clicks = []
            self.step = 0
            self.presses = []

        def dump_hierarchy(self):
            return pages[min(self.step, len(pages) - 1)]

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))
            self.step = min(self.step + 1, len(pages) - 1)

        def press(self, key):
            self.presses.append(key)

    device = Device()
    kit = FakeKitUia2()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="赤上烧肉酒场(娄山关路店)",
        write_selector=('uiautomator:new UiSelector().text("写评价")',),
        search_bar=("id:com.dianping.v1:id/title_search_bar",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
    )

    assert result.success, result.message
    assert "via 我的/待评价" in result.message
    # CTA centre: (880+1040)//2, (590+670)//2
    assert (960, 630) in device.clicks
    # Search path never engaged: no type_text through the kit.
    assert "type_text" not in [name for name, _ in kit.calls]


def test_uia2_navigate_falls_back_to_search_when_shop_not_pending(monkeypatch):
    # The pending list exists but only carries an unrelated shop; the flow
    # must press BACK out of it and complete navigation via home search.
    pages = [
        _HOME_WITH_TABS_XML,
        _PENDING_LIST_OTHER_SHOP_XML,  # 我的 tab tapped → pending list
        _PENDING_LIST_OTHER_SHOP_XML,  # entry tap lands on the same list
        _HOME_WITH_TABS_XML,           # BACK unwinds to home, search proceeds
        _SEARCH_BOX_XML,
        _RESULTS_XML,
        _SHOP_WRITE_REVIEW_XML,
        _EDITOR_ADD_PHOTO_XML,
    ]

    class Device:
        def __init__(self):
            self.clicks = []
            self.step = 0
            self.presses = []

        def dump_hierarchy(self):
            return pages[min(self.step, len(pages) - 1)]

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))
            self.step = min(self.step + 1, len(pages) - 1)

        def press(self, key):
            self.presses.append(key)
            self.step = min(self.step + 1, len(pages) - 1)

    device = Device()

    class Kit(FakeKitUia2):
        def execute_action(self, action_name, **kwargs):
            result = super().execute_action(action_name, **kwargs)
            if result.success and action_name in ("tap", "press_key"):
                device.step = min(device.step + 1, len(pages) - 1)
            return result

    kit = Kit()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="细记港九宵夜大牌档(虹桥南丰城店)",
        write_selector=('uiautomator:new UiSelector().text("写评价")',),
        search_bar=("id:com.dianping.v1:id/title_search_bar",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
        search_confirm=('uiautomator:new UiSelector().text("搜索")',),
        search_results_marker=('uiautomator:new UiSelector().text("商户")',),
        shop_result=('uiautomator:new UiSelector().textContains("细记港九")',),
    )

    assert result.success, result.message
    assert "via search" in result.message
    # The pending list was entered and then unwound with BACK.
    assert "back" in device.presses
    assert "type_text" in [name for name, _ in kit.calls]


def test_uia2_navigate_back_unwinds_warm_start_on_other_tab(monkeypatch):
    # Live 2026-10-16: a relaunch restored the app on an inner page; the
    # search-bar wait hard-failed there. Navigation must BACK-unwind to home,
    # then still try the preferred pending-review entry before searching.
    pages = [
        _OTHER_TAB_XML,
        _HOME_WITH_TABS_XML,           # BACK unwinds to home
        _PENDING_LIST_OTHER_SHOP_XML,  # 我的 tab tapped → pending list
        _PENDING_LIST_OTHER_SHOP_XML,  # entry tap lands on the same list
        _HOME_WITH_TABS_XML,           # BACK out: target shop not pending
        _SEARCH_BOX_XML,
        _RESULTS_XML,
        _SHOP_WRITE_REVIEW_XML,
        _EDITOR_ADD_PHOTO_XML,
    ]

    class Device:
        def __init__(self):
            self.clicks = []
            self.step = 0
            self.presses = []

        def dump_hierarchy(self):
            return pages[min(self.step, len(pages) - 1)]

        def click(self, x, y):
            self.clicks.append((int(x), int(y)))
            self.step = min(self.step + 1, len(pages) - 1)

        def press(self, key):
            self.presses.append(key)
            self.step = min(self.step + 1, len(pages) - 1)

    device = Device()

    class Kit(FakeKitUia2):
        # The kit wait fakes success for absent selectors (live 2026-10-17:
        # the 设置 page did exactly that), so the navigate code now gates the
        # search tap on a real dump parse — _marker_present_now — and this
        # fake needs no wait override at all. Taps advance the page.
        def execute_action(self, action_name, **kwargs):
            result = super().execute_action(action_name, **kwargs)
            if result.success and action_name in ("tap", "press_key"):
                device.step = min(device.step + 1, len(pages) - 1)
            return result

    kit = Kit()
    kit.driver = device
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._session.driver = device

    result = session.execute_action(
        "navigate_to_review_editor",
        shop_name="细记港九宵夜大牌档(虹桥南丰城店)",
        write_selector=('uiautomator:new UiSelector().text("写评价")',),
        search_bar=("id:com.dianping.v1:id/title_search_bar",),
        search_input=("id:com.dianping.v1:id/search_keyword_edit",),
        search_confirm=('uiautomator:new UiSelector().text("搜索")',),
        search_results_marker=('uiautomator:new UiSelector().text("商户")',),
        shop_result=('uiautomator:new UiSelector().textContains("细记港九")',),
    )

    assert result.success, result.message
    assert "via search" in result.message
    # One BACK for the unwind, one for backing out of the pending list.
    assert device.presses == ["back", "back"]
    assert "type_text" in [name for name, _ in kit.calls]
