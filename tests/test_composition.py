import inspect
import types

import pytest
from pathlib import Path

from automation_core.drivers import ActionResult, ArtifactHandle, SessionInfo
from automation_runner import WorkflowContext, WorkflowOptions

from automation_app_dianping import composition as composition_module
from automation_app_dianping.composition import (
    build_composition,
    create_workflow_from_composition,
)


class FakeSession:
    def __init__(self):
        self.info = SessionInfo(
            driver_name="fake-dianping",
            platform="android",
            identifier="dianping-app",
        )

    def start(self):
        return None

    def stop(self):
        return None

    def execute_action(self, action_name, **kwargs):
        return ActionResult(success=True, message=action_name, data=kwargs)

    def capture_artifact(self, artifact_type, name):
        return ArtifactHandle(artifact_type=artifact_type, path=Path(name))


def test_build_composition_without_slidex_uses_public_capability_surface():
    composition = build_composition(enable_slidex=False)

    assert composition.enable_slidex is False
    assert composition.capability_registry is not None
    assert composition.capability_executor is not None


def test_build_composition_requires_slidex_only_when_enabled(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("slidex"):
            raise ImportError("slidex missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with pytest.raises(ImportError, match="requires slidex"):
        build_composition(enable_slidex=True)


def test_create_workflow_from_composition_runs_offline():
    composition = build_composition(enable_slidex=False)
    workflow = create_workflow_from_composition(
        composition,
        session_factory=FakeSession,
        context=WorkflowContext(workflow_name="dianping-android", live=False),
        options=WorkflowOptions(app_id="com.dianping.v1"),
    )
    result = workflow.run()
    assert result.success is True


def test_composition_module_is_only_slidex_registration_point():
    import automation_app_dianping.workflow as workflow_module

    source = inspect.getsource(composition_module)
    assert "SlidexVisualCapability" in source
    assert "slidex" not in inspect.getsource(workflow_module)


def test_require_capabilities_missing_module(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "automation_core.capabilities" or name.startswith("automation_core.capabilities"):
            raise ImportError("no capabilities")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with pytest.raises(ImportError, match="capability contracts are required"):
        composition_module._require_capabilities()



def test_build_composition_accepts_injected_executor_and_registers_slidex(monkeypatch):
    class FakeRegistry:
        def __init__(self):
            self.providers = []

        def register(self, provider, replace=False):
            if replace is False and self.providers:
                raise TypeError("replace required")
            self.providers.append(provider)

    class FakeProvider:
        def __init__(self, visual_solver=None):
            self.visual_solver = visual_solver

    fake_module = types.ModuleType("slidex.integrations.automation_kit")
    fake_module.SlidexVisualCapability = FakeProvider
    monkeypatch.setitem(__import__("sys").modules, "slidex", types.ModuleType("slidex"))
    monkeypatch.setitem(__import__("sys").modules, "slidex.integrations", types.ModuleType("slidex.integrations"))
    monkeypatch.setitem(
        __import__("sys").modules,
        "slidex.integrations.automation_kit",
        fake_module,
    )

    registry = FakeRegistry()
    sentinel = object()
    composition = build_composition(
        enable_slidex=True,
        visual_solver="solver",
        capability_registry=registry,
        capability_executor=sentinel,
    )
    assert composition.capability_executor is sentinel
    assert composition.enable_slidex is True
    assert registry.providers and registry.providers[0].visual_solver == "solver"


def test_build_composition_register_replace_type_error_path(monkeypatch):
    class FakeRegistry:
        def __init__(self):
            self.calls = []

        def register(self, provider, replace=False):
            self.calls.append(replace)
            if not replace:
                raise TypeError("replace required")

    class FakeProvider:
        def __init__(self, visual_solver=None):
            self.visual_solver = visual_solver

    import types
    import sys

    fake_module = types.ModuleType("slidex.integrations.automation_kit")
    fake_module.SlidexVisualCapability = FakeProvider
    monkeypatch.setitem(sys.modules, "slidex", types.ModuleType("slidex"))
    monkeypatch.setitem(sys.modules, "slidex.integrations", types.ModuleType("slidex.integrations"))
    monkeypatch.setitem(sys.modules, "slidex.integrations.automation_kit", fake_module)

    registry = FakeRegistry()
    composition = build_composition(
        enable_slidex=True,
        capability_registry=registry,
        capability_executor=object(),
    )
    assert composition.enable_slidex is True
    assert registry.calls == [False, True]


def test_build_composition_register_unexpected_error_is_not_swallowed(monkeypatch):
    class FakeRegistry:
        def register(self, provider, replace=False):
            raise RuntimeError("registry broken")

    class FakeProvider:
        def __init__(self, visual_solver=None):
            self.visual_solver = visual_solver

    import types
    import sys

    fake_module = types.ModuleType("slidex.integrations.automation_kit")
    fake_module.SlidexVisualCapability = FakeProvider
    monkeypatch.setitem(sys.modules, "slidex", types.ModuleType("slidex"))
    monkeypatch.setitem(sys.modules, "slidex.integrations", types.ModuleType("slidex.integrations"))
    monkeypatch.setitem(sys.modules, "slidex.integrations.automation_kit", fake_module)

    with pytest.raises(RuntimeError, match="registry broken"):
        build_composition(
            enable_slidex=True,
            capability_registry=FakeRegistry(),
            capability_executor=object(),
        )
