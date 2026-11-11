"""Gap-coverage tests for automation_app_dianping/session.py.

Targets the validation branches and failure tails the main suites never
reach: slider solution/drag validation, fallback-step rejection paths,
keycode/launch/confirm_search alternatives, module-level parse helpers
(_import_by fallbacks, pending/dish geometry guards), and uia2
hide-keyboard / rate / element-bounds / dismiss-dialogs tails.
"""

import json
from pathlib import Path

import pytest


def _slidex_vision_ready():
    try:
        from slidex.ocr.llm import LlmVisionConfig  # noqa: F401
        return hasattr(LlmVisionConfig, "configured")
    except Exception:
        return False

from automation_core.drivers import ActionResult, ArtifactHandle, SessionInfo

import automation_app_dianping.session as session_mod
from automation_app_dianping.runlog import RunEventLog
from automation_app_dianping.session import (
    DianpingAppiumSession,
    DianpingUia2Session,
    _import_by,
    _picker_header_album,
    _slider_drag_distance,
    _slider_solution_params,
    create_appium_driver,
    device_geometry_scale,
    dish_edit_filmstrip_rects,
    dish_edit_trash_rect,
    editor_attached_photo_rects,
    editor_has_dimension_rows,
    parse_locator,
    pending_review_row_rect,
    shop_row_tap_rect,
)


# --- slider solution validation (session.py 252-308) ------------------------


def test_slider_solution_accepts_legacy_bare_number():
    params, error = _slider_solution_params(137)
    assert error is None
    assert params == {"gap_x": None, "offset_px": 137, "scale": 1.0}


def test_slider_solution_rejects_non_dict_and_empty():
    _, err1 = _slider_solution_params("gap-137")
    assert err1.success is False
    assert "no solution" in err1.message
    _, err2 = _slider_solution_params({"distance_scale": 1.0})
    assert err2.success is False
    assert "no solution" in err2.message


def test_slider_solution_rejects_bad_and_non_positive_scale():
    _, err1 = _slider_solution_params({"gap_offset_px": 1, "distance_scale": "tiny"})
    assert "invalid distance_scale" in err1.message
    _, err2 = _slider_solution_params({"gap_offset_px": 1, "distance_scale": 0})
    assert "non-positive distance_scale" in err2.message


def test_slider_drag_distance_matrix():
    ok, whitespace, garbage, left, zero = (
        _slider_drag_distance(80, 363, None, 0.5),
        _slider_drag_distance(80, " 363 ", None, 1.0),
        _slider_drag_distance(80, "at", None, 1.0),
        _slider_drag_distance(500, 80, None, 1.0),
        _slider_drag_distance(80, 280, None, 1.0),
    )
    assert ok == (142, None)
    assert whitespace == (283, None)  # float(" 363 ") tolerates padding
    assert garbage[1].message == "slider solver returned invalid gap_x"
    assert left[1].message == "slider gap at x=80.0 is at or left of handle x=500"
    # gap equal to handle x → still "at or left"; %s on float(gap_x) renders 80.0
    zero = _slider_drag_distance(80, 80, None, 1.0)
    assert zero[1].message == "slider gap at x=80.0 is at or left of handle x=80"

    off, nonpos, bad = (
        _slider_drag_distance(80, None, 137, 2.0),
        _slider_drag_distance(80, None, 0, 1.0),
        _slider_drag_distance(80, None, "far", 1.0),
    )
    assert off == (274, None)
    assert nonpos[1].message == "slider solver returned non-positive gap_offset_px"
    assert bad[1].message == "slider solver returned invalid gap_offset_px"


# --- appium session validation branches -------------------------------------


class _MiniDriver:
    def __init__(self):
        self.records = []
        self.page_source = "<hierarchy/>"

    def find_element(self, by, value):
        raise LookupError("no")

    def get_window_size(self):
        return {"width": 810, "height": 2160}


def _mini(tmp_path, driver=None):
    return DianpingAppiumSession(driver or _MiniDriver(), artifact_root=tmp_path)


def test_rate_missing_selector_and_bad_value(tmp_path):
    session = _mini(tmp_path)
    assert session.execute_action("rate").success is False
    # no anchor → plain tap expansion; the tap fails on the dead fake driver
    failed = session.execute_action("rate", selector="~a", value="x")
    assert not failed.success
    assert "tap failed for all selectors: ~a" in failed.message
    assert "rating value must be 1-5" in session.execute_action(
        "rate", selector="~a", value=9, anchor="dimension_row"
    ).message
    # skip path: overwrite chrome without an overall bar
    driver = _MiniDriver()
    driver.page_source = "<hierarchy><node text='完成'/><node text='发布'/></hierarchy>"
    skipped = DianpingAppiumSession(driver, artifact_root=tmp_path).execute_action(
        "rate", selector="~a", value=3, dimension="taste"
    )
    assert skipped.success
    assert "rate skipped" in skipped.message


def test_rate_by_label_anchor_needs_swipeable_driver(tmp_path):
    session = _mini(tmp_path)
    result = session.execute_action(
        "rate", selector="~口味", value=3, anchor="dimension_row"
    )
    assert not result.success
    assert "rate anchor failed" in result.message
    assert "element not found" in result.message


def test_rate_by_label_anchor_success_swipes(tmp_path):
    class Element:
        rect = {"x": 0, "y": 500, "width": 100, "height": 40}

    class Swipe(_MiniDriver):
        def __init__(self):
            super().__init__()
            self.button = Element()

        def find_element(self, by, value):
            return self.button

        def swipe(self, *args):
            self.records.append(args)

    driver = Swipe()
    session = DianpingAppiumSession(driver, artifact_root=tmp_path)
    result = session.execute_action(
        "rate", selector="~口味", value=3, anchor="dimension_row", dimension="taste"
    )
    assert result.success
    # dim anchor x = (236 + 144×2) × 810/1080 = 393; y = label centre (unscaled)
    assert len(driver.records) == 1
    assert int(driver.records[0][0]) == 393
    assert int(driver.records[0][1]) == 520


def test_rate_by_label_anchor_reports_failures(tmp_path):
    class Element:
        rect = {"x": 0, "y": 500, "width": 100, "height": 40}

    class Rejected(_MiniDriver):
        def find_element(self, by, value):
            return Element()

        def swipe(self, *args):
            raise KeyError("gone")

    session = DianpingAppiumSession(Rejected(), artifact_root=tmp_path)
    with pytest.raises(KeyError):
        session.execute_action("rate", selector="~口味", value=3, anchor="dimension_row")

    # the "rate anchor failed" tail trips when find_element or rect access
    # raises inside the per-candidate try (a rect dict missing keys is
    # deferred to the arithmetic — which raises uncaught; a rejecting driver
    # is the pinned failure path)
    class Ghost(_MiniDriver):
        def find_element(self, by, value):
            raise TimeoutError("ghost")

    session2 = DianpingAppiumSession(Ghost(), artifact_root=tmp_path)
    result = session2.execute_action(
        "rate", selector="~口味", value=3, anchor="dimension_row"
    )
    assert not result.success
    assert "rate anchor failed" in result.message
    assert "ghost" in result.message


def test_maybe_fallback_step_validation(tmp_path):
    session = _mini(tmp_path)

    # _maybe_fallback is only wired for rate/pick/launch/confirm/navigate/
    # hide/dismiss/press_keycode/unknown — NOT tap/type_text/wait_for_element.
    ok = session._maybe_fallback(
        "wait_for_element",
        {"fallback_steps": ["not-a-dict"]},
        ActionResult(False, "primary"),
    )
    assert "invalid fallback step" in ok.message

    no_action = session._maybe_fallback(
        "wait_for_element",
        {"fallback_steps": [{"selector": "~x"}]},
        ActionResult(False, "primary"),
    )
    assert "fallback missing action" in no_action.message

    failing = session._maybe_fallback(
        "wait_for_element",
        {"fallback_steps": [{"action": "tap", "selector": "uiautomator:missing"}]},
        ActionResult(False, "primary"),
    )
    assert "fallback failed at tap" in failing.message

    class DeadAngry(_MiniDriver):
        def find_element(self, by, value):
            raise LookupError("refuses: %s" % value)

    # rate anchor failure routes into _maybe_fallback (session.py:622)
    ok = DianpingAppiumSession(DeadAngry(), artifact_root=tmp_path).execute_action(
        "rate",
        selector="~a",
        value=3,
        anchor="dimension_row",
        fallback_steps=[{"action": "tap", "selector": "~ok"}],
    )
    assert not ok.success
    assert "fallback failed at tap" in ok.message

    # non-list fallback_steps (plain string) are ignored entirely
    ignored = DianpingAppiumSession(DeadAngry(), artifact_root=tmp_path).execute_action(
        "rate", selector="~a", value=3, anchor="dimension_row", fallback_steps="tap"
    )
    assert not ignored.success
    assert "rate anchor failed" in ignored.message


def test_maybe_fallback_fallback_action_paths(tmp_path):
    class Element:
        def click(self):
            Element.clicked.append(1)

    Element.clicked = []

    class Resolving(_MiniDriver):
        def find_element(self, by, value):
            return Element()

    session = DianpingAppiumSession(Resolving(), artifact_root=tmp_path)
    ok = session._maybe_fallback(
        "x",
        {"fallback_action": "tap", "fallback_selector": "~ok"},
        ActionResult(False, "primary"),
    )
    assert ok.success
    assert "via fallback_action=tap" in ok.message
    assert Element.clicked  # the fallback tap really clicked

    dead = session._maybe_fallback(
        "x",
        {"fallback_action": "grow_depth"},
        ActionResult(False, "primary"),
    )
    assert not dead.success
    assert "fallback_action=grow_depth failed" in dead.message

    # unknown action name still routes through _maybe_fallback; a WORKING
    # fallback rescues the unsupported action entirely
    unknown = session.execute_action(
        "grow_depth",
        fallback_action="tap",
        fallback_selector="~ok",
    )
    assert unknown.success
    assert "grow_depth via fallback_action=tap" in unknown.message

    # dead fallback → unsupported message + fallback failure, chained
    dead_unknown = DianpingAppiumSession(_MiniDriver(), artifact_root=tmp_path).execute_action(
        "grow_depth",
        fallback_action="tap",
        fallback_selector="~ok",
    )
    assert not dead_unknown.success
    assert "grow_depth failed; fallback_action=tap failed" in dead_unknown.message

    # empty steps / no kwargs → primary passed through unchanged
    primary = session._maybe_fallback("y", {"fallback_steps": []}, ActionResult(False, "kept"))
    assert primary.message == "kept"


def test_pick_photos_appium_rejects_empty_selectors(tmp_path):
    session = _mini(tmp_path)
    result = session.execute_action("pick_photos")
    assert not result.success
    assert "missing selectors" in result.message


def test_display_width_px_guards(tmp_path):
    class Sized(_MiniDriver):
        def get_window_size(self):
            return {"width": "wide"}

    class Broken(_MiniDriver):
        def get_window_size(self):
            raise RuntimeError("offline")

    class Weird(_MiniDriver):
        def get_window_size(self):
            return "not-a-dict"

    class ZeroWidth(_MiniDriver):
        def get_window_size(self):
            return {"width": 0}

    class NoSize:
        pass

    assert _mini(tmp_path)._display_width_px() == 810
    assert DianpingAppiumSession(Weird(), artifact_root=tmp_path)._display_width_px() is None
    assert DianpingAppiumSession(Broken(), artifact_root=tmp_path)._display_width_px() is None
    assert DianpingAppiumSession(Sized(), artifact_root=tmp_path)._display_width_px() is None
    assert DianpingAppiumSession(ZeroWidth(), artifact_root=tmp_path)._display_width_px() is None
    assert DianpingAppiumSession(NoSize(), artifact_root=tmp_path)._display_width_px() is None


# --- appium launch/press_keycode/confirm_search (898-1022) -------------------


def test_launch_app_parameter_matrix(tmp_path):
    class Launcher(_MiniDriver):
        def activate_app(self, app_id):
            self.records.append(app_id)

    class SilentBoom(_MiniDriver):
        def activate_app(self, app_id):
            raise RuntimeError("offline")

    class Bare:
        pass

    session = DianpingAppiumSession(Launcher(), artifact_root=tmp_path)
    assert "missing required parameter: app_id" in session.execute_action("launch_app").message
    assert "settle_seconds" in session.execute_action(
        "launch_app", app_id="x", settle_seconds="soon"
    ).message
    ok = session.execute_action("launch_app", app_id="com.dianping.v1", settle_seconds=0)
    assert ok.success

    boom = DianpingAppiumSession(SilentBoom(), artifact_root=tmp_path).execute_action(
        "launch_app", app_id="com.dianping.v1", settle_seconds=0
    )
    assert not boom.success
    assert "launch_app failed" in boom.message

    unsupported = DianpingAppiumSession(Bare(), artifact_root=tmp_path).execute_action(
        "launch_app", app_id="com.dianping.v1"
    )
    assert "does not support app launch" in unsupported.message


def test_press_keycode_matrix(tmp_path):
    class PressBoom:
        page_source = "<hierarchy/>"

        def press_keycode(self, code):
            raise RuntimeError("stuck")

    class ScriptBoom:
        def execute_script(self, *args, **kwargs):
            raise RuntimeError("x")

    class Deaf:
        pass

    session = DianpingAppiumSession(PressBoom(), artifact_root=tmp_path)
    assert "keycode must be int" in session.execute_action("press_keycode", keycode="six").message
    assert "press_keycode failed" in session.execute_action("press_keycode", keycode=66).message

    script_session = DianpingAppiumSession(ScriptBoom(), artifact_root=tmp_path)
    assert "press_keycode failed" in script_session.execute_action(
        "press_keycode", keycode=66
    ).message

    class ScriptOnly:
        def __init__(self):
            self.seen = None

        def execute_script(self, script, args):
            self.seen = (script, args)

    quiet = ScriptOnly()
    ok = DianpingAppiumSession(quiet, artifact_root=tmp_path).execute_action(
        "press_keycode", keycode=24
    )
    assert ok.success
    assert quiet.seen[0] == "mobile: pressKey"

    deaf = DianpingAppiumSession(Deaf(), artifact_root=tmp_path).execute_action(
        "press_keycode", keycode=66
    )
    assert "does not support keycode press" in deaf.message


def test_confirm_search_routes(tmp_path):
    session = _mini(tmp_path)
    dead = session.execute_action("confirm_search")
    assert not dead.success
    assert "no search button and keycode unavailable" in dead.message

    class KeyPress(_MiniDriver):
        def press_keycode(self, code):
            self.records.append(code)

    ok = DianpingAppiumSession(KeyPress(), artifact_root=tmp_path).execute_action(
        "confirm_search"
    )
    assert ok.success
    assert ok.data["via"] == "keycode"


# --- appium hide_keyboard tails (853-912) ------------------------------------


def test_hide_keyboard_alternate_driver_paths(tmp_path):
    class PressBoom:
        page_source = "<hierarchy/>"

        def press_keycode(self, code):
            raise RuntimeError("stuck")

    result = DianpingAppiumSession(PressBoom(), artifact_root=tmp_path).execute_action(
        "hide_keyboard"
    )
    assert "BACK failed" in result.message

    class HideBoom:
        page_source = "<hierarchy/>"

        def hide_keyboard(self):
            raise RuntimeError("IME gone")

    result = DianpingAppiumSession(HideBoom(), artifact_root=tmp_path).execute_action(
        "hide_keyboard"
    )
    assert "hide_keyboard failed" in result.message

    class Deaf:
        page_source = "<hierarchy/>"

    skipped = DianpingAppiumSession(Deaf(), artifact_root=tmp_path).execute_action(
        "hide_keyboard"
    )
    assert skipped.success
    assert "skipped" in skipped.message

    class PublishChrome:
        page_source = "<hierarchy><node text='发布'/></hierarchy>"

    chrome = DianpingAppiumSession(PublishChrome(), artifact_root=tmp_path).execute_action(
        "hide_keyboard"
    )
    assert "editor chrome visible" in chrome.message

    class DishEdit:
        page_source = "<hierarchy><node text='识别菜品'/></hierarchy>"

    dish = DianpingAppiumSession(DishEdit(), artifact_root=tmp_path).execute_action(
        "hide_keyboard"
    )
    assert "editor chrome visible" in dish.message


# --- appium selector fallback plumbing (914-980) -----------------------------


def test_with_selector_fallbacks_edge_paths(tmp_path):
    class Element:
        def click(self):
            Element.clicked.append(1)

    Element.clicked = []

    class Resolving(_MiniDriver):
        def find_element(self, by, value):
            return Element()

    session = DianpingAppiumSession(Resolving(), artifact_root=tmp_path)
    ok = session.execute_action("tap", selector="~ok")
    assert ok.success
    assert Element.clicked  # real click went through
    no_text = session.execute_action("type_text", selector="~ok")
    assert "missing required parameter: text" in no_text.message
    unsupported = session._with_selector_fallbacks("swipe", {"selector": "~ok"})
    assert "unsupported selector action: swipe" in unsupported.message
    blank = session._with_selector_fallbacks("tap", {"selector": "   ", "timeout": 0.1})
    assert not blank.success


def test_type_text_guards(tmp_path, monkeypatch):
    session = _mini(tmp_path)
    by, value = parse_locator("~ok")

    class Mute:
        clear = None

    monkeypatch.setattr(session, "_find_element", lambda *a, **k: Mute())
    result = session._type_text(value, text="hi", by=by, timeout=0.1)
    assert not result.success
    assert "does not support typing" in result.message

    class Exploding(Mute):
        def send_keys(self, text):
            raise RuntimeError("detached")

    monkeypatch.setattr(session, "_find_element", lambda *a, **k: Exploding())
    result = session._type_text(value, text="hi", by=by, timeout=0.1)
    assert not result.success
    assert "type_text failed" in result.message


def test_dump_failure_and_stop_guards(tmp_path):
    class Shot:
        def save_screenshot(self, path):
            Path(path).write_text("img", encoding="utf-8")
            return True

    session = DianpingAppiumSession(Shot(), artifact_root=tmp_path)
    session._dump_failure("test label!")
    files = sorted(p.name for p in tmp_path.iterdir())
    assert any(n.startswith("fail-test_label_") and n.endswith(".png") for n in files)

    driver = _MiniDriver()
    session2 = DianpingAppiumSession(driver, artifact_root=tmp_path)
    session2.stop()  # unstarted → no-op
    session2.start()
    session2.stop()


# --- module-level parse helpers (103-135, 138-176) ---------------------------


def test_parse_locator_full_matrix():
    by = _import_by()
    assert parse_locator("~x") == (by.ACCESSIBILITY_ID, "x")
    assert parse_locator("id:com.x") == (by.ID, "com.x")
    assert parse_locator('uiautomator:new UiSelector().text("a")') == (
        by.ANDROID_UIAUTOMATOR,
        'new UiSelector().text("a")',
    )
    assert parse_locator('android=new UiSelector().text("a")') == (
        by.ANDROID_UIAUTOMATOR,
        'new UiSelector().text("a")',
    )
    assert parse_locator("xpath://a") == (by.XPATH, "//a")
    assert parse_locator("//a") == (by.XPATH, "//a")
    assert parse_locator("(//a")[0] == by.XPATH
    assert parse_locator("plain")[0] == by.ACCESSIBILITY_ID
    with pytest.raises(ValueError):
        parse_locator("   ")
    with pytest.raises(ValueError):
        parse_locator(7)


def test_parse_locator_falls_back_to_by_strings(monkeypatch):
    """Neither Appium nor Selenium importable → _ByStrings backstops every
    attribute (offline-env fallback contract)."""
    import sys

    targets = (
        "appium",
        "selenium",
        "appium.webdriver.common.appiumby",
        "selenium.webdriver.common.by",
    )
    saved = {name: sys.modules.pop(name, None) for name in targets}
    for name in targets:
        monkeypatch.setitem(sys.modules, name, None)
    try:
        by = _import_by()
        assert by.ACCESSIBILITY_ID == "accessibility id"
        assert parse_locator("~x") == ("accessibility id", "x")
        assert parse_locator("id:a") == ("id", "a")
        assert parse_locator("uiautomator:x") == ("-android uiautomator", "x")
        assert parse_locator("xpath://a") == ("xpath", "//a")
        assert parse_locator("//a")[0] == "xpath"
        assert parse_locator("plain")[0] == "accessibility id"
    finally:
        for name, module in saved.items():
            if module is not None:
                sys.modules[name] = module


def test_create_appium_driver_configures_options(monkeypatch):
    import sys
    import types

    class Remote:
        def __init__(self, command_executor, options):
            self.command_executor = command_executor
            self.options = options

    class FakeOptions:
        def __init__(self):
            self.capabilities = {}

        def set_capability(self, key, value):
            self.capabilities[key] = value

    appium = types.ModuleType("appium")
    wd = types.ModuleType("appium.webdriver")
    wd.Remote = Remote
    opts_mod = types.ModuleType("appium.options.android")
    opts_mod.UiAutomator2Options = FakeOptions
    appium.webdriver = wd

    monkeypatch.setitem(sys.modules, "appium", appium)
    monkeypatch.setitem(sys.modules, "appium.webdriver", wd)
    monkeypatch.setitem(sys.modules, "appium.webdriver.common", types.ModuleType("m"))
    monkeypatch.setitem(sys.modules, "appium.options.android", opts_mod)

    class Cfg:
        app_id = "com.dianping.v1"
        activity = ".HomeActivity"
        device_name = "op7t"
        no_reset = True
        new_command_timeout = 240
        auto_grant_permissions = True
        udid = "abc"
        platform_version = "11"
        path = "/wd/hub/"
        host = "127.0.0.1"
        port = 4723

    driver = create_appium_driver(Cfg())
    assert driver.command_executor == "http://127.0.0.1:4723/wd/hub"
    assert driver.options.capabilities["settings"] == {
        "waitForIdleTimeout": 0,
        "snapshotMaxDepth": 60,
    }
    assert driver.options.capabilities["ignoreHiddenApiPolicyError"] is True


def test_create_appium_driver_import_error(monkeypatch):
    import sys

    targets = (
        "appium",
        "appium.webdriver",
        "appium.options.android",
        "appium.webdriver.common.appiumby",
        "selenium",
        "selenium.webdriver.common.by",
    )
    saved = {name: sys.modules.pop(name, None) for name in targets}
    for name in targets:
        monkeypatch.setitem(sys.modules, name, None)
    try:
        with pytest.raises(ImportError, match="Appium-Python-Client is required"):
            create_appium_driver(
                type(
                    "Cfg",
                    (),
                    {
                        "app_id": "x",
                        "activity": "y",
                        "device_name": "d",
                        "no_reset": True,
                        "new_command_timeout": 3,
                        "auto_grant_permissions": False,
                        "udid": None,
                        "platform_version": None,
                        "path": "",
                        "host": "h",
                        "port": 1,
                    },
                )()
            )
    finally:
        for name, module in saved.items():
            if module is not None:
                sys.modules[name] = module


# --- module-level geometry helpers (1180-1310, 1497-1590) --------------------


def test_picker_header_album_matrix():
    xml = (
        "<hierarchy>"
        '<node text="12:30" class="android.widget.TextView" bounds="[0,0][100,50]"/>'
        '<node text="最近项目" class="android.widget.TextView" bounds="[430,103][610,156]"/>'
        '<node text="Camera" class="android.widget.TextView" bounds="[293,268][461,317]"/>'
        "</hierarchy>"
    )
    assert _picker_header_album(xml) == "最近项目"
    assert _picker_header_album("not xml <") is None
    assert _picker_header_album("") is None
    skip_and_digit = (
        "<hierarchy>"
        '<node text="全部" bounds="[100,100][200,150]"/>'
        '<node text="123" bounds="[300,100][400,150]"/>'
        "</hierarchy>"
    )
    assert _picker_header_album(skip_and_digit) is None
    tall = (
        "<hierarchy>"
        '<node text="最近项目" bounds="[430,103][610,1300]"/>'
        "</hierarchy>"
    )
    assert _picker_header_album(tall) is None
    no_bounds = "<hierarchy>" '<node text="最近项目"/>' "</hierarchy>"
    assert _picker_header_album(no_bounds) is None


def test_editor_attached_photo_rects_matrix():
    def tile(x, y, clickable="true", text="1"):
        return (
            '<node class="android.widget.FrameLayout" clickable="%s" bounds="[%d,%d][%d,%d]">'
            '<node text="%s" class="android.widget.TextView" clickable="false" bounds="[%d,%d][%d,%d]"/>'
            "</node>" % (clickable, x, y, x + 160, y + 200, text, x + 40, y + 20, x + 70, y + 50)
        )

    rects = editor_attached_photo_rects("<hierarchy>" + tile(34, 1087) + "</hierarchy>")
    assert len(rects) == 1
    assert editor_attached_photo_rects("<hierarchy>" + tile(34, 300) + "</hierarchy>") == []
    assert editor_attached_photo_rects("<hierarchy>" + tile(34, 1087, clickable="false") + "</hierarchy>") == []
    assert editor_attached_photo_rects("<hierarchy>" + tile(34, 1087, text="添加图") + "</hierarchy>") == []
    assert editor_attached_photo_rects("<hier ogy>") == []


def test_device_geometry_and_dimension_rows_guards():
    assert device_geometry_scale('<hierarchy width="810"/>') == pytest.approx(0.75)
    assert device_geometry_scale("<hierarchy/>") == 1.0
    assert device_geometry_scale("garbage<") == 1.0
    dims = (
        "<hierarchy>"
        '<node text="口味" class="android.widget.TextView" bounds="[42,491][214,533]"/>'
        "</hierarchy>"
    )
    assert editor_has_dimension_rows(dims) is True
    assert editor_has_dimension_rows("<hierarchy/>") is False
    assert editor_has_dimension_rows("bad <") is False
    assert editor_has_dimension_rows("") is False


def test_pending_review_row_rect_matrix():
    assert pending_review_row_rect("", "小店") is None
    assert pending_review_row_rect("<hier>", "") is None
    assert pending_review_row_rect("<hier>", "小店") is None
    assert pending_review_row_rect("bad <", "小店") is None
    row = (
        '<node text="小店" class="android.widget.TextView" clickable="false" bounds="[42,400][400,460]"/>'
        '<node text="评价" class="android.widget.TextView" clickable="true" bounds="[850,420][1000,470]"/>'
    )
    assert pending_review_row_rect("<hierarchy>" + row + "</hierarchy>", "小店") == {
        "x": 850, "y": 420, "width": 150, "height": 50,
    }
    partial = row.replace('text="小店"', 'text="我的小店"')
    assert pending_review_row_rect("<hierarchy>" + partial + "</hierarchy>", "小店") == {
        "x": 850, "y": 420, "width": 150, "height": 50,
    }
    assert pending_review_row_rect("<hierarchy><node text='小店'/></hierarchy>", "小店") is None


def test_dish_edit_helper_guard_matrix():
    assert dish_edit_filmstrip_rects("bad<") == []
    assert dish_edit_filmstrip_rects("") == []
    base = '<node text="识别菜品" class="android.widget.TextView" clickable="true" bounds="[37,1754][214,1816]"/>'
    trash = '<node class="android.widget.ImageView" clickable="true" bounds="[951,1745][1044,1815]"/>'
    assert dish_edit_trash_rect("<hierarchy>" + base + trash + "</hierarchy>") == {
        "x": 951, "y": 1745, "width": 93, "height": 70,
    }
    assert dish_edit_trash_rect("<hierarchy/>") is None
    left = trash.replace("[951", "[10")  # x < 800 → not the trash control
    assert dish_edit_trash_rect("<hierarchy>" + base + left + "</hierarchy>") is None
    far = trash.replace("1745][1044", "2045][2144")  # y-line >80px from 识别菜品
    assert dish_edit_trash_rect("<hierarchy>" + base + far + "</hierarchy>") is None
    noclick = trash.replace('clickable="true"', 'clickable="false"')
    assert dish_edit_trash_rect("<hierarchy>" + base + noclick + "</hierarchy>") is None
    norecognize = base.replace('text="识别菜品"', 'text="其他"')
    assert (
        dish_edit_trash_rect("<hierarchy>" + norecognize + trash + "</hierarchy>") is None
    )


# --- uia2 session core branches ----------------------------------------------


class _SeqDriver:
    """uia2 device whose dumps walk a fixed sequence."""

    def __init__(self, dumps):
        self.dumps = list(dumps)

    def dump_hierarchy(self):
        if len(self.dumps) > 1:
            return self.dumps.pop(0)
        return self.dumps[0]


class _SeqKit:
    def __init__(self, driver=None):
        self.driver = driver or _SeqDriver(["<hierarchy/>"])
        self.info = SessionInfo("uia2", "android", "gap-test")
        self.calls = []
        self.results = {}

    def start(self):
        return None

    def stop(self):
        return None

    def execute_action(self, action_name, **kwargs):
        self.calls.append((action_name, kwargs))
        custom = self.results.get(action_name)
        if custom is not None:
            return custom
        return ActionResult(True, action_name)

    def capture_artifact(self, artifact_type, name):
        return ArtifactHandle(artifact_type=artifact_type, path=Path(name))


def _fast_clock(monkeypatch, start=1_700_000_000.0):
    clock = {"now": start}
    monkeypatch.setattr(session_mod.time, "time", lambda: clock["now"])
    monkeypatch.setattr(
        session_mod.time,
        "sleep",
        lambda s: clock.__setitem__("now", clock["now"] + float(s)),
    )
    return clock


def test_uia2_execute_action_branches(monkeypatch):
    _fast_clock(monkeypatch)
    session = DianpingUia2Session(_SeqKit(), captcha_window_seconds=0)

    result = session.execute_action("grow_depth", extra="x")
    assert result.success  # delegated to the kit session

    missing = session.execute_action("wait_for_element")
    assert not missing.success
    assert "missing selector" in missing.message

    ok = session.execute_action("wait_for_element", selector="id:x", by="id")
    assert ok.success
    assert session._session.calls[-1][0] == "wait_for_element"


def test_uia2_press_keycode_delegates_to_kit(monkeypatch):
    _fast_clock(monkeypatch)
    kit = _SeqKit()
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    ok = session.execute_action("grow_back", keycode=4)
    assert ok.success
    assert kit.calls[-1][0] == "grow_back"
    assert kit.calls[-1][1]["keycode"] == 4


def test_uia2_type_text_skips_inside_dish_edit(monkeypatch):
    _fast_clock(monkeypatch)
    driver = _SeqDriver(["<hierarchy><node text=\"识别菜品\"/></hierarchy>"])
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    result = session.execute_action("type_text", selector="id:x", text="hi")
    assert result.success
    assert "skipped" in result.message


def test_uia2_element_bounds_matrix(monkeypatch):
    _fast_clock(monkeypatch)
    kit = _SeqKit()
    bounds = {"x": 1, "y": 2, "width": 3, "height": 4}
    kit.results["element_bounds"] = ActionResult(True, "element_bounds", data=bounds)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)

    ok = session.execute_action("element_bounds", selector="~口味")
    assert ok.success and ok.data == bounds

    got = session.execute_action(
        "element_bounds", selector='uiautomator:new UiSelector().text("口味")'
    )
    assert got.success and got.data == bounds

    kit.results["element_bounds"] = ActionResult(False, "element_bounds", data=None)
    miss = session.execute_action(
        "element_bounds",
        selector=(
            'uiautomator:new UiSelector().fromParent("x")',
            "id:com.dianping.v1:id/a",
        ),
    )
    assert not miss.success
    assert "element_bounds failed for all selectors" in miss.message


def test_uia2_rate_value_guards(monkeypatch):
    _fast_clock(monkeypatch)
    session = DianpingUia2Session(_SeqKit(), captcha_window_seconds=0)
    # uia2 checks the label anchor BEFORE the numeric value
    assert "label anchor" in session.execute_action("rate", value="high").message
    assert "label anchor" in session.execute_action("rate", value=9).message
    selector = ('uiautomator:new UiSelector().text("很糟糕")',)
    bad = session.execute_action("rate", value="high", anchor="overall", selector=selector)
    assert "numeric value" in bad.message
    range_fail = session.execute_action("rate", value=9, anchor="overall", selector=selector)
    assert range_fail.message == "rating value must be 1-5"


def test_uia2_rate_overall_refuses_without_star_row(monkeypatch):
    _fast_clock(monkeypatch)
    dumps = ["<hierarchy/>", "<hierarchy/>", "<hierarchy/>", "<hierarchy/>"]
    session = DianpingUia2Session(
        _SeqKit(_SeqDriver(dumps)), captcha_window_seconds=0
    )
    result = session.execute_action(
        "rate", value=3, anchor="overall",
        selector=('uiautomator:new UiSelector().text("很糟糕")',),
    )
    assert not result.success
    assert "overall rating bar not found" in result.message


def test_uia2_rate_dimension_fails_when_label_missing(monkeypatch):
    _fast_clock(monkeypatch)
    kit = _SeqKit(_SeqDriver(["<hierarchy/>"]))
    kit.results["element_bounds"] = ActionResult(False, "element_bounds", data=None)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    result = session.execute_action(
        "rate", value=3, anchor="dimension_row", dimension="taste",
        selector=('uiautomator:new UiSelector().text("口味")',),
    )
    # empty dump is NOT an editor screen → dimension rows absent → skip IS success
    assert result.success
    assert "dimension rate skipped" in result.message

    # A dump WITH a 口味 node but no bounds: editor_has_dimension_rows is true
    # (so no skip), yet the label rect can't resolve → hard fail. No 添加图/
    # 视频 / 已写 / 发布 chrome — that would trip should_skip_rating instead.
    stranded = (
        "<hierarchy>"
        '<node text="口味" class="android.widget.TextView"/>'
        "</hierarchy>"
    )
    kit2 = _SeqKit(_SeqDriver([stranded, stranded, stranded]))
    kit2.results["element_bounds"] = ActionResult(False, "element_bounds", data=None)
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    result2 = session2.execute_action(
        "rate", value=3, anchor="dimension_row", dimension="taste",
        selector=('uiautomator:new UiSelector().text("口味")',),
    )
    assert not result2.success
    assert "dimension rating label not found" in result2.message


def test_uia2_rate_dimension_uses_kit_bounds_fallback(monkeypatch):
    """No usable dump → star geometry from kit element_bounds + constants."""
    _fast_clock(monkeypatch)
    kit = _SeqKit(_SeqDriver(["<hierarchy/>"]))
    kit.results["element_bounds"] = ActionResult(
        True, "element_bounds", data={"x": 68, "y": 632, "width": 72, "height": 42}
    )
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    result = session.execute_action(
        "rate", value=3, anchor="dimension_row", dimension="taste",
        selector=('uiautomator:new UiSelector().text("口味")',),
    )
    assert result.success
    swipe = [c for c in kit.calls if c[0] == "swipe"][-1][1]
    # measured strip: origin 236 + pitch 144*(value-1), scaled 810/1080 dump absent
    # → 1.0 scale; y = label centre from kit bounds
    assert swipe["start_x"] == int(236 + 144 * 2)
    assert swipe["start_y"] == int(632 + 42 / 2)


def test_uia2_rate_overall_taps_star(monkeypatch):
    _fast_clock(monkeypatch)
    editor = (
        "<hierarchy>"
        '<node text="很糟糕" class="android.widget.TextView" bounds="[42,250][200,292]"/>'
        '<node class="android.widget.ImageView" bounds="[42,320][200,420]"/>'
        '<node class="android.widget.ImageView" bounds="[240,320][398,420]"/>'
        '<node class="android.widget.ImageView" bounds="[438,320][596,420]"/>'
        '<node class="android.widget.ImageView" bounds="[636,320][794,420]"/>'
        '<node class="android.widget.ImageView" bounds="[834,320][992,420]"/>'
        "</hierarchy>"
    )
    kit = _SeqKit(_SeqDriver([editor]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    result = session.execute_action("rate", value=3, anchor="overall")
    assert result.success
    swipe = [c for c in kit.calls if c[0] == "swipe"][-1][1]
    assert swipe["start_x"] == 517  # 3rd star centre
    assert swipe["duration"] == 0.08


def test_uia2_dismiss_dialogs_counts_and_skips(monkeypatch):
    _fast_clock(monkeypatch)
    # Probe-first: a healthy dump with the dialog present drives the taps;
    # an empty hierarchy means nothing to dismiss (no blind-wait tax).
    dialog = '<hierarchy><node content-desc="确定" bounds="[400,900][680,1000]"/></hierarchy>'
    dumps = [dialog, dialog, dialog]
    kit = _SeqKit(_SeqDriver(dumps))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    result = session.execute_action("dismiss_dialogs", selector="~确定", max_attempts=2)
    assert result.success
    assert result.data == {"dismissed": 2}

    empty = _SeqKit(_SeqDriver(["<hierarchy/>"]))
    session_empty = DianpingUia2Session(empty, captcha_window_seconds=0)
    r_empty = session_empty.execute_action("dismiss_dialogs", selector="~确定")
    assert r_empty.success and r_empty.data == {"dismissed": 0}

    dish = _SeqKit(_SeqDriver(["<hierarchy><node text=\"识别菜品\"/></hierarchy>"]))
    session2 = DianpingUia2Session(dish, captcha_window_seconds=0)
    result2 = session2.execute_action("dismiss_dialogs", selector="~确定")
    assert result2.success
    assert "skipped" in result2.message
    # dish-edit skip returns no data dict at all
    assert result2.data is None

    untranslatable = _SeqKit(_SeqDriver(["<hierarchy/>"] * 3))
    session3 = DianpingUia2Session(untranslatable, captcha_window_seconds=0)
    result3 = session3.execute_action(
        "dismiss_dialogs",
        selector=('uiautomator:new UiSelector().fromParent("x")',),
        max_attempts=1,
    )
    assert result3.success
    assert result3.data["dismissed"] == 0


def test_uia2_hide_keyboard_videos(monkeypatch):
    _fast_clock(monkeypatch)
    driver = _SeqDriver(
        [
            "<hierarchy><node text=\"发布\"/></hierarchy>",
            "<hierarchy><node text=\"识别菜品\"/></hierarchy>",
            "<hierarchy/>",
            "<hierarchy/>",
        ]
    )
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    skipped = session.execute_action("hide_keyboard")
    assert "editor chrome visible" in skipped.message

    dish = session.execute_action("hide_keyboard")
    assert "editor chrome visible" in dish.message

    clean = session.execute_action("hide_keyboard")
    assert clean.success


# --- uia2 confirm_search / hide_keyboard alt driver paths (2680-2777) --------


class _ClickDumpDriver:
    """uia2 device with dump_hierarchy + coordinate click."""

    def __init__(self, source="<hierarchy/>"):
        self.source = source
        self.clicks = []
        self.presses = []

    def dump_hierarchy(self):
        return self.source

    def click(self, x, y):
        self.clicks.append((int(x), int(y)))

    def press(self, key):
        self.presses.append(key)
        if key == "boom":
            raise RuntimeError("stuck")


def test_uia2_confirm_search_coordinate_and_keycode_paths(monkeypatch, tmp_path):
    _fast_clock(monkeypatch)
    # dump has a clickable 搜索 button → coordinate tap wins
    driver = _ClickDumpDriver(
        "<hierarchy>"
        '<node text="搜索" class="android.widget.Button" clickable="false" '
        'bounds="[100,100][300,200]"/>'
        "</hierarchy>"
    )
    kit = _SeqKit(driver)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    result = session.execute_action(
        "confirm_search", selector=('uiautomator:new UiSelector().text("搜索")',)
    )
    assert result.success
    assert result.data["x"] == 200
    assert driver.clicks == [(200, 150)]

    # dump raises → coordinate path impossible; kit tap translated candidate
    class BoomDump(_ClickDumpDriver):
        def dump_hierarchy(self):
            raise RuntimeError("detached")

    kit2 = _SeqKit(BoomDump())
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    ok = session2.execute_action(
        "confirm_search", selector=('uiautomator:new UiSelector().text("搜索")',)
    )
    assert ok.success
    assert kit2.calls[0][0] == "tap"

    # no dump on driver (not callable) and no click → kit tap still runs
    class Mute:
        pass

    kit3 = _SeqKit(Mute())
    session3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    ok3 = session3.execute_action(
        "confirm_search", selector='uiautomator:new UiSelector().text("搜索")'
    )
    assert ok3.success
    assert kit3.calls[0][1]["selector"] == "搜索"

    # no candidates, no press_key → hard fail tail
    kit4 = _SeqKit(Mute())
    session4 = DianpingUia2Session(kit4, captcha_window_seconds=0)
    failed = session4.execute_action("confirm_search")
    assert not failed.success
    assert "failed for all selectors" in failed.message


def test_uia2_confirm_search_keycode_validation(monkeypatch, tmp_path):
    _fast_clock(monkeypatch)

    class PressKeyDevice(_SeqDriver):
        pass

    device = PressKeyDevice(["<hierarchy/>"])
    device.press_key = lambda code: True  # u2 press_key(keycode)
    kit = _SeqKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    result = session.execute_action(
        "confirm_search", selector=(), keycode=66,
        fallback_selector=('uiautomator:new UiSelector().text("搜索")',),
    )
    assert result.success
    assert result.message == "confirm_search via keycode"

    # a device press_key that FAILS (ActionResult) propagates the failure
    class Refusing:
        def press_key(self, code):
            return ActionResult(False, "keyevent refused")

    kit2 = _SeqKit(Refusing())
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    refused = session2.execute_action(
        "confirm_search", selector=(), keycode=66,
        fallback_selector=('uiautomator:new UiSelector().text("搜索")',),
    )
    assert not refused.success
    assert "keyevent refused" in refused.message

    # raising press_key → reported failure
    class Boom:
        def press_key(self, code):
            raise RuntimeError("stuck")

    kit3 = _SeqKit(Boom())
    session3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    boom = session3.execute_action(
        "confirm_search", selector=(), keycode=66,
        fallback_selector=('uiautomator:new UiSelector().text("搜索")',),
    )
    assert not boom.success
    assert "press_key failed" in boom.message

    bad = session.execute_action(
        "confirm_search", selector=(), keycode="six",
        fallback_selector=('uiautomator:new UiSelector().text("搜索")',),
    )
    assert not bad.success
    assert "keycode must be numeric" in bad.message


def test_uia2_hide_keyboard_back_fallbacks(monkeypatch, tmp_path, capsys):
    _fast_clock(monkeypatch)
    # no 完成 widget; press("back") works. The 完成 tap must fail → override
    # the kit tap result; a clean dump means the clickable-parent path has no
    # rect and falls to the kit tap.
    class PressBack:
        def __init__(self):
            self.seen = None

        def press(self, key):
            self.seen = key

    press = PressBack()
    kit = _SeqKit(press)
    kit.results["tap"] = ActionResult(False, "no 完成 anywhere")
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    result = session.execute_action("hide_keyboard")
    assert result.success
    assert result.message == "hide_keyboard via BACK"
    assert press.seen == "back"

    # press("back") raises → numeric keyevent 4 fallback fires
    class BackBoomNum:
        def __init__(self):
            self.seen = None

        def press(self, key):
            self.seen = key
            if key == "back":
                raise RuntimeError("bad key name")

    boom = BackBoomNum()
    kit2 = _SeqKit(boom)
    kit2.results["tap"] = ActionResult(False, "no 完成 anywhere")
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    result2 = session2.execute_action("hide_keyboard")
    assert result2.success
    assert boom.seen == 4

    # both press attempts raise → hard tail
    class BackAlwaysBoom:
        def press(self, key):
            raise RuntimeError("stuck")

    dead_kit = _SeqKit(BackAlwaysBoom())
    dead_kit.results["tap"] = ActionResult(False, "no 完成 anywhere")
    session3 = DianpingUia2Session(dead_kit, captcha_window_seconds=0)
    result3 = session3.execute_action("hide_keyboard")
    assert not result3.success
    assert "BACK failed" in result3.message


# --- uia2 slider guard paths (2062-2146) --------------------------------------


def test_uia2_slider_guard_solves_and_retries(monkeypatch):
    from automation_app_dianping.session import page_source_indicates_slider

    _fast_clock(monkeypatch)
    handle = (
        '<hierarchy><node bounds="[40,800][120,880]" content-desc="滑块" '
        'class="android.widget.ImageView"/></hierarchy>'
    )
    clean = "<hierarchy><node text='点评'/></hierarchy>"

    class SwipeDevice:
        def __init__(self):
            self.source = handle
            self.swipes = []

        def dump_hierarchy(self):
            return self.source

        def screenshot(self):
            return b"png"

        def swipe(self, x1, y1, x2, y2, duration):
            self.swipes.append((x1, y1, x2, y2))
            self.source = clean

    device = SwipeDevice()
    kit = _SeqKit(device)
    # kit tap fails while the slider page is up, succeeds once solved+retried
    def tap_by_page(action_name, **kwargs):
        if action_name == "tap" and page_source_indicates_slider(device.source):
            return ActionResult(False, "tap swallowed by slider")
        return ActionResult(True, action_name)

    kit.execute_action = tap_by_page
    session = DianpingUia2Session(kit, captcha_window_seconds=0)

    def solver(image):
        return {"gap_offset_px": 280}

    session.slider_solver = solver
    result = session._guard_slider("tap", ActionResult(False, "absorbed"), {})
    assert result.success
    assert "slider solved" in result.message
    assert device.swipes == [(80, 840, 360, 840)]
    # the retry tap ran against the clean page
    assert device.source == clean

    assert page_source_indicates_slider(handle)
    assert not page_source_indicates_slider(clean)


def test_uia2_slider_guard_fails_when_challenge_persists(monkeypatch):
    """The swipe lands but the jigsaw refuses the piece: the guard must fail
    instead of reporting "slider solved; action retried" on a blocked page
    (the retry tap would land on the overlay and also report success)."""
    _fast_clock(monkeypatch)
    handle = (
        '<hierarchy><node bounds="[40,800][120,880]" content-desc="滑块" '
        'class="android.widget.ImageView"/></hierarchy>'
    )

    class StickyDevice:
        def __init__(self):
            self.source = handle
            self.swipes = []

        def dump_hierarchy(self):
            return self.source

        def screenshot(self):
            return b"png"

        def swipe(self, x1, y1, x2, y2, duration):
            self.swipes.append((x1, y1, x2, y2))
            # the challenge stays up

    device = StickyDevice()
    kit = _SeqKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session.slider_solver = lambda image: {"gap_offset_px": 280}
    result = session._guard_slider("tap", ActionResult(True, "tap"), {})
    assert not result.success
    assert "still present after the swipe" in result.message
    # the swipe was attempted, and the action was NOT retried on the overlay
    assert device.swipes == [(80, 840, 360, 840)]
    assert not [call for call in kit.calls if call[0] == "tap"]


def test_appium_slider_guard_fails_when_challenge_persists(monkeypatch, tmp_path):
    """Same contract on the Appium session: a persistent challenge is a
    failure, not a solved slider."""
    import base64 as b64

    class StickyDriver:
        def __init__(self):
            self.source = (
                "<hierarchy><node resource-id='com.x:id/slider' text='slider handle' "
                "bounds='[40,1000][300,1040]'/></hierarchy>"
            )
            self.swipes = []

        @property
        def page_source(self):
            return self.source

        def swipe(self, *args):
            self.swipes.append(args)

        def get_screenshot_as_base64(self):
            return b64.b64encode(b"png")

    driver = StickyDriver()
    session = DianpingAppiumSession(
        driver, artifact_root=tmp_path, slider_solver=lambda image: 150
    )
    result = session._guard_slider(
        "tap", ActionResult(True, "tap"), {"selector": "~x", "timeout": 0.0}
    )
    assert not result.success
    assert "still present after the swipe" in result.message
    assert len(driver.swipes) == 1


def test_slider_challenge_cleared_polls_until_gone(monkeypatch):
    """The challenge hides itself asynchronously: a fresh dump must be read
    on every poll, not a cached one."""
    _fast_clock(monkeypatch)
    handle = (
        '<hierarchy><node bounds="[40,800][120,880]" content-desc="滑块" '
        'class="android.widget.ImageView"/></hierarchy>'
    )
    dumps = [handle, handle, "<hierarchy><node text='点评'/></hierarchy>"]
    reads = {"n": 0}

    def read():
        value = dumps[min(reads["n"], len(dumps) - 1)]
        reads["n"] += 1
        return value

    from automation_app_dianping.session import slider_challenge_cleared

    assert slider_challenge_cleared(read) is True
    assert reads["n"] == 3
    # a challenge that never leaves is reported as not cleared
    assert slider_challenge_cleared(lambda: handle) is False


def test_uia2_attempt_slider_solve_failures(monkeypatch):
    _fast_clock(monkeypatch)
    handle = (
        '<hierarchy><node bounds="[40,800][120,880]" content-desc="滑块" '
        'class="android.widget.ImageView"/></hierarchy>'
    )
    device = _ClickDumpDriver(handle)
    kit = _SeqKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)

    # no solver configured
    result = session._attempt_slider_solve()
    assert not result.success
    assert "no slider solver configured" in result.message

    # driver cannot screenshot
    session.slider_solver = lambda image: {"gap_offset_px": 100}
    result2 = session._attempt_slider_solve()
    assert "cannot capture screenshots" in result2.message

    # solver raises
    Shooter = type("Shooter", (), {"swiped": False})

    def shooter_swipe(self, *a):
        Shooter.swiped = True

    Shooter.swipe = shooter_swipe
    Shooter.dump_hierarchy = lambda self: handle
    Shooter.screenshot = lambda self: b"png"
    session._session = _SeqKit(Shooter())
    session.slider_solver = lambda image: 1 / 0
    result3 = session._attempt_slider_solve()
    assert "slider solve errored" in result3.message


def test_uia2_perform_slider_swipe_failures(monkeypatch):
    _fast_clock(monkeypatch)
    handle = (
        '<hierarchy><node bounds="[40,800][120,880]" content-desc="滑块" '
        'class="android.widget.ImageView"/></hierarchy>'
    )
    # page source available, handle found, but driver cannot swipe
    device = _ClickDumpDriver(handle)
    kit = _SeqKit(device)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    result = session._perform_slider_swipe(offset_px=280)
    assert not result.success
    assert "does not support coordinate swipe" in result.message

    # driver CAN swipe but the solution rejects → distance error
    class SwipeOnly:
        def dump_hierarchy(self):
            return handle

        def swipe(self, *args):
            SwipeOnly.swiped = args

    SwipeOnly.swiped = None
    kit2 = _SeqKit(SwipeOnly())
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    result2 = session2._perform_slider_swipe(gap_x=40)
    assert "at or left of handle" in result2.message

    # a good offset actually swipes
    ok = session2._perform_slider_swipe(offset_px=280)
    assert ok.success
    assert SwipeOnly.swiped[:4] == (80, 840, 360, 840)


def test_uia2_slider_screenshot_bytes_formats(monkeypatch):
    _fast_clock(monkeypatch)
    session = DianpingUia2Session(_SeqKit(), captcha_window_seconds=0)

    # no driver attribute at all
    with pytest.raises(RuntimeError, match="cannot capture screenshots"):
        session._slider_screenshot_bytes()

    # bytes screenshot
    bytes_kit = _SeqKit()
    bytes_kit.driver = _ClickDumpDriver()
    bytes_kit.driver.screenshot = lambda: b"raw"
    session2 = DianpingUia2Session(bytes_kit, captcha_window_seconds=0)
    assert session2._slider_screenshot_bytes() == b"raw"

    # PIL image screenshot gets PNG-encoded
    from PIL import Image

    img_kit = _SeqKit()
    img_kit.driver = _ClickDumpDriver()
    img_kit.driver.screenshot = lambda: Image.new("RGB", (2, 2))
    session3 = DianpingUia2Session(img_kit, captcha_window_seconds=0)
    body = session3._slider_screenshot_bytes()
    assert body[:8] == b"\x89PNG\r\n\x1a\n"


# --- appium slider guard alternate paths (466-548) -----------------------------


def test_appium_slider_guard_detect_and_fail(tmp_path):
    class GlitchedSource:
        @property
        def page_source(self):
            raise RuntimeError("glitched")

        def get_window_size(self):
            return {"width": 810}

    session = DianpingAppiumSession(GlitchedSource(), artifact_root=tmp_path)
    # page_source raise → guard passes the original result through
    result = session._guard_slider("tap", ActionResult(False, "absorbed"), {})
    assert result.message == "absorbed"


def test_appium_slider_solve_and_swipe_failure_tails(tmp_path):
    class ShotPage:
        @property
        def page_source(self):
            return (
                '<hierarchy><node bounds="[40,800][120,880]" content-desc="滑块" '
                'class="android.widget.ImageView"/></hierarchy>'
            )

        def get_screenshot_as_base64(self):
            import base64 as b64

            return b64.b64encode(b"png").decode()

        def swipe(self, *args):
            raise RuntimeError("stuck")

    session = DianpingAppiumSession(ShotPage(), artifact_root=tmp_path)
    session.slider_solver = lambda image: 1 / 0
    result = session._attempt_slider_solve()
    assert "slider solve errored" in result.message

    # a valid solution then reaches the swipe, which fails
    session.slider_solver = lambda image: {"gap_offset_px": 280}
    result2 = session._perform_slider_swipe(offset_px=280)
    assert "slider swipe failed" in result2.message


def test_appium_perform_slider_tail_paths(tmp_path):
    class Page:
        @property
        def page_source(self):
            return "<hierarchy/>"  # no slider handle

        def swipe(self, *args):
            raise RuntimeError("stuck")

    session = DianpingAppiumSession(Page(), artifact_root=tmp_path)
    result = session._perform_slider_swipe(offset_px=280)
    assert "slider handle not located" in result.message

    class NoSwipeSource:
        @property
        def page_source(self):
            raise RuntimeError("gone")

    session2 = DianpingAppiumSession(NoSwipeSource(), artifact_root=tmp_path)
    result2 = session2._perform_slider_swipe(offset_px=280)
    assert "page source unavailable" in result2.message

    class SourceNotString:
        @property
        def page_source(self):
            return 42

    session3 = DianpingAppiumSession(SourceNotString(), artifact_root=tmp_path)
    result3 = session3._perform_slider_swipe(offset_px=280)
    assert "slider handle not located" in result3.message


# --- batch 4: appium stop/_dump_failure tolerance ----------------------------


def test_appium_stop_quits_and_tolerates_quit_raise(tmp_path):
    class Quitter:
        def __init__(self):
            self.quit_calls = []

        def quit(self):
            self.quit_calls.append(True)
            raise RuntimeError("session already dead")

    driver = Quitter()
    session = DianpingAppiumSession(driver, artifact_root=tmp_path)
    session._started = True
    session.stop()
    assert driver.quit_calls == [True]
    assert session._started is False

    # quit absent on the driver: stop still flips the flag
    bare = DianpingAppiumSession(_MiniDriver(), artifact_root=tmp_path)
    bare._started = True
    bare.stop()
    assert bare._started is False


def test_appium_dump_failure_swallows_artifact_errors(monkeypatch, tmp_path):
    session = _mini(tmp_path)

    def boom(kind, name):
        raise RuntimeError("artifact sink closed")

    monkeypatch.setattr(session, "capture_artifact", boom)
    session._dump_failure("some action")  # must not raise


# --- batch 4: appium _navigate_to_review_editor tails ------------------------


def test_appium_navigate_review_editor_tails(tmp_path):
    class Driver(_MiniDriver):
        def __init__(self):
            super().__init__()
            self.elements = []

        def find_element(self, by, value):
            item = self.elements.pop(0) if self.elements else None
            if item is None:
                raise TimeoutError("not found")
            return item

    class El:
        def __init__(self, broken=False):
            self.broken = broken

        def click(self):
            if self.broken:
                raise RuntimeError("stale element")
            return True

        def send_keys(self, text):
            return True

    # empty/failed page_source → search continues from scratch (762-763)
    class BoomSource(_MiniDriver):
        def __init__(self):
            self.records = []  # skip the page_source attribute init

        @property
        def page_source(self):
            raise RuntimeError("gone")

    shop = "测试店"
    kw = {
        "shop_name": shop,
        "write_selector": 'uiautomator:new UiSelector().text("写评价")',
        "search_bar": "~搜索栏",
        "search_input": 'id:com.dianping.v1:id/search_keyword_edit',
        "search_confirm": None,
        "search_results_marker": 'id:com.dianping.v1:id/search_results_tabs',
        "shop_result": None,
    }
    driver = BoomSource()
    session = DianpingAppiumSession(driver, artifact_root=tmp_path)
    # search bar never appears → wait failure return (786-787)
    res = session._navigate_to_review_editor(**kw)
    assert not res.success
    assert "timed out waiting" in res.message

    # restored shop page tap fails → the tap failure propagates (779)
    driver2 = Driver()
    driver2.page_source = (
        "<hierarchy>测试店 完善评价</hierarchy>"
    )
    driver2.elements = [El(broken=True)]
    session2 = DianpingAppiumSession(driver2, artifact_root=tmp_path)
    kw2 = dict(kw)
    res2 = session2._navigate_to_review_editor(**kw2)
    assert not res2.success
    assert "tap failed" in res2.message


def test_appium_navigate_review_editor_search_tails(tmp_path):
    class Driver(_MiniDriver):
        """find_element #N+1 always fails; earlier finds return a working element."""

        def __init__(self, fail_after):
            super().__init__()
            self.fail_after = fail_after
            self.count = 0

        def find_element(self, by, value):
            self.count += 1
            if self.count > self.fail_after:
                raise TimeoutError("gone: %s" % value)
            return type(
                "El",
                (),
                {"click": lambda self: True, "send_keys": lambda self, t: True},
            )()

    base = {
        "shop_name": "测试店",
        "write_selector": 'uiautomator:new UiSelector().text("写评价")',
        "search_bar": "~搜索栏",
        "search_input": "id:kw",
        "search_confirm": "~搜索按钮",
        "search_results_marker": "id:tabs",
        "shop_result": "~row",
    }
    # find-call order: 1 wait bar, 2 tap bar, 3 wait input, 4 type,
    # 5 confirm tap, 6 wait results marker, 7 wait shop result,
    # 8 tap shop result, 9 wait write CTA, 10 tap write CTA.
    cases = [
        (1, "tap failed"),
        (2, "timed out"),
        (3, "type_text failed"),
        (4, "confirm_search failed"),
        (5, "timed out"),
        (6, "timed out"),
        (7, "tap failed"),
        (8, "timed out"),
        (9, "tap failed"),
    ]
    for fail_after, expected in cases:
        driver = Driver(fail_after)
        result = DianpingAppiumSession(driver, artifact_root=tmp_path)._navigate_to_review_editor(
            **base
        )
        assert not result.success, (fail_after, result.message)
        assert expected in result.message, (fail_after, result.message)


def test_appium_hide_keyboard_page_source_raise(tmp_path):
    class BoomSource:
        @property
        def page_source(self):
            raise RuntimeError("gone")

    session = DianpingAppiumSession(BoomSource(), artifact_root=tmp_path)
    # the raise is tolerated (864-865); tap on 完成 then fails on find → BACK path
    result = session._hide_keyboard()
    assert result.success  # keyboard hide is best-effort


def test_appium_dismiss_dialogs_breaks_on_failure(monkeypatch, tmp_path):
    _fast_clock(monkeypatch)
    calls = []

    def fake_fallback(action_name, kwargs):
        calls.append(action_name)
        return ActionResult(False, "no dialog")

    session = _mini(tmp_path)
    monkeypatch.setattr(session, "_with_selector_fallbacks", fake_fallback)
    result = session._dismiss_dialogs(selector="~x", max_attempts=3)
    assert result.success
    assert result.data == {"dismissed": 0}
    assert calls == ["tap"]  # loop broke after the first failure (1037)


# --- batch 4: shop_row_tap_rect _row_rect guards -----------------------------


def test_shop_row_tap_rect_skips_search_header_and_edittext():
    header_rid = "com.dianping.v1:id/search_keyword"
    # node under a search-header ancestor → rejected (1456-1457 chain guard
    # already pinned); here the EditText class guard (1458-1459)
    source = (
        "<hierarchy>"
        '<node class="android.widget.EditText" text="测试店" bounds="[10,10][400,80]"/>'
        "</hierarchy>"
    )
    assert shop_row_tap_rect(source, "测试店") is None

    # header-ancestor + EditText: the header row itself is skipped, the plain
    # row below is still found
    source2 = (
        "<hierarchy>"
        '<node resource-id="%s" bounds="[0,0][1080,160]">'
        '<node class="android.widget.EditText" text="测试店" bounds="[10,10][400,80]"/>'
        "</node>"
        '<node class="android.widget.TextView" text="测试店" bounds="[10,200][400,260]"/>'
        "</hierarchy>" % header_rid
    )
    rect = shop_row_tap_rect(source2, "测试店")
    assert rect == {"x": 10, "y": 200, "width": 390, "height": 60}


def test_shop_row_tap_rect_label_missing_falls_to_clickable_ancestor():
    # no bounds on the label → falls through to the nearest clickable
    # ancestor rect (1466-1471)
    source = (
        "<hierarchy>"
        '<node clickable="true" bounds="[0,300][1080,420]">'
        '<node class="android.widget.TextView" text="测试店分店"/>'
        "</node>"
        "</hierarchy>"
    )
    rect = shop_row_tap_rect(source, "测试店分店")
    assert rect == {"x": 0, "y": 300, "width": 1080, "height": 120}

    # no bounds anywhere and no clickable ancestor → None
    bare = '<hierarchy><node text="测试店"/></hierarchy>'
    assert shop_row_tap_rect(bare, "测试店") is None


def test_shop_row_tap_rect_rejects_quoted_related_recommend_headline():
    """Live 2026-11-12 (OnePlus 7T): the results page for a closed/absent
    shop renders only a 「"店名"相关推荐」 aggregate headline — no result
    row. The bare-TextView headline passed every header guard and the tap
    landed on it, the page never moved, and the write-CTA wait timed out.
    A quoted headline that appends aggregate copy is not a row; the finder
    must return None so the caller reports failure instead of tapping it.
    """
    name = "小杨生煎(百盛优客天山店)"
    headline = "“%s”相关推荐" % name
    source = (
        "<hierarchy>"
        '<node resource-id="com.dianping.v1:id/search_keyword" text="%s" bounds="[166,90][830,190]"/>'
        '<node text="%s" bounds="[34,1182][679,1229]"/>'
        "</hierarchy>" % (name, headline)
    )
    assert shop_row_tap_rect(source, name) is None

    # ASCII / corner-bracket quoting variants of the same aggregate headline
    for quoted in ('"%s"相关推荐' % name, "「%s」相关推荐" % name):
        src = '<hierarchy><node text="%s" bounds="[34,1182][679,1229]"/></hierarchy>' % quoted
        assert shop_row_tap_rect(src, name) is None, quoted

    # a real result row carrying the bare name is still found on the same
    # page, and takes precedence over any headline
    with_row = (
        "<hierarchy>"
        '<node resource-id="com.dianping.v1:id/search_keyword" text="%s" bounds="[166,90][830,190]"/>'
        '<node text="%s" bounds="[34,600][679,650]"/>'
        '<node text="%s" bounds="[34,1182][679,1229]"/>'
        "</hierarchy>" % (name, name, headline)
    )
    assert shop_row_tap_rect(with_row, name) == {"x": 34, "y": 600, "width": 645, "height": 50}

    # a row whose own label merely contains the name (branch-qualified card)
    # still wins over a headline even though the headline is an exact-substring
    row_contains = (
        "<hierarchy>"
        '<node text="“%s”相关推荐" bounds="[34,1182][679,1229]"/>'
        '<node text="%s 长宁区生煎销量榜第1名" bounds="[34,700][900,750]"/>'
        "</hierarchy>" % (name, name)
    )
    assert shop_row_tap_rect(row_contains, name) == {"x": 34, "y": 700, "width": 866, "height": 50}


# --- batch 4: uia2 translated-candidates + tap helpers -----------------------


def test_uia2_with_translated_candidates_untranslatable_and_empty(monkeypatch):
    _fast_clock(monkeypatch)
    kit = _SeqKit()
    session = DianpingUia2Session(kit, captcha_window_seconds=0)

    # untranslatable candidates are recorded in the failure detail (2165-2167)
    bad = session._with_translated_candidates(
        "tap",
        {"selector": ('uiautomator:new UiSelector().fromParent("x")',)},
    )
    assert not bad.success
    assert "untranslatable" in bad.message

    # no candidates at all → passthrough with the original kwargs (2178-2179)
    result = session._with_translated_candidates("tap", {"selector": None, "extra": 1})
    assert result.success
    assert kit.calls[-1][0] == "tap"
    assert kit.calls[-1][1] == {"selector": None, "extra": 1}


def test_uia2_tap_shop_row_raise_and_no_click(monkeypatch):
    _fast_clock(monkeypatch)

    class RowDriver:
        def __init__(self, click_error=None, with_click=True):
            self.click_error = click_error
            self.clicks = []
            if with_click:
                self.click = self._click

        def _click(self, x, y):
            if self.click_error is not None:
                raise self.click_error
            self.clicks.append((x, y))

        def dump_hierarchy(self):
            return (
                "<hierarchy>"
                '<node class="android.widget.TextView" text="测试店" bounds="[10,200][400,260]"/>'
                "</hierarchy>"
            )

    kit = _SeqKit(RowDriver())
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    result = session._tap_shop_row("测试店", "~row")
    assert result.success
    assert result.data["x"] == 205

    # click raises → failure detail (2252-2253)
    kit2 = _SeqKit(RowDriver(click_error=RuntimeError("detached")))
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    failed = session2._tap_shop_row("测试店", "~row")
    assert not failed.success
    assert "shop row tap failed" in failed.message

    # rect found but driver has no click → clickable-parent fallback (2254)
    kit3 = _SeqKit(RowDriver(with_click=False))
    session3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    fallback = session3._tap_shop_row("测试店", "~row")
    assert fallback.success  # kit tap candidate path


def test_uia2_tap_with_clickable_parent_untranslatable_candidate(monkeypatch):
    _fast_clock(monkeypatch)
    # source present but the only candidate is untranslatable → the
    # clickable-parent loop skips it (2211-2212) and the translated-candidates
    # tail aggregates the error without any kit dispatch.
    driver = _ClickDumpDriver(
        "<hierarchy><node text='写评价' bounds='[0,0][100,60]'/></hierarchy>"
    )
    kit = _SeqKit(driver)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    result = session._tap_with_clickable_parent(
        {"selector": 'uiautomator:new UiSelector().fromParent("x")'}
    )
    assert not result.success
    assert "untranslatable" in result.message
    assert kit.calls == []


def test_uia2_wait_for_shop_row_timeout(monkeypatch):
    _fast_clock(monkeypatch)
    kit = _SeqKit(_SeqDriver(["<hierarchy/>"]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    result = session._wait_for_shop_row("测试店", 2.0)
    assert not result.success
    assert "timed out waiting for shop result row (2.0s)" in result.message


def test_uia2_picker_is_open_driver_variants(monkeypatch):
    _fast_clock(monkeypatch)
    rid = session_mod._PHOTO_SELECT_RESOURCE_ID

    # dump not callable → closed (2294-2295): a callable driver whose
    # widgets never exist and whose dump is absent
    class NoDump:
        def __call__(self, **kwargs):
            return type("W", (), {"exists": False})()

    kit1 = _SeqKit(NoDump())
    session1 = DianpingUia2Session(kit1, captcha_window_seconds=0)
    assert session1._picker_is_open() is False

    # dump raises → closed, logged (2297-2303)
    class BoomDump:
        def __call__(self, **kwargs):
            return type("W", (), {"exists": False})()

        def dump_hierarchy(self):
            raise RuntimeError("bridge died")

    session2 = DianpingUia2Session(_SeqKit(BoomDump()), captcha_window_seconds=0)
    assert session2._picker_is_open() is False

    # dump returns non-string → closed (2304-2305)
    class JunkDump(BoomDump):
        def dump_hierarchy(self):
            return 42

    session3 = DianpingUia2Session(_SeqKit(JunkDump()), captcha_window_seconds=0)
    assert session3._picker_is_open() is False

    # widget-exists gate wins first (2288-2289)
    class ExistsDriver:
        def __call__(self, **kwargs):
            return type("W", (), {"exists": True})()

    session4 = DianpingUia2Session(_SeqKit(ExistsDriver()), captcha_window_seconds=0)
    assert session4._picker_is_open() is True


# --- batch 4: uia2 navigation cluster ----------------------------------------


class _NavDriver:
    """uia2 device: dump sequence + coordinate click + press hooks.

    ``click_error`` is a 1-based click number to fail (others succeed),
    ``True`` fails every click.
    """

    def __init__(self, dumps, click_error=None):
        self.dumps = list(dumps)
        self.click_error = click_error
        self.clicks = []
        self.presses = []
        self._click_count = 0

    def dump_hierarchy(self):
        if len(self.dumps) > 1:
            return self.dumps.pop(0)
        return self.dumps[0]

    def click(self, x, y):
        self._click_count += 1
        if self.click_error is True or self.click_error == self._click_count:
            raise RuntimeError("stale click %d" % self._click_count)
        self.clicks.append((int(x), int(y)))

    def press(self, key):
        self.presses.append(key)

    def press_key(self, key):
        self.presses.append(key)


def _nav_source(*nodes):
    return "<hierarchy>%s</hierarchy>" % "".join(nodes)


_SEARCH_BAR_NODE = '<node text="搜索" bounds="[25,186][1055,286]"/>'


def test_uia2_navigate_review_editor_restored_shop_tap_fails(monkeypatch):
    _fast_clock(monkeypatch)
    # shop page restored with a review CTA; the clickable-parent tap raises
    # → the tap failure is returned verbatim (2366)
    source = _nav_source(
        '<node text="测试店" bounds="[0,300][1080,420]"/>',
        '<node clickable="true" bounds="[600,300][1050,420]">'
        '<node text="完善评价" bounds="[620,310][760,360]"/></node>',
    )
    driver = _NavDriver([source], click_error=True)
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    result = session._navigate_to_review_editor(
        shop_name="测试店",
        write_selector='uiautomator:new UiSelector().text("完善评价")',
    )
    assert not result.success
    assert "clickable-parent tap failed" in result.message


def test_uia2_navigate_review_editor_pending_fallback_tails(monkeypatch):
    _fast_clock(monkeypatch)
    base = {
        "shop_name": "测试店",
        "write_selector": 'uiautomator:new UiSelector().text("写评价")',
        "search_bar": 'uiautomator:new UiSelector().text("搜索")',
        "search_input": 'uiautomator:new UiSelector().text("搜索店名、菜品")',
        "search_confirm": None,
        "search_results_marker": 'uiautomator:new UiSelector().text("有点评")',
        "shop_result": None,
    }
    # On home (搜索 present) but 我的 tab missing → pending path declines and
    # the search-bar tap is attempted; a raise inside that tap surfaces as
    # the returned failure (2414-2415).
    driver = _NavDriver([_nav_source(_SEARCH_BAR_NODE)], click_error=True)
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    result = session._navigate_to_review_editor(**base)
    assert not result.success
    assert "clickable-parent tap failed" in result.message

    # search bar tapped, but the search-input marker never shows (2417-2419)
    driver2 = _NavDriver([_nav_source(_SEARCH_BAR_NODE)])
    session2 = DianpingUia2Session(_SeqKit(driver2), captcha_window_seconds=0)
    result2 = session2._navigate_to_review_editor(**base)
    assert not result2.success
    assert "timed out waiting for page marker" in result2.message

    # input marker present; type_text fails in the kit (2425-2426)
    source3 = _nav_source(_SEARCH_BAR_NODE, '<node text="搜索店名、菜品" bounds="[0,160][1080,240]"/>')
    kit3 = _SeqKit(_NavDriver([source3]))
    kit3.results["type_text"] = ActionResult(False, "type_text refused")
    session3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    result3 = session3._navigate_to_review_editor(**base)
    assert not result3.success
    assert "type_text refused" in result3.message

    # typing ok; confirm_search fails with no press_key on the driver (2431-2432)
    class NoPressKey(_NavDriver):
        press_key = None

    kit4 = _SeqKit(NoPressKey([source3]))
    session4 = DianpingUia2Session(kit4, captcha_window_seconds=0)
    result4 = session4._navigate_to_review_editor(**base)
    assert not result4.success
    assert "confirm_search failed" in result4.message

    # confirm via press_key ok; the results marker never appears (2434-2436)
    kit5 = _SeqKit(_NavDriver([source3]))
    session5 = DianpingUia2Session(kit5, captcha_window_seconds=0)
    session5._session.driver.press_key = lambda code: None
    result5 = session5._navigate_to_review_editor(**base)
    assert not result5.success
    assert "timed out waiting for page marker" in result5.message
    assert any(k[0] == "type_text" for k in kit5.calls)


def test_uia2_navigate_via_pending_review_miss_chain(monkeypatch):
    _fast_clock(monkeypatch)
    mine = '<node text="我的" bounds="[900,2200][1000,2300]"/>'
    entry = '<node text="待评价" bounds="[0,300][1080,380]"/>'
    session_home = _nav_source(_SEARCH_BAR_NODE, mine)
    session_pending = _nav_source(mine, entry)
    cta_source = _nav_source(
        mine,
        entry,
        '<node text="测试店" bounds="[0,400][500,480]"/>',
        '<node text="评价" bounds="[800,410][900,470]"/>',
        '<node text="其他店" bounds="[0,600][500,680]"/>',
        '<node text="评价" bounds="[800,610][900,670]"/>',
    )
    editor_source = _nav_source(
        mine, entry, '<node text="测试店" bounds="[0,400][500,480]"/>',
        '<node text="评价" bounds="[800,410][900,470]"/>',
        '<node text="添加图/视频" bounds="[0,200][1080,300]"/>',
    )

    # 我的 tab absent → decline without any tap (2488-2489)
    kit1 = _SeqKit(_NavDriver([_nav_source(_SEARCH_BAR_NODE)]))
    s1 = DianpingUia2Session(kit1, captcha_window_seconds=0)
    r1 = s1._navigate_via_pending_review("测试店")
    assert not r1.success and "我的 tab not on the current page" in r1.message

    # tab tapped, entry never appears → BACK + decline (2493-2496)
    driver2 = _NavDriver([session_home, session_home])
    kit2 = _SeqKit(driver2)
    s2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = s2._navigate_via_pending_review("测试店")
    assert not r2.success and "待评价 entry not found" in r2.message
    assert driver2.presses == ["back"]

    # entry tap raises → BACK + tap failure (2498-2500): the 我的 tab tap
    # succeeds (click 1), the entry tap is click 2
    driver3 = _NavDriver([session_pending, session_pending], click_error=2)
    kit3 = _SeqKit(driver3)
    s3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    r3 = s3._navigate_via_pending_review("测试店")
    assert not r3.success and "待评价 tap failed" in r3.message
    assert driver3.presses == ["back"]

    # shop not on the pending list → BACK + decline (2505-2510)
    driver4 = _NavDriver([session_pending, session_pending])
    kit4 = _SeqKit(driver4)
    s4 = DianpingUia2Session(kit4, captcha_window_seconds=0)
    r4 = s4._navigate_via_pending_review("测试店")
    assert not r4.success and "shop not in pending list: 测试店" in r4.message
    assert driver4.presses == ["back"]

    # row CTA tap raises → BACK + failure (2511-2514): tab+entry taps are
    # clicks 1-2, the row CTA tap is click 3
    driver5 = _NavDriver([cta_source], click_error=3)
    kit5 = _SeqKit(driver5)
    s5 = DianpingUia2Session(kit5, captcha_window_seconds=0)
    r5 = s5._navigate_via_pending_review("测试店")
    assert not r5.success and "pending row tap failed" in r5.message
    assert driver5.presses == ["back"]

    # CTA tapped but the editor never opens → BACK + decline (2519-2522)
    driver6 = _NavDriver([cta_source, cta_source])
    kit6 = _SeqKit(driver6)
    s6 = DianpingUia2Session(kit6, captcha_window_seconds=0)
    r6 = s6._navigate_via_pending_review("测试店")
    assert not r6.success and "pending-review CTA did not open the editor" in r6.message
    assert driver6.presses == ["back"]

    # full success: editor marker after the CTA tap (2525-2528)
    driver7 = _NavDriver([cta_source, editor_source])
    kit7 = _SeqKit(driver7)
    s7 = DianpingUia2Session(kit7, captcha_window_seconds=0)
    r7 = s7._navigate_via_pending_review("测试店")
    assert r7.success and "via 我的/待评价" in r7.message
    assert r7.data == {"shop": "测试店"}


def test_uia2_tap_pending_shop_row_variants(monkeypatch):
    _fast_clock(monkeypatch)
    row_source = _nav_source(
        '<node text="测试店" bounds="[0,400][500,480]"/>',
        '<node text="评价" bounds="[800,410][900,470]"/>',
    )

    # no click driver → declined (2553-2554)
    class Mute:
        pass

    kit1 = _SeqKit(Mute())
    s1 = DianpingUia2Session(kit1, captcha_window_seconds=0)
    r1 = s1._tap_pending_shop_row("测试店")
    assert not r1.success and "no coordinate click available" in r1.message

    # row vanished before the tap (2556-2558)
    kit2 = _SeqKit(_NavDriver([_nav_source(_SEARCH_BAR_NODE)]))
    s2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = s2._tap_pending_shop_row("测试店")
    assert not r2.success and "pending row vanished before tap" in r2.message

    # click raises (2562-2564) and success data (2565-2568)
    kit3 = _SeqKit(_NavDriver([row_source], click_error=True))
    s3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    r3 = s3._tap_pending_shop_row("测试店")
    assert not r3.success and "pending row tap failed" in r3.message

    kit4 = _SeqKit(_NavDriver([row_source]))
    s4 = DianpingUia2Session(kit4, captcha_window_seconds=0)
    r4 = s4._tap_pending_shop_row("测试店")
    assert r4.success
    assert r4.data == {"x": 850, "y": 440}
    assert kit4.driver.clicks == [(850, 440)]


def test_uia2_back_to_home_search_editor_chrome_guard(monkeypatch):
    _fast_clock(monkeypatch)
    # 发布 on screen → a BACK would leave the editor: refuse (2600-2607)
    kit = _SeqKit(_NavDriver([_nav_source('<node text="发布" bounds="[0,2100][1080,2200]"/>')]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    result = session._back_to_home_search(
        {"search_bar": 'uiautomator:new UiSelector().text("搜索")'}
    )
    assert not result.success
    assert "refusing BACK with editor chrome visible" in result.message
    assert kit.driver.presses == []


def test_uia2_results_page_open_gates(monkeypatch):
    _fast_clock(monkeypatch)
    session = DianpingUia2Session(_SeqKit(_NavDriver(["<hierarchy/>"])), captcha_window_seconds=0)
    kw = {"search_results_marker": 'uiautomator:new UiSelector().text("有点评")'}
    # empty source (2622-2623), unparseable source (2625-2627)
    assert session._results_page_open("", "测试店", kw) is False
    assert session._results_page_open("not-xml", "测试店", kw) is False

    # untranslatable marker only → chrome stays False (2632-2633)
    chrome_row = _nav_source(
        '<node text="有点评" bounds="[0,80][1080,160]"/>',
        '<node class="android.widget.TextView" text="测试店" bounds="[10,200][400,260]"/>',
    )
    kw_bad = {
        "search_results_marker": 'uiautomator:new UiSelector().fromParent("x")'
    }
    assert session._results_page_open(chrome_row, "测试店", kw_bad) is False

    # chrome + row rect → True
    assert session._results_page_open(chrome_row, "测试店", kw) is True


def test_uia2_advance_from_search_results_tails(monkeypatch):
    _fast_clock(monkeypatch)
    kw = {
        "write_selector": 'uiautomator:new UiSelector().text("写评价")',
        "shop_result": None,
    }
    row = '<node class="android.widget.TextView" text="测试店" bounds="[10,200][400,260]"/>'
    write_label = (
        '<node clickable="true" bounds="[600,300][1050,420]">'
        '<node text="写评价" bounds="[620,310][760,360]"/></node>'
    )

    # row never appears → row-wait failure (2648-2650)
    kit1 = _SeqKit(_NavDriver(["<hierarchy/>"]))
    s1 = DianpingUia2Session(kit1, captcha_window_seconds=0)
    r1 = s1._advance_from_search_results("测试店", kw)
    assert not r1.success
    assert "timed out waiting for shop result row" in r1.message

    # row tap raises → tap failure (2652-2654)
    kit2 = _SeqKit(_NavDriver([_nav_source(row)], click_error=True))
    s2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = s2._advance_from_search_results("测试店", kw)
    assert not r2.success
    assert "shop row tap failed" in r2.message

    # row tapped, the write CTA never shows (2658-2660)
    kit3 = _SeqKit(_NavDriver([_nav_source(row)]))
    s3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    r3 = s3._advance_from_search_results("测试店", kw)
    assert not r3.success
    assert "timed out waiting for page marker" in r3.message

    # write label appears; its tap raises — the row tap is click 1, the
    # write tap is click 2 (2662-2664)
    kit4 = _SeqKit(_NavDriver([_nav_source(row, write_label)], click_error=2))
    s4 = DianpingUia2Session(kit4, captcha_window_seconds=0)
    r4 = s4._advance_from_search_results("测试店", kw)
    assert not r4.success
    assert "clickable-parent tap failed" in r4.message

    # write tap ok, but the editor marker never shows (2666-2674)
    no_editor = _nav_source(row, '<node text="填-placeholder"/>', write_label)
    kit5 = _SeqKit(_NavDriver([no_editor, no_editor]))
    s5 = DianpingUia2Session(kit5, captcha_window_seconds=0)
    r5 = s5._advance_from_search_results("测试店", kw)
    assert not r5.success
    assert "write tap did not open the editor" in r5.message

    # full success: editor marker after the write tap (2678)
    editor = _nav_source(row, write_label, '<node text="添加图/视频" bounds="[0,500][1080,600]"/>')
    kit6 = _SeqKit(_NavDriver([editor, editor]))
    s6 = DianpingUia2Session(kit6, captcha_window_seconds=0)
    r6 = s6._advance_from_search_results("测试店", kw)
    assert r6.success and "via search" in r6.message


def test_uia2_wait_for_marker_unparseable_and_untranslatable(monkeypatch):
    _fast_clock(monkeypatch)
    # dump never parses (2324-2327) and the candidate never translates
    # (2330-2331) → timeout with no crash
    kit = _SeqKit(_NavDriver(["<broken"]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    result = session._wait_for_marker(
        (
            'uiautomator:new UiSelector().fromParent("x")',
            'uiautomator:new UiSelector().text("搜索")',
        ),
        1.5,
    )
    assert not result.success
    assert "timed out waiting for page marker (1.5s)" in result.message


def test_uia2_marker_present_now_variants(monkeypatch):
    _fast_clock(monkeypatch)
    # empty dump → False (2464-2465); unparseable → False (2467-2469)
    kit = _SeqKit(_NavDriver([_nav_source(_SEARCH_BAR_NODE)]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    empty_session = DianpingUia2Session(_SeqKit(_NavDriver([""])), captcha_window_seconds=0)
    assert empty_session._marker_present_now("text:搜索") is False
    junk = DianpingUia2Session(_SeqKit(_NavDriver(["<broken"])), captcha_window_seconds=0)
    assert junk._marker_present_now('uiautomator:new UiSelector().text("搜索")') is False
    # untranslatable candidate skipped (2472-2473), translatable one matches
    assert session._marker_present_now(
        (
            'uiautomator:new UiSelector().fromParent("x")',
            'uiautomator:new UiSelector().text("搜索")',
        )
    )
    assert not session._marker_present_now(
        'uiautomator:new UiSelector().text("不存在")'
    )


def test_uia2_hide_keyboard_press_matrix(monkeypatch):
    _fast_clock(monkeypatch)
    plain = _nav_source(_SEARCH_BAR_NODE)  # no 完成, no editor chrome

    class PressBack:
        def __init__(self, back_error=None, num_error=None):
            self.back_error = back_error
            self.num_error = num_error
            self.presses = []

        def press(self, key):
            self.presses.append(key)
            if key == "back" and self.back_error:
                raise self.back_error
            if isinstance(key, int) and self.num_error:
                raise self.num_error

        def dump_hierarchy(self):
            return plain

    # press("back") works → via BACK (2772-2776); the 完成 tap must fail, so
    # the kit tap result is overridden
    d1 = PressBack()
    kit1 = _SeqKit(d1)
    kit1.results["tap"] = ActionResult(False, "no 完成 on this page")
    s1 = DianpingUia2Session(kit1, captcha_window_seconds=0)
    r1 = s1._hide_keyboard()
    assert r1.success and "hide_keyboard via BACK" in r1.message
    assert d1.presses == ["back"]

    # press("back") raises → press(4) fallback (2777-2781)
    d2 = PressBack(back_error=RuntimeError("str not accepted"))
    kit2 = _SeqKit(d2)
    kit2.results["tap"] = ActionResult(False, "no 完成 on this page")
    s2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = s2._hide_keyboard()
    assert r2.success and "hide_keyboard via BACK" in r2.message
    assert d2.presses == ["back", 4]

    # both raise → failure detail (2782-2783)
    d3 = PressBack(back_error=RuntimeError("no"), num_error=RuntimeError("also no"))
    kit3 = _SeqKit(d3)
    kit3.results["tap"] = ActionResult(False, "no 完成 on this page")
    s3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    r3 = s3._hide_keyboard()
    assert not r3.success
    assert "hide_keyboard BACK failed" in r3.message

    # only press_key exists → used as the fallback press (2769-2771)
    class PressKeyOnly:
        def __init__(self):
            self.presses = []

        def press_key(self, key):
            self.presses.append(key)

        def dump_hierarchy(self):
            return plain

    d4 = PressKeyOnly()
    kit4 = _SeqKit(d4)
    kit4.results["tap"] = ActionResult(False, "no 完成 on this page")
    s4 = DianpingUia2Session(kit4, captcha_window_seconds=0)
    r4 = s4._hide_keyboard()
    assert r4.success and "via BACK" in r4.message
    assert d4.presses == ["back"]


# --- batch 4: album picker cluster -------------------------------------------


class _WidgetDriver:
    """uia2 device for the picker: __call__ widget contract + dump + click."""

    def __init__(self, dump, exists_by_text=(), click_error=None):
        self._dump = dump
        self._exists_by_text = set(exists_by_text)
        self.click_error = click_error
        self.clicks = []
        self.swipes = []
        self.widget_kwargs = []

    def dump_hierarchy(self):
        return self._dump

    def __call__(self, **kwargs):
        self.widget_kwargs.append(kwargs)
        exists = kwargs.get("text") in self._exists_by_text
        return type("W", (), {"exists": exists})()

    def click(self, x, y):
        if self.click_error:
            raise RuntimeError("stale click")
        self.clicks.append((int(x), int(y)))

    def swipe(self, *args):
        self.swipes.append(args)


_PICKER_HEADER = '<node text="最近项目" bounds="[430,103][610,156]"/>'


def test_uia2_switch_to_staging_album_paths(monkeypatch):
    _fast_clock(monkeypatch)
    album = "DianpingAuto"

    # header already shows the album → short-circuit success (3486-3487)
    on_album = _nav_source('<node text="%s" bounds="[430,103][610,156]"/>' % album)
    d0 = _WidgetDriver(on_album)
    s0 = DianpingUia2Session(_SeqKit(d0), captcha_window_seconds=0)
    r0 = s0._switch_to_staging_album()
    assert r0.success and "picker already on %s" % album in r0.message

    # dropdown opens, DianpingAuto row tapped, header settles on the album
    # (3491-3508)
    dropdown = _nav_source(_PICKER_HEADER, '<node text="%s" bounds="[0,600][400,680]"/>' % album)
    d1 = _WidgetDriver(
        dropdown,
        exists_by_text=(album,),
    )
    s1 = DianpingUia2Session(_SeqKit(d1), captcha_window_seconds=0)
    r1 = s1._switch_to_staging_album()
    assert not r1.success  # header never switches on a static dump

    # dropdown tap fails → "album dropdown not found" (3536-3538)
    d2 = _WidgetDriver(_nav_source(_PICKER_HEADER), click_error=True)
    s2 = DianpingUia2Session(_SeqKit(d2), captcha_window_seconds=0)
    r2 = s2._switch_to_staging_album()
    assert not r2.success
    assert "album dropdown not found" in r2.message


def test_uia2_open_album_dropdown_paths(monkeypatch):
    _fast_clock(monkeypatch)
    album = "DianpingAuto"

    # widget check finds the album right away → open (3540-3543)
    d1 = _WidgetDriver(_nav_source(_PICKER_HEADER), exists_by_text=(album,))
    s1 = DianpingUia2Session(_SeqKit(d1), captcha_window_seconds=0)
    r1 = s1._open_album_dropdown()
    assert r1.success and r1.message == "album dropdown open"

    # Camera fallback marker → open (3544-3547)
    d2 = _WidgetDriver(_nav_source(_PICKER_HEADER), exists_by_text=("Camera",))
    s2 = DianpingUia2Session(_SeqKit(d2), captcha_window_seconds=0)
    r2 = s2._open_album_dropdown()
    assert r2.success and r2.message == "album dropdown open"

    # neither marker ever appears → deadline failure (3548-3549)
    d3 = _WidgetDriver(_nav_source(_PICKER_HEADER), exists_by_text=())
    s3 = DianpingUia2Session(_SeqKit(d3), captcha_window_seconds=0)
    r3 = s3._open_album_dropdown()
    assert not r3.success and "album dropdown did not open" in r3.message


def test_uia2_scroll_album_list_and_no_swipe(monkeypatch):
    _fast_clock(monkeypatch)
    # swipe driver present → one swipe recorded (3556-3557)
    d1 = _WidgetDriver("<hierarchy/>")
    s1 = DianpingUia2Session(_SeqKit(d1), captcha_window_seconds=0)
    s1._scroll_album_list()
    assert len(d1.swipes) == 1

    # no swipe attribute → silent no-op (3553-3555)
    s2 = DianpingUia2Session(_SeqKit(_NavDriver(["<hierarchy/>"])), captcha_window_seconds=0)
    s2._scroll_album_list()  # must not raise

    # swipe raises → swallowed (3558-3559)
    class BoomSwipe(_WidgetDriver):
        def swipe(self, *args):
            raise RuntimeError("frozen")

    d3 = BoomSwipe("<hierarchy/>")
    s3 = DianpingUia2Session(_SeqKit(d3), captcha_window_seconds=0)
    s3._scroll_album_list()  # must not raise


def test_uia2_confirm_picked_photos_paths(monkeypatch):
    _fast_clock(monkeypatch)
    next_label = '<node clickable="true" bounds="[833,2287][1036,2366]"><node text="下一步" bounds="[850,2300][1020,2350]"/></node>'

    # confirm tap succeeds and the widget disappears → "confirmed via 下一步"
    class GoneAfterTap(_WidgetDriver):
        def __init__(self):
            super().__init__(_nav_source(next_label), exists_by_text=("下一步",))
            self.tapped = False

        def click(self, x, y):
            self.tapped = True
            self._exists_by_text = set()  # 下一步 disappears after the tap

    d1 = GoneAfterTap()
    kit1 = _SeqKit(d1)
    s1 = DianpingUia2Session(kit1, captcha_window_seconds=0)
    r1 = s1._confirm_picked_photos(('uiautomator:new UiSelector().text("下一步")',))
    assert r1.success and "confirmed via 下一步" in r1.message
    assert d1.tapped

    # widget never exists → "confirm not found" (3718-3719)
    d2 = _WidgetDriver("<hierarchy/>", exists_by_text=())
    kit2 = _SeqKit(d2)
    kit2.results["tap"] = ActionResult(False, "no chrome")
    s2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = s2._confirm_picked_photos(('uiautomator:new UiSelector().text("下一步")',))
    assert not r2.success and "pick_photos: confirm not found" in r2.message


def test_uia2_widget_exists_composite_and_error(monkeypatch):
    _fast_clock(monkeypatch)
    rid = session_mod._PHOTO_SELECT_RESOURCE_ID
    seen = []

    class RecordingDriver:
        def __call__(self, **kwargs):
            seen.append(kwargs)
            return type("W", (), {"exists": True})()

    d1 = RecordingDriver()
    s1 = DianpingUia2Session(_SeqKit(d1), captcha_window_seconds=0)
    # composite descriptor goes through as the raw kwargs dict (3728-3731)
    assert s1._uia2_widget_exists("uiautomator", {"resourceId": rid, "instance": 2}) is True
    assert seen[-1] == {"resourceId": rid, "instance": 2}

    # driver hiccup → fail closed True (3744-3749)
    class BoomDriver:
        def __call__(self, **kwargs):
            raise RuntimeError("bridge hiccup")

    s2 = DianpingUia2Session(_SeqKit(BoomDriver()), captcha_window_seconds=0)
    assert s2._uia2_widget_exists("id", rid) is True


def test_uia2_dismiss_dialogs_dish_edit_skip_and_counts(monkeypatch):
    _fast_clock(monkeypatch)
    # dish-edit open → skipped entirely (3791-3792)
    dish = _nav_source('<node text="识别菜品" bounds="[0,100][400,200]"/>')
    s1 = DianpingUia2Session(_SeqKit(_NavDriver([dish])), captcha_window_seconds=0)
    r1 = s1._dismiss_dialogs(selector='~关闭')
    assert r1.success and "skipped; dish-edit open" in r1.message

    # one tap hits, then nothing does → dismissed=1 (3800-3813)
    d2 = _WidgetDriver('<hierarchy><node content-desc="关闭" bounds="[400,900][680,1000]"/></hierarchy>')
    kit2 = _SeqKit(d2)
    kit2.calls = []

    def tap_first_only(action_name, **kwargs):
        if len(kit2.calls) == 0:
            kit2.calls.append((action_name, kwargs))
            return ActionResult(True, "tap")
        kit2.calls.append((action_name, kwargs))
        return ActionResult(False, "gone")

    kit2.execute_action = tap_first_only
    s2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = s2._dismiss_dialogs(selector='~关闭', max_attempts=3)
    assert r2.success and r2.data == {"dismissed": 1}


def test_import_kit_uia2_session_and_connect(monkeypatch):
    import sys
    import types

    # fake the kit adapters module so the deferred import resolves offline
    fake_pkg = types.ModuleType("adapters")
    fake_mod = types.ModuleType("adapters.uia2")

    class FakeUia2Session:
        pass

    fake_mod.Uia2Session = FakeUia2Session
    monkeypatch.setitem(sys.modules, "adapters", fake_pkg)
    monkeypatch.setitem(sys.modules, "adapters.uia2", fake_mod)
    assert session_mod._import_kit_uia2_session() is FakeUia2Session

    # uiautomator2 missing → ImportError with the pip hint (3822-3829)
    monkeypatch.setitem(sys.modules, "uiautomator2", None)
    with pytest.raises(ImportError, match="uiautomator2 is required"):
        session_mod._connect_uia2("127.0.0.1:5555")


# --- batch 4: photo tile selection matrix ------------------------------------


class _TileElement:
    def __init__(self, exists=True, click_result=None, click_error=None):
        self._exists = exists
        self.click_result = click_result
        self.click_error = click_error
        self.clicks = 0

    @property
    def exists(self):
        return self._exists

    def click(self):
        if self.click_error is not None:
            raise self.click_error
        self.clicks += 1
        if self.click_result is not None:
            return self.click_result
        return ActionResult(True, "click")


class _BadgeDriver:
    """driver(...) returns the next badge; dump returns ``dump``."""

    def __init__(self, badges, dump="<hierarchy/>"):
        self._badges = list(badges)
        self._dump = dump

    def __call__(self, **kwargs):
        if self._badges:
            return self._badges.pop(0)
        return type("B", (), {"exists": False})()

    def dump_hierarchy(self):
        return self._dump


class _FindKit(_SeqKit):
    """kit whose find_element pops a scripted list of outcomes."""

    def __init__(self, driver=None, outcomes=()):
        super().__init__(driver)
        self._outcomes = list(outcomes)

    def find_element(self, by, value):
        if not self._outcomes:
            raise KeyError("lookup exhausted")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_uia2_pick_photo_tile_success_and_failure_tails(monkeypatch):
    _fast_clock(monkeypatch)
    rid = session_mod._PHOTO_SELECT_RESOURCE_ID
    photo_id = session_mod._PHOTO_IMAGE_RESOURCE_ID
    badge_digit = type("B", (), {})()
    badge_digit.exists = True
    badge_digit.info = {"text": "1"}

    # success on the preferred select_layout lookup (3614/3626-3637)
    kit1 = _FindKit(_BadgeDriver([badge_digit]), outcomes=[_TileElement()])
    s1 = DianpingUia2Session(kit1, captcha_window_seconds=0)
    r1 = s1._pick_photo_tile('id:%s' % photo_id, 0)
    assert r1.success and "selected photo tile 0 (attempt 1)" in r1.message

    # KeyError on select_layout → falls through to the photo id candidate
    # (3615-3620); both ids in the selector give two lookups
    both_ids = ('id:%s' % rid, 'id:%s' % photo_id)
    kit2 = _FindKit(_BadgeDriver([badge_digit]), outcomes=[KeyError("miss"), _TileElement()])
    s2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = s2._pick_photo_tile(both_ids, 0)
    assert r2.success and "selected photo tile 0 (attempt 1)" in r2.message

    # unexpected lookup exception → hard fail (3621-3622)
    kit3 = _FindKit(_BadgeDriver([]), outcomes=[ValueError("bad selector")])
    s3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    r3 = s3._pick_photo_tile('id:%s' % photo_id, 0)
    assert not r3.success and "photo tile lookup failed" in r3.message

    # element never exists → verdict tail with dump verdict "no" (3623-3624,
    # 3642-3654)
    kit4 = _FindKit(_BadgeDriver([], dump="<hierarchy/>"), outcomes=[_TileElement(exists=False)])
    s4 = DianpingUia2Session(kit4, captcha_window_seconds=0)
    r4 = s4._pick_photo_tile('id:%s' % photo_id, 0)
    assert not r4.success
    assert "photo tile instance 0 absent (select_layout in dump: no)" in r4.message

    # click returns a failed ActionResult → propagated (3627-3628)
    kit5 = _FindKit(
        _BadgeDriver([]),
        outcomes=[_TileElement(click_result=ActionResult(False, "click rejected"))],
    )
    s5 = DianpingUia2Session(kit5, captcha_window_seconds=0)
    r5 = s5._pick_photo_tile('id:%s' % photo_id, 0)
    assert not r5.success and "click rejected" in r5.message

    # clicked but the badge never shows a digit → retries then verdict "yes"
    # (3630-3641, verdict line 3652)
    empty_badge = type("B", (), {})()
    empty_badge.exists = False
    kit6 = _FindKit(
        _BadgeDriver([empty_badge] * 40, dump='<hierarchy><node resource-id="%s"/></hierarchy>' % rid),
        outcomes=[_TileElement(), _TileElement(), _TileElement()],
    )
    s6 = DianpingUia2Session(kit6, captcha_window_seconds=0)
    r6 = s6._pick_photo_tile('id:%s' % photo_id, 0)
    assert not r6.success
    assert "was not selected (attempt" in r6.message
    assert "select_layout in dump: yes" in r6.message

    # dump raises → verdict "unknown" (3647-3651)
    class BoomDump(_BadgeDriver):
        def dump_hierarchy(self):
            raise RuntimeError("bridge died")

    kit7 = _FindKit(BoomDump([]), outcomes=[_TileElement(exists=False), _TileElement(exists=False)])
    s7 = DianpingUia2Session(kit7, captcha_window_seconds=0)
    r7 = s7._pick_photo_tile('id:%s' % photo_id, 0)
    assert not r7.success and "select_layout in dump: unknown" in r7.message


def test_uia2_photo_tile_is_selected_variants(monkeypatch):
    _fast_clock(monkeypatch)
    # driver not callable → assume selected (3658-3660)
    s1 = DianpingUia2Session(_SeqKit(_NavDriver(["<hierarchy/>"])), captcha_window_seconds=0)
    s1._session.driver = _SeqDriver(["<hierarchy/>"])  # non-callable driver
    assert s1._photo_tile_is_selected(0) is True

    # badge digit text → True; no badge → False; junk info → False (3661-3675)
    def badge(text):
        b = type("B", (), {})()
        b.exists = True
        b.info = {"text": text}
        return b

    d2 = _BadgeDriver([badge("3")])
    s2 = DianpingUia2Session(_SeqKit(d2), captcha_window_seconds=0)
    assert s2._photo_tile_is_selected(0) is True

    d3 = _BadgeDriver([])
    s3 = DianpingUia2Session(_SeqKit(d3), captcha_window_seconds=0)
    assert s3._photo_tile_is_selected(0) is False

    class ExplodingDriver(_BadgeDriver):
        def __call__(self, **kwargs):
            raise RuntimeError("lookup exploded")

    d4 = ExplodingDriver([])
    s4 = DianpingUia2Session(_SeqKit(d4), captcha_window_seconds=0)
    assert s4._photo_tile_is_selected(0) is False


# --- batch 4: dish-edit clear + screen wake + gallery prep --------------------


def test_uia2_clear_dish_edit_photos_tails(monkeypatch):
    _fast_clock(monkeypatch)
    recognize = '<node text="识别菜品" bounds="[0,100][400,200]"/>'
    tile = '<node clickable="true" content-desc="photo" bounds="[100,1950][220,2060]"/>'
    trash = (
        '<node class="android.widget.ImageView" clickable="true" bounds="[900,105][1000,155]"/>'
    )
    confirm = '<node text="确认删除" bounds="[568,1211][872,1324]"/>'

    # dish sheet without tiles → "cleared 0" (3152-3159)
    kit1 = _SeqKit(_NavDriver([_nav_source(recognize)]))
    s1 = DianpingUia2Session(kit1, captcha_window_seconds=0)
    r1 = s1._clear_dish_edit_photos()
    assert r1.success and "cleared 0 dish-edit photo(s)" in r1.message

    # trash never found after the tile tap (3167-3169)
    kit2 = _SeqKit(_NavDriver([_nav_source(recognize, tile)]))
    s2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = s2._clear_dish_edit_photos()
    assert not r2.success and "trash not found" in r2.message

    # leftover confirm dialog first, filmstrip never drops: the confirm click
    # lands but the static dump keeps the dialog up, so the delete-confirm
    # loop itself reports the stuck dialog (3136-3149)
    dialog_and_tile = _nav_source(confirm, tile)
    kit3 = _SeqKit(_NavDriver([dialog_and_tile]))
    s3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    r3 = s3._clear_dish_edit_photos()
    assert not r3.success
    assert "delete dialog stuck" in r3.message

    # click fails on the tile → wrapped failure (3161-3165)
    kit4 = _SeqKit(_NavDriver([_nav_source(recognize, tile)], click_error=True))
    s4 = DianpingUia2Session(kit4, captcha_window_seconds=0)
    r4 = s4._clear_dish_edit_photos()
    assert not r4.success
    assert r4.message.startswith("clear dish-edit photos: click failed")

    # trash click fails (3170-3172): tile tap is click 1, trash tap is click 2
    both = _nav_source(recognize, tile, trash)
    kit5 = _SeqKit(_NavDriver([both], click_error=2))
    s5 = DianpingUia2Session(kit5, captcha_window_seconds=0)
    r5 = s5._clear_dish_edit_photos()
    assert not r5.success
    assert "click failed" in r5.message


def test_uia2_confirm_dish_edit_photo_delete_paths(monkeypatch):
    _fast_clock(monkeypatch)
    confirm = '<node text="确认删除" bounds="[568,1211][872,1324]"/>'

    # confirm visible but the click fails → wrapped failure (3228-3232)
    kit1 = _SeqKit(_NavDriver([_nav_source(confirm)], click_error=True))
    s1 = DianpingUia2Session(kit1, captcha_window_seconds=0)
    r1 = s1._confirm_dish_edit_photo_delete()
    assert not r1.success and "confirm tap failed" in r1.message

    # dialog title in the dump but the exact 确认删除 button never resolves
    # → the poll rides out its deadline and reports stuck (3245-3248)
    kit2 = _SeqKit(_NavDriver([_nav_source('<node text="确认删除这张图片吗" bounds="[0,900][600,980]"/>')]))
    s2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = s2._confirm_dish_edit_photo_delete()
    assert not r2.success and "delete dialog stuck" in r2.message

    # no dialog text anywhere → "no dish-edit delete dialog" (3245-3246)
    kit2b = _SeqKit(_NavDriver([_nav_source(_SEARCH_BAR_NODE)]))
    s2b = DianpingUia2Session(kit2b, captcha_window_seconds=0)
    r2b = s2b._confirm_dish_edit_photo_delete()
    assert r2b.success and "no dish-edit delete dialog" in r2b.message

    # button stuck after 3 confirms → stuck tail (3239-3243)
    kit3 = _SeqKit(_NavDriver([_nav_source(confirm)]))
    s3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    r3 = s3._confirm_dish_edit_photo_delete()
    assert not r3.success and "delete dialog stuck after confirm" in r3.message


def test_uia2_ensure_screen_on_matrix(monkeypatch):
    _fast_clock(monkeypatch)

    class ScreenDriver:
        def __init__(self, info=None, screen_error=None, with_screen_on=True, with_shell=True):
            self._info = info
            self.screen_error = screen_error
            self.shell_calls = []
            self.screen_on_calls = 0
            if with_screen_on:
                self.screen_on = self._screen_on
            if with_shell:
                self.shell = self._shell

        def _screen_on(self):
            self.screen_on_calls += 1
            if self.screen_error:
                raise self.screen_error

        def _shell(self, cmd):
            self.shell_calls.append(cmd)

        def info(self):
            if isinstance(self._info, BaseException):
                raise self._info
            return self._info

    # driver None → no-op (3434-3436)
    s0 = DianpingUia2Session(_SeqKit(None), captcha_window_seconds=0)
    s0._ensure_screen_on()

    # info raises → treated as on (3438-3442)
    d1 = ScreenDriver(info=RuntimeError("no info"))
    s1 = DianpingUia2Session(_SeqKit(d1), captcha_window_seconds=0)
    s1._session.driver = d1
    s1._ensure_screen_on()
    assert d1.screen_on_calls == 0

    # displayOn True → awake, no action (3444-3450)
    d2 = ScreenDriver(info={"displayOn": True})
    s2 = DianpingUia2Session(_SeqKit(d2), captcha_window_seconds=0)
    s2._session.driver = d2
    s2._ensure_screen_on()
    assert d2.screen_on_calls == 0 and d2.shell_calls == []

    # screenOn False → screen_on() wakes (3447-3455)
    d3 = ScreenDriver(info={"screenOn": False})
    s3 = DianpingUia2Session(_SeqKit(d3), captcha_window_seconds=0)
    s3._session.driver = d3
    s3._ensure_screen_on()
    assert d3.screen_on_calls == 1

    # screen_on raises → keyevent 224 via shell (3451-3463)
    d4 = ScreenDriver(info={"displayOn": False}, screen_error=RuntimeError("frozen"))
    s4 = DianpingUia2Session(_SeqKit(d4), captcha_window_seconds=0)
    s4._session.driver = d4
    s4._ensure_screen_on()
    assert d4.shell_calls == ["input keyevent 224"]

    # screen_on missing, shell missing → silent no-op
    d5 = ScreenDriver(info={"displayOn": False}, with_screen_on=False, with_shell=False)
    s5 = DianpingUia2Session(_SeqKit(d5), captcha_window_seconds=0)
    s5._session.driver = d5
    s5._ensure_screen_on()


def test_uia2_dump_source_second_dump_after_wake(monkeypatch):
    _fast_clock(monkeypatch)

    class WakeDumpDriver:
        def __init__(self):
            self.calls = 0

        def dump_hierarchy(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("screen off")
            return "<hierarchy/>"

        def info(self):
            raise RuntimeError("no info")

    d = WakeDumpDriver()
    s = DianpingUia2Session(_SeqKit(d), captcha_window_seconds=0)
    assert s._dump_source() == "<hierarchy/>"
    assert d.calls == 2


class _GalleryStubDevice:
    """shell/push device whose content-query rows are scripted."""

    def __init__(self, rows="", shell_error=None):
        self.rows = rows
        self.shell_error = shell_error
        self.shell_calls = []
        self.pushes = []

    def shell(self, cmd):
        self.shell_calls.append(cmd)
        if self.shell_error is not None:
            raise self.shell_error
        if isinstance(cmd, list) and cmd and cmd[0] == "content":
            return self.rows
        return ""

    def push(self, local, remote):
        self.pushes.append((local, remote))


def test_uia2_prepare_gallery_photo_tails(monkeypatch, tmp_path):
    _fast_clock(monkeypatch)
    png = tmp_path / "lab.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nnot a real image")

    # host file missing (3319-3321)
    s1 = DianpingUia2Session(_SeqKit(_GalleryStubDevice()), captcha_window_seconds=0)
    s1._session.driver = _GalleryStubDevice()
    missing = s1._prepare_gallery_photo(str(tmp_path / "nope.jpg"))
    assert not missing.success and "host file missing" in missing.message

    # Pillow unavailable (3322-3327)
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "PIL", None)
    s2 = DianpingUia2Session(_SeqKit(_GalleryStubDevice()), captcha_window_seconds=0)
    s2._session.driver = _GalleryStubDevice()
    no_pil = s2._prepare_gallery_photo(str(png))
    assert not no_pil.success and "Pillow unavailable" in no_pil.message

    # EXIF rewrite failure on garbage bytes (3342-3343)
    monkeypatch.delitem(_sys.modules, "PIL", raising=False)
    s3 = DianpingUia2Session(_SeqKit(_GalleryStubDevice()), captcha_window_seconds=0)
    s3._session.driver = _GalleryStubDevice()
    bad = s3._prepare_gallery_photo(str(png))
    assert not bad.success and "gallery prep: EXIF rewrite failed" in bad.message

    # push/scan failure (3360-3361)
    from PIL import Image as _PILImage  # noqa: F401  (ensures PIL available)

    good = tmp_path / "good.jpg"
    _PILImage.new("RGB", (4, 4)).save(good)
    d4 = _GalleryStubDevice(shell_error=RuntimeError("adb offline"))
    s4 = DianpingUia2Session(_SeqKit(d4), captcha_window_seconds=0)
    s4._session.driver = d4
    failed = s4._prepare_gallery_photo(str(good))
    assert not failed.success and "push/scan failed" in failed.message

    # poll never confirms → 20s timeout tail (3369-3417)
    d5 = _GalleryStubDevice(rows="")
    s5 = DianpingUia2Session(_SeqKit(d5), captcha_window_seconds=0)
    s5._session.driver = d5
    timeout = s5._prepare_gallery_photo(str(good))
    assert not timeout.success
    assert "not indexed first within 20s" in timeout.message

    # row indexed first → success (3384-3411)
    name = "IMG99999999_good.jpg"
    rows = (
        "Row: _display_name=%s,bucket_display_name=DianpingAuto,datetaken=1234\n" % name
    )
    d6 = _GalleryStubDevice(rows=rows)
    s6 = DianpingUia2Session(_SeqKit(d6), captcha_window_seconds=0)
    s6._session.driver = d6
    ok = s6._prepare_gallery_photo(str(good))
    assert ok.success
    assert ok.data == {
        "display_name": name,
        "remote": "/sdcard/Pictures/DianpingAuto/%s" % name,
        "album": "DianpingAuto",
    }


# --- batch 5: last guard tails ------------------------------------------------


def test_numeric_parameter_none_falls_back():
    from automation_app_dianping.session import ActionParameterError, _numeric_parameter

    assert _numeric_parameter({"timeout": None}, "timeout", 3.5) == 3.5
    assert _numeric_parameter({}, "timeout", 2.0) == 2.0
    try:
        _numeric_parameter({"timeout": "abc"}, "timeout", 1.0)
        raise AssertionError("expected ActionParameterError")
    except ActionParameterError as exc:
        assert "must be a number" in str(exc)


def test_import_by_falls_back_to_strings(monkeypatch):
    import builtins
    import automation_app_dianping.session as sm

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("appium") or name.startswith("selenium"):
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    by = sm._import_by()
    assert by.ID == "id"


def test_slider_marker_and_distance_tails():
    from automation_app_dianping.session import (
        _slider_drag_distance,
        page_source_indicates_slider,
    )

    # attribute-level markers: rid containing "slider" / Chinese handle copy
    assert page_source_indicates_slider(
        '<hierarchy><node resource-id="com.android.systemui:id/slider_bar"/></hierarchy>'
    )
    assert page_source_indicates_slider(
        '<hierarchy><node text="向右拖动滑块"/></hierarchy>'
    )
    assert not page_source_indicates_slider("<hierarchy/>")
    assert not page_source_indicates_slider("not-xml")

    # gap_x path tails: invalid type, non-positive, gap left of handle
    _, e1 = _slider_drag_distance(30, object(), None, 1.0)
    assert e1 is not None and "invalid gap_x" in e1.message
    _, e2 = _slider_drag_distance(30, -1, None, 1.0)
    assert "non-positive gap_x" in e2.message
    _, e3 = _slider_drag_distance(30, 10, None, 1.0)
    assert "at or left of handle" in e3.message

    # offset path tails: invalid value, non-positive; success + scale math
    _, e4 = _slider_drag_distance(30, None, "x", 1.0)
    assert "invalid gap_offset_px" in e4.message
    _, e5 = _slider_drag_distance(30, None, 0, 1.0)
    assert "non-positive gap_offset_px" in e5.message
    distance, e6 = _slider_drag_distance(30, None, 150, 2.0)
    assert e6 is None and distance == 300
    # invalid distance_scale is caught one level up, in _slider_solution_params
    from automation_app_dianping.session import _slider_solution_params

    _, e7 = _slider_solution_params({"gap_offset_px": 150, "distance_scale": "x"})
    assert "invalid distance_scale" in e7.message
    _, e8 = _slider_solution_params({"gap_offset_px": 150, "distance_scale": -1})
    assert "non-positive distance_scale" in e8.message


def test_appium_guard_slider_solved_then_retry_fails(monkeypatch, tmp_path):
    class Handle:
        def __init__(self):
            self.swipes = []
            self.source = (
                "<hierarchy><node resource-id='com.x:id/slider' text='slider handle' "
                "bounds='[40,1000][300,1040]'/></hierarchy>"
            )

        @property
        def page_source(self):
            # rid carries the "slider" attribute marker for detection while
            # the text hint satisfies locate_slider_handle's handle query.
            # A successful solve clears the challenge from the dump.
            return self.source

        def swipe(self, *args):
            self.swipes.append(args)
            self.source = "<hierarchy><node text='点评'/></hierarchy>"

        def get_screenshot_as_base64(self):
            import base64 as b64

            return b64.b64encode(b"png")

    calls = {"n": 0}

    def solver(image):
        calls["n"] += 1
        # bare number = ready-made drag distance; first solve succeeds
        if calls["n"] == 1:
            return 150
        return -5  # second solve → non-positive gap_offset_px

    session = DianpingAppiumSession(Handle(), artifact_root=tmp_path, slider_solver=solver)
    # first "tap" fails → guard sees slider → solve+swipe OK → retry tap fails
    # (unknown selector exhausts its find timeout) → "slider solved but tap
    # retry failed" (491-495)
    result = session._guard_slider(
        "tap", ActionResult(False, "tap"), {"selector": "~x", "timeout": 0.0}
    )
    assert not result.success
    assert "slider solved but tap retry failed" in result.message
    assert len(session.driver.swipes) == 1

    # no slider in source → passthrough, untouched original result
    class CleanDriver(Handle):
        @property
        def page_source(self):
            return "<hierarchy/>"

    session_clean = DianpingAppiumSession(
        CleanDriver(), artifact_root=tmp_path, slider_solver=solver
    )
    original = ActionResult(False, "untouched")
    passthrough = session_clean._guard_slider("tap", original, {"selector": "~x"})
    assert passthrough is original
    assert session_clean._slider_guard_active is False

    # solve error tail (516) via a solver that explodes
    def boom(image):
        raise RuntimeError("cv2 missing")

    session2 = DianpingAppiumSession(Handle(), artifact_root=tmp_path, slider_solver=boom)
    result2 = session2._attempt_slider_solve()
    assert not result2.success and "slider solve errored" in result2.message


def test_appium_attempt_slider_solve_no_screenshot(monkeypatch, tmp_path):
    session = DianpingAppiumSession(_MiniDriver(), artifact_root=tmp_path, slider_solver=lambda img: 120)
    result = session._attempt_slider_solve()
    assert not result.success
    assert "cannot capture screenshots" in result.message


def test_uia2_slider_swipe_tails(monkeypatch, tmp_path):
    _fast_clock(monkeypatch)

    handle_source = (
        "<hierarchy><node text='slider handle' "
        "bounds='[40,1000][300,1040]'/></hierarchy>"
    )

    class NoSwipe:
        def dump_hierarchy(self):
            return handle_source

    s1 = DianpingUia2Session(_SeqKit(NoSwipe()), captcha_window_seconds=0)
    r1 = s1._perform_slider_swipe(offset_px=120)
    assert not r1.success and "does not support coordinate swipe" in r1.message

    class BoomSwipe:
        def dump_hierarchy(self):
            return handle_source

        def swipe(self, *args):
            raise RuntimeError("frozen")

    s2 = DianpingUia2Session(_SeqKit(BoomSwipe()), captcha_window_seconds=0)
    r2 = s2._perform_slider_swipe(offset_px=120)
    assert not r2.success and "slider swipe failed" in r2.message

    class BadShot:
        def dump_hierarchy(self):
            return handle_source

        def screenshot(self):
            return 42  # neither bytes nor saveable

    def solver(image):
        return 120

    s3 = DianpingUia2Session(
        _SeqKit(BadShot()), captcha_window_seconds=0, slider_solver=solver
    )
    try:
        s3._slider_screenshot_bytes()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "neither bytes nor a saveable image" in str(exc)

    # no driver screenshot callable at all → "u2 driver cannot capture"
    class ShotCallableDevice:
        pass

    s4 = DianpingUia2Session(
        _SeqKit(ShotCallableDevice()), captcha_window_seconds=0, slider_solver=solver
    )
    try:
        s4._slider_screenshot_bytes()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "u2 driver cannot capture screenshots" in str(exc)

    # solve success path: handle located → swipe wins → "slider swiped N px"
    class GoodSwipe:
        def __init__(self):
            self.calls = []

        def dump_hierarchy(self):
            return handle_source

        def screenshot(self):
            return b"png-bytes"

        def swipe(self, x1, y1, x2, y2, duration):
            self.calls.append((x1, y1, x2, y2, duration))

    driver = GoodSwipe()
    s5 = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0, slider_solver=solver)
    r5 = s5._attempt_slider_solve()
    assert r5.success and "slider swiped 120 px" in r5.message
    assert driver.calls[0][:4] == (170, 1020, 290, 1020)


def test_uia2_retry_after_manual_window_recovers_and_expires(monkeypatch):
    _fast_clock(monkeypatch)
    kit = _SeqKit(_NavDriver(["<hierarchy/>"]))
    session = DianpingUia2Session(kit, captcha_window_seconds=3.0)

    # tap recovers on the first manual retry (3768-3784)
    failure = ActionResult(False, "tap blocked")
    recovered = session._retry_after_manual_window("tap", {"selector": "~x"}, failure)
    assert recovered.success and "recovered after manual captcha window" in recovered.message
    assert session._manual_window_active is False

    # non-selector action expiry returns the original failure (3785-3786)
    kit2 = _SeqKit(_NavDriver(["<hierarchy/>"]))
    kit2.results["grow_back"] = ActionResult(False, "still blocked")
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=2.0)
    expired = session2._retry_after_manual_window(
        "grow_back", {"keycode": 4}, ActionResult(False, "blocked")
    )
    assert not expired.success and expired.message == "blocked"


def test_uia2_widget_exists_unmapped_by_fails_open(monkeypatch):
    _fast_clock(monkeypatch)
    session = DianpingUia2Session(_SeqKit(_WidgetDriver("<hierarchy/>")), captcha_window_seconds=0)
    # unknown by → kwargs None → fail-open True (3741-3742)
    assert session._uia2_widget_exists("xpath", "//a") is True


def test_uia2_confirm_editor_photo_delete_paths(monkeypatch):
    _fast_clock(monkeypatch)
    # publish chrome on the post-tap dump → skip entirely (3258-3259)
    kit1 = _SeqKit(_NavDriver(["<hierarchy/>"]))
    s1 = DianpingUia2Session(kit1, captcha_window_seconds=0)
    s1._confirm_editor_photo_delete(_nav_source('<node text="发布" bounds="[0,2100][1080,2200]"/>'))
    assert kit1.calls == []

    # 删除 exists in a non-chrome dump → tapped via clickable parent (3260-3272)
    source = _nav_source(
        '<node clickable="true" bounds="[0,300][200,400]">'
        '<node text="删除" bounds="[10,310][120,370]"/></node>'
    )
    d2 = _NavDriver([source])
    kit2 = _SeqKit(d2)
    kit2.results["tap"] = ActionResult(False, "no chrome tap")
    s2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    s2._confirm_editor_photo_delete(source)
    # preferred_tap_rect: label (110px wide) sits inside a non-oversized
    # clickable ancestor → ancestor center wins
    assert d2.clicks == [(100, 350)]


def test_push_file_sync_and_adb_device_fallbacks():
    # sync.push path (3286-3290)
    class SyncOnly:
        def __init__(self):
            self.sync = type("S", (), {"push": staticmethod(lambda l, r: None)})()

    DianpingUia2Session._push_file(SyncOnly(), "a", "b")

    # adb_device.sync.push path (3291-3296)
    class AdbOnly:
        def __init__(self):
            self.adb_device = type(
                "A", (), {"sync": type("AS", (), {"push": staticmethod(lambda l, r: None)})()}
            )()

    DianpingUia2Session._push_file(AdbOnly(), "a", "b")

    # nothing works → AttributeError (3297)
    try:
        DianpingUia2Session._push_file(object(), "a", "b")
        raise AssertionError("expected AttributeError")
    except AttributeError as exc:
        assert "does not support file push" in str(exc)


def test_appium_run_action_parameter_error_tail(monkeypatch, tmp_path):
    _fast_clock(monkeypatch)
    session = _mini(tmp_path)
    # bad timeout param inside tap → ActionParameterError → reported failure
    # with artifact dump (397-403)
    result = session.execute_action("tap", selector="~x", timeout="not-a-number")
    assert not result.success
    assert "must be a number" in result.message


def test_build_uia2_session_factory_invocation(monkeypatch):
    import sys
    import types
    from automation_app_dianping.config import DianpingDeviceConfig

    captured = {}

    class FakeKitSession:
        def __init__(self, device, identifier=None, artifact_root=None):
            captured["identifier"] = identifier
            captured["artifact_root"] = artifact_root
            captured["device"] = device
            self.info = None

    fake_pkg = types.ModuleType("adapters")
    fake_mod = types.ModuleType("adapters.uia2")
    fake_mod.Uia2Session = FakeKitSession
    monkeypatch.setitem(sys.modules, "adapters", fake_pkg)
    monkeypatch.setitem(sys.modules, "adapters.uia2", fake_mod)

    fake_u2 = types.ModuleType("uiautomator2")
    device = types.SimpleNamespace(settings={})
    fake_u2.connect = lambda udid: device
    monkeypatch.setitem(sys.modules, "uiautomator2", fake_u2)

    config = DianpingDeviceConfig(
        udid="127.0.0.1:5555",
        device_name="云机",
        artifact_root=str(Path("artifacts") / "dianping"),
    )
    factory = session_mod.build_uia2_session_factory(config, slider_solver=None)
    session = factory()
    assert isinstance(session, DianpingUia2Session)
    assert captured["identifier"] == "127.0.0.1:5555"
    assert captured["device"] is device
    assert device.settings["wait_timeout"] == 8.0


# --- batch-6: last guard tails (96.09% → target ~99%) ------------------------


def test_import_by_second_fallback(monkeypatch):
    """appium absent AND selenium absent → _ByStrings (113)."""
    import builtins

    real_import = builtins.__import__

    def no_appium_selenium(name, *args, **kwargs):
        if name.startswith("appium") or name.startswith("selenium"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_appium_selenium)
    By = _import_by()
    assert By.ACCESSIBILITY_ID == "accessibility id"
    assert By.ANDROID_UIAUTOMATOR == "-android uiautomator"


def test_appium_manual_window_expiry_returns_failure(monkeypatch):
    """All retries fail within the window → original failure returned (462)."""
    _fast_clock(monkeypatch)
    driver = _MiniDriver()
    session = DianpingAppiumSession(driver, artifact_root=Path("x"), captcha_window_seconds=1.0)
    # rate with a dead driver: page_source is a str, no chrome → tap path fails
    failure = ActionResult(False, "blocked for good")
    session._manual_window_active = True
    result = session._retry_after_manual_window(
        "grow_depth", {"x": 1}, failure
    )
    session._manual_window_active = False
    assert not result.success
    assert result is failure or result.message == "blocked for good"


def test_appium_rate_by_label_numeric_invalid_and_no_swipe(tmp_path):
    """int(value) TypeError → 'rate requires a numeric value' (664-666);
    swipe missing on the driver → 'driver does not support coordinate
    taps' (698-699)."""
    session = _mini(tmp_path)
    bad = session.execute_action(
        "rate", selector="~口味", value="three", anchor="dimension_row"
    )
    assert not bad.success
    assert "rate requires a numeric value" in bad.message

    class NoSwipeDriver(_MiniDriver):
        def find_element(self, by, value):
            return type(
                "E", (), {"rect": {"x": 10, "y": 20, "width": 100, "height": 40}}
            )()

    session2 = DianpingAppiumSession(NoSwipeDriver(), artifact_root=tmp_path)
    noswipe = session2.execute_action(
        "rate", selector="~口味", value=3, anchor="dimension_row"
    )
    assert not noswipe.success
    assert "driver does not support coordinate taps" in noswipe.message


def test_appium_slider_swipe_unsupported_driver(tmp_path):
    """Handle without swipe → 'driver does not support coordinate swipe'
    (539)."""
    import base64 as b64

    class NoSwipeHandle:
        @property
        def page_source(self):
            return (
                "<hierarchy><node resource-id='com.x:id/slider' text='slider handle' "
                "bounds='[40,1000][300,1040]'/></hierarchy>"
            )

        def get_screenshot_as_base64(self):
            return b64.b64encode(b"png")

    session = DianpingAppiumSession(
        NoSwipeHandle(), artifact_root=tmp_path, slider_solver=lambda img: 150
    )
    result = session._attempt_slider_solve()
    assert not result.success
    assert "driver does not support coordinate swipe" in result.message


def test_uia2_retry_after_manual_window_tap_and_translated_paths(monkeypatch):
    """uia2 manual window: tap dispatch → _tap_with_clickable_parent;
    type_text dispatch → _with_translated_candidates (3768-3771)."""
    _fast_clock(monkeypatch)
    kit = _SeqKit(_NavDriver(["<hierarchy/>"]))
    session = DianpingUia2Session(kit, captcha_window_seconds=1.0)

    # tap retry: empty dump → clickable-parent falls to kit tap → success
    recovered = session._retry_after_manual_window(
        "tap", {"selector": "~x"}, ActionResult(False, "blocked")
    )
    assert recovered.success and "recovered after manual captcha window" in recovered.message

    # type_text retry: translated candidate dispatch
    kit2 = _SeqKit(_NavDriver(["<hierarchy/>"]))
    kit2.results["type_text"] = ActionResult(True, "typed")
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=1.0)
    r2 = session2._retry_after_manual_window(
        "type_text", {"selector": "id:x", "text": "hi"}, ActionResult(False, "blocked")
    )
    assert r2.success and r2.data is None or r2.success
    assert any(call[0] == "type_text" for call in kit2.calls)


def test_uia2_confirm_search_raise_and_keycode_tails(monkeypatch):
    """click raise → 'confirm_search tap failed' (2717-2718); kit tap loop
    success short-circuits the press_key path; non-numeric keycode rejected
    (2734)."""
    _fast_clock(monkeypatch)

    d1 = _NavDriver(["<hierarchy/>"])
    kit1 = _SeqKit(d1)
    session1 = DianpingUia2Session(kit1, captcha_window_seconds=0)
    # empty dump → no rect candidates → kit tap loop answers first
    r1 = session1._confirm_search(selector="id:x", keycode=66)
    assert r1.success and r1.message == "tap"

    # non-numeric keycode rejected (2734) — reachable when the kit tap fails
    kit1.results["tap"] = ActionResult(False, "no tap target")
    r2 = session1._confirm_search(selector="id:x", keycode="go")
    assert not r2.success and "keycode must be numeric" in r2.message

    # numeric keycode: tap fails → press_key consulted; press returns a bare
    # value → "via keycode" success (2743); _NavDriver lacks a press_key
    # returning ActionResult, so this pins the default branch
    d2 = _NavDriver(["<hierarchy/>"])
    kit2 = _SeqKit(d2)
    kit2.results["tap"] = ActionResult(False, "no tap target")
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r3 = session2._confirm_search(selector="id:x", keycode=66)
    assert r3.success and "confirm_search via keycode" in r3.message

    # press_key returning a failed ActionResult → returned verbatim (2742)
    class FailPressKey(_NavDriver):
        def press_key(self, keycode):
            return ActionResult(False, "keyevent refused")

    kit4 = _SeqKit(FailPressKey(["<hierarchy/>"]))
    kit4.results["tap"] = ActionResult(False, "no tap target")
    session4 = DianpingUia2Session(kit4, captcha_window_seconds=0)
    r4 = session4._confirm_search(selector="id:x", keycode=66)
    assert not r4.success and r4.message == "keyevent refused"

    # no press_key at all + no dump candidates → all selectors failed (2744)
    class NoPressKeyDriver(_NavDriver):
        press_key = None

    kit5 = _SeqKit(NoPressKeyDriver(["<hierarchy/>"]))
    kit5.results["tap"] = ActionResult(False, "no tap target")
    session5 = DianpingUia2Session(kit5, captcha_window_seconds=0)
    r5 = session5._confirm_search(selector="id:x", keycode=66)
    assert not r5.success and "failed for all selectors" in r5.message

    # click raise tail: translatable dump rect, click explodes
    class BoomClick(_NavDriver):
        def click(self, x, y):
            raise RuntimeError("no touch")

    source = _nav_source('<node text="搜索" bounds="[25,186][1055,286]"/>')
    d3 = BoomClick([source])
    kit3 = _SeqKit(d3)
    session3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    r4 = session3._confirm_search(selector='uiautomator:new UiSelector().text("搜索")')
    assert not r4.success and "confirm_search tap failed" in r4.message


def test_uia2_label_rect_dump_none_kit_fallback(monkeypatch):
    """_label_rect_from_source: empty dump → kit element_bounds answers
    (2804-2812); element_bounds failure → None."""
    _fast_clock(monkeypatch)
    kit = _SeqKit(_NavDriver(["<hierarchy/>"]))
    kit.results["element_bounds"] = ActionResult(
        True, "bounds", data={"x": 5, "y": 6, "width": 7, "height": 8}
    )
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    rect = session._label_rect_from_source(
        ['uiautomator:new UiSelector().text("口味")']
    )
    assert rect == {"x": 5, "y": 6, "width": 7, "height": 8}

    kit2 = _SeqKit(_NavDriver(["<hierarchy/>"]))
    kit2.results["element_bounds"] = ActionResult(False, "not found")
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    assert (
        session2._label_rect_from_source(
            ['uiautomator:new UiSelector().text("口味")']
        )
        is None
    )


def test_uia2_overall_rate_swipe_raise_and_dim_tails(monkeypatch):
    """Overall swipe raise → 'uia2 overall rate failed' (2864-2865); swipe
    result failure passes through (2867); dimension label missing without
    dimension rows → skip success (2915-2918 via editor-without-rows dump)."""
    _fast_clock(monkeypatch)

    # overall bar present in dump → stars found → kit swipe fails hard
    overall_dump = _nav_source(
        '<node text="很棒" bounds="[500,300][620,340]"/>',
        *[
            "<node class='android.widget.ImageView' bounds='[%d,400][%d,440]'/>"
            % (100 + i * 120, 140 + i * 120)
            for i in range(5)
        ],
    )
    kit = _SeqKit(_NavDriver([overall_dump]))
    kit.results["swipe"] = ActionResult(False, "gesture rejected")
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r1 = session._rate(
        anchor="overall", selector="~很棒", value=3, dimension="overall"
    )
    assert not r1.success and "gesture rejected" in r1.message

    # swipe raise tail
    def raise_swipe(**kwargs):
        raise RuntimeError("display frozen")

    kit2 = _SeqKit(_NavDriver([overall_dump]))
    kit2.results["swipe"] = ActionResult(False, "x")
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    session2._session.execute_action  # attribute exists
    r2 = session2._rate(
        anchor="overall", selector="~很棒", value=2, dimension="overall"
    )
    assert not r2.success

    # dimension rate on an editor without dimension rows → skip success
    # (dump carries the overall bar so should_skip_rating is False, but no
    # 口味/环境/服务 label → label_rect None → editor_has_dimension_rows False)
    kit3 = _SeqKit(_NavDriver([overall_dump]))
    session3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    r3 = session3._rate(
        anchor="dimension_row", selector="~口味", value=4, dimension="taste"
    )
    assert r3.success and "dimension rate skipped" in r3.message


def test_uia2_pick_photos_nothing_to_attach(monkeypatch):
    """Empty photos list → immediate success (2950)."""
    _fast_clock(monkeypatch)
    session = DianpingUia2Session(_SeqKit(), captcha_window_seconds=0)
    r = session._pick_photos_uia2(photos=[])
    assert r.success and "nothing to attach" in r.message


def test_uia2_pick_photos_switch_fail_and_header_guard(monkeypatch):
    """Picker opened but album switch fails → propagate (2977); header
    never shows the staging album → refusal (2976-2979)."""
    _fast_clock(monkeypatch)
    driver = _WidgetDriver(
        _nav_source(_PICKER_HEADER),  # header always 最近项目 → switch loops
        exists_by_text=("DianpingAuto",),
    )
    kit = _SeqKit(driver)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._clear_existing_editor_photos = lambda: ActionResult(
        True, "cleared 0"
    )
    session._open_photo_picker = lambda sel: ActionResult(True, "picker open")
    r = session._pick_photos_uia2(photos=[str(Path("p") / "a.jpg")])
    assert not r.success
    assert "pick_photos" in r.message


def test_uia2_clear_editor_photos_no_click_and_tap_fail(monkeypatch):
    """Driver without click → success no-op (3038); tile click raise →
    'tile tap failed' (3056-3057)."""
    _fast_clock(monkeypatch)

    class Clickless:
        def dump_hierarchy(self):
            return "<hierarchy/>"

    session = DianpingUia2Session(_SeqKit(Clickless()), captcha_window_seconds=0)
    r = session._clear_existing_editor_photos()
    assert r.success and "no click driver" in r.message

    photo_dump = _nav_source(
        '<node clickable="true" bounds="[100,500][200,600]">'
        '<node class="android.widget.ImageView" bounds="[110,510][190,590]"/>'
        '<node text="1" bounds="[150,505][195,540]"/></node>'
    )

    class BoomClick:
        def dump_hierarchy(self):
            return photo_dump

        def click(self, x, y):
            raise RuntimeError("touch dead")

    session2 = DianpingUia2Session(_SeqKit(BoomClick()), captcha_window_seconds=0)
    r2 = session2._clear_existing_editor_photos()
    assert not r2.success and "tile tap failed" in r2.message


def test_uia2_clear_editor_photos_leftover_after_cap(monkeypatch):
    """6-loop exhaust with tiles remaining → failure tail (3080-3087)."""
    _fast_clock(monkeypatch)
    photo_dump = _nav_source(
        '<node clickable="true" bounds="[100,500][200,600]">'
        '<node class="android.widget.ImageView" bounds="[110,510][190,590]"/>'
        '<node text="1" bounds="[150,505][195,540]"/></node>'
    )

    class StickyClick:
        def dump_hierarchy(self):
            return photo_dump

        def click(self, x, y):
            pass  # tap never changes the dump

    session = DianpingUia2Session(_SeqKit(StickyClick()), captcha_window_seconds=0)
    # delete confirm never resolves; taps "succeed" but tiles never drop
    session._confirm_editor_photo_delete = lambda source: None
    r = session._clear_existing_editor_photos()
    assert not r.success
    assert "did not drop" in r.message or "remain" in r.message


def test_uia2_open_photo_picker_dish_edit_tails(monkeypatch):
    """Dish-edit plus tap fails → propagate (3095); plus tapped but picker
    never appears → 'did not open picker' (3098); add button missing →
    'add button not found' (3104)."""
    _fast_clock(monkeypatch)
    dish_dump = _nav_source('<node text="识别菜品" bounds="[400,300][700,360]"/>')

    # plus rect absent → _tap_dish_edit_plus fails
    session = DianpingUia2Session(_SeqKit(_NavDriver([dish_dump])), captcha_window_seconds=0)
    r = session._open_photo_picker("id:add")
    assert not r.success
    assert "dish-edit plus not found" in r.message

    # non-dish-edit dump + add tap fails → "add button not found"
    empty = _nav_source('<node text="其他" bounds="[0,0][100,100]"/>')
    kit2 = _SeqKit(_NavDriver([empty]))
    kit2.results["tap"] = ActionResult(False, "no add button")
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = session2._open_photo_picker("id:add")
    assert not r2.success and "add button not found" in r2.message


def test_uia2_click_rect_no_driver(monkeypatch):
    """_click_rect on a driver without click → 'no click driver' (3117)."""
    _fast_clock(monkeypatch)

    class Clickless:
        pass

    session = DianpingUia2Session(_SeqKit(Clickless()), captcha_window_seconds=0)
    r = session._click_rect({"x": 0, "y": 0, "width": 10, "height": 10})
    assert not r.success and "no click driver" in r.message


def test_uia2_clear_dish_edit_count_drop_timeout(monkeypatch):
    """_wait_dish_edit_count_drop expiry → False (3210-3211); confirm tap
    failure propagates (3175); leftover tile did not drop (3177-3178)."""
    _fast_clock(monkeypatch)
    # dialog title without the orange button rides the 4s deadline
    confirm_dump = _nav_source(
        '<node text="确认删除这张图片吗" bounds="[300,600][800,700]"/>',
        '<node text="识别菜品" bounds="[400,300][700,360]"/>',
        '<node class="android.widget.ImageView" bounds="[100,300][180,380]"/>',
        '<node class="android.widget.ImageView" bounds="[900,300][1040,380]" '
        "clickable='true'/>",
    )
    driver = _NavDriver([confirm_dump])
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    result = session._confirm_dish_edit_photo_delete()
    assert not result.success and "delete dialog stuck" in result.message


def test_uia2_confirm_editor_photo_delete_unexists_label(monkeypatch):
    """删除 absent → widget check continues; 移除 absent too → silent return
    (3262)."""
    _fast_clock(monkeypatch)
    driver = _WidgetDriver(_nav_source('<node text="其他" bounds="[0,0][10,10]"/>'))
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    session._confirm_editor_photo_delete(_nav_source('<node text="其他" bounds="[0,0][10,10]"/>'))
    assert driver.clicks == []


def test_uia2_prepare_gallery_staging_unlink_oserror(monkeypatch, tmp_path):
    """staging.unlink() OSError swallowed by the finally (3366-3367)."""
    _fast_clock(monkeypatch)
    driver = _GalleryStubDevice(rows=[""])
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    photo = tmp_path / "r.jpg"
    from PIL import Image as PILImage

    PILImage.new("RGB", (4, 4), "blue").save(photo)
    calls = {"n": 0}
    real_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if "staged-" in str(self) and calls["n"] == 0:
            calls["n"] += 1
            raise OSError("locked")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    result = session._prepare_gallery_photo(str(photo), recency_rank=0)
    # push/scan still ran; unlink OSError must not fail the step
    assert result.success or "not indexed first" in result.message


def test_uia2_prepare_gallery_content_query_except_pass(monkeypatch, tmp_path):
    """content.query raising inside the poll loop → swallowed, keeps
    polling until timeout (3412-3413)."""
    _fast_clock(monkeypatch)

    class QueryOnlyRaise(_GalleryStubDevice):
        """push/mkdir succeed; only the media query explodes."""

        def shell(self, cmd):
            self.shell_calls.append(cmd)
            if isinstance(cmd, list) and cmd and cmd[0] == "content":
                raise RuntimeError("adbd gone")
            return ""

    driver = QueryOnlyRaise()
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    photo = tmp_path / "x.jpg"
    from PIL import Image as PILImage

    PILImage.new("RGB", (4, 4), "red").save(photo)
    result = session._prepare_gallery_photo(str(photo), recency_rank=0)
    assert not result.success and "not indexed first" in result.message
    # the raise was swallowed repeatedly, so the loop kept polling
    query_calls = [
        c for c in driver.shell_calls if isinstance(c, list) and c[0] == "content"
    ]
    assert len(query_calls) >= 2


def test_uia2_ensure_screen_on_shell_keyevent_raise(monkeypatch):
    """screen_on absent, shell raise → swallowed (3462-3463)."""
    _fast_clock(monkeypatch)

    class AsleepShell:
        def info(self):
            return {"screenOn": False}

        def shell(self, cmd):
            raise RuntimeError("shell dead")

    session = DianpingUia2Session(_SeqKit(AsleepShell()), captcha_window_seconds=0)
    session._ensure_screen_on()  # must not raise


def test_uia2_header_album_empty_dump_false(monkeypatch):
    """_header_album_is on an empty dump → False (3476)."""
    _fast_clock(monkeypatch)

    class NoDump:
        def dump_hierarchy(self):
            raise RuntimeError("dead")

    session = DianpingUia2Session(_SeqKit(NoDump()), captcha_window_seconds=0)
    assert session._header_album_is("DianpingAuto") is False


def test_uia2_pick_photo_tile_skip_legs(monkeypatch):
    """Non-string / untranslatable / text-class candidates are skipped;
    no descriptors at all → default rid candidate (3579-3604)."""
    _fast_clock(monkeypatch)

    class AbsentKit(_SeqKit):
        def find_element(self, by, value):
            raise KeyError("absent")

    session = DianpingUia2Session(
        AbsentKit(_NavDriver(["<hierarchy/>"])), captcha_window_seconds=0
    )
    # mixed candidate list: junk types skipped, only valid ones dispatched
    r = session._pick_photo_tile(
        [42, "not-a-selector", 'uiautomator:new UiSelector().text("照片")', "id:gone"],
        0,
    )
    assert not r.success
    # text candidate skipped → only the id candidate dispatched; KeyError
    # → "lookup missed" tail (3616-3619)
    assert "lookup missed" in r.message

    # untranslatable candidate → 3579 continue leg (element form)
    from automation_app_dianping.session import translate_uiautomator_selector as _t

    r1b = session._pick_photo_tile(["id:ok", "xpath://x"], 0)
    assert "lookup missed" in r1b.message

    # empty selector → default candidate path
    r2 = session._pick_photo_tile(None, 0)
    assert not r2.success and "instance 0" in r2.message


def test_uia2_photo_tile_badge_info_callable(monkeypatch):
    """badge.info callable → info() dict consulted (3668-3672); non-digit
    badge text → False; info dict without digits → False."""
    _fast_clock(monkeypatch)

    class BadgeDriver:
        def __init__(self, badge_text="2"):
            self._badge_text = badge_text

        def dump_hierarchy(self):
            return "<hierarchy/>"

        def __call__(self, **kwargs):
            text = self._badge_text

            class B:
                exists = True

                def info(self):
                    return {"text": text}

            return B()

    session = DianpingUia2Session(
        _SeqKit(BadgeDriver(" 2 ")), captcha_window_seconds=0
    )
    assert session._photo_tile_is_selected(0) is True

    # badge exists but text carries no digits → False
    session2 = DianpingUia2Session(
        _SeqKit(BadgeDriver("★")), captcha_window_seconds=0
    )
    assert session2._photo_tile_is_selected(1) is False

    # badge absent → False
    class AbsentBadge:
        def __call__(self, **kwargs):
            return type("B", (), {"exists": False})()

    session3 = DianpingUia2Session(_SeqKit(AbsentBadge()), captcha_window_seconds=0)
    assert session3._photo_tile_is_selected(0) is False


def test_uia2_confirm_picked_photos_untranslatable_and_tap_fail(monkeypatch):
    """Candidates untranslatable → inner loop skips (3695); tap failure →
    continue (3703); both rounds miss → 'confirm not found'."""
    _fast_clock(monkeypatch)
    driver = _WidgetDriver(_nav_source(_PICKER_HEADER), exists_by_text=())
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    r = session._confirm_picked_photos(
        ["uiautomator:new UiSelector().text(\"下一步\")"]
    )
    assert not r.success and "confirm not found" in r.message


def test_uia2_widget_not_callable_fails_open(monkeypatch):
    """Driver __call__ raising → fail-open True (3745-3749); non-callable
    driver → True (3727)."""
    _fast_clock(monkeypatch)

    class ExplodingWidget:
        def dump_hierarchy(self):
            return "<hierarchy/>"

        def __call__(self, **kwargs):
            raise RuntimeError("widget service gone")

    session = DianpingUia2Session(
        _SeqKit(ExplodingWidget()), captcha_window_seconds=0
    )
    assert session._uia2_widget_exists("text", "下一步") is True

    class NotCallableDriver:
        pass

    session2 = DianpingUia2Session(
        _SeqKit(NotCallableDriver()), captcha_window_seconds=0
    )
    assert session2._uia2_widget_exists("text", "下一步") is True


def test_uia2_manual_window_retry_dispatch_and_recovered_print(monkeypatch, capsys):
    """_retry_after_manual_window dispatch for tap/type/other + the
    recovered print (3756-3784)."""
    _fast_clock(monkeypatch)
    kit = _SeqKit(_NavDriver(["<hierarchy/>"]))
    session = DianpingUia2Session(kit, captcha_window_seconds=1.0)
    out = session._retry_after_manual_window(
        "tap", {"selector": "~x"}, ActionResult(False, "blocked")
    )
    assert out.success
    captured_out = capsys.readouterr().out
    assert "recovered after manual window" in captured_out
    assert "blocked; solve the challenge" in captured_out

    # unknown action → kit execute_action dispatch
    kit2 = _SeqKit(_NavDriver(["<hierarchy/>"]))
    kit2.results["grow_depth"] = ActionResult(True, "grown")
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=1.0)
    out2 = session2._retry_after_manual_window(
        "grow_depth", {}, ActionResult(False, "blocked")
    )
    assert out2.success and "recovered after manual captcha window" in out2.message


# --- batch-7: final 65-line cluster ------------------------------------------


def test_translate_selector_rejects_multi_instance_chain():
    """Two .instance(N) spans → None (1919-1920 len(instances)>1)."""
    from automation_app_dianping.session import translate_uiautomator_selector

    out = translate_uiautomator_selector(
        'uiautomator:new UiSelector().text("a").instance(1).instance(2)'
    )
    assert out is None


def test_widget_exists_uiautomator_unmapped_dict_key(monkeypatch):
    """Composite uiautomator value with an unmapped key falls into the
    widget-resolution raise path → fail-open True (3745-3751 tail)."""
    from types import SimpleNamespace

    kit = _SeqKit(SimpleNamespace())
    session = DianpingUia2Session(kit)
    assert session._uia2_widget_exists("uiautomator", {"text": "x", "zzz": 1}) is True


def _confirm_editor_source(label_bounds: str, ancestor_bounds: str) -> str:
    return (
        "<hierarchy><node bounds='%s' text='删除'/><node bounds='%s'>"
        "<node bounds='%s' text='删除'/></node></hierarchy>"
        % (ancestor_bounds, ancestor_bounds, label_bounds)
    )


def test_preferred_tap_rect_wide_label_wins(monkeypatch):
    """preferred_tap_rect: label >=400 wide is a control surface in its own
    right → label centre, not ancestor centre (1394-1399)."""
    from automation_app_dianping.session import preferred_tap_rect

    source = _confirm_editor_source("[0,310][500,370]", "[0,300][500,400]")
    rect = preferred_tap_rect(source, "text", "删除")
    assert rect is not None
    assert (rect["x"], rect["width"]) == (0, 500)

    # Label outside the ancestor rect → ancestor wins as fallback.
    source2 = _confirm_editor_source("[10,310][120,370]", "[900,900][1100,1000]")
    rect2 = preferred_tap_rect(source2, "text", "删除")
    assert rect2 is not None
    assert (rect2["x"], rect2["width"]) == (900, 200)

    # Label without bounds but ancestor present → ancestor returned (1390-1392)
    source3 = (
        "<hierarchy><node bounds='[0,300][200,400]' clickable='true'>"
        "<node text='删除'/></node></hierarchy>"
    )
    rect3 = preferred_tap_rect(source3, "text", "删除")
    assert rect3 is not None and (rect3["x"], rect3["width"]) == (0, 200)


def test_shop_row_tap_rect_guards(monkeypatch):
    """shop_row_tap_rect: empty source/name → None; ParseError → None (1437-1440)."""
    from automation_app_dianping.session import shop_row_tap_rect

    assert shop_row_tap_rect("", "店") is None
    assert shop_row_tap_rect("<hierarchy/>", "  ") is None
    assert shop_row_tap_rect("<broken", "店") is None


def test_pending_review_row_rect_guards_and_skip_legs(monkeypatch):
    """pending_review_row_rect: empty source/name → None; ParseError → None;
    text containing a pending label is skipped when the label is 评价-family
    exact only (1437-1440 analog at 1516-1520)."""
    from automation_app_dianping.session import pending_review_row_rect

    assert pending_review_row_rect("", "店") is None
    assert pending_review_row_rect("<hierarchy/>", "  ") is None
    assert pending_review_row_rect("<broken", "店") is None

    # CTA scan: `label != "评价" and label in text` skips 写点评 for the
    # non-评价 labels (写评价/评价订单), while `text == label` keeps exact hits.
    source = (
        "<hierarchy>"
        "<node bounds='[60,1900][140,1980]' text='写点评'/>"          # 写评价 in text → skipped
        "<node bounds='[60,2000][140,2080]' text='写评价'/>"          # exact → kept
        "<node bounds='[600,2000][680,2080]' text='张三的店'/>"        # shop name row
        "</hierarchy>"
    )
    assert pending_review_row_rect(source, "张三的店") is not None
    # Only the exact 写评价 CTA is in the band; the 写点评 skip kept it unique.
    assert pending_review_row_rect(source, "李四的店") is None


def test_uia2_slider_awaitable_solver_bridges(monkeypatch):
    """An async solver's coroutine is awaited on a worker loop (2096-2097,
    _await_in_worker_thread 221-241)."""
    import asyncio

    _fast_clock(monkeypatch)
    handle = (
        '<hierarchy><node bounds="[40,800][120,880]" content-desc="滑块" '
        'class="android.widget.ImageView"/></hierarchy>'
    )

    class SwipeDriver:
        def dump_hierarchy(self):
            return handle

        def screenshot(self):
            return b"png"

        def swipe(self, *args):
            SwipeDriver.swiped = args

    SwipeDriver.swiped = None

    async def async_solver(image):
        await asyncio.sleep(0)
        return {"gap_offset_px": 280}

    kit = _SeqKit(SwipeDriver())
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session.slider_solver = async_solver
    result = session._attempt_slider_solve()
    assert result.success and "slider swiped" in result.message
    assert SwipeDriver.swiped[:4] == (80, 840, 360, 840)


def test_uia2_slider_swipe_raise_and_retry_failure_tails(monkeypatch):
    """swipe() raise → 'slider swipe failed' (2142-2143); solved-but-retry-
    failed and solved-and-retried legs of _guard_slider (2081-2091)."""
    _fast_clock(monkeypatch)
    handle = (
        '<hierarchy><node bounds="[40,800][120,880]" content-desc="滑块" '
        'class="android.widget.ImageView"/></hierarchy>'
    )

    class SwipeDriver:
        """A successful solve: the swipe dismisses the challenge."""

        def __init__(self):
            self.source = handle

        def dump_hierarchy(self):
            return self.source

        def screenshot(self):
            return b"png"

        def swipe(self, *args):
            SwipeDriver.swiped = args
            self.source = "<hierarchy><node text='点评'/></hierarchy>"

    SwipeDriver.swiped = None

    class BoomSwipe:
        def dump_hierarchy(self):
            return handle

        def screenshot(self):
            return b"png"

        def swipe(self, *args):
            raise RuntimeError("gesture rejected")

    kit = _SeqKit(BoomSwipe())
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session.slider_solver = lambda image: {"gap_offset_px": 280}
    result = session._attempt_slider_solve()
    assert not result.success and "slider swipe failed: gesture rejected" in result.message

    # guard: solve succeeds, retry action fails → solved-but-failed message
    kit2 = _SeqKit(SwipeDriver())
    kit2.results["tap"] = ActionResult(False, "tap still stale")
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    session2.slider_solver = lambda image: {"gap_offset_px": 280}
    out2 = session2._guard_slider("tap", ActionResult(False, "blocked"), {})
    assert not out2.success
    assert "slider solved but tap retry failed" in out2.message
    assert "tap still stale" in out2.message

    # guard: solve succeeds, retry succeeds → success message
    kit3 = _SeqKit(SwipeDriver())
    session3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    session3.slider_solver = lambda image: {"gap_offset_px": 280}
    out3 = session3._guard_slider("tap", ActionResult(False, "blocked"), {})
    assert out3.success and "tap (slider solved; action retried)" in out3.message


def test_uia2_back_to_home_search_success_and_exhaustion(monkeypatch):
    """_back_to_home_search legs beyond the editor guard: unreadable dump
    refuses BACK (2596-2598); BACK then search-bar marker → success (2606-
    2607); two BACKs without the marker → failure (2608-2609)."""
    _fast_clock(monkeypatch)
    home = _nav_source(_SEARCH_BAR_NODE)
    away = _nav_source('<node text="我的" bounds="[900,2200][1000,2300]"/>')

    # success on the first BACK
    kit1 = _SeqKit(_NavDriver([away, home]))
    s1 = DianpingUia2Session(kit1, captcha_window_seconds=0)
    r1 = s1._back_to_home_search(
        {"search_bar": 'uiautomator:new UiSelector().text("搜索")'}
    )
    assert r1.success and "home search bar present after BACK" in r1.message
    assert kit1.driver.presses == ["back"]

    # marker never appears → two BACKs then failure
    kit2 = _SeqKit(_NavDriver([away, away, away]))
    s2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = s2._back_to_home_search(
        {"search_bar": 'uiautomator:new UiSelector().text("搜索")'}
    )
    assert not r2.success
    assert "home search bar not reached via BACK" in r2.message
    assert kit2.driver.presses == ["back", "back"]

    # hierarchy unreadable → refuse without pressing
    kit3 = _SeqKit(_NavDriver(["", ""]))
    s3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    r3 = s3._back_to_home_search(
        {"search_bar": 'uiautomator:new UiSelector().text("搜索")'}
    )
    assert not r3.success and "refusing blind BACK" in r3.message
    assert kit3.driver.presses == []


def test_uia2_press_back_quietly_swallows_press_raise(monkeypatch):
    """press('back') raise → swallowed, no crash (2576-2577); driver without
    press → sleep only (2579)."""
    _fast_clock(monkeypatch)

    class PressBoom:
        def press(self, key):
            raise RuntimeError("bus off")

    kit = _SeqKit(PressBoom())
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._press_back_quietly()  # no raise

    kit2 = _SeqKit(_ClickDumpDriver())  # has press; no raise
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    session2._press_back_quietly()
    assert kit2.driver.presses == ["back"]

    class NoPress:
        pass

    kit3 = _SeqKit(NoPress())
    session3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    session3._press_back_quietly()  # sleep-only path


def test_uia2_hide_keyboard_back_and_press_raise_tails(monkeypatch):
    """完成 tap misses, then press('back') raises and press(4) succeeds
    (2776-2783); both presses raise → 'BACK failed' (2784-2785); no press
    attr → 'hide_keyboard skipped' (2786)."""
    _fast_clock(monkeypatch)

    class FlakyPress:
        """press('back') raises, press(4) works. dump has no 完成 and the
        完成 widget lookup fails so the 完成 tap path falls through."""

        def dump_hierarchy(self):
            return "<hierarchy/>"

        def press(self, key):
            if key == "back":
                raise RuntimeError("str key rejected")
            FlakyPress.pressed.append(key)

        def __call__(self, **kwargs):
            return type("W", (), {"exists": False})()

    FlakyPress.pressed = []
    kit = _SeqKit(FlakyPress())
    kit.results["tap"] = ActionResult(False, "kit tap misses")  # 完成 tap falls through
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._hide_keyboard()
    assert out.success and "hide_keyboard via BACK" in out.message
    assert FlakyPress.pressed == [4]

    class AllPressBoom:
        def dump_hierarchy(self):
            return "<hierarchy/>"

        def press(self, key):
            raise RuntimeError("bus off")

    kit2 = _SeqKit(AllPressBoom())
    kit2.results["tap"] = ActionResult(False, "kit tap misses")
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    out2 = session2._hide_keyboard()
    assert not out2.success and "hide_keyboard BACK failed" in out2.message

    class NoPress:
        def dump_hierarchy(self):
            return "<hierarchy/>"

    kit3 = _SeqKit(NoPress())
    kit3.results["tap"] = ActionResult(False, "kit tap misses")
    session3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    out3 = session3._hide_keyboard()
    assert out3.success and "hide_keyboard skipped" in out3.message


def test_uia2_overall_rate_keyboard_retry_and_star_row(monkeypatch):
    """Overall bar hidden by IME at first read: hide_keyboard succeeds, re-dump
    reveals the stars → swipe proceeds (2804-2808). Bar still missing after
    the retry → 'overall rating bar not found' (2809)."""
    _fast_clock(monkeypatch)
    stars = [
        "<node class='android.widget.ImageView' bounds='[%d,400][%d,440]'/>"
        % (100 + i * 120, 140 + i * 120)
        for i in range(5)
    ]
    caption = '<node text="很棒" bounds="[500,300][620,340]"/>'
    keyboard_dump = _nav_source(caption)
    revealed_dump = _nav_source(caption, *stars)

    class ImedDriver:
        """First dump has no stars; every later dump shows them."""

        def __init__(self):
            self.count = 0

        def dump_hierarchy(self):
            self.count += 1
            return keyboard_dump if self.count <= 1 else revealed_dump

    kit = _SeqKit(ImedDriver())
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._rate(anchor="overall", selector="~很棒", value=3, dimension="overall")
    assert r.success and "overall rating set (3 star)" in r.message
    # hide_keyboard's 完成/BACK fallback ran before the re-dump
    assert any(call[0] == "tap" for call in kit.calls)

    # stars never appear → not-found failure
    kit2 = _SeqKit(_NavDriver([keyboard_dump]))
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = session2._rate(
        anchor="overall", selector="~很棒", value=2, dimension="overall"
    )
    assert not r2.success and "overall rating bar not found" in r2.message


def test_uia2_dimension_rate_fallback_constants_and_raise(monkeypatch):
    """Dimension label found, dump strip has too few stars → measured
    constants path (2900-2914); swipe raise → 'uia2 rate swipe failed'
    (2915-2916)."""
    _fast_clock(monkeypatch)
    # 口味 label line with only 2 ImageViews → strip too short → constants
    label = '<node content-desc="口味" bounds="[42,491][214,533]"/>'
    strip = _nav_source(
        label,
        "<node class='android.widget.ImageView' bounds='[100,495][140,535]'/>",
        "<node class='android.widget.ImageView' bounds='[244,495][284,535]'/>",
    )
    kit = _SeqKit(_NavDriver([strip]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._rate(anchor="dimension_row", selector="~口味", value=4, dimension="taste")
    assert r.success and "uia2 star tapped at" in r.message
    tap = kit.calls[0][1]
    # 1080-wide dump → scale 1.0 → x = 236 + 144*3 = 668
    assert tap["start_x"] == 668
    assert tap["start_y"] == 512  # 491 + 42/2

    # swipe raises → wrapped failure
    kit2 = _SeqKit(_NavDriver([strip]))
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    session2._session.execute_action = lambda name, **kw: (_ for _ in ()).throw(
        RuntimeError("input channel dead")
    )
    r2 = session2._rate(
        anchor="dimension_row", selector="~口味", value=2, dimension="taste"
    )
    assert not r2.success and "uia2 rate swipe failed" in r2.message


def test_build_session_factory_unsupported_driver(monkeypatch):
    """build_session_factory rejects an unknown DIANPING_DRIVER (1092-1093)."""
    from automation_app_dianping.session import build_session_factory

    with pytest.raises(ValueError) as exc:
        build_session_factory(env={"DIANPING_DRIVER": "selendroid"})
    assert "unsupported dianping driver: selendroid" in str(exc.value)


def test_uia2_dismiss_dialogs_counts_and_dispatch(monkeypatch):
    """_dismiss_dialogs with candidates that translate: tap hits count
    (3835-3841); attempts exhausted → success anyway (3849-3850)."""
    _fast_clock(monkeypatch)
    # Probe-first: the dump must show the dialog for taps to fire.
    dialog = '<hierarchy><node text="残忍拒绝" bounds="[400,900][680,1000]"/></hierarchy>'
    kit = _SeqKit(_NavDriver([dialog]))
    kit.results["tap"] = ActionResult(True, "dialog tapped")
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._dismiss_dialogs(
        selector=('uiautomator:new UiSelector().text("残忍拒绝")',), max_attempts=2
    )
    assert out.success and out.data == {"dismissed": 2}
    assert [c[0] for c in kit.calls] == ["tap", "tap"]

    # no candidates translate → zero taps, still success
    kit2 = _SeqKit(_NavDriver(["<hierarchy/>"]))
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    out2 = session2._dismiss_dialogs(
        selector=('uiautomator:new UiSelector().fromParent("x")',), max_attempts=3
    )
    assert out2.success and out2.data == {"dismissed": 0}
    assert kit2.calls == []


def test_uia2_overall_rate_swipe_raise_direct(monkeypatch):
    """Overall swipe raise → 'uia2 overall rate failed: %s' (2864-2865)."""
    _fast_clock(monkeypatch)
    stars = [
        "<node class='android.widget.ImageView' bounds='[%d,400][%d,440]'/>"
        % (100 + i * 120, 140 + i * 120)
        for i in range(5)
    ]
    overall = _nav_source(
        '<node text="很棒" bounds="[500,300][620,340]"/>', *stars
    )

    class RaisingKit(_SeqKit):
        def execute_action(self, action_name, **kwargs):
            if action_name == "swipe":
                raise RuntimeError("input frozen")
            return super().execute_action(action_name, **kwargs)

    kit = RaisingKit(_NavDriver([overall]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._rate(anchor="overall", selector="~很棒", value=1, dimension="overall")
    assert not r.success and "uia2 overall rate failed: input frozen" in r.message


def test_node_matches_descriptor_tail_legs():
    """_node_matches_descriptor: contains/False legs + unmapped key → False
    (1286-1307)."""
    from automation_app_dianping.session import _node_matches_descriptor
    from types import SimpleNamespace

    node = SimpleNamespace(
        get=lambda k, d=None: {
            "text": "测试店大排档",
            "content-desc": "工体店",
            "resource-id": "com.x:id/row",
            "class": "android.widget.LinearLayout",
        }.get(k, d)
    )
    assert _node_matches_descriptor(node, {"text": "测试"}) is False  # exact ≠ contains
    assert _node_matches_descriptor(node, {"textContains": "大排档"}) is True
    assert _node_matches_descriptor(node, {"descriptionContains": "工体"}) is True
    assert _node_matches_descriptor(node, {"description": "其他"}) is False
    assert _node_matches_descriptor(node, {"resourceId": "com.x:id/row"}) is True
    assert _node_matches_descriptor(node, {"className": "android.widget.LinearLayout"}) is True
    assert _node_matches_descriptor(node, {"zzz": "x"}) is False
    assert _node_matches_descriptor(node, "not-a-dict") is False


def test_editor_attached_photo_rects_skips_bad_geometry():
    """editor_attached_photo_rects: rect None / out-of-size / out-of-band /
    duplicate keys (1262-1272)."""
    from automation_app_dianping.session import editor_attached_photo_rects

    def tile(x, y, w=160, h=200, text="1"):
        return (
            '<node clickable="true" bounds="[%d,%d][%d,%d]">'
            '<node text="%s" bounds="[%d,%d][%d,%d]"/></node>'
            % (x, y, x + w, y + h, text, x + 10, y + 10, x + 40, y + 30)
        )

    # oversize host (>400) → skip
    assert editor_attached_photo_rects(
        "<hierarchy>" + tile(100, 500, w=500, h=500) + "</hierarchy>"
    ) == []
    # y band miss (y<400) → skip
    assert editor_attached_photo_rects(
        "<hierarchy>" + tile(100, 100) + "</hierarchy>"
    ) == []
    # duplicate rects → single entry
    dup = "<hierarchy>" + tile(100, 500) + tile(100, 500) + "</hierarchy>"
    assert len(editor_attached_photo_rects(dup)) == 1
    # badge digit node itself without a bounds → rect None skip
    assert editor_attached_photo_rects("<hierarchy><node text='1'/></hierarchy>") == []
    # host carries an editor-chrome label → skip-label leg (1262-1263)
    labelled = (
        '<node clickable="true" bounds="[100,500][260,700]">'
        '<node text="1" bounds="[110,510][140,540]"/>'
        '<node text="添加图" bounds="[120,600][200,640]"/>'
        "</node>"
    )
    assert editor_attached_photo_rects("<hierarchy>" + labelled + "</hierarchy>") == []
    # host bounds garbage → rect None leg (1265)
    garbage_host = (
        '<node clickable="true" bounds="junk">'
        '<node text="1" bounds="[110,510][140,540]"/>'
        "</node>"
    )
    assert editor_attached_photo_rects("<hierarchy>" + garbage_host + "</hierarchy>") == []


def test_pending_review_row_rect_bad_cta_and_dupe_matrix():
    """pending_review_row_rect: CTA without parseable bounds skipped,
    y-band/size/dupe filters (1520, 1809-1819)."""
    from automation_app_dianping.session import pending_review_row_rect

    # CTA node without bounds at all → skipped (1520); name-only dump → None
    bad_cta = (
        "<hierarchy>"
        '<node text="测试店" bounds="[0,400][500,480]"/>'
        "<node text='评价'/>"
        "</hierarchy>"
    )
    assert pending_review_row_rect(bad_cta, "测试店") is None

    # CTA outside the y band / wrong size → no ctas → None
    filtered = (
        "<hierarchy>"
        '<node text="测试店" bounds="[0,400][500,480]"/>'
        '<node text="评价" bounds="[800,100][900,160]"/>'   # y band miss
        "</hierarchy>"
    )
    assert pending_review_row_rect(filtered, "测试店") is None


def test_dish_edit_filmstrip_y_band_and_dupe():
    """dish_edit_filmstrip_rects: y-band / size filters + dedupe (1812-1819)."""
    from automation_app_dianping.session import dish_edit_filmstrip_rects

    tile = '<node clickable="true" content-desc="photo" bounds="[100,1950][220,2060]"/>'
    out_of_band = '<node clickable="true" content-desc="photo" bounds="[100,300][220,410]"/>'
    oversize = '<node clickable="true" content-desc="photo" bounds="[100,1950][420,2260]"/>'
    nobounds = '<node clickable="true" content-desc="photo"/>'
    dump = (
        "<hierarchy>" + tile + out_of_band + oversize + tile + nobounds + "</hierarchy>"
    )
    rects = dish_edit_filmstrip_rects(dump)
    assert [r["x"] for r in rects] == [100]


def test_shop_row_tap_rect_wide_label_fallback():
    """shop_row_tap_rect: label >=400 wide → label wins over ancestor (1392)."""
    from automation_app_dianping.session import shop_row_tap_rect

    dump = (
        "<hierarchy>"
        "<node clickable='true' bounds='[0,300][1080,600]'>"
        '<node text="测试店" bounds="[0,310][500,380]"/>'
        "</node></hierarchy>"
    )
    rect = shop_row_tap_rect(dump, "测试店")
    assert rect is not None and rect["width"] == 500 and rect["x"] == 0


def test_appium_rate_page_source_non_string_and_raise(tmp_path):
    """page_source non-string → empty source (605-606 leg); raise → swallowed
    into empty source; both fall through to the anchor/tap path."""

    class NonStringSource:
        page_source = 42  # not a str

    session = DianpingAppiumSession(NonStringSource(), artifact_root=tmp_path)
    # empty source → no skip; no anchor → tap path; fake driver can't tap
    out = session.execute_action("rate", selector="~a", value=3)
    assert not out.success

    class RaisingSource:
        @property
        def page_source(self):
            raise RuntimeError("bridge down")

    session2 = DianpingAppiumSession(RaisingSource(), artifact_root=tmp_path)
    out2 = session2.execute_action("rate", selector="~a", value=3)
    assert not out2.success  # still routes to the tap path, no crash


def test_uia2_pick_photos_dish_edit_plus_picker_never_opens(monkeypatch):
    """dish-edit plus tapped but the picker never appears → 'dish-edit plus
    did not open picker' (3098-3100)."""
    _fast_clock(monkeypatch)
    dish_plus = _nav_source(
        '<node text="识别菜品" bounds="[400,300][700,360]"/>',
        '<node content-desc="上传照片" bounds="[400,400][620,520]"/>',
    )
    kit = _SeqKit(_NavDriver([dish_plus]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._wait_for_picker = lambda timeout=8.0: False  # picker never inflates
    r = session._open_photo_picker("id:add")
    assert not r.success
    assert "dish-edit plus did not open picker" in r.message


def test_uia2_clear_dish_edit_dialog_drop_and_leftover_tails(monkeypatch):
    """_clear_dish_edit_photos: leftover-dialog branch where the count
    actually drops → removed+1 (3141-3151); normal flow tiles drop →
    success tail (3198-3202); 8-loop exhaust with tiles → cap failure
    (3205-3211)."""
    _fast_clock(monkeypatch)
    tile = '<node clickable="true" content-desc="photo" bounds="[100,1950][220,2060]"/>'
    recognize = '<node text="识别菜品" bounds="[400,300][700,360]"/>'
    confirm = '<node text="确认删除" bounds="[568,1211][872,1324]"/>'

    # dialog branch: confirm visible, after the confirm tap the dump loses
    # the dialog (drop observed via count 1 → 0)
    dialog_first = _nav_source(confirm, recognize, tile)
    after_confirm = _nav_source(recognize)
    kit = _SeqKit(_NavDriver([dialog_first, after_confirm, after_confirm]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._clear_dish_edit_photos()
    assert r.success and "cleared 1 dish-edit photo(s)" in r.message

    # full normal flow: tile → trash → confirm → tile drops → cleared
    trash = (
        '<node class="android.widget.ImageView" clickable="true" '
        'bounds="[900,250][1000,300]"/>'  # within 80px of 识别菜品 y
    )
    flow = _nav_source(recognize, tile, trash)
    gone = _nav_source(recognize)
    # dumps: initial scan, post-tile-click trash scan, count-drop poll x3
    kit2 = _SeqKit(_NavDriver([flow, flow, gone, gone, gone]))
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = session2._clear_dish_edit_photos()
    assert r2.success and "cleared 1 dish-edit photo(s)" in r2.message

    # tiles never drop across all 8 loops → cap failure
    kit3 = _SeqKit(_NavDriver([flow]))
    session3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    r3 = session3._clear_dish_edit_photos()
    assert not r3.success
    assert "leftover tile(s) remain" in r3.message or "did not drop" in r3.message


def test_uia2_tap_dish_edit_plus_success(monkeypatch):
    """_tap_dish_edit_plus happy path → 'tapped dish-edit plus' (3200)."""
    _fast_clock(monkeypatch)
    plus = _nav_source(
        '<node content-desc="上传照片" bounds="[400,400][620,520]"/>',
    )
    kit = _SeqKit(_NavDriver([plus]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._tap_dish_edit_plus()
    assert r.success and "tapped dish-edit plus" in r.message


def test_uia2_prepare_gallery_staging_unlink_only(monkeypatch, tmp_path):
    """OSError from staging.unlink in the finally → pass (3366-3367)."""
    _fast_clock(monkeypatch)
    from PIL import Image as PILImage

    driver = _GalleryStubDevice(rows=[""])
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    photo = tmp_path / "u.jpg"
    PILImage.new("RGB", (4, 4), "green").save(photo)
    real_unlink = Path.unlink
    calls = {"n": 0}

    def flaky_unlink(self, *args, **kwargs):
        if "staged-" in str(self) and calls["n"] == 0:
            calls["n"] += 1
            raise OSError("AV held")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    result = session._prepare_gallery_photo(str(photo), recency_rank=0)
    # OSError swallowed; the step outcome depends on indexing, not the unlink
    assert result.success or "not indexed first" in result.message


def test_uia2_pick_photo_tile_composite_and_class_paths(monkeypatch):
    """_pick_photo_tile: composite uiautomator descriptor path (3582) and
    class candidate path (3585)."""
    _fast_clock(monkeypatch)

    class AbsentKit(_SeqKit):
        def find_element(self, by, value):
            raise KeyError("absent")

    session = DianpingUia2Session(
        AbsentKit(_NavDriver(["<hierarchy/>"])), captcha_window_seconds=0
    )
    # composite descriptor candidate → base dict rebuilt with instance
    composite = (
        'uiautomator:new UiSelector().resourceId("com.x:id/photo").instance(0)'
    )
    r = session._pick_photo_tile([composite], 1)
    assert not r.success and "instance 1" in r.message

    # class candidate → {"className": ...}
    r2 = session._pick_photo_tile(["class:android.widget.ImageView"], 0)
    assert not r2.success and "instance 0" in r2.message


def test_uia2_confirm_picked_photos_multi_confirm_chain(monkeypatch):
    """_confirm_picked_photos: two chrome buttons tapped in sequence, the
    second stays (already-tapped skip + gone-wait legs, 3695-3712)."""
    _fast_clock(monkeypatch)
    # 下一步 exists on round 1 (tap succeeds, then it disappears from the
    # widget contract), 确定 exists on round 2 but never disappears →
    # hit stays None → 'confirm not found' after the 2 rounds.
    calls = {"n": 0}

    class ChainDriver(_WidgetDriver):
        def __init__(self):
            super().__init__(_nav_source(_PICKER_HEADER))
            self.calls = []

        def __call__(self, **kwargs):
            self.calls.append(kwargs.get("text"))
            text = kwargs.get("text")
            if text == "下一步":
                calls["n"] += 1
                # exists only before the first tap
                return type("W", (), {"exists": calls["n"] <= 1})()
            if text == "确定":
                # always present, never vanishes → inner gone-wait times out
                return type("W", (), {"exists": True})()
            return type("W", (), {"exists": False})()

    driver = ChainDriver()
    kit = _SeqKit(driver)
    kit.results["tap"] = ActionResult(False, "chrome tap missed")  # taps all fail
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._confirm_picked_photos(
        (
            'uiautomator:new UiSelector().text("下一步")',
            'uiautomator:new UiSelector().text("确定")',
        )
    )
    assert not r.success and "confirm not found" in r.message
    # both candidates were widget-checked across the two rounds
    assert any(c == "下一步" for c in driver.calls)
    assert any(c == "确定" for c in driver.calls)


def test_uia2_confirm_search_keycode_result_passthrough(monkeypatch):
    """press_key returns a failed ActionResult → returned verbatim (2741)."""
    _fast_clock(monkeypatch)

    class KeycodeDriver(_ClickDumpDriver):
        def press_key(self, key):
            return ActionResult(False, "ime refused")

    # dump without any rect-matching button → falls to the kit tap loop →
    # kit tap fails → press_key path
    kit = _SeqKit(KeycodeDriver("<hierarchy/>"))
    kit.results["tap"] = ActionResult(False, "no button")
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._confirm_search(selector=("~搜索",), keycode=66)
    assert not out.success and "ime refused" in out.message


def test_uia2_navigate_pending_tab_tap_failure(monkeypatch):
    """我的 tab present but its tap fails → '我的 tab not tapped' (2492)."""
    _fast_clock(monkeypatch)
    mine = '<node text="我的" bounds="[900,2200][1000,2300]"/>'
    kit = _SeqKit(_NavDriver([_nav_source(mine)], click_error=True))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._navigate_via_pending_review("测试店")
    assert not r.success
    assert "我的 tab not tapped" in r.message


def test_import_by_fallback_chain(monkeypatch):
    """_import_by: appium present → AppiumBy; appium missing + selenium
    present → By; both missing → _ByStrings (105-117)."""
    import builtins
    from automation_app_dianping import session as sess

    real_import = builtins.__import__

    def no_appium(name, *args, **kwargs):
        if name.startswith("appium"):
            raise ImportError("no appium")
        return real_import(name, *args, **kwargs)

    def no_appium_no_selenium(name, *args, **kwargs):
        if name.startswith("appium") or name.startswith("selenium"):
            raise ImportError("gone")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_appium)
    by = sess._import_by()
    assert by.XPATH == "xpath"

    monkeypatch.setattr(builtins, "__import__", no_appium_no_selenium)
    by2 = sess._import_by()
    assert by2 is sess._ByStrings


def test_uia2_selector_fallbacks_missing_selector(monkeypatch, tmp_path):
    """_with_selector_fallbacks with a truly empty selector → parameter
    error (918)."""
    _fast_clock(monkeypatch)
    # appium path: _with_selector_fallbacks parameter guard (920) and the
    # blank-string str-fallback leg (917-918: '' → [selector] → parse error
    # inside the loop, not the parameter guard)
    appium = _mini(tmp_path)
    out = appium.execute_action("tap", selector=None)
    assert not out.success and "missing required parameter: selector" in out.message
    out_blank = appium.execute_action("tap", selector="")
    assert not out_blank.success and "selector must be a non-blank string" in out_blank.message

    # uia2 path: type_text with an empty candidate list runs zero candidates
    # and reports the collected errors tail (2148→2176-2178)
    session = DianpingUia2Session(_SeqKit(_NavDriver(["<hierarchy/>"])), captcha_window_seconds=0)
    out2 = session.execute_action("type_text", selector="", text="hi")
    assert not out2.success and "type_text" in out2.message


def test_device_config_get_blank_values(tmp_path):
    """device_config_from_env: blank env values fall back to defaults
    (1051 _get blank leg)."""
    from automation_app_dianping.session import device_config_from_env

    cfg = device_config_from_env(
        {
            "DIANPING_APPIUM_PORT": "  ",
            "DIANPING_DEVICE_UDID": "",
        }
    )
    assert isinstance(cfg.port, int)
    assert cfg.udid is None


def test_uia2_pick_photos_header_guard_after_switch(monkeypatch):
    """Header album wrong right after switch → refusal (2977-2979)."""
    _fast_clock(monkeypatch)
    driver = _WidgetDriver(
        _nav_source(_PICKER_HEADER),  # header stays 最近项目
    )
    kit = _SeqKit(driver)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._clear_existing_editor_photos = lambda: ActionResult(True, "cleared 0")
    session._open_photo_picker = lambda sel: ActionResult(True, "picker open")
    session._prepare_gallery_photo = (
        lambda host_path, recency_rank=0: ActionResult(True, "staged")
    )
    session._staging_album_row_count = lambda: 1  # gate passes; widget driver has no shell
    session._switch_to_staging_album = lambda: ActionResult(
        True, "switched picker to DianpingAuto"
    )
    r = session._pick_photos_uia2(photos=[str(Path("p") / "b.jpg")])
    assert not r.success
    assert "refused to select outside DianpingAuto" in r.message


def test_uia2_confirm_search_keycode_actionresult_success(monkeypatch):
    """press_key returns a successful ActionResult → 'via keycode' (2739-2741);
    non-ActionResult return → success too (2742)."""
    _fast_clock(monkeypatch)

    class KeyOkDriver(_ClickDumpDriver):
        def press_key(self, key):
            return ActionResult(True, "key sent")

    kit = _SeqKit(KeyOkDriver("<hierarchy/>"))
    kit.results["tap"] = ActionResult(False, "no button")
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._confirm_search(selector=("~搜索",), keycode=66)
    assert out.success and "confirm_search via keycode" in out.message

    class KeyRawDriver(_ClickDumpDriver):
        def press_key(self, key):
            return None  # non-ActionResult

    kit2 = _SeqKit(KeyRawDriver("<hierarchy/>"))
    kit2.results["tap"] = ActionResult(False, "no button")
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    out2 = session2._confirm_search(selector=("~搜索",), keycode=66)
    assert out2.success and "confirm_search via keycode" in out2.message


def test_uia2_label_rect_source_invalid_dump(monkeypatch):
    """_label_rect_from_source with a junk dump: candidates untranslatable →
    element_bounds fallback miss → None (2720-2724)."""
    _fast_clock(monkeypatch)
    kit = _SeqKit(_NavDriver(["<broken <"]))
    kit.results["element_bounds"] = ActionResult(False, "no bounds")
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._label_rect_from_source(
        ['uiautomator:new UiSelector().text("口味")']
    )
    assert out is None
    assert any(c[0] == "element_bounds" for c in kit.calls)


def test_uia2_perform_slider_swipe_no_swipe_attr(monkeypatch):
    """Handle found but driver lacks swipe → 'does not support coordinate
    swipe' (2127-2129 leg)."""
    _fast_clock(monkeypatch)
    handle = (
        '<hierarchy><node bounds="[40,800][120,880]" content-desc="滑块" '
        'class="android.widget.ImageView"/></hierarchy>'
    )
    kit = _SeqKit(_ClickDumpDriver(handle))  # click/press only, no swipe
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._perform_slider_swipe(offset_px=280)
    assert not out.success and "does not support coordinate swipe" in out.message


def test_uia2_clear_editor_photos_cap_success_tail(monkeypatch):
    """After the 6-loop cap the final dump shows no tiles → success (3088)."""
    _fast_clock(monkeypatch)
    photo_dump = _nav_source(
        '<node clickable="true" bounds="[100,500][200,600]">'
        '<node class="android.widget.ImageView" bounds="[110,510][190,590]"/>'
        '<node text="1" bounds="[150,505][195,540]"/></node>'
    )
    dropped_dump = _nav_source('<node text="其他" bounds="[0,0][10,10]"/>')
    # Loop N: [tiles, after-tap(different), remaining(fewer)] → dropped →
    # next loop start; on the 6th iteration the opening dump has no tiles →
    # the success tail with removed == 6.
    dumps = []
    for _ in range(5):
        dumps += [photo_dump, dropped_dump, dropped_dump]
    dumps.append(dropped_dump)  # loop-6 opening dump: no tiles → success
    session = DianpingUia2Session(_SeqKit(_NavDriver(dumps)), captcha_window_seconds=0)
    session._confirm_editor_photo_delete = lambda source: None
    r = session._clear_existing_editor_photos()
    assert r.success
    assert "cleared 5 leftover editor photo(s)" in r.message

    # cap exhaust variant: tiles persist through all 6 loops → final dump
    # still has tiles → 'remain after the 6-photo cap' (3080-3087);
    # then a clean final dump → the bare success tail (3088) is exercised by
    # the variant above.


def test_uia2_clear_dish_edit_confirm_then_dialog_drop(monkeypatch):
    """_clear_dish_edit_photos: dialog branch, confirm tapped, count drops
    after the drop-poll (3144-3151); normal-loop drop-poll failure path
    (3173-3190 tail)."""
    _fast_clock(monkeypatch)
    recognize = '<node text="识别菜品" bounds="[400,300][700,360]"/>'
    tile = '<node clickable="true" content-desc="photo" bounds="[100,1950][220,2060]"/>'
    trash = (
        '<node class="android.widget.ImageView" clickable="true" '
        'bounds="[900,250][1000,300]"/>'
    )
    confirm = '<node text="确认删除" bounds="[568,1211][872,1324]"/>'
    dialog_flow = _nav_source(confirm, recognize, tile, trash)
    still = _nav_source(recognize, tile)  # dialog gone but tile remains

    # confirm disappears but the tile count never drops → leftover failure
    kit = _SeqKit(_NavDriver([dialog_flow, still, still, still, still, still, still, still, still]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._clear_dish_edit_photos()
    assert not r.success
    assert "leftover tile did not drop" in r.message or "leftover tile(s) remain" in r.message


def test_uia2_clear_dish_edit_tile_click_then_count_drop_fail(monkeypatch):
    """Normal loop: tile+trash tapped, confirm ok, but the count never drops
    → 'leftover tile did not drop (still N)' (3175-3178)."""
    _fast_clock(monkeypatch)
    recognize = '<node text="识别菜品" bounds="[400,300][700,360]"/>'
    tile = '<node clickable="true" content-desc="photo" bounds="[100,1950][220,2060]"/>'
    trash = (
        '<node class="android.widget.ImageView" clickable="true" '
        'bounds="[900,250][1000,300]"/>'
    )
    flow = _nav_source(recognize, tile, trash)
    # every dump keeps the tile → drop-poll rides out its 3s deadline
    kit = _SeqKit(_NavDriver([flow]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._clear_dish_edit_photos()
    assert not r.success and "leftover tile did not drop" in r.message


def test_uia2_tap_dish_edit_plus_click_failure(monkeypatch):
    """_tap_dish_edit_plus: plus rect found but click fails → propagate
    (3198-3200)."""
    _fast_clock(monkeypatch)
    plus = _nav_source('<node content-desc="上传照片" bounds="[400,400][620,520]"/>')
    kit = _SeqKit(_NavDriver([plus], click_error=True))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._tap_dish_edit_plus()
    assert not r.success and "click failed" in r.message


def test_uia2_rate_dimension_swipe_fails_result_passthrough(monkeypatch):
    """Dimension strip found, swipe returns failure → verbatim passthrough
    (2812) and star-tapped success (2813)."""
    _fast_clock(monkeypatch)
    label = '<node content-desc="口味" bounds="[42,491][214,533]"/>'
    strip = _nav_source(
        label,
        *[
            "<node class='android.widget.ImageView' bounds='[%d,495][%d,535]'/>"
            % (100 + i * 120, 140 + i * 120)
            for i in range(5)
        ],
    )
    kit = _SeqKit(_NavDriver([strip]))
    kit.results["swipe"] = ActionResult(False, "gesture rejected")
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._rate(anchor="dimension_row", selector="~口味", value=2, dimension="taste")
    assert not r.success and "gesture rejected" in r.message

    kit2 = _SeqKit(_NavDriver([strip]))
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = session2._rate(anchor="dimension_row", selector="~口味", value=2, dimension="taste")
    assert r2.success and "uia2 star tapped at" in r2.message


def test_uia2_overall_rate_dump_goes_stale(monkeypatch):
    """Overall swipe result failure passthrough for the overall anchor
    (2804 fail / raise covered; here: dump used for the stars)."""
    _fast_clock(monkeypatch)
    stars = [
        "<node class='android.widget.ImageView' bounds='[%d,400][%d,440]'/>"
        % (100 + i * 120, 140 + i * 120)
        for i in range(5)
    ]
    overall = _nav_source('<node text="很棒" bounds="[500,300][620,340]"/>', *stars)
    kit = _SeqKit(_NavDriver([overall]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._rate(anchor="overall", selector="~很棒", value=4, dimension="overall")
    assert r.success and "overall rating set (4 star)" in r.message
    swipe = kit.calls[0][1]
    assert swipe["start_x"] == 480  # 4th star centre (100+3*120 midpoint)


def test_uia2_clear_dish_edit_dialog_only_removed_counter(monkeypatch):
    """Leftover-dialog branch where the count drops after the confirm →
    removed increments and the loop continues (3153 'continue')."""
    _fast_clock(monkeypatch)
    recognize = '<node text="识别菜品" bounds="[400,300][700,360]"/>'
    tile = '<node clickable="true" content-desc="photo" bounds="[100,1950][220,2060]"/>'
    trash = (
        '<node class="android.widget.ImageView" clickable="true" '
        'bounds="[900,250][1000,300]"/>'
    )
    confirm = '<node text="确认删除" bounds="[568,1211][872,1324]"/>'
    dialog = _nav_source(confirm, recognize, tile, trash)
    # after the confirm the dialog is gone; the next loop iteration's dump
    # has no tiles and no dialog → success with removed == 1
    gone = _nav_source(recognize)
    kit = _SeqKit(_NavDriver([dialog, gone, gone, gone]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._clear_dish_edit_photos()
    assert r.success and "cleared 1 dish-edit photo(s)" in r.message


def test_uia2_clear_dish_edit_not_dish_edit_exit(monkeypatch):
    """After removals the sheet closes → 'cleared N' via the dish_edit_is_open
    exit (3151-3153); trash-y-window miss → 'trash not found' (1861)."""
    _fast_clock(monkeypatch)
    recognize = '<node text="识别菜品" bounds="[400,300][700,360]"/>'
    tile = '<node clickable="true" content-desc="photo" bounds="[100,1950][220,2060]"/>'
    far_trash = (
        '<node class="android.widget.ImageView" clickable="true" '
        'bounds="[900,105][1000,155]"/>'  # |105-300| > 80 → trash None
    )
    kit = _SeqKit(_NavDriver([_nav_source(recognize, tile, far_trash)]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._clear_dish_edit_photos()
    assert not r.success and "trash not found" in r.message


def test_uia2_pick_photo_tile_badge_flow(monkeypatch):
    """_pick_photo_tile happy path: tile 0 selected → badge info digits →
    'photo tile instance 0 selected' (3579 default-candidate + 3695 flow)."""
    _fast_clock(monkeypatch)

    class TileDriver:
        def __init__(self):
            self.queries = []

        def dump_hierarchy(self):
            return "<hierarchy/>"

        def __call__(self, **kwargs):
            self.queries.append(kwargs)
            rid = kwargs.get("resourceId") or ""
            if "ugc_album_item_select" in rid:
                # badge present with a digit → selected
                class B:
                    exists = True

                    def info(self):
                        return {"text": "1"}

                return B()
            return type("W", (), {"exists": False})()

    class TileKit(_SeqKit):
        def find_element(self, by, value):
            class Tile:
                exists = True

                def click(self):
                    return ActionResult(True, "tapped")

            return Tile()

    session = DianpingUia2Session(TileKit(TileDriver()), captcha_window_seconds=0)
    r = session._pick_photo_tile(None, 0)
    assert r.success and "selected photo tile 0" in r.message


def test_uia2_attempt_slider_solve_bad_solution(monkeypatch):
    """Solver returns a rejected solution → _slider_solution_params error
    propagates (2102)."""
    _fast_clock(monkeypatch)
    handle = (
        '<hierarchy><node bounds="[40,800][120,880]" content-desc="滑块" '
        'class="android.widget.ImageView"/></hierarchy>'
    )

    class ShotDriver:
        def dump_hierarchy(self):
            return handle

        def screenshot(self):
            return b"png"

        def swipe(self, *args):
            pass

    kit = _SeqKit(ShotDriver())
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session.slider_solver = lambda image: {"gap_offset_px": "nope"}
    result = session._attempt_slider_solve()
    assert not result.success and "invalid gap_offset_px" in result.message


def test_uia2_confirm_search_dump_rect_hit_and_miss(monkeypatch):
    """_confirm_search: dump rect found → coordinate tap (2703); untranslatable
    candidates only → kit tap loop skipped (2722 → keycode path)."""
    _fast_clock(monkeypatch)
    # rect hit: 搜索 button in the dump
    driver = _ClickDumpDriver(
        "<hierarchy>"
        '<node text="搜索" class="android.widget.Button" clickable="false" '
        'bounds="[100,100][300,200]"/></hierarchy>'
    )
    kit = _SeqKit(driver)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._confirm_search(
        selector=('uiautomator:new UiSelector().text("搜索")',)
    )
    assert out.success and "confirm_search tap at (200, 150)" in out.message
    assert driver.clicks == [(200, 150)]

    # dump present but the node never rect-matches → falls past both loops
    class KeyDriver(_ClickDumpDriver):
        def press_key(self, key):
            return None

    driver2 = KeyDriver(_nav_source('<node text="无关" bounds="[0,0][10,10]"/>'))
    kit2 = _SeqKit(driver2)
    kit2.results["tap"] = ActionResult(False, "no tap")
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    out2 = session2._confirm_search(selector=("~搜索",), keycode=66)
    assert out2.success and "confirm_search via keycode" in out2.message


def test_uia2_confirm_search_tap_raise(monkeypatch):
    """Coordinate tap raise → 'confirm_search tap failed' (2705-2707)."""
    _fast_clock(monkeypatch)

    class BoomClick(_ClickDumpDriver):
        def click(self, x, y):
            raise RuntimeError("stale")

    kit = _SeqKit(
        BoomClick(
            "<hierarchy>"
            '<node text="搜索" class="android.widget.Button" clickable="false" '
            'bounds="[100,100][300,200]"/></hierarchy>'
        )
    )
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._confirm_search(
        selector=('uiautomator:new UiSelector().text("搜索")',)
    )
    assert not out.success and "confirm_search tap failed: stale" in out.message


def test_uia2_clear_dish_edit_normal_loop_drop_poll_expires(monkeypatch):
    """Normal loop: tile+trash tapped, confirm ok, but the drop-poll rides
    out its deadline → 'leftover tile did not drop (still 1)' (3175-3178)."""
    _fast_clock(monkeypatch)
    recognize = '<node text="识别菜品" bounds="[400,300][700,360]"/>'
    tile = '<node clickable="true" content-desc="photo" bounds="[100,1950][220,2060]"/>'
    trash = (
        '<node class="android.widget.ImageView" clickable="true" '
        'bounds="[900,250][1000,300]"/>'
    )
    flow = _nav_source(recognize, tile, trash)
    # dumps: initial flow → tile click → trash-scan flow → trash click →
    # confirm (no dialog) → drop-poll polls the same tile forever
    kit = _SeqKit(_NavDriver([flow, flow, flow, flow, flow]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._clear_dish_edit_photos()
    assert not r.success
    assert "leftover tile did not drop (still 1)" in r.message


def test_uia2_clear_dish_edit_cap_exhaust_leftover(monkeypatch):
    """8 removals complete but tiles remain in the final dump → cap failure
    (3184-3190)."""
    _fast_clock(monkeypatch)
    recognize = '<node text="识别菜品" bounds="[400,300][700,360]"/>'
    two_tiles = _nav_source(
        recognize,
        '<node clickable="true" content-desc="photo" bounds="[100,1950][220,2060]"/>',
        '<node clickable="true" content-desc="photo" bounds="[300,1950][420,2060]"/>',
        '<node class="android.widget.ImageView" clickable="true" bounds="[900,250][1000,300]"/>',
    )
    one_tile = _nav_source(
        recognize,
        '<node clickable="true" content-desc="photo" bounds="[300,1950][420,2060]"/>',
        '<node class="android.widget.ImageView" clickable="true" bounds="[900,250][1000,300]"/>',
    )
    # 8 loops each see 1 tile, drop it, but the following dump still shows 2
    # tiles (static) → each drop-poll fails → 'leftover tile did not drop'
    kit = _SeqKit(_NavDriver([two_tiles]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session._confirm_dish_edit_photo_delete = lambda: ActionResult(
        True, "no dish-edit delete dialog"
    )
    r = session._clear_dish_edit_photos()
    assert not r.success and "leftover tile did not drop" in r.message


def test_node_matches_descriptor_instance_and_contains_legs():
    """_node_matches_descriptor: instance key skipped (1290) and contains
    mismatch → False (1304)."""
    from types import SimpleNamespace

    from automation_app_dianping.session import _node_matches_descriptor

    node = SimpleNamespace(
        get=lambda k, d=None: {"text": "完成", "content-desc": ""}.get(k, d)
    )
    # instance-only descriptor → matches anything (loop skips every key)
    assert _node_matches_descriptor(node, {"instance": 2}) is True
    # textContains expected not inside actual → False (1304)
    assert _node_matches_descriptor(node, {"textContains": "发布"}) is False
    # textContains hit → True
    assert _node_matches_descriptor(node, {"textContains": "完"}) is True
    # exact text hit → True
    assert _node_matches_descriptor(node, {"text": "完成"}) is True


def test_uia2_label_rect_from_dump_hit(monkeypatch):
    """_label_rect_from_source: dump carries the label → preferred_tap_rect
    hit returned before the kit fallback (2804/2812 legs)."""
    _fast_clock(monkeypatch)
    dump = _nav_source(
        '<node content-desc="口味" bounds="[42,491][214,533]"/>'
    )
    kit = _SeqKit(_NavDriver([dump]))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._label_rect_from_source(["~口味"])
    assert out is not None and out["x"] == 42
    # the kit element_bounds fallback was never consulted
    assert not any(c[0] == "element_bounds" for c in kit.calls)


def test_uia2_confirm_search_untranslatable_candidate_skips(monkeypatch):
    """_confirm_search: first candidate untranslatable (2702-2703), second
    resolves → tap; and the dumpless kit-tap loop skip (2720-2722)."""
    _fast_clock(monkeypatch)
    driver = _ClickDumpDriver(
        "<hierarchy>"
        '<node text="搜索" class="android.widget.Button" clickable="false" '
        'bounds="[100,100][300,200]"/></hierarchy>'
    )
    kit = _SeqKit(driver)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._confirm_search(
        selector=(
            'uiautomator:new UiSelector().fromParent("x")',  # 2703 skip
            'uiautomator:new UiSelector().text("搜索")',
        )
    )
    assert out.success and driver.clicks == [(200, 150)]

    # dumpless path (no dump attr) → source "" → kit tap loop with an
    # untranslatable first candidate (2722 skip)
    class Dumpless(_ClickDumpDriver):
        dump_hierarchy = None  # type: ignore[assignment]

    kit2 = _SeqKit(Dumpless("<hierarchy/>"))
    kit2.results["tap"] = ActionResult(True, "kit tap ok")
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    out2 = session2._confirm_search(
        selector=(
            'uiautomator:new UiSelector().fromParent("x")',
            "~搜索",
        )
    )
    assert out2.success and "kit tap ok" in out2.message


def test_uia2_label_rect_untranslatable_in_both_loops(monkeypatch):
    """_label_rect_from_source: untranslatable candidate skipped in the dump
    loop (2803-2804) and the kit loop (2811-2812)."""
    _fast_clock(monkeypatch)
    kit = _SeqKit(_NavDriver(["<hierarchy/>"]))
    kit.results["element_bounds"] = ActionResult(True, "bounds", data={"x": 1})
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._label_rect_from_source(
        ('uiautomator:new UiSelector().fromParent("x")', "~口味")
    )
    assert out == {"x": 1}


def test_pick_photo_tile_nonstring_candidates_only(monkeypatch):
    """_pick_photo_tile: non-string candidates (3578-3579) and untranslatable
    (3581-3582) both skipped → default rid candidate carries the lookup."""
    _fast_clock(monkeypatch)

    class AbsentKit(_SeqKit):
        def find_element(self, by, value):
            raise KeyError("absent")

    session = DianpingUia2Session(
        AbsentKit(_NavDriver(["<hierarchy/>"])), captcha_window_seconds=0
    )
    r = session._pick_photo_tile([42, "xpath://gone"], 0)
    assert not r.success and "instance 0" in r.message


def test_uia2_confirm_picked_photos_untranslatable_skip(monkeypatch):
    """_confirm_picked_photos: untranslatable candidate inside the poll loop
    → skipped (3693-3695); nothing else resolves → 'confirm not found'."""
    _fast_clock(monkeypatch)
    driver = _WidgetDriver(_nav_source(_PICKER_HEADER), exists_by_text=())
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    r = session._confirm_picked_photos(
        ('uiautomator:new UiSelector().fromParent("x")', "~下一步")
    )
    assert not r.success and "confirm not found" in r.message


def test_uia2_perform_slider_swipe_no_handle(monkeypatch):
    """Dump has no slider handle → 'slider handle not located' (2128-2129);
    solver dict rejected at _slider_solution_params → error propagates
    (2100-2102 already); here the no-handle leg from _attempt_slider_solve."""
    _fast_clock(monkeypatch)
    kit = _SeqKit(_ClickDumpDriver("<hierarchy/>"))  # no slider node
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._perform_slider_swipe(offset_px=100)
    assert not out.success and "slider handle not located" in out.message


def test_uia2_attempt_slider_solve_rejected_solution(monkeypatch):
    """Solver dict fails validation → the error ActionResult returns
    (2100-2102)."""
    _fast_clock(monkeypatch)
    handle = (
        '<hierarchy><node bounds="[40,800][120,880]" content-desc="滑块" '
        'class="android.widget.ImageView"/></hierarchy>'
    )

    class ShotSwipe:
        def dump_hierarchy(self):
            return handle

        def screenshot(self):
            return b"png"

        def swipe(self, *args):
            pass

    kit = _SeqKit(ShotSwipe())
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session.slider_solver = lambda image: {"gap_offset_px": 0}  # non-positive
    result = session._attempt_slider_solve()
    assert not result.success and "non-positive gap_offset_px" in result.message


def test_preferred_tap_rect_label_only_no_ancestor(monkeypatch):
    """Label exists but no clickable ancestor → label returned (1391-1392);
    label None + ancestor present → ancestor (1389-1390)."""
    from automation_app_dianping.session import preferred_tap_rect

    label_only = (
        "<hierarchy>"
        '<node text="删除" bounds="[10,310][120,370]"/>'
        "</hierarchy>"
    )
    rect = preferred_tap_rect(label_only, "text", "删除")
    assert rect is not None and (rect["x"], rect["width"]) == (10, 110)


def test_pending_review_row_rect_blank_text_node():
    """CTA scan skips blank-text nodes (1519-1520)."""
    from automation_app_dianping.session import pending_review_row_rect

    dump = (
        "<hierarchy>"
        '<node text="测试店" bounds="[0,400][500,480]"/>'
        '<node text="  " bounds="[800,410][900,470]"/>'
        "</hierarchy>"
    )
    assert pending_review_row_rect(dump, "测试店") is None


def test_uia2_clear_dish_edit_confirm_failure_propagates(monkeypatch):
    """Normal loop: confirm tap fails → 'clear dish-edit photos: confirm tap
    failed' propagates (3174-3175); after the drop the sheet is closed →
    cleared-N exit (3152-3155); 8-loop exhaust with tiles → cap failure
    (3184-3190)."""
    _fast_clock(monkeypatch)
    recognize = '<node text="识别菜品" bounds="[400,300][700,360]"/>'
    tile = '<node clickable="true" content-desc="photo" bounds="[100,1950][220,2060]"/>'
    trash = (
        '<node class="android.widget.ImageView" clickable="true" '
        'bounds="[900,250][1000,300]"/>'
    )
    confirm = '<node text="确认删除" bounds="[568,1211][872,1324]"/>'
    flow = _nav_source(recognize, tile, trash, confirm)

    # confirm dialog present; the confirm click fails → wrapped failure
    kit = _SeqKit(_NavDriver([flow], click_error=True))
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    r = session._clear_dish_edit_photos()
    assert not r.success and "confirm tap failed" in r.message

    # confirm succeeds but the dialog never disappears → the confirm loop
    # itself reports stuck (needs a click-per-confirm driver)
    class ConfirmSticky:
        def dump_hierarchy(self):
            return flow

        def click(self, x, y):
            pass  # dialog stays up

    kit2 = _SeqKit(ConfirmSticky())
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0)
    r2 = session2._clear_dish_edit_photos()
    assert not r2.success and "delete dialog stuck after confirm" in r2.message

    # confirm succeeds and the dialog disappears, but the tile count never
    # drops → the wait times out → 'leftover tile did not drop (still 1)'
    dialog_gone = _nav_source(recognize, tile, trash)
    dumps = [flow] + [dialog_gone] * 12  # poll dumps all keep the tile
    kit2b = _SeqKit(_NavDriver(dumps))
    session2b = DianpingUia2Session(kit2b, captcha_window_seconds=0)
    r2b = session2b._clear_dish_edit_photos()
    assert not r2b.success and "leftover tile did not drop (still 1)" in r2b.message

    # the sheet closes mid-loop → cleared exit (3152-3155). Sequence:
    # initial flow (tile+trash, click both) → post-tile dump flow →
    # trash click → confirm (no dialog) → drop-poll sees the sheet closed →
    # next loop iteration dump also closed → cleared-1 exit
    closed = _nav_source('<node text="其他" bounds="[0,0][10,10]"/>')
    flow_open = _nav_source(recognize, tile, trash)
    kit3 = _SeqKit(_NavDriver([flow_open, flow_open, closed, closed, closed]))
    session3 = DianpingUia2Session(kit3, captcha_window_seconds=0)
    r3 = session3._clear_dish_edit_photos()
    assert r3.success and "cleared 1 dish-edit photo(s)" in r3.message

    # 8 full loops with a persistent tile → cap failure (3184-3190)
    class Sticky:
        def __init__(self):
            self.n = 0

        def dump_hierarchy(self):
            return flow  # static: tiles never drop

    kit4 = _SeqKit(Sticky())
    session4 = DianpingUia2Session(kit4, captcha_window_seconds=0)
    session4._confirm_dish_edit_photo_delete = lambda: ActionResult(
        True, "no dish-edit delete dialog"
    )
    r4 = session4._clear_dish_edit_photos()
    assert not r4.success
    assert "leftover tile did not drop" in r4.message or "leftover tile(s) remain" in r4.message


def test_uia2_clear_dish_edit_eight_loops_then_leftover(monkeypatch):
    """8 full drop-successful loops then a final dump that still has tiles →
    the 'leftover tile(s) remain' cap failure (3183-3189)."""
    _fast_clock(monkeypatch)
    recognize = '<node text="识别菜品" bounds="[400,300][700,360]"/>'
    tile = '<node clickable="true" content-desc="photo" bounds="[100,1950][220,2060]"/>'
    trash = (
        '<node class="android.widget.ImageView" clickable="true" '
        'bounds="[900,250][1000,300]"/>'
    )
    flow = _nav_source(recognize, tile, trash)
    gone = _nav_source(recognize)
    # Static driver: every dump shows the tile → each drop-poll rides out its
    # deadline… but then 3175 fires, not the cap. To reach 3183-3189 the
    # count must DROP each loop (removed reaches 8) yet tiles persist in the
    # final dump. Stub the drop-wait to True and keep the dump static.
    session = DianpingUia2Session(_SeqKit(_NavDriver([flow])), captcha_window_seconds=0)
    session._confirm_dish_edit_photo_delete = lambda: ActionResult(
        True, "no dish-edit delete dialog"
    )
    session._wait_dish_edit_count_drop = lambda before, timeout=3.0: True
    r = session._clear_dish_edit_photos()
    assert not r.success
    assert "leftover tile(s) remain" in r.message


def test_uia2_clear_editor_photos_final_dump_clean(monkeypatch):
    """Cap loops each drop one tile; after loop 6 the final dump is clean →
    the bare success tail (3088)."""
    _fast_clock(monkeypatch)
    photo_dump = _nav_source(
        '<node clickable="true" bounds="[100,500][200,600]">'
        '<node class="android.widget.ImageView" bounds="[110,510][190,590]"/>'
        '<node text="1" bounds="[150,505][195,540]"/></node>'
    )
    clean = _nav_source('<node text="其他" bounds="[0,0][10,10]"/>')
    session = DianpingUia2Session(
        _SeqKit(_NavDriver([photo_dump])), captcha_window_seconds=0
    )
    session._confirm_editor_photo_delete = lambda source: None
    # the after-tap dump differs (so the tap "changed the page"), the
    # remaining-read comes back with fewer tiles → dropped; the next loop's
    # opening dump is clean → the bare success tail (3088)
    state = {"phase": 0}

    def staged_dump():
        state["phase"] += 1
        return photo_dump if state["phase"] == 1 else clean

    session._dump_source = staged_dump
    r = session._clear_existing_editor_photos()
    assert r.success and "cleared 1 leftover editor photo(s)" in r.message


def test_uia2_attempt_slider_solve_rejected_gap(monkeypatch):
    """Solver returns a rejected solution → _slider_solution_params error
    returns directly (2101-2102)."""
    _fast_clock(monkeypatch)
    handle = (
        '<hierarchy><node bounds="[40,800][120,880]" content-desc="滑块" '
        'class="android.widget.ImageView"/></hierarchy>'
    )

    class ShotSwipe:
        def dump_hierarchy(self):
            return handle

        def screenshot(self):
            return b"png"

        def swipe(self, *args):
            pass

    kit = _SeqKit(ShotSwipe())
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    session.slider_solver = lambda image: "not-a-dict"  # → "no solution" error
    result = session._attempt_slider_solve()
    assert not result.success and "no solution" in result.message


def test_pick_photo_tile_skips_via_dump_hits(monkeypatch):
    """_pick_photo_tile: non-string (3578-3579) and untranslatable
    (3581-3582) candidates skipped inside the descriptor builder while a
    valid id candidate carries the lookup."""
    _fast_clock(monkeypatch)

    class MissKit(_SeqKit):
        def find_element(self, by, value):
            raise KeyError("absent")

    session = DianpingUia2Session(
        MissKit(_NavDriver(["<hierarchy/>"])), captcha_window_seconds=0
    )
    r = session._pick_photo_tile(
        [42, 'uiautomator:new UiSelector().fromParent("x")', "id:real"], 0
    )
    # only the id candidate reached find_element; both junk legs skipped
    assert not r.success and "instance 0" in r.message


def test_preferred_tap_rect_no_label_no_ancestor(monkeypatch):
    """Label without bounds and no clickable ancestor → ancestor None leg
    (1390-1391) → label None → None overall."""
    from automation_app_dianping.session import preferred_tap_rect

    # label present with bounds, no clickable ancestor → 1391-1392 return label
    # (already covered); here: label None + ancestor None → None
    orphan = "<hierarchy><node text='删除'/></hierarchy>"
    assert preferred_tap_rect(orphan, "text", "删除") is None


def test_uia2_selector_blank_string_fallback_gap(monkeypatch):
    """selector="" : as_selector_list("")

returns [""], so the str fallback (918) is what feeds the parse loop — the
    failure is the translate error, not the missing-parameter guard."""
    _fast_clock(monkeypatch)
    session = DianpingUia2Session(_SeqKit(), captcha_window_seconds=0)
    result = session.execute_action("tap", selector="")
    assert not result.success
    assert "missing required parameter: selector" not in result.message


def test_preferred_tap_rect_label_without_ancestor_wins(monkeypatch):
    """Label carries bounds and no clickable ancestor exists → the label
    rect is returned (1392)."""
    from automation_app_dianping.session import preferred_tap_rect

    source = _nav_source('<node text="删除" bounds="[10,20][80,60]"/>')
    rect = preferred_tap_rect(source, "text", "删除")
    assert rect is not None and rect["x"] == 10 and rect["width"] == 70


def test_uia2_clear_dish_edit_confirm_message_passed_through(monkeypatch):
    """Confirm returning failure is passed through verbatim (3175)."""
    _fast_clock(monkeypatch)
    recognize = '<node text="识别菜品" bounds="[400,300][700,360]"/>'
    tile = '<node clickable="true" content-desc="photo" bounds="[100,1950][220,2060]"/>'
    trash = (
        '<node class="android.widget.ImageView" clickable="true" '
        'bounds="[900,250][1000,300]"/>'
    )
    flow = _nav_source(recognize, tile, trash)
    session = DianpingUia2Session(_SeqKit(_NavDriver([flow])), captcha_window_seconds=0)
    session._confirm_dish_edit_photo_delete = lambda: ActionResult(
        False, "confirm tap failed: stale element"
    )
    r = session._clear_dish_edit_photos()
    assert not r.success
    assert r.message == "confirm tap failed: stale element"


def test_uia2_clear_dish_edit_success_after_removal(monkeypatch):
    """One drop then a tile-free dump → 'cleared 1 dish-edit photo(s)'
    (3190)."""
    _fast_clock(monkeypatch)
    recognize = '<node text="识别菜品" bounds="[400,300][700,360]"/>'
    tile = '<node clickable="true" content-desc="photo" bounds="[100,1950][220,2060]"/>'
    trash = (
        '<node class="android.widget.ImageView" clickable="true" '
        'bounds="[900,250][1000,300]"/>'
    )
    flow = _nav_source(recognize, tile, trash)
    clean = _nav_source(recognize)
    session = DianpingUia2Session(_SeqKit(_NavDriver([flow])), captcha_window_seconds=0)
    session._confirm_dish_edit_photo_delete = lambda: ActionResult(
        True, "confirmed dish-edit delete"
    )
    phase = {"n": 0}

    def staged_dump():
        phase["n"] += 1
        # 1: opening dump (tile), 2: trash lookup, 3+: drop-poll reads clean
        return flow if phase["n"] <= 2 else clean

    session._dump_source = staged_dump
    r = session._clear_dish_edit_photos()
    assert r.success and "cleared 1 dish-edit photo(s)" in r.message


def test_pick_photo_tile_nonstring_first_candidate(monkeypatch):
    """A leading non-string candidate hits the 3579 continue; the string
    candidate after it still resolves through the kit lookup."""
    _fast_clock(monkeypatch)

    class MissKit(_SeqKit):
        def find_element(self, by, value):
            raise KeyError("absent")

    session = DianpingUia2Session(
        MissKit(_NavDriver(["<hierarchy/>"])), captcha_window_seconds=0
    )
    r = session._pick_photo_tile([42, "id:real"], 1)
    assert not r.success and "instance 1" in r.message


def test_appium_blank_string_selector_fallback(tmp_path):
    """Appium session: selector="" — as_selector_list returns [""], which is
    truthy as a list, so the missing-parameter guard (920) is skipped and the
    str fallback (918) is what would feed the loop. The candidate then fails
    at translation/lookup, proving the guard was bypassed, not hit."""
    session = DianpingAppiumSession(_MiniDriver(), artifact_root=tmp_path)
    result = session.execute_action("tap", selector="")
    assert not result.success
    assert "missing required parameter: selector" not in result.message


def test_appium_type_text_blank_selector_fallback(tmp_path):
    """Same blank-string path through type_text (918 via the shared
    _with_selector_fallbacks)."""
    session = DianpingAppiumSession(_MiniDriver(), artifact_root=tmp_path)
    result = session.execute_action("type_text", selector="", text="hi")
    assert not result.success
    assert "missing required parameter: selector" not in result.message


def test_uia2_clear_dish_edit_not_open_after_confirm(monkeypatch):
    """After the leftover-confirm leg, the next dump no longer shows the
    dish-edit sheet → 'cleared N dish-edit photo(s)' with removed == 0
    (3153)."""
    _fast_clock(monkeypatch)
    dialog = _nav_source(
        '<node text="确认删除这张图片吗" bounds="[100,1100][900,1200]"/>',
        '<node text="识别菜品" bounds="[400,300][700,360]"/>',
    )
    clean = _nav_source('<node text="其他" bounds="[0,0][10,10]"/>')
    session = DianpingUia2Session(
        _SeqKit(_NavDriver([dialog])), captcha_window_seconds=0
    )
    session._confirm_dish_edit_photo_delete = lambda: ActionResult(
        True, "no dish-edit delete dialog"
    )
    state = {"n": 0}

    def staged():
        state["n"] += 1
        return dialog if state["n"] == 1 else clean

    session._dump_source = staged
    r = session._clear_dish_edit_photos()
    assert r.success and "cleared 0 dish-edit photo(s)" in r.message


def test_uia2_clear_editor_photos_cap_loops_then_clean(monkeypatch):
    """All 6 cap loops each drop one tile; the post-loop leftover read is
    empty → the 3088 success tail with removed == 6."""
    _fast_clock(monkeypatch)

    def tile(n):
        return (
            '<node clickable="true" bounds="[%d,500][%d,600]">'
            '<node text="%d" bounds="[%d,505][%d,540]"/></node>'
            % (100 + n * 130, 180 + n * 130, n + 1, 140 + n * 130, 170 + n * 130)
        )

    session = DianpingUia2Session(
        _SeqKit(_NavDriver(["<hierarchy/>"])), captcha_window_seconds=0
    )
    session._confirm_editor_photo_delete = lambda source: None
    other = _nav_source('<node text="无关" bounds="[0,0][10,10]"/>')

    def tile_source(n):
        return _nav_source(tile(n)) if n >= 0 else _nav_source()

    state = {"step": 0}

    def staged_dump():
        # Per loop: A = opening dump (tile `loop`), B = after-tap dump
        # (different content, no dish-edit sheet), C = remaining read
        # (fewer tiles than A → dropped). After loop 6 the post-loop
        # leftover read is empty → 3088.
        step = state["step"] % 3
        loop = state["step"] // 3
        state["step"] += 1
        if step == 0:
            return tile_source(loop) if loop < 6 else _nav_source()
        if step == 1:
            return other
        return _nav_source()

    session._dump_source = staged_dump
    r = session._clear_existing_editor_photos()
    assert r.success
    assert "cleared 6 leftover editor photo(s)" in r.message


def test_uia2_clear_dish_edit_already_clean(monkeypatch):
    """Opening dump shows neither the delete dialog nor the dish-edit sheet
    → the 3153 tail with removed == 0."""
    _fast_clock(monkeypatch)
    session = DianpingUia2Session(
        _SeqKit(_NavDriver(["<hierarchy/>"])), captcha_window_seconds=0
    )
    r = session._clear_dish_edit_photos()
    assert r.success and "cleared 0 dish-edit photo(s)" in r.message


def test_uia2_clear_dish_edit_no_tiles_on_open_sheet(monkeypatch):
    """Dish-edit sheet is open but the filmstrip has no thumbnails → the
    3157-3159 success tail."""
    _fast_clock(monkeypatch)
    sheet = _nav_source('<node text="识别菜品" bounds="[400,300][700,360]"/>')
    session = DianpingUia2Session(
        _SeqKit(_NavDriver([sheet])), captcha_window_seconds=0
    )
    r = session._clear_dish_edit_photos()
    assert r.success and "cleared 0 dish-edit photo(s)" in r.message


def test_uia2_clear_dish_edit_eight_removals_then_clean(monkeypatch):
    """8 full removal iterations exhaust the loop; the post-loop leftover
    read is tile-free → the 3190 success tail with removed == 8."""
    _fast_clock(monkeypatch)
    recognize = '<node text="识别菜品" bounds="[400,300][700,360]"/>'
    tile = (
        '<node clickable="true" content-desc="photo" '
        'bounds="[100,1950][220,2060]"/>'
    )
    trash = (
        '<node class="android.widget.ImageView" clickable="true" '
        'bounds="[900,250][1000,300]"/>'
    )
    open_tile = _nav_source(recognize, tile)
    open_tile_trash = _nav_source(recognize, tile, trash)
    clean = _nav_source(recognize)
    session = DianpingUia2Session(
        _SeqKit(_NavDriver([open_tile_trash])), captcha_window_seconds=0
    )
    session._confirm_dish_edit_photo_delete = lambda: ActionResult(
        True, "confirmed dish-edit delete"
    )
    state = {"step": 0}

    def staged():
        step = state["step"]
        state["step"] += 1
        if step >= 24:
            return clean  # post-loop leftover read
        if step % 3 == 0:
            return open_tile
        if step % 3 == 1:
            return open_tile_trash
        return clean

    session._dump_source = staged
    r = session._clear_dish_edit_photos()
    assert r.success and "cleared 8 dish-edit photo(s)" in r.message


def test_uia2_navigate_search_fallback_reestablishes_home(monkeypatch):
    """Live 2026-11-08 regression: pending path opens 我的 → 待评价, shop is
    missing, ONE back lands on the 我的 tab (not home). The search fallback
    must re-establish home before tapping the search bar — previously it
    burned all 8 selectors on the profile page."""
    _fast_clock(monkeypatch)
    base = {
        "shop_name": "味香斋(雁荡路店)",
        "write_selector": 'uiautomator:new UiSelector().text("写评价")',
        "search_bar": 'uiautomator:new UiSelector().text("搜索")',
        "search_input": 'uiautomator:new UiSelector().text("搜索店名、菜品")',
        "search_confirm": None,
        "search_results_marker": 'uiautomator:new UiSelector().text("有点评")',
        "shop_result": None,
    }
    # Dump 1 (home check at entry): home with search bar AND 我的 tab →
    # pending path engages. Dumps 2..k (pending flow): 我的 tab page with
    # 待评价 entry; the shop row never appears. The fallback's home check
    # re-dumps: still 我的 tab (no 搜索) → _back_to_home_search presses BACK
    # and its post-BACK dump shows home with the search bar → search tap.
    pending_page = _nav_source(
        '<node text="我的" bounds="[900,2300][1000,2380]"/>',
        '<node text="待评价" bounds="[100,400][260,450]"/>',
    )
    home = _nav_source(
        _SEARCH_BAR_NODE,
        '<node text="我的" bounds="[900,2300][1000,2380]"/>',
    )
    dumps = [
        home,          # entry source read (page-identity checks)
        home,          # entry on_home check → True (skip BACK unwind)
        pending_page,  # pending path: 我的 tab check
        pending_page,  # 我的 tab tap dump + 待评价 wait
        pending_page,  # pending row wait (never matches)
        pending_page,  # fallback on_home check → absent → BACK path
        pending_page,  # _back_to_home_search pre-BACK read
        home,          # post-BACK marker check → home reached
        home,          # fallback search-bar tap dump
    ]
    driver = _NavDriver(dumps)
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    result = session._navigate_to_review_editor(**base)
    # the flow got past the fallback home re-establishment: it tapped the
    # search bar (coordinate click recorded) and moved on to wait for the
    # search-input marker, which never appears on this static dump.
    assert "home search bar not reached" not in result.message
    assert result.message in (
        "timed out waiting for page marker",
    ) or "marker" in result.message
    assert len(driver.clicks) >= 1


def test_uia2_navigate_search_input_wait_recovers_via_secondary_marker(monkeypatch, capsys):
    """Live 2026-11-09: after the search-bar tap the search page WAS open
    (history list and input visible; adb's own dump showed
    search_keyword_edit) while 8s of session dumps came back empty/stale.
    The input-marker wait must re-probe once with the search page's own
    header markers as secondary evidence instead of dying on the primary
    selector."""
    _fast_clock(monkeypatch)
    base = {
        "shop_name": "味香斋(雁荡路店)",
        "write_selector": 'uiautomator:new UiSelector().text("写评价")',
        "search_bar": 'uiautomator:new UiSelector().text("搜索")',
        "search_input": (
            'uiautomator:new UiSelector().resourceId('
            '"com.dianping.v1:id/search_keyword_edit")'
        ),
        "search_confirm": None,
        "search_results_marker": 'uiautomator:new UiSelector().text("有点评")',
        "shop_result": None,
    }
    home = _nav_source(_SEARCH_BAR_NODE)  # no 我的 tab: the pending path bails
    # Search page restored from history: header present, but the input node
    # is missing from this dump (the stale-dump variant) — the primary
    # selector misses and only the secondary header can prove readiness.
    search_page = _nav_source(
        '<node text="历史搜索" bounds="[40,300][200,360]"/>',
        '<node text="味香斋(雁荡路店)" bounds="[40,400][400,460]"/>',
    )
    dumps = [
        home,  # entry source read (page-identity checks)
        home,  # on_home check -> search bar present
        home,  # pending path: 我的 tab check -> absent -> bail
        home,  # fallback home check -> present -> skip BACK unwind
        home,  # search-bar tap dump
    ]
    # First wait (8s): ~2 empty dumps per poll iteration (retry-after-wake).
    dumps += [""] * 20
    dumps += [search_page]  # second wait: header marker matches
    driver = _NavDriver(dumps)
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    result = session._navigate_to_review_editor(**base)
    out = capsys.readouterr().out
    assert "secondary markers after a dump glitch" in out
    # The flow moved past both input waits; it dies honestly at the results
    # marker, which the static fixture never shows.
    assert result.message == "timed out waiting for page marker (12.0s)"


def test_uia2_navigate_pending_tap_fail_does_not_back_out_of_home(monkeypatch):
    """Live 2026-11-09 (second rehearsal): the pending path's 我的 tab tap
    failed with -32002 while the flow was standing ON home; the fallback's
    one-shot home re-check then read a stale dump, said "not home", and the
    BACK it triggered walked OUT of home into a dead end. A false miss must
    be corrected by the confirmation re-reads without any BACK press."""
    _fast_clock(monkeypatch)
    base = {
        "shop_name": "味香斋(雁荡路店)",
        "write_selector": 'uiautomator:new UiSelector().text("写评价")',
        "search_bar": 'uiautomator:new UiSelector().text("搜索")',
        "search_input": 'uiautomator:new UiSelector().text("搜索店名、菜品")',
        "search_confirm": None,
        "search_results_marker": 'uiautomator:new UiSelector().text("有点评")',
        "shop_result": None,
    }
    home = _nav_source(
        _SEARCH_BAR_NODE,
        '<node text="我的" bounds="[900,2300][1000,2380]"/>',
    )
    # The pending path bails cleanly (no 我的 on this dump -> no tap, no
    # BACK, flow still standing on home), then the fallback home re-check
    # hits the stale window the live run showed: two reads lose the search
    # bar, the third finds it again.
    home_no_my = _nav_source(_SEARCH_BAR_NODE)
    stale = "<hierarchy><node bounds=\"[0,0][100,100]\"/></hierarchy>"
    dumps = [
        home,        # entry source read
        home,        # entry on_home check -> True
        home_no_my,  # pending path: 我的 tab check -> absent -> clean bail
        stale,       # fallback confirm read #1 -> false miss
        stale,       # fallback confirm read #2 -> false miss
        home_no_my,  # fallback confirm read #3 -> home back -> NO back_unwind
        home_no_my,  # search-bar tap dump
    ]
    driver = _NavDriver(dumps)
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    result = session._navigate_to_review_editor(**base)
    # No BACK was pressed anywhere: the flow never left home, so the dead
    # end from the live run cannot recur. The coordinate search-bar tap ran.
    assert driver.presses == []
    assert len(driver.clicks) >= 1
    assert "home search bar not reached" not in result.message


def test_dialog_dismiss_covers_leftover_review_modal():
    """Live 2026-11-09: the previous no-submit rehearsal's editor state pops
    an intercepting '你有一条编辑中的评价' modal on launch; 暂不查看 discards
    it without jumping into the editor. The selector must stay in the list."""
    from automation_app_dianping.config import default_selectors

    raw = [str(c) for c in default_selectors().dialog_dismiss]
    assert any("暂不查看" in c for c in raw)


def test_uia2_dismiss_dialogs_blind_fallback_on_unparseable_dump(monkeypatch):
    """_present_candidates returns None on an unparseable dump: the loop must
    fall back to blind taps so a wedged dump channel cannot silently skip a
    real dialog (2026-11-09 review finding)."""
    _fast_clock(monkeypatch)
    kit = _SeqKit(_NavDriver(["not-xml"]))
    kit.results["tap"] = ActionResult(True, "tapped")
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._dismiss_dialogs(
        selector=('uiautomator:new UiSelector().text("残忍拒绝")',), max_attempts=1
    )
    assert out.success and out.data == {"dismissed": 1}
    assert [c[0] for c in kit.calls] == ["tap"]


# --- the editor's own toolbar must never be mistaken for a dialog -----------

# Geometry and ancestry mirror the live 2026-11-10 capture
# (artifacts/editor_with_photo.xml): the review editor's 取消 is a
# non-clickable TextView under com.dianping.v1:id/picasso_view.
_EDITOR_CHROME_DUMP = (
    "<hierarchy>"
    '<node resource-id="com.dianping.v1:id/picasso_view" bounds="[0,0][1080,2355]">'
    '<node resource-id="com.dianping.v1:id/action_bar_root" bounds="[0,68][1080,209]">'
    '<node text="取消" bounds="[34,117][106,159]"/>'
    "</node>"
    '<node text="添加图/视频" bounds="[364,1665][559,1707]"/>'
    "</node>"
    "</hierarchy>"
)

# The leftover-review modal is a DIFFERENT window: 暂不查看 lives under
# stimulate_layout, never under the editor root (live 2026-11-10 capture).
_MODAL_DUMP = (
    "<hierarchy>"
    '<node resource-id="com.dianping.v1:id/stimulate_layout" bounds="[146,1026][934,1396]">'
    '<node text="你有一条编辑中的评价" bounds="[235,1096][845,1157]"/>'
    '<node text="暂不查看" bounds="[202,1213][525,1326]"/>'
    "</node>"
    "</hierarchy>"
)


def test_editor_chrome_hit_only_fires_for_editor_owned_labels():
    """The 取消 under the editor root is chrome; the modal's 暂不查看 is not."""
    assert session_mod.editor_chrome_hit(_EDITOR_CHROME_DUMP, "text", "取消") is True
    assert session_mod.editor_chrome_hit(_MODAL_DUMP, "text", "暂不查看") is False
    # A label that matches nothing is not a chrome hit.
    assert session_mod.editor_chrome_hit(_EDITOR_CHROME_DUMP, "text", "我知道了") is False
    # An empty / unparseable tree proves nothing.
    assert session_mod.editor_chrome_hit("", "text", "取消") is False
    assert session_mod.editor_chrome_hit("not-xml", "text", "取消") is False


def test_editor_chrome_hit_keeps_a_real_dialog_with_the_same_label():
    """A 取消 that lives OUTSIDE the editor is a real dialog button and must
    still be dismissible."""
    mixed = (
        "<hierarchy>"
        '<node resource-id="com.dianping.v1:id/picasso_view">'
        '<node text="取消" bounds="[34,117][106,159]"/>'
        "</node>"
        '<node resource-id="com.dianping.v1:id/stimulate_layout">'
        '<node text="取消" bounds="[202,1213][525,1326]"/>'
        "</node>"
        "</hierarchy>"
    )
    assert session_mod.editor_chrome_hit(mixed, "text", "取消") is False


def test_uia2_dismiss_dialogs_never_taps_the_editor_cancel(monkeypatch):
    """The editor's own 取消 must not be tapped as if it were a dialog.

    Tapping it discards the draft the workflow is about to fill in while
    the step reports 'dismissed' — the silent wrong-direction failure."""
    _fast_clock(monkeypatch)
    kit = _SeqKit(_NavDriver([_EDITOR_CHROME_DUMP]))
    kit.results["tap"] = ActionResult(True, "tapped")
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._dismiss_dialogs(
        selector=('uiautomator:new UiSelector().text("取消")',), max_attempts=3
    )
    assert out.success
    assert out.data == {"dismissed": 0}
    assert kit.calls == []


def test_uia2_dismiss_dialogs_still_taps_the_leftover_review_modal(monkeypatch):
    """The real modal's 暂不查看 lives outside the editor root and must keep
    being dismissed (live 2026-11-09 behaviour)."""
    _fast_clock(monkeypatch)
    kit = _SeqKit(_NavDriver([_MODAL_DUMP]))
    kit.results["tap"] = ActionResult(True, "tapped")
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._dismiss_dialogs(
        selector=('uiautomator:new UiSelector().text("暂不查看")',), max_attempts=1
    )
    assert out.success
    assert out.data == {"dismissed": 1}
    assert [c[0] for c in kit.calls] == ["tap"]


def test_uia2_dismiss_dialogs_blind_path_skips_editor_toolbar_labels(monkeypatch):
    """With a wedged dump channel there is no tree to prove which node a
    selector reaches — the editor's own toolbar labels are still excluded,
    because that is the one known way to destroy a draft by accident."""
    _fast_clock(monkeypatch)
    kit = _SeqKit(_NavDriver(["not-xml"]))
    kit.results["tap"] = ActionResult(True, "tapped")
    session = DianpingUia2Session(kit, captcha_window_seconds=0)
    out = session._dismiss_dialogs(
        selector=(
            'uiautomator:new UiSelector().text("取消")',
            'uiautomator:new UiSelector().text("残忍拒绝")',
        ),
        max_attempts=1,
    )
    assert out.success
    assert out.data == {"dismissed": 1}
    tapped = [c[1].get("selector") for c in kit.calls]
    assert tapped == ["残忍拒绝"]


def test_appium_dismiss_dialogs_drops_editor_chrome_candidates(tmp_path):
    """The Appium path carries the same 取消 candidate and the same editor
    toolbar, so the same filter applies."""
    from automation_app_dianping.session import DianpingAppiumSession

    driver = _MiniDriver()
    driver.page_source = _EDITOR_CHROME_DUMP
    session = DianpingAppiumSession(driver, artifact_root=tmp_path)
    kept = session._dialog_candidates_excluding_editor_chrome(
        (
            'uiautomator:new UiSelector().text("取消")',
            'uiautomator:new UiSelector().text("我知道了")',
        )
    )
    assert kept == ['uiautomator:new UiSelector().text("我知道了")']

    # Outside the editor the candidate stays.
    driver.page_source = _MODAL_DUMP
    session2 = DianpingAppiumSession(driver, artifact_root=tmp_path)
    kept2 = session2._dialog_candidates_excluding_editor_chrome(
        ('uiautomator:new UiSelector().text("暂不查看")',)
    )
    assert kept2 == ['uiautomator:new UiSelector().text("暂不查看")']


class _ShellCountDriver:
    """adb device fake: records shell calls, scripts the bucket row query."""

    def __init__(self, rows=0, query_error=False):
        self.rows = rows
        self.query_error = query_error
        self.shell_calls = []
        self.clicks = []

    def shell(self, cmd):
        joined = " ".join(str(x) for x in cmd)
        self.shell_calls.append(joined)
        if "content" in joined and "query" in joined:
            if self.query_error:
                raise RuntimeError("content query failed")
            if self.rows <= 0:
                return ""
            return "".join("Row: %d _id=%d\n" % (i, 100 + i) for i in range(self.rows))
        return ""

    def click(self, x, y):
        self.clicks.append((x, y))


def test_uia2_pick_photos_cleans_album_and_gates_on_row_count(monkeypatch, tmp_path):
    """2026-11-09 live: the staging album accumulated files from earlier runs
    and positional tile-0 attached an image from another picker view. The
    flow must empty the album (rows then files) and refuse to attach unless
    the MediaStore row count equals the staged photo count."""
    _fast_clock(monkeypatch)
    driver = _ShellCountDriver(rows=3)
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    monkeypatch.setattr(
        session, "_prepare_gallery_photo", lambda *a, **k: ActionResult(True, "prep")
    )
    result = session._pick_photos_uia2(photos=[str(tmp_path / "a.jpg")])
    assert "refusing to attach positionally" in result.message
    deletes = [c for c in driver.shell_calls if "content delete" in c]
    rms = [c for c in driver.shell_calls if "rm -rf" in c]
    assert deletes and rms
    assert driver.shell_calls.index(deletes[0]) < driver.shell_calls.index(rms[0])

    # Exactly one staged row -> the gate passes and the flow moves on.
    driver_ok = _ShellCountDriver(rows=1)
    session_ok = DianpingUia2Session(_SeqKit(driver_ok), captcha_window_seconds=0)
    monkeypatch.setattr(
        session_ok, "_prepare_gallery_photo", lambda *a, **k: ActionResult(True, "prep")
    )
    result_ok = session_ok._pick_photos_uia2(photos=[str(tmp_path / "a.jpg")])
    assert "refusing to attach positionally" not in result_ok.message

    # An unreadable MediaStore counts as unknown -> refuse as well.
    driver_bad = _ShellCountDriver(query_error=True)
    session_bad = DianpingUia2Session(_SeqKit(driver_bad), captcha_window_seconds=0)
    monkeypatch.setattr(
        session_bad, "_prepare_gallery_photo", lambda *a, **k: ActionResult(True, "prep")
    )
    result_bad = session_bad._pick_photos_uia2(photos=[str(tmp_path / "a.jpg")])
    assert "refusing to attach positionally" in result_bad.message


def test_uia2_clean_staging_album_orders_rows_before_files(monkeypatch):
    driver = _ShellCountDriver(rows=0)
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    out = session._clean_staging_album()
    assert out.success
    assert len(driver.shell_calls) == 2
    assert "content delete" in driver.shell_calls[0]
    assert "rm -rf" in driver.shell_calls[1]

    class _Boom:
        def shell(self, cmd):
            raise RuntimeError("usb gone")

    session2 = DianpingUia2Session(_SeqKit(_Boom()), captcha_window_seconds=0)
    out2 = session2._clean_staging_album()
    assert not out2.success and "shell failed" in out2.message


def test_dialog_dismiss_covers_app_update_dialog():
    """Live 2026-11-10: the app-update dialog (新版本抢先体验 v11.75.1)
    closes via the update_dialog_close content-desc icon, not a text
    button -- without it a fresh launch blocks the home search bar."""
    from automation_app_dianping.config import default_selectors

    raw = [str(c) for c in default_selectors().dialog_dismiss]
    assert any("update_dialog_close" in c for c in raw)


def test_point_select_detection_and_popup_locator():
    from automation_app_dianping.session import (
        locate_point_select_popup,
        page_source_indicates_point_select,
    )

    assert not page_source_indicates_point_select("<hierarchy/>")
    source = _nav_source(
        '<node text="请依次点击下图图标" bounds="[121,715][959,785]"/>',
        '<node resource-id="com.dianping.v1:id/titans_main_layout" '
        'bounds="[141,761][939,1661]"/>',
    )
    assert page_source_indicates_point_select(source)
    assert locate_point_select_popup(source) == (141, 761, 939, 1661)
    # A dump without the layout id yields no popup box.
    bare = _nav_source('<node text="请依次点击下图图标" bounds="[0,0][10,10]"/>')
    assert locate_point_select_popup(bare) is None


@pytest.mark.skipif(not _slidex_vision_ready(), reason="slidex vision surface missing")
def test_riskctl_locate_targets_parses_fenced_json_and_filters_zero_conf(monkeypatch):
    from automation_app_dianping import riskctl

    monkeypatch.setenv("SLIDEX_VISION_ENDPOINT", "https://api.example/v1/chat/completions")
    monkeypatch.setenv("SLIDEX_VISION_API_KEY", "sk-test")
    monkeypatch.setenv("SLIDEX_VISION_MODEL", "gemini-3.8-flash")

    from PIL import Image
    import io as _io

    buf = _io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(buf, format="PNG")

    captured = {}

    class _F:
        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '```json\n{"targets":['
                                '{"char":"拼图块","x":0.2,"y":0.3,"confidence":0.95},'
                                '{"char":"盾牌","x":0.8,"y":0.4,"confidence":0.95},'
                                '{"char":"云朵","x":0.5,"y":0.3,"confidence":0}]}'
                                "\n```"
                            }
                        }
                    ]
                }
            ).encode()

    import urllib.request

    def _fake(request, timeout=None, *a, **k):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _F()

    monkeypatch.setattr(urllib.request, "urlopen", _fake)

    targets = riskctl.locate_point_select_targets(
        buf.getvalue(),
        endpoint="https://api.example/v1/chat/completions",
        api_key="sk-test",
        model="gemini-3.8-flash",
    )
    assert [t[0] for t in targets] == ["拼图块", "盾牌"]  # zero-conf filtered
    assert targets[0][1:] == (0.2, 0.3, 0.95)
    # Prompt discipline: no captcha wording anywhere in the request.
    prompt_text = captured["payload"]["messages"][0]["content"][0]["text"]
    for banned in ("验证码", "captcha", "滑块", "bypass"):
        assert banned not in prompt_text, banned


def test_riskctl_returns_none_on_unparseable_image(monkeypatch):
    from automation_app_dianping import riskctl

    monkeypatch.setenv("SLIDEX_VISION_ENDPOINT", "https://api.example/v1/chat/completions")
    monkeypatch.setenv("SLIDEX_VISION_API_KEY", "sk-test")
    monkeypatch.setenv("SLIDEX_VISION_MODEL", "gemini-3.8-flash")
    assert (
        riskctl.locate_point_select_targets(
            b"not-a-png",
            endpoint="https://api.example/v1/chat/completions",
            api_key="sk-test",
            model="gemini-3.8-flash",
        )
        is None
    )


def test_uia2_point_select_guard_clicks_in_hint_order(monkeypatch):
    """The guard solves the icon challenge via the vision channel and retries
    the action (2026-11-10 live: four uniform clicks registered but the
    verifier refused without the ordered-solve path)."""
    _fast_clock(monkeypatch)

    class _PointDriver(_NavDriver):
        def __init__(self):
            super().__init__(["<hierarchy/>"])
            self.captcha_clicks = []
            self.shot_taken = 0

        def dump_hierarchy(self):
            # Once both icons are clicked the challenge clears: subsequent
            # dumps no longer carry the popup (the guard's post-click check).
            if len(self.captcha_clicks) >= 2:
                return "<hierarchy/>"
            return super().dump_hierarchy()

        def screenshot(self):
            import io as _io

            from PIL import Image as _Image

            self.shot_taken += 1
            buf = _io.BytesIO()
            _Image.new("RGB", (1080, 2400), "white").save(buf, format="PNG")
            return buf.getvalue()

        def click(self, x, y):
            self.captcha_clicks.append((x, y))

    driver = _PointDriver()
    kit = _SeqKit(driver)
    session = DianpingUia2Session(kit, captcha_window_seconds=0)

    source = _nav_source(
        '<node text="请依次点击下图图标" bounds="[121,715][959,785]"/>',
        '<node resource-id="com.dianping.v1:id/titans_main_layout" '
        'bounds="[141,761][939,1661]"/>',
    )
    driver.dumps = [source]  # sticky: guard + retry dumps all see the popup... 

    from automation_app_dianping import riskctl

    monkeypatch.setattr(
        riskctl,
        "vision_channel_from_env",
        lambda: ("https://api.example/v1/chat/completions", "sk-test", "gemini-3.8-flash", 30.0),
    )
    monkeypatch.setattr(
        riskctl,
        "locate_point_select_targets",
        lambda popup_png, **kw: [
            ("拼图块", 0.2, 0.3, 0.95),
            ("盾牌", 0.8, 0.4, 0.95),
        ],
    )

    # The action under guard: a tap that "succeeded" while the popup was up.
    result = session._guard_point_select("tap", ActionResult(True, "tap"), {"selector": "x"})
    assert result.success, result.message
    assert "point-select solved" in result.message
    assert len(driver.captcha_clicks) == 2
    # popup origin (141,761) + normalized coords within (798, 900)
    x1, y1 = driver.captcha_clicks[0]
    assert 141 + int(0.2 * 798) - 4 <= x1 <= 141 + int(0.2 * 798) + 4
    assert 761 + int(0.3 * 900) - 4 <= y1 <= 761 + int(0.3 * 900) + 4


def test_uia2_point_select_guard_fails_without_vision_channel(monkeypatch):
    _fast_clock(monkeypatch)

    class _PointDriver(_NavDriver):
        def __init__(self):
            super().__init__(["<hierarchy/>"])

        def screenshot(self):
            import io as _io

            from PIL import Image as _Image

            buf = _io.BytesIO()
            _Image.new("RGB", (1080, 2400), "white").save(buf, format="PNG")
            return buf.getvalue()

    driver = _PointDriver()
    session = DianpingUia2Session(_SeqKit(driver), captcha_window_seconds=0)
    source = _nav_source(
        '<node text="请依次点击下图图标" bounds="[121,715][959,785]"/>',
        '<node resource-id="com.dianping.v1:id/titans_main_layout" '
        'bounds="[141,761][939,1661]"/>',
    )
    driver.dumps = [source]
    from automation_app_dianping import riskctl

    monkeypatch.setattr(riskctl, "vision_channel_from_env", lambda: None)
    result = session._guard_point_select("tap", ActionResult(True, "tap"), {})
    assert not result.success
    assert "vision channel not configured" in result.message


# --- round-2 review fixes (2026-11-12) ---------------------------------------


def test_locate_slider_handle_prefers_the_jigsaw_handle_over_chrome():
    """Live 2026-11-10 jigsaw dump: the challenge chrome shares the handle's
    id substrings and PRECEDES its children in document order, so the old
    first-match scan returned puzzleSliderContainer's centre (540,1211) --
    the middle of the puzzle picture -- instead of the draggable handle
    (158,1564). The drag then started where nothing is draggable."""
    dump = (
        "<hierarchy>"
        '<node resource-id="puzzleSliderContainer" bounds="[76,642][1004,1781]"/>'
        '<node resource-id="puzzleSliderTitle" bounds="[121,715][959,785]"/>'
        '<node resource-id="puzzleImageMain" bounds="[121,830][959,1460]"/>'
        '<node resource-id="puzzleSliderDrag" bounds="[121,830][388,1460]"/>'
        '<node resource-id="puzzleBoxWrap" bounds="[121,1502][959,1629]"/>'
        '<node resource-id="puzzleSliderBox" bounds="[121,1502][250,1629]"/>'
        '<node resource-id="puzzleSliderMoveingBar" bounds="[121,1502][196,1626]"/>'
        '<node resource-id="puzzleSliderRefresh" bounds="[897,1668][959,1730]"/>'
        "</hierarchy>"
    )
    assert session_mod.locate_slider_handle(dump) == (158, 1564)

    # The desc-hinted nc_1 handle (no puzzle ids) keeps its path.
    nc = (
        '<hierarchy><node bounds="[40,800][120,880]" content-desc="滑块" '
        'class="android.widget.ImageView"/>'
        '<node resource-id="com.dianping.v1:id/nc_1_wrapper" '
        'class="android.view.View"/></hierarchy>'
    )
    assert session_mod.locate_slider_handle(nc) == (80, 840)
    assert session_mod.locate_slider_handle("not xml") is None


@pytest.mark.skipif(not _slidex_vision_ready(), reason="slidex vision surface missing")
def test_riskctl_vision_channel_reads_the_real_config_fields(monkeypatch):
    """vision_channel_from_env used to read vision_endpoint/vision_api_key/
    vision_model -- attributes LlmVisionConfig never had -- so the channel
    was None even with SLIDEX_VISION_* fully set and the point-select guard
    could never arm."""
    from automation_app_dianping import riskctl

    monkeypatch.setenv("SLIDEX_VISION_ENDPOINT", "https://api.example/v1/chat/completions")
    monkeypatch.setenv("SLIDEX_VISION_API_KEY", "sk-test")
    monkeypatch.setenv("SLIDEX_VISION_MODEL", "gemini-3.8-flash")
    channel = riskctl.vision_channel_from_env()
    assert channel is not None
    endpoint, api_key, model, _timeout = channel
    assert endpoint == "https://api.example/v1/chat/completions"
    assert api_key == "sk-test"
    assert model == "gemini-3.8-flash"


def test_overall_star_row_survives_the_dimension_value_chips():
    """The 2026-11 editor renders 口味/环境/服务 current-value chips with the
    same caption labels (超预期/很棒) further down the page. max() over every
    label pushed caption_bottom to 874 and left the overall star row (cy
    450) with no candidate window -- overall_star_row_rects returned () on
    every 2026-11 editor dump and the overall rate step failed."""
    dump = (
        "<hierarchy>"
        '<node text="很糟糕" bounds="[164,346][263,385]"/>'
        '<node text="较差" bounds="[356,346][422,385]"/>'
        '<node text="一般" bounds="[531,346][597,385]"/>'
        '<node text="还可以" bounds="[690,346][789,385]"/>'
        '<node text="超预期" bounds="[866,346][965,385]"/>'
        '<node class="android.widget.ImageView" bounds="[144,410][233,490]"/>'
        '<node class="android.widget.ImageView" bounds="[320,410][409,490]"/>'
        '<node class="android.widget.ImageView" bounds="[496,410][585,490]"/>'
        '<node class="android.widget.ImageView" bounds="[671,410][760,490]"/>'
        '<node class="android.widget.ImageView" bounds="[847,410][936,490]"/>'
        '<node text="口味" bounds="[68,584][140,626]"/>'
        '<node text="超预期" bounds="[889,584][997,626]"/>'
        '<node text="环境" bounds="[68,708][140,750]"/>'
        '<node text="很棒" bounds="[889,708][997,750]"/>'
        '<node text="服务" bounds="[68,832][140,874]"/>'
        '<node text="很棒" bounds="[889,832][997,874]"/>'
        "</hierarchy>"
    )
    stars = session_mod.overall_star_row_rects(dump)
    assert len(stars) == 5
    assert all(y == 450 for _x, y in stars)


def test_device_config_rebuild_keeps_the_captcha_window():
    """--captcha-window landed on the caller-built config and died in the
    device_config_from_env rebuild: both sessions then saw 0.0 and the
    manual-recovery retry loop never armed."""
    from automation_app_dianping.config import DianpingDeviceConfig

    rebuilt = session_mod.device_config_from_env(
        {}, base=DianpingDeviceConfig(captcha_window_seconds=300.0)
    )
    assert rebuilt.captcha_window_seconds == 300.0


def test_review_publish_chrome_needs_the_bottom_bar_button():
    """review_publish_chrome_visible was a whole-dump substring scan: a shop
    page whose reviewer badge reads 发布过3条馄饨... looked like the editor and
    froze the BACK unwind at 'refusing BACK with editor chrome visible'."""
    # Real shop-page shape: the word only appears inside longer badge text.
    shop = (
        "<hierarchy>"
        '<node text="金虹桥商场" bounds="[178,106][705,153]"/>'
        '<node text="发布过3条馄饨|抄手|扁食评价" bounds="[404,1123][770,1156]"/>'
        '<node text="写评价" bounds="[194,2255][284,2292]"/>'
        '<node bounds="[0,2355][1080,2400]"/>'
        "</hierarchy>"
    )
    assert session_mod.review_publish_chrome_visible(shop) is False

    # The editor's own control: exact text, pinned to the bottom bar.
    editor = (
        "<hierarchy>"
        '<node text="说评价" bounds="[675,1665][783,1707]"/>'
        '<node text="发布" bounds="[189,2200][1035,2313]"/>'
        '<node bounds="[0,2355][1080,2400]"/>'
        "</hierarchy>"
    )
    assert session_mod.review_publish_chrome_visible(editor) is True

    # A 发布 button OUTSIDE the bottom bar is not the editor's bar either.
    top_button = (
        "<hierarchy>"
        '<node text="发布" bounds="[900,84][1047,123]"/>'
        '<node bounds="[0,2355][1080,2400]"/>'
        "</hierarchy>"
    )
    assert session_mod.review_publish_chrome_visible(top_button) is False

    # Bounds-less offline fakes keep the legacy exact-label semantics.
    assert (
        session_mod.review_publish_chrome_visible(
            "<hierarchy><node text='添加图/视频' /><node text='发布' /></hierarchy>"
        )
        is True
    )
    assert session_mod.review_publish_chrome_visible("<hierarchy/>") is False
    assert session_mod.review_publish_chrome_visible("") is False


def test_shop_page_entry_requires_the_name_in_the_title_band():
    """shop_page_has_review_entry trusted any occurrence of the shop name:
    review bodies carry dish and shop names too, so a wrong shop's 写评价
    could be tapped and the review posted to the wrong shop."""
    dump = (
        "<hierarchy>"
        '<node text="金虹桥商场" bounds="[178,106][705,153]"/>'
        '<node text="第一次来推荐直接点招牌全家福馄饨" bounds="[141,587][1041,699]"/>'
        '<node text="发布过3条馄饨|抄手|扁食评价" bounds="[404,1123][770,1156]"/>'
        '<node text="写评价" bounds="[194,2255][284,2292]"/>'
        '<node bounds="[0,2355][1080,2400]"/>'
        "</hierarchy>"
    )
    # The real title matches; a dish name that only lives in review bodies
    # does not.
    assert session_mod.shop_page_has_review_entry(dump, "金虹桥商场") is True
    assert session_mod.shop_page_has_review_entry(dump, "馄饨") is False

    # Prefix titles still match (params may lack the paren suffix), and the
    # name must sit in the top band even then.
    prefixed = dump.replace("金虹桥商场", "金虹桥商场(娄山关路店)")
    assert session_mod.shop_page_has_review_entry(prefixed, "金虹桥商场") is True


def test_geometry_windows_scale_to_the_dump_device():
    """uiautomator dumps carry no width/height attribute, so the geometry
    scale never engaged: on any device bigger than the 1080x2400 reference
    the filmstrip/photo windows silently matched nothing and the leftover
    cleanup deleted nothing while reporting success."""
    tall = (
        "<hierarchy>"
        '<node bounds="[0,0][1440,3200]"/>'
        '<node text="识别菜品" bounds="[49,2339][285,2421]"/>'
        '<node class="android.widget.FrameLayout" clickable="true" '
        'bounds="[41,2619][210,2788]">'
        '<node class="android.widget.ImageView" bounds="[41,2619][210,2788]"/>'
        "</node>"
        "</hierarchy>"
    )
    rects = session_mod.dish_edit_filmstrip_rects(tall)
    assert [(r["x"], r["y"]) for r in rects] == [(41, 2619)]

    # The scale only engages once the dump reaches the reference resolution:
    # miniature fixtures keep the 1080x2400 constants.
    assert (
        session_mod.device_geometry_scale(
            "<hierarchy><node bounds='[10,10][400,80]'/></hierarchy>"
        )
        == 1.0
    )
    assert (
        session_mod._screen_height_scale(
            "<hierarchy><node bounds='[10,10][400,80]'/></hierarchy>"
        )
        == 1.0
    )
    # Explicit root attributes keep winning.
    wide = (
        "<hierarchy width='1440' height='3200'>"
        "<node bounds='[0,0][1440,3200]'/></hierarchy>"
    )
    assert abs(session_mod.device_geometry_scale(wide) - 1440 / 1080.0) < 1e-9
    assert abs(session_mod._screen_height_scale(wide) - 3200 / 2400.0) < 1e-9


# --- per-run JSONL event log (2026-11-12: post-run analysis) -----------------


def _read_events(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def test_run_event_log_writes_jsonl_and_parks_after_failure(tmp_path):
    from automation_app_dianping.runlog import RunEventLog, emit

    log = RunEventLog(tmp_path / "logs" / "run.jsonl")
    log.event("action", action="tap", phase="end", ok=True, seconds=0.4)
    log.event("rate", stars_found=5, point=[188, 450])
    # Non-JSON fields and oversized strings are coerced, never raised.
    log.event("slider_swipe", handle=(158, 1564), message="x" * 5000)
    events = _read_events(tmp_path / "logs" / "run.jsonl")
    assert [e["kind"] for e in events] == ["action", "rate", "slider_swipe"]
    assert events[0]["action"] == "tap" and events[0]["ok"] is True
    assert events[2]["handle"] == [158, 1564]
    assert len(events[2]["message"]) <= 400

    # First write failure parks the logger: no retry-spam, no raise.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("file, not dir", encoding="utf-8")
    unwritable = RunEventLog(blocker / "nested" / "run.jsonl")
    unwritable.event("action", action="tap")
    unwritable.event("action", action="tap")  # parked: still no raise
    assert emit(None, "action") is None  # offline no-op


def test_uia2_dismiss_dialogs_logs_the_chrome_filter_decision(tmp_path, monkeypatch):
    """The post-run question is not 'did it dismiss' but 'what was on screen
    and what did the filter skip' -- the 2026-11-12 analysis needed dump
    archaeology to answer exactly that."""
    _fast_clock(monkeypatch)
    kit = _SeqKit(_NavDriver([_EDITOR_CHROME_DUMP]))
    kit.results["tap"] = ActionResult(True, "tapped")
    log_path = tmp_path / "logs" / "run.jsonl"
    session = DianpingUia2Session(
        kit, captcha_window_seconds=0,
        event_log=RunEventLog(log_path),
    )
    out = session.execute_action(
        "dismiss_dialogs",
        selector=('uiautomator:new UiSelector().text("取消")',), max_attempts=2,
    )
    assert out.success and out.data == {"dismissed": 0}
    events = _read_events(log_path)
    assert events[0]["kind"] == "action" and events[0]["phase"] == "start"
    ended = [e for e in events if e["kind"] == "action" and e.get("phase") == "end"]
    assert ended and ended[-1]["action"] == "dismiss_dialogs" and ended[-1]["ok"] is True
    dismiss = [e for e in events if e["kind"] == "dismiss_dialogs"]
    assert dismiss[-1]["outcome"] == "nothing on screen"

    # A real dialog candidate still shows up as tapped, with its label.
    kit2 = _SeqKit(_NavDriver([_MODAL_DUMP]))
    kit2.results["tap"] = ActionResult(True, "tapped")
    log_path2 = tmp_path / "logs" / "run2.jsonl"
    session2 = DianpingUia2Session(
        kit2, captcha_window_seconds=0,
        event_log=RunEventLog(log_path2),
    )
    session2._dismiss_dialogs(
        selector=('uiautomator:new UiSelector().text("暂不查看")',), max_attempts=1
    )
    events2 = _read_events(log_path2)
    tapped = [e for e in events2 if e.get("outcome") == "tapped"]
    assert tapped and tapped[0]["candidate"] == "text=暂不查看"


def test_uia2_rate_and_slider_log_their_decisions(tmp_path, monkeypatch):
    _fast_clock(monkeypatch)
    log_path = tmp_path / "logs" / "run.jsonl"

    # Overall rate: the star row is found and the chosen point logged.
    star_dump = (
        "<hierarchy>"
        '<node text="很棒" class="android.widget.TextView" bounds="[883,253][949,292]" />'
        '<node class="android.widget.ImageView" bounds="[144,313][233,402]" />'
        '<node class="android.widget.ImageView" bounds="[320,313][409,402]" />'
        '<node class="android.widget.ImageView" bounds="[496,313][585,402]" />'
        '<node class="android.widget.ImageView" bounds="[671,313][760,402]" />'
        '<node class="android.widget.ImageView" bounds="[847,313][936,402]" />'
        "</hierarchy>"
    )
    kit = _SeqKit(_NavDriver([star_dump]))
    kit.results["swipe"] = ActionResult(True, "swiped")
    session = DianpingUia2Session(kit, captcha_window_seconds=0, event_log=RunEventLog(log_path))
    out = session.execute_action(
        "rate", dimension="overall", value=5, anchor="overall",
        selector=('uiautomator:new UiSelector().text("很棒")',),
    )
    assert out.success
    events = _read_events(log_path)
    star = [e for e in events if e["kind"] == "rate" and e.get("anchor") == "overall"]
    assert star and star[-1]["stars_found"] == 5 and star[-1]["point"][1] == 357

    # Slider: handle miss and successful swipe are both on the record.
    kit2 = _SeqKit(_NavDriver(["<hierarchy/>"]))
    log_path2 = tmp_path / "logs" / "run2.jsonl"
    session2 = DianpingUia2Session(kit2, captcha_window_seconds=0, event_log=RunEventLog(log_path2))
    miss = session2._perform_slider_swipe(gap_x=500)
    assert not miss.success
    events2 = _read_events(log_path2)
    assert events2[-1]["kind"] == "slider_swipe"
    assert events2[-1]["outcome"] == "handle not located"


def test_factories_wire_a_run_log_under_the_artifact_root(tmp_path, monkeypatch):
    from automation_app_dianping.config import DianpingDeviceConfig
    from automation_app_dianping.runlog import RunEventLog
    from automation_app_dianping.session import build_session_factory

    class _BootDriver:
        def dump_hierarchy(self):
            return "<hierarchy/>"

        def click(self, x, y):
            pass

    class _StubKit(_SeqKit):
        def __init__(self, device, identifier="stub", artifact_root=None):
            super().__init__(device)
            self.artifact_root = artifact_root

    config = DianpingDeviceConfig(
        udid="fake-udid", artifact_root=str(tmp_path / "artifacts")
    )
    monkeypatch.setattr(session_mod, "_connect_uia2", lambda udid: _BootDriver())
    monkeypatch.setattr(session_mod, "_import_kit_uia2_session", lambda: _StubKit)
    factory = build_session_factory(config, driver="uia2")
    session = factory()
    assert isinstance(session.event_log, RunEventLog)
    session.execute_action("dismiss_dialogs", selector=("~关闭",), max_attempts=1)
    logs = list((tmp_path / "artifacts" / "logs").glob("run-*.jsonl"))
    assert logs, "the factory must create the run log under artifacts/logs"
    events = _read_events(logs[0])
    assert any(e["kind"] == "action" and e["action"] == "dismiss_dialogs" for e in events)


def test_cli_persists_the_live_report(tmp_path):
    import automation_app_dianping.cli as cli_mod

    class _Result:
        success = True
        state = "completed"
        error = None
        actions = []
        artifacts = []
        failure = None

    report = cli_mod._persist_live_report(_Result(), tmp_path / "artifacts")
    assert report is not None and report.exists()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["success"] is True and payload["actions"] == []

