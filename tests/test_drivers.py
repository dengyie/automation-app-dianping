"""Driver dispatch and uia2 session tests (offline, fake devices only)."""
from pathlib import Path

import pytest

from automation_core.drivers import ActionResult, ArtifactHandle, SessionInfo

from automation_app_dianping.config import DianpingDeviceConfig
from automation_app_dianping.session import (
    DianpingAppiumSession,
    DianpingUia2Session,
    build_session_factory,
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


def test_build_session_factory_dispatches_appium_by_default():
    factory = build_session_factory(env={}, driver_factory=lambda: object())

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


def test_uia2_rate_uses_label_anchor_geometry(monkeypatch):
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


class _FakeGalleryDevice:
    """Records push/shell calls; shell() drives the index lifecycle."""

    def __init__(self, name, tops_after=2):
        self.sync = self
        self.pushed = []
        self.shell_calls = []
        self._name = name
        self._tops_after = tops_after

    class _Widget:
        exists = True

        def click(self):
            return True

    def __call__(self, **kwargs):
        # u2 widget lookup used by _pick_photo_tile
        return self._Widget()

    def push(self, local, remote):
        self.pushed.append((local, remote))
        self.pushed_bytes = Path(local).read_bytes()

    def shell(self, args):
        self.shell_calls.append(list(args))
        joined = " ".join(args)
        if "--where" in joined and self._name in joined:
            # index lifecycle: absent → present-but-NULL → real row
            n = len([c for c in self.shell_calls if "--where" in c])
            if n <= self._tops_after:
                return ""
            if n <= self._tops_after + 1:
                return "Row: 0 _display_name=%s, datetaken=NULL" % self._name
            return "Row: 0 _display_name=%s, datetaken=1789859011371" % self._name
        if "--sort" in joined and "DESC" in joined:
            return (
                "Row: 0 _display_name=%s, datetaken=1789859011371\n"
                "Row: 1 _display_name=other.jpg, datetaken=1" % self._name
            )
        return "Broadcasting: Intent { act=MEDIA_SCANNER_SCAN_FILE }"


def _write_jpeg(tmp_path, name="gni.jpg"):
    from PIL import Image

    path = tmp_path / name
    Image.new("RGB", (4, 4)).save(path, "JPEG")
    return path


def test_uia2_pick_photos_stages_then_selects(monkeypatch, tmp_path):
    import io

    from PIL import Image

    import automation_app_dianping.session as session_module

    photo = _write_jpeg(tmp_path)
    name = "IMG99999999_gni.jpg"
    device = _FakeGalleryDevice(name)
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
        add_selector=('uiautomator:new UiSelector().textContains("添加图")',),
        thumbnail_selector=('uiautomator:new UiSelector().className("android.widget.ImageView")',),
        confirm_selector=('uiautomator:new UiSelector().textContains("下一步")',),
    )

    assert result.success, result.message
    assert len(device.pushed) == 1
    remote = device.pushed[0][1]
    assert remote.endswith("DCIM/Camera/" + name)
    # staged bytes carry a current EXIF capture time; source file untouched
    source_exif = Image.open(io.BytesIO(photo.read_bytes())).getexif()
    staged_exif = Image.open(io.BytesIO(device.pushed_bytes)).getexif()
    assert source_exif.get(36867) is None
    assert staged_exif.get(36867) is not None
    scan = [c for c in device.shell_calls if c[:1] == ["am"]][0]
    assert "MEDIA_SCANNER_SCAN_FILE" in " ".join(scan)
    # picker taps only happened after prep succeeded
    assert any("添加图" in str(c) for c in kit.calls if c[0] == "tap")


def test_uia2_pick_photos_fails_when_not_indexed_first(monkeypatch, tmp_path):
    """Indexed but not topping the DESC order → refuse to select."""
    import automation_app_dianping.session as session_module

    photo = _write_jpeg(tmp_path, "late.jpg")
    name = "IMG99999999_late.jpg"
    device = _FakeGalleryDevice(name)
    # never let the DESC probe see the target on top
    real_shell = device.shell

    def shell(args):
        if "--sort" in " ".join(args):
            return "Row: 0 _display_name=other.jpg, datetaken=9"
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
