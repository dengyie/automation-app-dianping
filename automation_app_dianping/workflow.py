from automation_runner.workflows import ManagedWorkflow, WorkflowStep, run_workflow_steps

DEFAULT_APP_ID = "com.dianping.v1"
DEFAULT_WORKFLOW_NAME = "dianping-android"


def build_android_screenshot_capability_request(
    *,
    screenshot_bytes: bytes,
    provider: str = "auto",
    metadata=None,
    run_id: str = None,
    task_id: str = None,
):
    """Assemble a public capability request. No provider internals."""
    from automation_core.capabilities import CapabilityRequest

    request_metadata = {}
    if run_id is not None:
        request_metadata["run_id"] = run_id
    if task_id is not None:
        request_metadata["task_id"] = task_id

    return CapabilityRequest(
        capability="visual.challenge",
        operation="solve",
        parameters={
            "challenge_type": "image_text",
            "context": "android_screenshot_bytes",
            "image_bytes": screenshot_bytes,
            "provider": provider,
            "metadata": dict(metadata or {}),
        },
        metadata=request_metadata,
    )


async def _execute_capability(capability_executor, request, run_id=None, task_id=None):
    """Support both V1 aexecute(request) and V2 execute(request, context)."""
    import inspect

    aexecute = getattr(capability_executor, "aexecute", None)
    if callable(aexecute):
        result = aexecute(request)
        if inspect.isawaitable(result):
            return await result
        return result

    execute = getattr(capability_executor, "execute", None)
    if not callable(execute):
        raise TypeError("capability_executor must provide execute or aexecute")

    # V2 executor requires ExecutionContext.
    try:
        from automation_core.execution import ExecutionContext
    except ImportError:
        result = execute(request)
        if inspect.isawaitable(result):
            return await result
        return result

    context = ExecutionContext(
        run_id=run_id or "dianping-run",
        task_id=task_id,
        workflow_name=DEFAULT_WORKFLOW_NAME,
    )
    result = execute(request, context)
    if inspect.isawaitable(result):
        return await result
    return result


async def solve_android_screenshot_capability(
    *,
    capability_executor,
    screenshot_bytes: bytes = None,
    screenshot_provider=None,
    provider: str = "auto",
    metadata=None,
    run_id: str = None,
    task_id: str = None,
):
    """Execute visual.challenge through an injected public executor."""
    if capability_executor is None:
        return None

    image_bytes = screenshot_bytes
    if image_bytes is None and screenshot_provider is not None:
        image_bytes = screenshot_provider()
    if image_bytes is None:
        raise ValueError("screenshot_bytes or screenshot_provider is required")

    request = build_android_screenshot_capability_request(
        screenshot_bytes=image_bytes,
        provider=provider,
        metadata=metadata,
        run_id=run_id,
        task_id=task_id,
    )
    return await _execute_capability(
        capability_executor,
        request,
        run_id=run_id,
        task_id=task_id,
    )


def _string_param(parameters, key, default=None):
    value = parameters.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("%s must be a string" % key)
    cleaned = value.strip()
    return cleaned or None


def _ratings_from_parameters(parameters):
    ratings = parameters.get("ratings") or {}
    if not isinstance(ratings, dict):
        raise ValueError("ratings must be an object")
    result = {}
    for key in ("taste", "environment", "service"):
        value = ratings.get(key)
        if value is None:
            continue
        if not isinstance(value, int) or value < 1 or value > 5:
            raise ValueError("ratings.%s must be an integer between 1 and 5" % key)
        result[key] = value
    return result


def _photos_from_parameters(parameters):
    photos = parameters.get("photos") or []
    if not isinstance(photos, list):
        raise ValueError("photos must be a list")
    cleaned = []
    for item in photos:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("photos entries must be non-blank strings")
        cleaned.append(item.strip())
    return cleaned


def build_publish_steps(options, selectors):
    parameters = dict(getattr(options, "parameters", None) or {})
    shop_name = _string_param(parameters, "shop_name")
    content = _string_param(parameters, "content")
    if not shop_name:
        raise ValueError("publish mode requires parameters.shop_name")
    if not content:
        raise ValueError("publish mode requires parameters.content")

    ratings = _ratings_from_parameters(parameters)
    photos = _photos_from_parameters(parameters)
    app_id = options.app_id or DEFAULT_APP_ID

    steps = [
        WorkflowStep.action("launch_app", app_id=app_id),
        WorkflowStep.artifact("screenshot", "publish-launch.png"),
        WorkflowStep.action(
            "wait_for_element",
            selector=selectors.search_bar,
            timeout=10.0,
        ),
        WorkflowStep.action("tap", selector=selectors.search_bar),
        WorkflowStep.action(
            "type_text",
            selector=selectors.search_input,
            text=shop_name,
        ),
        WorkflowStep.action(
            "wait_for_element",
            selector=selectors.shop_result,
            timeout=10.0,
        ),
        WorkflowStep.action("tap", selector=selectors.shop_result),
        WorkflowStep.action(
            "wait_for_element",
            selector=selectors.write_review,
            timeout=10.0,
        ),
        WorkflowStep.action("tap", selector=selectors.write_review),
        WorkflowStep.action(
            "type_text",
            selector=selectors.review_input,
            text=content,
        ),
    ]

    if ratings:
        steps.append(
            WorkflowStep.action(
                "wait_for_element",
                selector=selectors.rating_panel,
                timeout=5.0,
            )
        )
        for key, value in ratings.items():
            selector = selectors.rating_star(key, value)
            if selector:
                steps.append(WorkflowStep.action("tap", selector=selector))

    if photos:
        steps.append(WorkflowStep.action("tap", selector=selectors.add_photo))
        for index, photo in enumerate(photos):
            steps.append(
                WorkflowStep.action(
                    "tap",
                    selector=selectors.photo_thumbnail,
                    photo_path=photo,
                    photo_index=index,
                )
            )
        steps.append(WorkflowStep.action("tap", selector=selectors.photo_confirm))

    steps.extend(
        [
            WorkflowStep.action("tap", selector=selectors.submit),
            WorkflowStep.artifact("screenshot", "publish-submit.png"),
            WorkflowStep.action(
                "wait_for_element",
                selector=selectors.success,
                timeout=10.0,
            ),
            WorkflowStep.artifact("screenshot", "publish-success.png"),
        ]
    )
    return steps


def build_smoke_steps(options):
    app_id = options.app_id or DEFAULT_APP_ID
    return [
        WorkflowStep.action("launch_app", app_id=app_id),
        WorkflowStep.artifact("screenshot", "startup.png"),
    ]


def create_workflow(session_factory, context, options, capability_executor=None):
    """Create a Dianping workflow.

    capability_executor is accepted for composition-root injection. Smoke/publish
    steps currently use action/artifact primitives; visual challenges use helper
    APIs with the injected executor.
    """
    del capability_executor

    parameters = dict(getattr(options, "parameters", None) or {})
    mode = (_string_param(parameters, "mode", "smoke") or "smoke").lower()

    if mode == "publish":
        from automation_app_dianping.config import default_selectors

        steps = build_publish_steps(options, default_selectors())
    elif mode == "smoke":
        steps = build_smoke_steps(options)
    else:
        raise ValueError("unsupported workflow mode: %s" % mode)

    return ManagedWorkflow(
        name=context.workflow_name or DEFAULT_WORKFLOW_NAME,
        session_factory=session_factory,
        run_fn=lambda session: run_workflow_steps(session, steps),
    )
