from pathlib import Path

import pytest

from automation_core.drivers import ActionResult, ArtifactHandle, SessionInfo
from automation_app_dianping.live import LIVE_FLAG, build_live_workflow, live_enabled, require_live_enabled
from automation_app_dianping.storage import DraftRecord, DraftReview, DraftStore, ReviewRatings


class FakeSession:
    def __init__(self):
        self.info = SessionInfo(driver_name="fake", platform="android", identifier="live")

    def start(self):
        return None

    def stop(self):
        return None

    def execute_action(self, action_name, **kwargs):
        return ActionResult(success=True, message=action_name, data=kwargs)

    def capture_artifact(self, artifact_type, name):
        return ArtifactHandle(artifact_type=artifact_type, path=Path(name))


def test_live_enabled_defaults_false():
    assert live_enabled({}) is False
    assert live_enabled({LIVE_FLAG: "1"}) is True
    with pytest.raises(RuntimeError, match="live E2E disabled"):
        require_live_enabled({})


def test_publish_requires_the_uia2_driver():
    from automation_app_dianping.live import require_uia2_publish

    require_uia2_publish({LIVE_FLAG: "1"})
    require_uia2_publish({LIVE_FLAG: "1", "DIANPING_DRIVER": "uia2"})
    with pytest.raises(ValueError, match="requires DIANPING_DRIVER=uia2"):
        require_uia2_publish({LIVE_FLAG: "1", "DIANPING_DRIVER": "appium"})


def test_publish_guard_skips_an_injected_session_factory():
    from automation_app_dianping.live import require_uia2_publish

    require_uia2_publish({"DIANPING_DRIVER": "appium"}, session_factory=FakeSession)


def test_build_live_workflow_refuses_an_appium_publish(tmp_path: Path):
    content = "红烧肉肥而不腻，响油鳝丝很香，环境有烟火气，服务利落，值得再来。" * 4
    DraftStore(tmp_path).save(
        DraftRecord(
            id="live-appium",
            shop_url="https://www.dianping.com/shop/live1",
            shop_name="直播店",
            shop_slug="live1",
            draft=DraftReview(
                content=content, ratings=ReviewRatings(5, 4, 4), photos=[], status="edited"
            ),
        )
    )

    with pytest.raises(ValueError, match="requires DIANPING_DRIVER=uia2"):
        build_live_workflow(
            draft_id="live-appium",
            data_dir=str(tmp_path),
            env={LIVE_FLAG: "1", "DIANPING_DRIVER": "appium"},
        )


def test_build_live_workflow_requires_flag_and_runs_with_fake_session(tmp_path: Path):
    content = "红烧肉肥而不腻，响油鳝丝很香，环境有烟火气，服务利落，值得再来。" * 4
    draft = DraftRecord(
        id="live-1",
        shop_url="https://www.dianping.com/shop/live1",
        shop_name="直播店",
        shop_slug="live1",
        draft=DraftReview(
            content=content,
            ratings=ReviewRatings(5, 4, 4),
            photos=[],
            status="edited",
        ),
    )
    DraftStore(tmp_path).save(draft)

    with pytest.raises(RuntimeError):
        build_live_workflow(
            session_factory=FakeSession,
            draft_id="live-1",
            data_dir=str(tmp_path),
            env={},
        )

    workflow = build_live_workflow(
        session_factory=FakeSession,
        draft_id="live-1",
        data_dir=str(tmp_path),
        env={LIVE_FLAG: "1"},
    )
    result = workflow.run()
    assert result.success is True

def test_build_live_smoke_and_run_live_publish_params(tmp_path: Path, default_photo):
    from automation_app_dianping.live import build_live_smoke_workflow, run_live, LIVE_FLAG
    class S(FakeSession):
        def __init__(self):
            super().__init__()
            self.actions=[]
        def execute_action(self, action_name, **kwargs):
            self.actions.append((action_name, kwargs))
            return ActionResult(success=True, message=action_name, data=kwargs)
    holder={}
    def factory():
        s=S(); holder['s']=s; return s
    wf=build_live_smoke_workflow(session_factory=factory, env={LIVE_FLAG:'1'})
    assert wf.run().success
    content='红烧肉肥而不腻，响油鳝丝很香，环境有烟火气，服务利落，值得再来。'*4
    s=S()
    result=run_live(mode='publish', shop_name='店', content=content, session_factory=lambda:s, env={LIVE_FLAG:'1'})
    assert result.success
    pick = next(kwargs for name, kwargs in s.actions if name == "pick_photos")
    from automation_app_dianping.config import DEFAULT_REVIEW_PHOTO
    assert pick["photos"] == [str(DEFAULT_REVIEW_PHOTO)]


def _slider_solver_with_result(result):
    """Build the live slider bridge around a fake capability executor."""

    class FakeExecutor:
        def __init__(self):
            self.requests = []

        async def execute(self, request, context):
            self.requests.append(request)

            class _Result:
                success = result["success"]
                error_code = result.get("error_code")
                data = result["data"]

            return _Result()

    class FakeComposition:
        def __init__(self):
            self.capability_executor = FakeExecutor()

    from automation_app_dianping.live import _build_slider_solver

    composition = FakeComposition()
    import asyncio

    solve = _build_slider_solver(composition)
    return composition, solve, asyncio.run(solve(b"png-bytes"))


def test_slider_solver_bridge_passes_gap_x_from_slidex():
    _, _, solution = _slider_solver_with_result(
        {"success": True, "data": {"metadata": {"gap_x": 363, "distance_px": 363}}}
    )
    assert solution == {"gap_x": 363}


def test_slider_solver_bridge_prefers_explicit_offset():
    _, _, solution = _slider_solver_with_result(
        {"success": True, "data": {"gap_offset_px": 137, "metadata": {"gap_x": 363}}}
    )
    assert solution == {"gap_offset_px": 137}


def test_slider_solver_bridge_uses_distance_px_when_no_gap_x():
    _, _, solution = _slider_solver_with_result(
        {"success": True, "data": {"metadata": {"distance_px": 211}}}
    )
    assert solution == {"gap_x": 211}


def test_slider_solver_bridge_raises_without_any_offset():
    import pytest as _pytest

    with _pytest.raises(RuntimeError, match="no gap_x/gap_offset_px"):
        _slider_solver_with_result(
            {"success": True, "data": {"metadata": {"method": "contour"}}}
        )


def test_slider_solver_bridge_sends_android_screenshot_context():
    composition, _, _ = _slider_solver_with_result(
        {"success": True, "data": {"metadata": {"gap_x": 100}}}
    )
    request = composition.capability_executor.requests[0]
    assert request.parameters["context"] == "android_screenshot_bytes"
    assert request.parameters["challenge_type"] == "slider_captcha"
    assert request.parameters["image_bytes"] == b"png-bytes"

