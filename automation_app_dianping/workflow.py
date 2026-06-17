from automation_runner.workflows import ManagedWorkflow, WorkflowStep, run_workflow_steps


def create_workflow(session_factory, context, options):
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
