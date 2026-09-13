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
