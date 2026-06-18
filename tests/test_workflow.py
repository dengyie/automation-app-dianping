import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

from automation_core.drivers import ActionResult, ArtifactHandle, SessionInfo
from automation_runner import WorkflowContext, WorkflowOptions
from automation_app_dianping.workflow import (
    build_android_screenshot_visual_request,
    create_workflow,
    describe_optional_capabilities,
    solve_android_screenshot_visual_challenge,
    visual_result_to_workflow_payload,
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


def test_dianping_workflow_uses_public_runner_contract():
    workflow = create_workflow(
        session_factory=FakeSession,
        context=WorkflowContext(workflow_name="dianping-android", live=False),
        options=WorkflowOptions(app_id="com.dianping.v1"),
    )

    result = workflow.run()

    assert workflow.name == "dianping-android"
    assert result.success is True


def test_dianping_workflow_reports_visual_capability_flag():
    assert describe_optional_capabilities()["visual_challenges"] == "disabled"

    class FakeVisualSolver:
        pass

    assert (
        describe_optional_capabilities(visual_solver=FakeVisualSolver())[
            "visual_challenges"
        ]
        == "enabled"
    )


def test_create_workflow_accepts_visual_solver_without_changing_offline_flow():
    class FakeVisualSolver:
        pass

    workflow = create_workflow(
        session_factory=FakeSession,
        context=WorkflowContext(workflow_name="dianping-android", live=False),
        options=WorkflowOptions(app_id="com.dianping.v1"),
        visual_solver=FakeVisualSolver(),
    )

    result = workflow.run()

    assert result.success is True


def test_visual_helpers_are_lazy_and_cover_default_offline_contract(monkeypatch):
    slidex = types.ModuleType("slidex")
    vision = types.ModuleType("slidex.vision")
    integrations = types.ModuleType("slidex.integrations")
    automation_kit = types.ModuleType("slidex.integrations.automation_kit")

    class ChallengeType:
        IMAGE_TEXT = "image_text"

    class VisionContext:
        ANDROID_SCREENSHOT_BYTES = "android_screenshot_bytes"

    class VisualChallengeRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    vision.ChallengeType = ChallengeType
    vision.VisionContext = VisionContext
    vision.VisualChallengeRequest = VisualChallengeRequest
    automation_kit.to_action_result = lambda result, prefer_native=False: {
        "success": result["success"]
    }
    automation_kit.to_artifacts = lambda result, prefer_native=False: [
        {"artifact_type": "ocr", "path": "result.json"}
    ]
    automation_kit.to_events = lambda result, task_id=None, prefer_native=False: [
        {"event_type": "task.end", "task_id": task_id}
    ]

    monkeypatch.setitem(sys.modules, "slidex", slidex)
    monkeypatch.setitem(sys.modules, "slidex.vision", vision)
    monkeypatch.setitem(sys.modules, "slidex.integrations", integrations)
    monkeypatch.setitem(
        sys.modules,
        "slidex.integrations.automation_kit",
        automation_kit,
    )

    request = build_android_screenshot_visual_request(
        screenshot_bytes=b"fake",
        provider="fake",
    )
    payload = visual_result_to_workflow_payload({"success": True}, task_id="task-1")

    assert request.challenge_type == "image_text"
    assert request.context == "android_screenshot_bytes"
    assert request.image_bytes == b"fake"
    assert payload["action"]["success"] is True
    assert payload["events"][0]["task_id"] == "task-1"

    class FakeVisualSolver:
        async def solve(self, visual_request):
            assert visual_request.context == "android_screenshot_bytes"
            assert visual_request.image_bytes == b"fake"
            return {"success": True}

    visual_payload = asyncio.run(
        solve_android_screenshot_visual_challenge(
            visual_solver=FakeVisualSolver(),
            screenshot_bytes=b"fake",
            task_id="task-2",
        )
    )

    assert visual_payload["action"]["success"] is True
    assert visual_payload["events"][0]["task_id"] == "task-2"


def test_build_android_screenshot_visual_request_uses_slidex_contract():
    pytest.importorskip("slidex")

    request = build_android_screenshot_visual_request(
        screenshot_bytes=b"fake-png",
        provider="fake",
        metadata={"scene": "startup"},
    )

    from slidex.vision import ChallengeType, VisionContext

    assert request.challenge_type == ChallengeType.IMAGE_TEXT
    assert request.context == VisionContext.ANDROID_SCREENSHOT_BYTES
    assert request.image_bytes == b"fake-png"
    assert request.metadata["scene"] == "startup"


def test_visual_result_to_workflow_payload_returns_json_safe_shapes():
    pytest.importorskip("slidex")

    from slidex.vision import ChallengeType, VisualChallengeResult

    result = VisualChallengeResult(
        success=True,
        challenge_type=ChallengeType.IMAGE_TEXT,
        provider="fake",
        metadata={"text": "dianping"},
    )

    payload = visual_result_to_workflow_payload(result, task_id="task-1")

    assert payload["action"]["success"] is True
    assert payload["events"][-1]["event_type"] == "task.end"
    assert payload["events"][-1]["payload"]["metadata"]["text"] == "dianping"
    json.dumps(payload)


def test_solve_android_screenshot_visual_challenge_uses_provider_callback():
    pytest.importorskip("slidex")

    from slidex.vision import ChallengeType, VisualChallengeResult

    class FakeVisualSolver:
        def __init__(self):
            self.requests = []

        async def solve(self, request):
            self.requests.append(request)
            return VisualChallengeResult(
                success=True,
                challenge_type=request.challenge_type,
                provider="fake",
                metadata={"scene": request.metadata["scene"]},
            )

    solver = FakeVisualSolver()

    payload = asyncio.run(
        solve_android_screenshot_visual_challenge(
            visual_solver=solver,
            screenshot_provider=lambda: b"fake-png",
            task_id="visual-1",
            metadata={"scene": "startup"},
        )
    )

    assert solver.requests[0].challenge_type == ChallengeType.IMAGE_TEXT
    assert solver.requests[0].image_bytes == b"fake-png"
    assert payload["action"]["success"] is True
    assert payload["events"][-1]["payload"]["metadata"]["scene"] == "startup"


def test_solve_android_screenshot_visual_challenge_returns_none_without_solver():
    payload = asyncio.run(
        solve_android_screenshot_visual_challenge(
            visual_solver=None,
            screenshot_bytes=b"fake",
        )
    )

    assert payload is None


def test_solve_android_screenshot_visual_challenge_requires_screenshot_input():
    class FakeVisualSolver:
        async def solve(self, request):
            return {"success": True}

    with pytest.raises(ValueError, match="screenshot_bytes or screenshot_provider"):
        asyncio.run(
            solve_android_screenshot_visual_challenge(
                visual_solver=FakeVisualSolver(),
            )
        )
