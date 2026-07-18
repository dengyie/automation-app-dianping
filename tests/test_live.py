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


@pytest.mark.skipif(True, reason="default suite keeps live E2E disabled")
def test_live_e2e_placeholder_skipped_by_default():
    assert False


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

def test_build_live_smoke_and_run_live_publish_params(tmp_path: Path):
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

