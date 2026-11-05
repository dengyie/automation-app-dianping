"""Deep-coverage tests for dianping workflow/live gaps.

Pins: policy-shape dispatch contract (execute vs aexecute vs neither),
ratings normalization edges, photos validation, ComposedWorkflow failure
callthrough, and run_live mode/error routing.
"""

import asyncio

import pytest

from automation_app_dianping import workflow as wf


class ActionOnlyExecutor:
    """V2-style executor exposing only execute(request, context)."""

    def __init__(self):
        self.calls = []

    def execute(self, request, context):
        import asyncio as _aio

        async def run():
            self.calls.append((request, context))
            from automation_core.capabilities import CapabilityResult

            return CapabilityResult(success=True, provider="v2")

        return _aio.run_coroutine_threadsafe


class ContextExecutor:
    """execute(request, context) returning a plain value."""

    def __init__(self):
        self.contexts = []

    def execute(self, request, context):
        import asyncio

        async def _r():
            self.contexts.append(context)
            from automation_core.capabilities import CapabilityResult

            return CapabilityResult(success=True, provider="ctx")

        return asyncio.ensure_future(_r())


def test_ratings_non_object_rejected():
    with pytest.raises(ValueError, match="ratings must be an object"):
        wf._ratings_from_parameters({"ratings": "5"})


def test_ratings_bool_value_is_accepted_as_1_or_0():
    """Known leniency: bool is an int subclass so True survives the
    isinstance(int) check as 1 (and clamps at _overall_rating_value).
    Pinned as documented behavior — a tightening here is a contract change."""
    assert wf._ratings_from_parameters({"ratings": {"taste": True}}) == {"taste": True}
    # _overall_rating_value excludes bools from its numeric scan (the
    # isinstance(value, bool) guard) — all-bool ratings raise.
    with pytest.raises(ValueError, match="at least one numeric value"):
        wf._overall_rating_value({"taste": True})


def test_ratings_out_of_range_value_rejected():
    with pytest.raises(ValueError, match="must be an integer between 1 and 5"):
        wf._ratings_from_parameters({"ratings": {"taste": 6}})

    with pytest.raises(ValueError, match="must be an integer between 1 and 5"):
        wf._ratings_from_parameters({"ratings": {"taste": 0}})


def test_ratings_none_entries_are_skipped():
    assert wf._ratings_from_parameters({"ratings": {"taste": None}}) == {}


def test_overall_rating_requires_numeric_value():
    with pytest.raises(ValueError, match="at least one numeric value"):
        wf._overall_rating_value({"taste": "good"})


def test_overall_rating_clamps_to_star_range():
    assert wf._overall_rating_value({"taste": 6, "service": 6}) == 5
    assert wf._overall_rating_value({"taste": 3}) == 3


def test_photos_non_list_rejected():
    with pytest.raises(ValueError, match="photos must be a list"):
        wf._photos_from_parameters({"photos": "a.jpg"})


def test_photos_blank_entries_rejected():
    with pytest.raises(ValueError, match="non-blank strings"):
        wf._photos_from_parameters({"photos": ["ok.jpg", "  "]})


def test_photos_entries_are_stripped():
    assert wf._photos_from_parameters({"photos": [" a.jpg ", "b.jpg"]}) == [
        "a.jpg",
        "b.jpg",
    ]


def test_allow_photos_false_skips_photo_resolution():
    assert wf._photos_from_parameters({"allow_photos": False, "photos": ["x.jpg"]}) == []


def test_run_live_rejects_unknown_mode():
    from automation_app_dianping.live import run_live

    with pytest.raises(ValueError, match="unsupported live mode"):
        run_live(mode="teleport", session_factory=lambda: None, env={})


# --- _execute_capability dispatch matrix (workflow 48/56-60/70) --------------------


class _CapResult:
    def __init__(self, ok=True):
        self.success = ok


class SyncAexecuteOnly:
    def aexecute(self, request):
        return _CapResult()  # sync return, no awaitable


class AsyncAexecuteOnly:
    async def aexecute(self, request):
        return _CapResult()


class ContextExecuteOnly:
    def __init__(self):
        self.contexts = []

    def execute(self, request, context):
        async def _run():
            self.contexts.append(context)
            return _CapResult()

        import asyncio

        return asyncio.ensure_future(_run())


class SyncExecuteOnly:
    def execute(self, request, context):
        return _CapResult()


def test_execute_capability_sync_aexecute_passthrough():
    result = asyncio.run(wf._execute_capability(SyncAexecuteOnly(), request=object()))
    assert result.success is True


def test_execute_capability_async_aexecute_awaited():
    result = asyncio.run(wf._execute_capability(AsyncAexecuteOnly(), request=object()))
    assert result.success is True


def test_execute_capability_context_execute_getsExecutionContext():
    from automation_core.execution import ExecutionContext

    ex = ContextExecuteOnly()
    result = asyncio.run(
        wf._execute_capability(ex, request=object(), run_id="r-1", task_id="t-1")
    )
    assert result.success is True
    assert ex.contexts[0].run_id == "r-1"
    assert ex.contexts[0].task_id == "t-1"


def test_execute_capability_sync_execute_passthrough():
    result = asyncio.run(wf._execute_capability(SyncExecuteOnly(), request=object()))
    assert result.success is True


def test_execute_capability_neither_method_is_typeerror():
    class Neither:
        pass

    with pytest.raises(TypeError, match="execute or aexecute"):
        asyncio.run(wf._execute_capability(Neither(), request=object()))


# --- services publish-gate edges (69, 75-76) ---------------------------------------


def _gate_draft():
    from automation_app_dianping.storage import DraftRecord, DraftReview, ReviewRatings

    text = "红烧肉肥而不腻，响油鳝丝很香，环境有烟火气，服务利落，值得再来。" * 4
    return DraftRecord(
        id="gate-gaps",
        shop_url="https://www.dianping.com/shop/gg",
        shop_name="缺口店",
        shop_slug="gg",
        draft=DraftReview(
            content=text,
            ratings=ReviewRatings(taste=5, environment=4, service=4),
            photos=[],
            status="edited",
        ),
    )


def test_publish_gate_quota_exceeded(tmp_path):
    from automation_app_dianping.services import PublishGateError, assert_publish_allowed
    from automation_app_dianping.config import (
        DianpingAppConfig,
        DianpingPublishPolicy,
    )
    from automation_app_dianping.storage import DraftStore, StateStore

    config = DianpingAppConfig(
        city="shanghai",
        publish=DianpingPublishPolicy(max_per_day=1, min_interval_minutes=0),
    )
    DraftStore(tmp_path).save(_gate_draft())
    # StateStore has no record_publish; quota state is mutated directly on
    # RuntimeState and persisted via save().
    store = StateStore(tmp_path)
    state = store.load()
    state.today_published_count = config.publish.max_per_day
    state.last_published_date = __import__("datetime").date.today().isoformat()
    store.save(state)

    with pytest.raises(PublishGateError, match="quota exceeded"):
        assert_publish_allowed(
            draft=_gate_draft(), config=config, data_dir=tmp_path
        )


def test_publish_gate_interval_not_met(tmp_path, monkeypatch):
    from automation_app_dianping.services import PublishGateError, assert_publish_allowed
    from automation_app_dianping.config import (
        DianpingAppConfig,
        DianpingPublishPolicy,
    )
    from automation_app_dianping.storage import DraftStore, StateStore

    config = DianpingAppConfig(
        city="shanghai",
        publish=DianpingPublishPolicy(max_per_day=5, min_interval_minutes=30),
    )
    DraftStore(tmp_path).save(_gate_draft())
    store = StateStore(tmp_path)
    state = store.load()
    state.today_published_count = 1
    state.last_published_date = __import__("datetime").date.today().isoformat()
    store.save(state)
    # Fake "just published": minutes_since_last_publish returns ~0.
    import automation_app_dianping.storage as st

    monkeypatch.setattr(
        st.StateStore, "minutes_since_last_publish", lambda self, s: 0.5
    )

    with pytest.raises(PublishGateError, match="interval not met"):
        assert_publish_allowed(
            draft=_gate_draft(), config=config, data_dir=tmp_path
        )
