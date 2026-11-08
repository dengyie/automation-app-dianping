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


def test_run_live_no_submit_stops_before_submit(tmp_path: Path):
    """no_submit runs dialogs/editor/rating/photos but never taps 发布."""
    from automation_app_dianping.live import run_live, LIVE_FLAG

    # Explicit photo (real file under tmp_path): the repo-local default photo
    # does not exist on CI, where the photos block would be skipped entirely.
    photo = tmp_path / "rehearsal.jpg"
    photo.write_bytes(b"\xff\xd8fake")

    class S(FakeSession):
        def __init__(self):
            super().__init__()
            self.actions = []
            self.artifacts = []

        def execute_action(self, action_name, **kwargs):
            self.actions.append((action_name, kwargs))
            return ActionResult(success=True, message=action_name, data=kwargs)

        def capture_artifact(self, artifact_type, name):
            # Artifact steps dispatch via capture_artifact, not execute_action.
            self.artifacts.append((artifact_type, name))
            return ArtifactHandle(artifact_type=artifact_type, path=Path(name))

    s = S()
    content = "红烧肉肥而不腻，响油鳝丝很香，环境有烟火气，服务利落，值得再来。" * 4
    result = run_live(
        mode="publish",
        shop_name="店",
        content=content,
        photos=[str(photo)],
        session_factory=lambda: s,
        env={LIVE_FLAG: "1"},
        no_submit=True,
    )
    assert result.success
    # The flow got all the way through photo picking…
    assert any(name == "pick_photos" for name, _ in s.actions)
    assert any(name == "rate" for name, _ in s.actions)
    # …but never tapped the externally-visible submit button, and captured
    # the rehearsal proof artifact as the final action.
    submit_taps = [
        kwargs
        for name, kwargs in s.actions
        if name == "tap" and "发布" in str(kwargs.get("selector"))
    ]
    assert submit_taps == []
    # Artifact steps dispatch via capture_artifact; the rehearsal proof is
    # the final artifact, and the run stopped before any post-submit capture.
    assert s.artifacts[-1] == ("screenshot", "publish-no-submit.png")


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



def test_dish_hint_from_content_lexicon_matches_real_drafts():
    from automation_app_dianping.imagegen import dish_hint_from_content

    # Real draft bodies (2026-09/10 corpus): each names its dish plainly.
    assert dish_hint_from_content(
        "味香斋的麻酱面是上海经典的老味道，芝麻酱浓稠香滑，再加一勺辣油。"
    ) == "麻酱面"
    assert dish_hint_from_content(
        "小杨生煎的鲜肉生煎皮薄底脆，咬开先是一口热汤，肉馅紧实不散。"
    ) == "鲜肉生煎"
    assert dish_hint_from_content(
        "赤上烧肉酒场的双人烧肉套餐性价比很高，和牛入口即化。"
    ) == "烧肉"
    # Longest match wins when several terms appear.
    assert dish_hint_from_content(
        "点了蟹粉小笼和鲜肉生煎，小笼汤汁多。"
    ) == "蟹粉小笼"
    # Simile mentions are not the dish being reviewed (2026-11-09 review
    # finding: "环境像咖啡馆" must not attach a coffee photo to a noodle
    # review); with no usable match the generic prompt is honest.
    assert dish_hint_from_content(
        "店的环境像咖啡馆一样安静，但麻酱面是真好吃。"
    ) == "麻酱面"
    assert dish_hint_from_content("环境像咖啡馆一样安静，值得再来。") == ""
    # No dish named -> empty (generic signature-dish prompt), never a guess.
    assert dish_hint_from_content("这家店环境不错，服务态度也很好，值得再来。") == ""
    assert dish_hint_from_content("") == ""


def test_build_live_workflow_passes_dish_hint_from_draft(tmp_path: Path, default_photo, monkeypatch):
    """Draft publish: the resolved photo generation gets a content-grounded prompt."""
    import automation_app_dianping.photos as photos_mod
    from automation_app_dianping.live import LIVE_FLAG, build_live_workflow

    content = "味香斋的麻酱面是上海经典的老味道，芝麻酱浓稠香滑，拌开之后根根面上都挂满酱，再加一勺辣油和醋，层次一下子就出来了，配一碟花生和几瓣糖蒜，解腻又提香，环境有烟火气，服务利落，值得专程来吃。" * 2
    DraftStore(tmp_path).save(
        DraftRecord(
            id="live-hint",
            shop_url="https://www.dianping.com/shop/liveh",
            shop_name="味香斋",
            shop_slug="liveh",
            draft=DraftReview(
                content=content, ratings=ReviewRatings(5, 4, 4), photos=[], status="edited"
            ),
        )
    )

    captured = {}

    def _fake_resolve(*, slug, shop_name, data_dir, env, dish_hint=""):
        captured["dish_hint"] = dish_hint
        from automation_app_dianping.config import default_review_photos

        return default_review_photos()

    monkeypatch.setattr(photos_mod, "resolve_review_photos", _fake_resolve)
    workflow = build_live_workflow(
        session_factory=FakeSession,
        draft_id="live-hint",
        data_dir=str(tmp_path),
        env={LIVE_FLAG: "1"},
    )
    workflow.run()
    assert captured["dish_hint"] == "麻酱面"


def test_decode_image_skips_loopback_media_urls():
    """grok-style backends answer with an origin-loopback media URL that only
    resolves on the gateway host; fetching it here must be skipped outright
    instead of burning a retry cycle as a vague 'no image'."""
    from automation_app_dianping.imagegen import _fetchable_url

    assert _fetchable_url("http://127.0.0.1:18000/v1/media/images/img_x") is False
    assert _fetchable_url("http://localhost:18000/v1/media/images/img_x") is False
    assert _fetchable_url("http://10.5.103.26:18000/v1/media/images/img_x") is False
    assert _fetchable_url("https://api.mangoqwq.com/v1/media/images/img_x") is True


def test_build_live_workflow_prefers_explicit_dish_hint(tmp_path, default_photo, monkeypatch):
    """Non-draft publish: an explicit --dish-hint wins over the content-derived
    hint (the content mentions 麻酱面, the operator asked for 红烧肉)."""
    import automation_app_dianping.photos as photos_mod
    from automation_app_dianping.live import LIVE_FLAG, build_live_workflow

    captured = {}

    def _fake_resolve(*, slug, shop_name, data_dir, env, dish_hint=""):
        captured["dish_hint"] = dish_hint
        from automation_app_dianping.config import default_review_photos

        return default_review_photos()

    monkeypatch.setattr(photos_mod, "resolve_review_photos", _fake_resolve)
    content = "味香斋的麻酱面是上海经典的老味道，芝麻酱浓稠香滑，拌开之后根根面上都挂满酱，再加一勺辣油和醋，层次一下子就出来了，配一碟花生和几瓣糖蒜，解腻又提香，环境有烟火气，服务利落，值得专程来吃。" * 2
    workflow = build_live_workflow(
        session_factory=FakeSession,
        shop_name="味香斋",
        content=content,
        dish_hint="红烧肉",
        env={LIVE_FLAG: "1"},
    )
    workflow.run()
    assert captured["dish_hint"] == "红烧肉"
