from pathlib import Path

from automation_core.drivers import ActionResult, ArtifactHandle, SessionInfo
from automation_runner import WorkflowContext, WorkflowOptions
from automation_app_dianping.workflow import create_workflow


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
