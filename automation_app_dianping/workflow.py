from automation_runner.workflows import ManagedWorkflow, WorkflowStep, run_workflow_steps


def describe_optional_capabilities(visual_solver=None):
    return {
        "visual_challenges": "enabled" if visual_solver is not None else "disabled"
    }


def build_android_screenshot_visual_request(
    *,
    screenshot_bytes: bytes,
    provider: str = "auto",
    metadata=None,
):
    from slidex.vision import ChallengeType, VisionContext, VisualChallengeRequest

    return VisualChallengeRequest(
        challenge_type=ChallengeType.IMAGE_TEXT,
        context=VisionContext.ANDROID_SCREENSHOT_BYTES,
        image_bytes=screenshot_bytes,
        provider=provider,
        metadata=dict(metadata or {}),
    )


def visual_result_to_workflow_payload(
    result,
    *,
    task_id: str = None,
    prefer_native: bool = False,
):
    from slidex.integrations.automation_kit import (
        to_action_result,
        to_artifacts,
        to_events,
    )

    return {
        "action": to_action_result(result, prefer_native=prefer_native),
        "artifacts": to_artifacts(result, prefer_native=prefer_native),
        "events": to_events(result, task_id=task_id, prefer_native=prefer_native),
    }


def create_workflow(session_factory, context, options, visual_solver=None):
    return ManagedWorkflow(
        name=context.workflow_name,
        session_factory=session_factory,
        run_fn=lambda session: run_workflow_steps(
            session,
            [
                WorkflowStep.action(
                    "launch_app",
                    app_id=options.app_id or "com.dianping.v1",
                ),
                WorkflowStep.artifact("screenshot", "startup.png"),
            ],
        ),
    )
