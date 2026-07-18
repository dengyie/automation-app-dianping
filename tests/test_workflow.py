import asyncio
import inspect
from pathlib import Path

import pytest

from automation_core.drivers import ActionResult, ArtifactHandle, SessionInfo
from automation_runner import WorkflowContext, WorkflowOptions
from automation_app_dianping.workflow import (
    build_android_screenshot_capability_request,
    build_publish_steps,
    create_capability_steps,
    create_workflow,
    solve_android_screenshot_capability,
)
from automation_app_dianping.config import default_selectors


class FakeSession:
    def __init__(self):
        self.info = SessionInfo(
            driver_name="fake-dianping",
            platform="android",
            identifier="dianping-app",
        )
        self.actions = []

    def start(self):
        return None

    def stop(self):
        return None

    def execute_action(self, action_name, **kwargs):
        self.actions.append((action_name, kwargs))
        return ActionResult(success=True, message=action_name, data=kwargs)

    def capture_artifact(self, artifact_type, name):
        return ArtifactHandle(artifact_type=artifact_type, path=Path(name))


def test_dianping_smoke_workflow_uses_public_runner_contract():
    workflow = create_workflow(
        session_factory=FakeSession,
        context=WorkflowContext(workflow_name="dianping-android", live=False),
        options=WorkflowOptions(app_id="com.dianping.v1"),
    )

    result = workflow.run()

    assert workflow.name == "dianping-android"
    assert result.success is True
    assert any(action.message == "launch_app" for action in result.actions)


def test_build_android_screenshot_capability_request_uses_platform_contract_only():
    request = build_android_screenshot_capability_request(
        screenshot_bytes=b"fake-png",
        provider="auto",
        metadata={"scene": "startup"},
        run_id="run-1",
        task_id="task-1",
    )

    assert request.capability == "visual.challenge"
    assert request.operation == "solve"
    assert request.parameters["challenge_type"] == "image_text"
    assert request.parameters["context"] == "android_screenshot_bytes"
    assert request.parameters["image_bytes"] == b"fake-png"
    assert request.parameters["metadata"]["scene"] == "startup"
    assert request.metadata == {"run_id": "run-1", "task_id": "task-1"}


def test_create_capability_steps_uses_platform_request_contract():
    steps = create_capability_steps(screenshot_bytes=b"fake-png")

    assert steps[0].kind == "capability"
    assert steps[0].request.parameters["image_bytes"] == b"fake-png"


def test_solve_android_screenshot_capability_returns_none_without_executor():
    result = asyncio.run(
        solve_android_screenshot_capability(
            capability_executor=None,
            screenshot_bytes=b"fake",
        )
    )

    assert result is None


def test_solve_android_screenshot_capability_uses_screenshot_callback():
    class FakeExecutor:
        def __init__(self):
            self.requests = []

        async def aexecute(self, request):
            self.requests.append(request)
            from automation_core.capabilities import CapabilityResult

            return CapabilityResult(success=True, provider="fake")

    executor = FakeExecutor()
    result = asyncio.run(
        solve_android_screenshot_capability(
            capability_executor=executor,
            screenshot_provider=lambda: b"fake-png",
            task_id="task-1",
        )
    )

    assert result.success is True
    assert executor.requests[0].parameters["image_bytes"] == b"fake-png"
    assert executor.requests[0].metadata["task_id"] == "task-1"


def test_solve_android_screenshot_capability_requires_screenshot_input():
    class FakeExecutor:
        async def aexecute(self, request):
            return request

    with pytest.raises(ValueError, match="screenshot_bytes or screenshot_provider"):
        asyncio.run(
            solve_android_screenshot_capability(
                capability_executor=FakeExecutor(),
            )
        )


def test_dianping_workflow_exposes_only_generic_visual_capability_surface():
    import automation_app_dianping.workflow as module

    assert "visual_solver" not in inspect.signature(module.create_workflow).parameters
    assert "capability_executor" in inspect.signature(module.create_workflow).parameters
    for retired_name in [
        "describe_optional_capabilities",
        "build_android_screenshot_visual_request",
        "visual_result_to_workflow_payload",
        "solve_android_screenshot_visual_challenge",
    ]:
        assert not hasattr(module, retired_name)


def test_publish_workflow_declares_business_success_path():
    session = FakeSession()
    content = "红烧肉肥而不腻，响油鳝丝很香，葱油拌面落胃，环境有烟火气，适合三五好友再来。" * 3
    workflow = create_workflow(
        session_factory=lambda: session,
        context=WorkflowContext(workflow_name="dianping-publish", live=False),
        options=WorkflowOptions(
            app_id="com.dianping.v1",
            parameters={
                "mode": "publish",
                "shop_name": "老上海本帮菜",
                "content": content,
                "ratings": {"taste": 5, "environment": 4, "service": 4},
                "photos": ["data/photos/mock-shop-001/dish1.jpg"],
                "allow_photos": True,
            },
        ),
    )

    result = workflow.run()

    assert result.success is True
    action_names = [action.message for action in result.actions]
    assert action_names[0] == "launch_app"
    assert "type_text" in action_names
    assert "rate" in action_names
    assert "pick_photos" in action_names
    assert any(action.message == "wait_for_element" for action in result.actions)

    rate_actions = [kwargs for name, kwargs in session.actions if name == "rate"]
    assert any(item.get("dimension") == "taste" and item.get("value") == 5 for item in rate_actions)
    assert all(item.get("fallback_action") == "tap" for item in rate_actions)

    pick = next(kwargs for name, kwargs in session.actions if name == "pick_photos")
    assert pick["photos"] == ["data/photos/mock-shop-001/dish1.jpg"]
    assert pick["fallback_action"] == "tap"
    assert isinstance(pick["fallback_steps"], list) and pick["fallback_steps"]


def test_publish_steps_require_business_fields():
    options = WorkflowOptions(parameters={"mode": "publish"})
    with pytest.raises(ValueError, match="shop_name"):
        build_publish_steps(options, default_selectors())


def test_create_workflow_rejects_unknown_mode():
    with pytest.raises(ValueError, match="unsupported workflow mode"):
        create_workflow(
            session_factory=FakeSession,
            context=WorkflowContext(workflow_name="dianping-android", live=False),
            options=WorkflowOptions(parameters={"mode": "hack"}),
        )


def test_solve_android_screenshot_capability_supports_v2_execute_context():
    class FakeExecutor:
        def __init__(self):
            self.seen = []

        async def execute(self, request, context):
            self.seen.append((request, context))
            from automation_core.capabilities import CapabilityResult

            return CapabilityResult(success=True, provider="v2")

    executor = FakeExecutor()
    result = asyncio.run(
        solve_android_screenshot_capability(
            capability_executor=executor,
            screenshot_bytes=b"png",
            run_id="run-9",
            task_id="task-9",
        )
    )
    assert result.success is True
    assert executor.seen[0][0].parameters["image_bytes"] == b"png"
    assert executor.seen[0][1].run_id == "run-9"
    assert executor.seen[0][1].task_id == "task-9"


def test_solve_android_screenshot_capability_rejects_invalid_executor():
    class Broken:
        pass

    with pytest.raises(TypeError, match="execute or aexecute"):
        asyncio.run(
            solve_android_screenshot_capability(
                capability_executor=Broken(),
                screenshot_bytes=b"png",
            )
        )


def test_publish_steps_validate_content_ratings_and_photos():
    selectors = default_selectors()
    with pytest.raises(ValueError, match="content"):
        build_publish_steps(
            WorkflowOptions(parameters={"mode": "publish", "shop_name": "shop"}),
            selectors,
        )
    with pytest.raises(ValueError, match="ratings must be an object"):
        build_publish_steps(
            WorkflowOptions(
                parameters={
                    "mode": "publish",
                    "shop_name": "shop",
                    "content": "内容足够长" * 40,
                    "ratings": "bad",
                }
            ),
            selectors,
        )
    with pytest.raises(ValueError, match="photos must be a list"):
        build_publish_steps(
            WorkflowOptions(
                parameters={
                    "mode": "publish",
                    "shop_name": "shop",
                    "content": "内容足够长" * 40,
                    "photos": "bad",
                }
            ),
            selectors,
        )
    with pytest.raises(ValueError, match="photos entries"):
        build_publish_steps(
            WorkflowOptions(
                parameters={
                    "mode": "publish",
                    "shop_name": "shop",
                    "content": "内容足够长" * 40,
                    "photos": [" "],
                }
            ),
            selectors,
        )


def test_string_param_type_errors_surface_in_mode_parsing():
    with pytest.raises(ValueError, match="mode must be a string"):
        create_workflow(
            session_factory=FakeSession,
            context=WorkflowContext(workflow_name="dianping-android", live=False),
            options=WorkflowOptions(parameters={"mode": 1}),
        )


def test_build_publish_steps_prefer_semantic_actions():
    content = "内容足够长用于构造步骤" * 20
    steps = build_publish_steps(
        WorkflowOptions(
            parameters={
                "mode": "publish",
                "shop_name": "店",
                "content": content,
                "ratings": {"taste": 4, "environment": 3, "service": 4},
                "photos": ["a.jpg", "b.jpg"],
                "allow_photos": True,
            }
        ),
        default_selectors(),
    )
    rate_steps = [step for step in steps if step.kind == "action" and step.name == "rate"]
    pick_steps = [step for step in steps if step.kind == "action" and step.name == "pick_photos"]

    assert len(rate_steps) == 3
    assert {step.parameters["dimension"] for step in rate_steps} == {"taste", "environment", "service"}
    assert all(step.parameters.get("fallback_action") == "tap" for step in rate_steps)

    assert len(pick_steps) == 1
    assert pick_steps[0].parameters["photos"] == ["a.jpg", "b.jpg"]
    assert pick_steps[0].parameters["fallback_action"] == "tap"
    assert isinstance(pick_steps[0].parameters["fallback_steps"], list)
    assert pick_steps[0].parameters["fallback_steps"][0]["action"] == "tap"


def test_dianping_capability_runs_through_platform_executor_and_slidex_adapter():
    pytest.importorskip("slidex")
    from slidex.integrations.automation_kit import SlidexVisualCapability
    from slidex.vision import VisualChallengeResult
    from automation_app_dianping.workflow import create_capability_steps
    from automation_core.capabilities import (
        CapabilityExecutor,
        CapabilityRegistry,
        CapabilityResolver,
    )
    from automation_runner.runtime import WorkflowRuntime

    class FakeVisualSolver:
        async def solve(self, request):
            assert request.metadata["run_id"] == "run-1"
            assert request.metadata["task_id"]
            return VisualChallengeResult(
                success=True,
                challenge_type=request.challenge_type,
                provider="fake-ocr",
                metadata={"text": "dianping"},
            )

    session = FakeSession()
    registry = CapabilityRegistry()
    registry.register(SlidexVisualCapability(visual_solver=FakeVisualSolver()))
    runtime = WorkflowRuntime(
        session_factory=lambda: session,
        capability_executor=CapabilityExecutor(CapabilityResolver(registry)),
        workflow_name="dianping-android",
        run_id="run-1",
    )
    result = runtime.run(create_capability_steps(screenshot_bytes=b"fake-png"))

    assert result.success is True
    assert result.steps[0].capability_result.provider == "slidex"
    assert result.steps[0].capability_result.data["metadata"]["text"] == "dianping"


def test_publish_steps_include_search_confirm_and_skip_photos_by_default():
    content = "内容足够长用于构造步骤" * 20
    steps = build_publish_steps(
        WorkflowOptions(
            parameters={
                "mode": "publish",
                "shop_name": "店",
                "content": content,
                "ratings": {"taste": 4, "environment": 3, "service": 4},
                "photos": ["a.jpg"],
            }
        ),
        default_selectors(),
    )
    names = [step.name for step in steps if step.kind == "action"]
    assert "confirm_search" in names
    assert "dismiss_dialogs" in names
    assert "pick_photos" not in names


def test_smoke_steps_include_dismiss_and_page_source():
    from automation_app_dianping.workflow import build_smoke_steps

    steps = build_smoke_steps(WorkflowOptions(app_id="com.dianping.v1"))
    names = [(step.kind, step.name) for step in steps]
    assert ("action", "dismiss_dialogs") in names
    assert ("artifact", "page_source") in names or any(
        s.kind == "artifact" and s.name == "page_source" for s in steps
    )
