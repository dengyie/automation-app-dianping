import json
from pathlib import Path

import pytest

from automation_core.drivers import ActionResult, ArtifactHandle, SessionInfo
from automation_runner import WorkflowContext, WorkflowOptions
from automation_app_dianping.workflow import (
    build_android_screenshot_visual_request,
    create_workflow,
    describe_optional_capabilities,
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
