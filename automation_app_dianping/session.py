"""Live Android/Appium session wiring for Dianping."""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import inspect
import io
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from automation_core.drivers import ActionResult, ArtifactHandle, SessionInfo

from automation_app_dianping.config import DianpingDeviceConfig, as_selector_list


class ActionParameterError(ValueError):
    """A workflow action carried a parameter the driver cannot honour.

    Raised instead of letting a bare ``float()``/``int()`` raise, so the
    surfaced error names the parameter instead of only the action. Callers
    that want a soft failure return an ``ActionResult``; this is for the
    coercion points where a raw ``ValueError`` used to escape the session.
    """


def _coerce_number(
    name: str,
    raw: Any,
    default: Any,
    *,
    cast: Callable[[Any], Any] = float,
    minimum: Optional[float] = None,
) -> Any:
    """Coerce a numeric parameter, naming it in the error when it is garbage.

    An explicit ``None`` falls back to ``default`` because the workflow
    templates emit keys with null values for omitted knobs.
    """
    if raw is None:
        raw = default
    try:
        value = cast(raw)
    except (TypeError, ValueError):
        raise ActionParameterError("%s must be a number, got %r" % (name, raw))
    if minimum is not None and value < minimum:
        raise ActionParameterError(
            "%s must be >= %s, got %r" % (name, minimum, value)
        )
    return value


def _numeric_parameter(
    kwargs: Dict[str, Any],
    name: str,
    default: Any,
    *,
    cast: Callable[[Any], Any] = float,
    minimum: Optional[float] = None,
) -> Any:
    """Read a numeric action parameter out of the step's kwargs."""
    return _coerce_number(
        name, kwargs.get(name, default), default, cast=cast, minimum=minimum
    )


_SWALLOW_LOG_INTERVAL_SECONDS = 10.0
_SWALLOW_LOG_LAST: Dict[str, float] = {}


def _log_swallowed(label: str, exc: Exception) -> None:
    """Best-effort helpers must stay silent to the caller, but a failure that
    made the session act blind is still worth a line on the console so a live
    run is not diagnosed from a blank page source.

    Repeated calls are throttled: a persistent device fault makes every
    hierarchy poll raise, and without dedupe a broken run would spam one line
    per poll.
    """
    now = time.time()
    if now - _SWALLOW_LOG_LAST.get(label, -_SWALLOW_LOG_INTERVAL_SECONDS) < _SWALLOW_LOG_INTERVAL_SECONDS:
        return
    _SWALLOW_LOG_LAST[label] = now
    print(
        "[dianping] %s: swallowed %s: %s"
        % (label, type(exc).__name__, exc),
        flush=True,
    )


class _ByStrings:
    ACCESSIBILITY_ID = "accessibility id"
    ID = "id"
    ANDROID_UIAUTOMATOR = "-android uiautomator"
    XPATH = "xpath"


def _import_by():
    try:
        from appium.webdriver.common.appiumby import AppiumBy

        return AppiumBy
    except ImportError:
        pass
    try:
        from selenium.webdriver.common.by import By

        return By
    except ImportError:
        return _ByStrings


def parse_locator(selector: str) -> Tuple[str, str]:
    if not isinstance(selector, str) or not selector.strip():
        raise ValueError("selector must be a non-blank string")
    text = selector.strip()
    By = _import_by()
    if text.startswith("~"):
        return getattr(By, "ACCESSIBILITY_ID", "accessibility id"), text[1:]
    if text.startswith("id:"):
        return getattr(By, "ID", "id"), text[3:]
    if text.startswith("uiautomator:"):
        return getattr(By, "ANDROID_UIAUTOMATOR", "-android uiautomator"), text[len("uiautomator:") :]
    if text.startswith("android=new UiSelector()"):
        return getattr(By, "ANDROID_UIAUTOMATOR", "-android uiautomator"), text[len("android=") :]
    if text.startswith("xpath:"):
        return getattr(By, "XPATH", "xpath"), text[6:]
    if text.startswith("//") or text.startswith("(//"):
        return getattr(By, "XPATH", "xpath"), text
    return getattr(By, "ACCESSIBILITY_ID", "accessibility id"), text


def create_appium_driver(device: DianpingDeviceConfig):
    try:
        from appium import webdriver as appium_webdriver
        from appium.options.android import UiAutomator2Options
    except ImportError as exc:
        raise ImportError(
            "Appium-Python-Client is required for live runs. pip install Appium-Python-Client"
        ) from exc

    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.automation_name = "UiAutomator2"
    options.app_package = device.app_id
    options.app_activity = device.activity
    options.device_name = device.device_name
    options.no_reset = device.no_reset
    options.new_command_timeout = device.new_command_timeout
    options.set_capability("autoGrantPermissions", device.auto_grant_permissions)
    options.set_capability("disableIdLocatorAutocompletion", True)
    # ColorOS/OnePlus chained `settings put global hidden_api_policy*` adb
    # calls exit 255; Appium aborts the session unless told to ignore it.
    options.set_capability("ignoreHiddenApiPolicyError", True)
    # Dianping's search results / shop pages are WebView-heavy and keep the
    # UI thread busy; without this the uiautomator2 server waits for idle
    # until the 240s proxy timeout instead of returning promptly.
    options.set_capability(
        "settings",
        {"waitForIdleTimeout": 0, "snapshotMaxDepth": 60},
    )
    if device.udid:
        options.udid = device.udid
    if device.platform_version:
        options.platform_version = device.platform_version
    # Selenium joins the base URL and the "/session" route by plain string
    # concatenation, so a trailing slash in the configured base path would
    # produce "//session" and 404 on Appium's router.
    base_path = (device.path or "").rstrip("/")
    server_url = "http://%s:%s%s" % (device.host, device.port, base_path)
    return appium_webdriver.Remote(command_executor=server_url, options=options)


_SLIDER_HANDLE_HINTS = ("滑块", "slider", "拖动", "handle")
_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")

# Latin markers only count inside structural attributes: H5 pages carry
# words like "slider" inside rendered copy and CSS-instrumented text, which
# made raw-source substring matching false-positive on the review editor.
_SLIDER_ATTR_MARKERS = ("captcha", "slider", "geetest", "nocaptcha", "nc_1")
_SLIDER_TEXT_MARKERS = ("滑块", "拖动滑块", "向右拖动", "安全验证")


def page_source_indicates_slider(source: str) -> bool:
    """Attribute-level slider detection over a page source dump."""
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return False
    for node in root.iter("node"):
        klass = (node.get("class") or "").lower()
        rid = (node.get("resource-id") or "").lower()
        if any(marker in klass or marker in rid for marker in _SLIDER_ATTR_MARKERS):
            return True
        text = (node.get("text") or "").strip().lower()
        desc = (node.get("content-desc") or "").strip().lower()
        if any(marker in text or marker in desc for marker in _SLIDER_TEXT_MARKERS):
            return True
    return False


def locate_slider_handle(source: str) -> Optional[Tuple[int, int]]:
    """Best-effort slider handle position from a page source dump.

    Returns the center of the first node whose text/content-desc looks like
    a slider handle and whose bounds are parseable, else None.
    """
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return None
    for node in root.iter("node"):
        text = (node.get("text") or "").strip().lower()
        desc = (node.get("content-desc") or "").strip().lower()
        if not any(hint in text or hint in desc for hint in _SLIDER_HANDLE_HINTS):
            continue
        match = _BOUNDS_RE.match(node.get("bounds") or "")
        if match is None:
            continue
        x1, y1, x2, y2 = (int(part) for part in match.groups())
        if x2 > x1 and y2 > y1:
            return ((x1 + x2) // 2, (y1 + y2) // 2)
    return None


def _await_in_worker_thread(awaitable: Any) -> Any:
    """Bridge an awaitable onto a private loop in a worker thread.

    Session actions run inside the runtime's event loop; asyncio.run there
    is illegal, so awaitable solvers execute on their own loop in a thread.
    """

    async def _await():
        return await awaitable

    def _run():
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_await())
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_run).result()


def _slider_solution_params(
    solution: Any,
) -> Tuple[Optional[Dict[str, Any]], Optional[ActionResult]]:
    """Validate a slider solver result into swipe parameters.

    slidex's pure-image path reports the gap's left edge in screenshot pixels
    (``gap_x`` / ``distance_px``); older providers reported a ready-made drag
    distance (``gap_offset_px``). Either may carry ``distance_scale`` when the
    screenshot is rendered smaller than device pixels. A bare number is the
    legacy ready-made-distance shape.
    """
    if isinstance(solution, (int, float)) and not isinstance(solution, bool):
        solution = {"gap_offset_px": int(solution)}
    if not isinstance(solution, dict):
        return None, ActionResult(False, "slider solver produced no solution")
    gap_x = solution.get("gap_x")
    offset = solution.get("gap_offset_px")
    if gap_x is None and offset is None:
        return None, ActionResult(False, "slider solver produced no solution")
    try:
        scale = float(solution.get("distance_scale", 1.0))
    except (TypeError, ValueError):
        return None, ActionResult(False, "slider solver returned invalid distance_scale")
    if scale <= 0:
        return None, ActionResult(False, "slider solver returned non-positive distance_scale")
    return {"gap_x": gap_x, "offset_px": offset, "scale": scale}, None


def _slider_drag_distance(
    start_x: int, gap_x: Any, offset_px: Any, scale: float
) -> Tuple[Optional[int], Optional[ActionResult]]:
    """Compute the horizontal drag distance for a located slider handle.

    ``gap_x`` is the gap's absolute left edge and the handle starts on the
    piece, so the drag is the gap x minus the handle's own start x. ``offset_px``
    is already a drag distance. Both are multiplied by ``scale``.
    """
    if gap_x is not None:
        try:
            target = float(gap_x)
        except (TypeError, ValueError):
            return None, ActionResult(False, "slider solver returned invalid gap_x")
        if target <= 0:
            return None, ActionResult(False, "slider solver returned non-positive gap_x")
        distance = int(round((target - start_x) * scale))
        if distance <= 0:
            return None, ActionResult(
                False,
                "slider gap at x=%s is at or left of handle x=%s" % (target, start_x),
            )
        return distance, None
    try:
        distance = int(round(float(offset_px) * scale))
    except (TypeError, ValueError):
        return None, ActionResult(False, "slider solver returned invalid gap_offset_px")
    if distance <= 0:
        return None, ActionResult(False, "slider solver returned non-positive gap_offset_px")
    return distance, None


class DianpingAppiumSession:
    """DriverSession-compatible Appium session with multi-selector support."""

    _SLIDER_GUARDED_ACTIONS = frozenset(
        {
            "tap",
            "type_text",
            "wait_for_element",
            "confirm_search",
            "navigate_to_review_editor",
            "rate",
            "pick_photos",
        }
    )

    def __init__(
        self,
        driver: Any,
        *,
        identifier: str = "dianping-appium",
        artifact_root: Optional[Path] = None,
        slider_solver: Optional[Callable[[Any], Any]] = None,
        captcha_window_seconds: float = 0.0,
    ):
        self.driver = driver
        self.info = SessionInfo(driver_name="appium", platform="android", identifier=identifier)
        self.artifact_root = Path(artifact_root or "artifacts/dianping-live")
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.slider_solver = slider_solver
        # Risk-control dialogs (e.g. the jigsaw slider) render without
        # accessibility nodes, so they are invisible to page-source detection;
        # the manual window keeps retrying a blocked action while a human
        # solves the challenge on the device.
        self.captcha_window_seconds = _coerce_number(
            "captcha_window_seconds", captcha_window_seconds, 0.0, minimum=0.0
        )
        self._started = False
        self._slider_guard_active = False
        self._manual_window_active = False

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        quit_method = getattr(self.driver, "quit", None)
        if callable(quit_method):
            try:
                quit_method()
            except Exception:
                pass
        self._started = False


    def _dump_failure(self, label: str) -> None:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(label))[:40] or "failure"
        stamp = str(int(time.time()))
        try:
            self.capture_artifact("screenshot", "fail-%s-%s.png" % (safe, stamp))
        except Exception:
            pass
        try:
            self.capture_artifact("page_source", "fail-%s-%s.xml" % (safe, stamp))
        except Exception:
            pass

    def execute_action(self, action_name: str, **kwargs: Any) -> ActionResult:
        started = time.time()
        print("[dianping] >> %s" % action_name, flush=True)
        result = self._run_action(action_name, kwargs)
        print(
            "[dianping] << %s: %s (%.1fs)"
            % (action_name, "ok" if result.success else "FAIL", time.time() - started),
            flush=True,
        )
        return result

    def _run_action(self, action_name: str, kwargs: Dict[str, Any]) -> ActionResult:
        """Dispatch one action, turning a bad parameter into a reported failure.

        A parameter error short-circuits the slider guard and the manual
        captcha window: retrying a tap with an unparseable timeout would only
        re-raise for the whole window.
        """
        try:
            return self._run_named_action(action_name, kwargs)
        except ActionParameterError as exc:
            result = ActionResult(False, "%s: %s" % (action_name, exc))
            print("[dianping] failure detail: %s" % result.message[:400], flush=True)
            self._dump_failure(action_name)
            return result

    def _run_named_action(self, action_name: str, kwargs: Dict[str, Any]) -> ActionResult:
        if action_name == "rate":
            result = self._rate(**kwargs)
        elif action_name == "pick_photos":
            result = self._pick_photos(**kwargs)
        elif action_name == "launch_app":
            result = self._launch_app(**kwargs)
        elif action_name == "confirm_search":
            result = self._confirm_search(**kwargs)
        elif action_name == "navigate_to_review_editor":
            result = self._navigate_to_review_editor(**kwargs)
        elif action_name == "hide_keyboard":
            result = self._hide_keyboard(**kwargs)
        elif action_name == "dismiss_dialogs":
            result = self._dismiss_dialogs(**kwargs)
        elif action_name == "press_keycode":
            result = self._press_keycode(**kwargs)
        elif action_name in {"tap", "type_text", "wait_for_element"}:
            result = self._with_selector_fallbacks(action_name, kwargs)
        else:
            failed = ActionResult(False, "unsupported appium action: %s" % action_name)
            result = self._maybe_fallback(action_name, kwargs, failed)
        if result.success and action_name in self._SLIDER_GUARDED_ACTIONS:
            result = self._guard_slider(action_name, result, kwargs)
        elif (
            not result.success
            and action_name in self._SLIDER_GUARDED_ACTIONS
            and self.captcha_window_seconds > 0
            and not self._manual_window_active
        ):
            result = self._retry_after_manual_window(action_name, kwargs, result)
        if not result.success:
            print("[dianping] failure detail: %s" % result.message[:400], flush=True)
            self._dump_failure(action_name)
        return result

    def _retry_after_manual_window(
        self, action_name: str, kwargs: Dict[str, Any], failure: ActionResult
    ) -> ActionResult:
        """Keep re-attempting a blocked action while a human solves a challenge.

        Risk-control dialogs expose no accessibility nodes, so the session
        cannot see them; it can only observe that the action stopped failing
        once the challenge is cleared on the device.
        """
        self._manual_window_active = True
        try:
            deadline = time.time() + self.captcha_window_seconds
            while time.time() < deadline:
                time.sleep(min(5.0, max(1.0, deadline - time.time())))
                retry = self.execute_action(action_name, **kwargs)
                if retry.success:
                    return ActionResult(
                        True,
                        "%s (recovered after manual captcha window)" % action_name,
                        data=retry.data,
                    )
            return failure
        finally:
            self._manual_window_active = False

    def _guard_slider(self, action_name: str, result: ActionResult, kwargs: Dict[str, Any]) -> ActionResult:
        """Detect risk-control sliders that appeared during an action.

        A slider that pops up after a tap absorbs it and blocks the UI; the
        original action must be retried once after the challenge is cleared.
        The re-entrancy flag keeps the retry itself out of the guard.
        """
        if self._slider_guard_active:
            return result
        try:
            source = getattr(self.driver, "page_source", "")
        except Exception as exc:
            _log_swallowed("slider guard page source", exc)
            return result
        if not isinstance(source, str) or not page_source_indicates_slider(source):
            return result
        self._slider_guard_active = True
        try:
            solve = self._attempt_slider_solve()
            if not solve.success:
                return ActionResult(
                    False,
                    "slider challenge detected during %s; %s" % (action_name, solve.message),
                )
            retry = self.execute_action(action_name, **kwargs)
            if not retry.success:
                return ActionResult(
                    False,
                    "slider solved but %s retry failed: %s" % (action_name, retry.message),
                )
            return ActionResult(True, "%s (slider solved; action retried)" % action_name)
        finally:
            self._slider_guard_active = False

    def _attempt_slider_solve(self) -> ActionResult:
        if self.slider_solver is None:
            return ActionResult(
                False,
                "no slider solver configured; rerun with --enable-slidex "
                "(requires slidex android_screenshot_bytes slider support)",
            )
        screenshot = getattr(self.driver, "get_screenshot_as_base64", None)
        if not callable(screenshot):
            return ActionResult(False, "driver cannot capture screenshots for slider solving")
        try:
            image = base64.b64decode(screenshot())
            solution = self.slider_solver(image)
            if inspect.isawaitable(solution):
                solution = _await_in_worker_thread(solution)
        except Exception as exc:
            return ActionResult(False, "slider solve errored: %s" % exc)

        params, error = _slider_solution_params(solution)
        if error is not None:
            return error
        return self._perform_slider_swipe(**params)

    def _perform_slider_swipe(
        self,
        *,
        gap_x: Any = None,
        offset_px: Any = None,
        scale: float = 1.0,
    ) -> ActionResult:
        try:
            source = str(getattr(self.driver, "page_source", "") or "")
        except Exception as exc:
            return ActionResult(False, "page source unavailable for slider handle: %s" % exc)
        handle = locate_slider_handle(source)
        if handle is None:
            return ActionResult(False, "slider handle not located in page source")
        swipe = getattr(self.driver, "swipe", None)
        if not callable(swipe):
            return ActionResult(False, "driver does not support coordinate swipe")
        distance, error = _slider_drag_distance(handle[0], gap_x, offset_px, scale)
        if error is not None:
            return error
        start_x, start_y = handle
        try:
            swipe(int(start_x), int(start_y), int(start_x + distance), int(start_y), 600)
        except Exception as exc:
            return ActionResult(False, "slider swipe failed: %s" % exc)
        return ActionResult(True, "slider swiped %d px" % distance)

    def capture_artifact(self, artifact_type: str, name: str) -> ArtifactHandle:
        path = self.artifact_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if artifact_type == "screenshot":
            save = getattr(self.driver, "save_screenshot", None) or getattr(self.driver, "get_screenshot_as_file", None)
            if callable(save):
                save(str(path))
        elif artifact_type in {"page_source", "ui_tree"}:
            source = getattr(self.driver, "page_source", "")
            if isinstance(source, str):
                path.write_text(source, encoding="utf-8")
        return ArtifactHandle(artifact_type=artifact_type, path=path)

    def _maybe_fallback(self, action_name: str, kwargs: Dict[str, Any], primary: ActionResult) -> ActionResult:
        fallback_steps = kwargs.get("fallback_steps")
        if isinstance(fallback_steps, list) and fallback_steps:
            for step in fallback_steps:
                if not isinstance(step, dict):
                    return ActionResult(False, "%s invalid fallback step" % action_name)
                step_action = step.get("action") or step.get("name")
                if not step_action:
                    return ActionResult(False, "%s fallback missing action" % action_name)
                params = {k: v for k, v in step.items() if k not in {"action", "name"}}
                result = self.execute_action(str(step_action), **params)
                if not result.success:
                    return ActionResult(
                        False,
                        "%s fallback failed at %s: %s" % (action_name, step_action, result.message),
                    )
            return ActionResult(True, "%s via fallback_steps" % action_name)

        fallback_action = kwargs.get("fallback_action")
        if fallback_action:
            params = dict(kwargs)
            params["selector"] = params.get("fallback_selector") or params.get("selector")
            params.pop("fallback_action", None)
            params.pop("fallback_selector", None)
            params.pop("fallback_steps", None)
            result = self.execute_action(str(fallback_action), **params)
            if result.success:
                return ActionResult(True, "%s via fallback_action=%s" % (action_name, fallback_action))
            return ActionResult(
                False,
                "%s failed; fallback_action=%s failed: %s" % (action_name, fallback_action, result.message),
            )
        return primary

    def _rate(self, **kwargs: Any) -> ActionResult:
        selector = kwargs.get("selector") or kwargs.get("fallback_selector")
        if selector is None:
            return ActionResult(False, "rate requires selector")
        source = ""
        try:
            raw = getattr(self.driver, "page_source", "")
            source = raw if isinstance(raw, str) else ""
        except Exception:
            source = ""
        if should_skip_rating(source):
            return ActionResult(
                True,
                "rate skipped; overall bar not on overwrite chrome",
                data={"dimension": kwargs.get("dimension"), "value": kwargs.get("value")},
            )
        anchor = kwargs.get("anchor")
        if anchor in {"overall", "dimension_row"}:
            result = self._rate_by_label_anchor(selector, anchor, kwargs.get("value"))
            if result.success:
                return ActionResult(
                    True,
                    "rate",
                    data={"dimension": kwargs.get("dimension"), "value": kwargs.get("value")},
                )
            return self._maybe_fallback("rate", kwargs, result)
        result = self.execute_action("tap", selector=selector)
        if result.success:
            return ActionResult(
                True,
                "rate",
                data={"dimension": kwargs.get("dimension"), "value": kwargs.get("value")},
            )
        return self._maybe_fallback("rate", kwargs, result)

    def _display_width_px(self) -> Optional[int]:
        """Device display width for scaling pixel geometry.

        None when the driver cannot report it (offline fakes), which keeps
        the 1080px reference constants unscaled.
        """
        size = getattr(self.driver, "get_window_size", None)
        if not callable(size):
            return None
        try:
            value = size()
        except Exception:
            return None
        if not isinstance(value, dict):
            return None
        width = value.get("width")
        try:
            return int(width) if width else None
        except (TypeError, ValueError):
            return None

    def _rate_by_label_anchor(self, selector: Any, anchor: str, value: Any) -> ActionResult:
        """Tap a rating star by anchoring on its text label.

        The 2026-09 editor exposes no stable star ids: the overall row stacks
        each star under its emoji+label (integer values tap the right half,
        the left half rates a half star), and dimension rows place the label
        left of the star strip. Geometry constants live on DianpingSelectors.
        """
        from automation_app_dianping.config import default_selectors

        try:
            numeric_value = int(value)
        except (TypeError, ValueError):
            return ActionResult(False, "rate requires a numeric value")
        if not 1 <= numeric_value <= 5:
            return ActionResult(False, "rating value must be 1-5")
        selectors = default_selectors()
        width = self._display_width_px()
        scale = (width / _GEOMETRY_REFERENCE_WIDTH_PX) if width else 1.0
        candidates = as_selector_list(selector) if selector is not None else []
        errors = []
        for candidate in candidates:
            try:
                by, label_value = parse_locator(candidate)
                element = self._find_element(label_value, by=by, timeout=5.0)
                rect = element.rect
            except Exception as exc:
                errors.append("%s: %s" % (candidate, exc))
                continue
            if anchor == "overall":
                x = (
                    selectors.rating_overall_star_origin_px
                    + selectors.rating_overall_star_pitch_px * (numeric_value - 1)
                    + selectors.rating_star_tap_fraction * selectors.rating_star_width_px
                ) * scale
                y = rect["y"] + rect["height"] + selectors.rating_overall_star_gap_px * scale
            else:
                # Measured 2026-09 strip: first star centre 236, pitch 144 —
                # tap star centres, no width fraction.
                x = (
                    selectors.rating_dim_star_origin_px
                    + selectors.rating_dim_star_pitch_px * (numeric_value - 1)
                ) * scale
                y = rect["y"] + rect["height"] / 2
            swipe = getattr(self.driver, "swipe", None)
            if not callable(swipe):
                return ActionResult(False, "driver does not support coordinate taps")
            swipe(int(x), int(y), int(x), int(y), 80)
            if anchor == "overall":
                self._resolve_half_star_popup(numeric_value)
            return ActionResult(True, "star tapped at (%d, %d)" % (int(x), int(y)))
        return ActionResult(False, "rate anchor failed: %s" % "; ".join(errors))

    def _resolve_half_star_popup(self, value: int) -> None:
        """Pick the exact integer if the tap split a star.

        Tapping near the half-star boundary opens a chooser with the two
        adjacent values (e.g. 4.5星/5星); tapping the integer option pins the
        rating. Best effort: the popup only exists after a split tap.
        """
        try:
            by, popup_value = parse_locator(
                'uiautomator:new UiSelector().text("%s星")' % value
            )
            element = self._find_element(popup_value, by=by, timeout=1.5)
            element.click()
        except Exception:
            pass

    def _pick_photos(self, **kwargs: Any) -> ActionResult:
        if kwargs.get("fallback_steps"):
            return self._maybe_fallback(
                "pick_photos",
                kwargs,
                ActionResult(False, "pick_photos uses fallback_steps"),
            )
        photos = kwargs.get("photos") or []
        steps: List[Dict[str, Any]] = []
        if kwargs.get("add_selector"):
            steps.append({"action": "tap", "selector": kwargs.get("add_selector")})
        for index, photo in enumerate(photos):
            steps.append(
                {
                    "action": "tap",
                    "selector": kwargs.get("thumbnail_selector"),
                    "photo_path": photo,
                    "photo_index": index,
                }
            )
        if kwargs.get("confirm_selector"):
            steps.append({"action": "tap", "selector": kwargs.get("confirm_selector")})
        if not steps:
            return ActionResult(False, "pick_photos missing selectors")
        payload = dict(kwargs)
        payload["fallback_steps"] = steps
        return self._maybe_fallback(
            "pick_photos",
            payload,
            ActionResult(False, "pick_photos expanded"),
        )

    def _navigate_to_review_editor(self, **kwargs: Any) -> ActionResult:
        """Open the review editor from home search or a restored shop page."""
        shop_name = str(kwargs.get("shop_name") or "")
        write_selector = kwargs.get("write_selector")
        source = ""
        try:
            raw = getattr(self.driver, "page_source", "")
            source = raw if isinstance(raw, str) else ""
        except Exception:
            source = ""
        if dish_edit_is_open(source):
            return ActionResult(True, "navigate_to_review_editor already in dish-edit")
        if review_editor_is_open(source):
            return ActionResult(True, "navigate_to_review_editor already in review editor")
        if shop_page_has_review_entry(source, shop_name):
            wait = self._with_selector_fallbacks(
                "wait_for_element",
                {"selector": write_selector, "timeout": 4.0},
            )
            if wait.success:
                tap = self._with_selector_fallbacks("tap", {"selector": write_selector})
                if tap.success:
                    return ActionResult(
                        True, "navigate_to_review_editor via restored shop page"
                    )
                return tap
        search_bar = kwargs.get("search_bar")
        search_input = kwargs.get("search_input")
        wait = self._with_selector_fallbacks(
            "wait_for_element",
            {"selector": search_bar, "timeout": 10.0},
        )
        if not wait.success:
            return wait
        tap = self._with_selector_fallbacks("tap", {"selector": search_bar})
        if not tap.success:
            return tap
        wait = self._with_selector_fallbacks(
            "wait_for_element",
            {"selector": search_input, "timeout": 8.0},
        )
        if not wait.success:
            return wait
        typed = self._with_selector_fallbacks(
            "type_text",
            {"selector": search_input, "text": shop_name},
        )
        if not typed.success:
            return typed
        confirmed = self._confirm_search(
            selector=kwargs.get("search_confirm"),
            keycode=66,
        )
        if not confirmed.success:
            return confirmed
        wait = self._with_selector_fallbacks(
            "wait_for_element",
            {"selector": kwargs.get("search_results_marker"), "timeout": 12.0},
        )
        if not wait.success:
            return wait
        shop_result = shop_result_candidates(shop_name, kwargs.get("shop_result"))
        wait = self._with_selector_fallbacks(
            "wait_for_element",
            {"selector": shop_result, "timeout": 12.0},
        )
        if not wait.success:
            return wait
        tap = self._with_selector_fallbacks("tap", {"selector": shop_result})
        if not tap.success:
            return tap
        wait = self._with_selector_fallbacks(
            "wait_for_element",
            {"selector": write_selector, "timeout": 10.0},
        )
        if not wait.success:
            return wait
        tap = self._with_selector_fallbacks("tap", {"selector": write_selector})
        if not tap.success:
            return tap
        # The write CTA tap reports success even when the editor never opens
        # (live 2026-09-23: the shop page can stall on a notice), so require
        # an editor marker before declaring the navigation done.
        opened = self._with_selector_fallbacks(
            "wait_for_element",
            {
                "selector": (
                    'uiautomator:new UiSelector().textContains("添加图")',
                    'uiautomator:new UiSelector().text("发布")',
                ),
                "timeout": _EDITOR_OPEN_TIMEOUT_SECONDS,
            },
        )
        if not opened.success:
            return ActionResult(
                False, "navigate_to_review_editor: write tap did not open the editor"
            )
        return ActionResult(True, "navigate_to_review_editor via search")

    def _hide_keyboard(self, **kwargs: Any) -> ActionResult:
        """Dismiss the IME so the overall rating bar is visible.

        2026-09-21 editor: type_text leaves the keyboard covering 超预期.
        Prefer the Picasso toolbar 「完成」; fall back to BACK.
        Do not BACK once 发布 is already on screen — that leaves the editor.
        """
        source = ""
        try:
            raw = getattr(self.driver, "page_source", "")
            source = raw if isinstance(raw, str) else ""
        except Exception:
            source = ""
        if dish_edit_is_open(source) or (
            review_publish_chrome_visible(source) and not review_ime_toolbar_visible(source)
        ):
            return ActionResult(True, "hide_keyboard skipped; editor chrome visible")
        tap = self._with_selector_fallbacks(
            "tap",
            {
                "selector": (
                    'uiautomator:new UiSelector().text("完成")',
                    "~完成",
                ),
                "timeout": 2.0,
            },
        )
        if tap.success:
            return ActionResult(True, "hide_keyboard via 完成")
        press = getattr(self.driver, "press_keycode", None)
        if callable(press):
            try:
                press(4)
                return ActionResult(True, "hide_keyboard via BACK")
            except Exception as exc:
                return ActionResult(False, "hide_keyboard BACK failed: %s" % exc)
        hide = getattr(self.driver, "hide_keyboard", None)
        if callable(hide):
            try:
                hide()
                return ActionResult(True, "hide_keyboard via driver")
            except Exception as exc:
                return ActionResult(False, "hide_keyboard failed: %s" % exc)
        return ActionResult(True, "hide_keyboard skipped")

    def _launch_app(self, **kwargs: Any) -> ActionResult:
        app_id = kwargs.get("app_id")
        if not app_id:
            return ActionResult(False, "missing required parameter: app_id")
        activate = getattr(self.driver, "activate_app", None)
        if not callable(activate):
            return ActionResult(False, "driver does not support app launch")
        try:
            activate(app_id)
            time.sleep(_numeric_parameter(kwargs, "settle_seconds", 2.0, minimum=0.0))
            return ActionResult(True, "launch_app")
        except ActionParameterError as exc:
            return ActionResult(False, str(exc))
        except Exception as exc:
            return ActionResult(False, "launch_app failed: %s" % exc)

    def _with_selector_fallbacks(self, action_name: str, kwargs: Dict[str, Any]) -> ActionResult:
        selector = kwargs.get("selector")
        candidates = as_selector_list(selector) if selector is not None else []
        if not candidates and isinstance(selector, str):
            candidates = [selector]
        if not candidates:
            return ActionResult(False, "missing required parameter: selector")
        timeout = _numeric_parameter(
            kwargs, "timeout", 8.0 if action_name == "wait_for_element" else 5.0, minimum=0.0
        )
        errors = []
        for candidate in candidates:
            try:
                by, value = parse_locator(candidate)
            except Exception as exc:
                errors.append("%s: %s" % (candidate, exc))
                continue
            if action_name == "wait_for_element":
                result = self._wait_for_element(value, by=by, timeout=timeout)
            elif action_name == "tap":
                result = self._tap(value, by=by, timeout=timeout)
            elif action_name == "type_text":
                text = kwargs.get("text")
                if text is None:
                    return ActionResult(False, "missing required parameter: text")
                result = self._type_text(value, text=text, by=by, timeout=timeout)
            else:
                return ActionResult(False, "unsupported selector action: %s" % action_name)
            if result.success:
                return result
            errors.append("%s => %s" % (candidate, result.message))
        return ActionResult(False, "%s failed for all selectors: %s" % (action_name, " | ".join(errors[:5])))

    def _find_element(self, value: str, by: Any, timeout: float):
        end = time.time() + max(timeout, 0.1)
        last_error = None
        while time.time() < end:
            try:
                return self.driver.find_element(by, value)
            except Exception as exc:
                last_error = exc
                time.sleep(0.25)
        raise TimeoutError("element not found: %s (%s)" % (value, last_error))

    def _tap(self, value: str, *, by: Any, timeout: float) -> ActionResult:
        try:
            self._find_element(value, by=by, timeout=timeout).click()
            return ActionResult(True, "tap", data={"selector": value})
        except Exception as exc:
            return ActionResult(False, "tap failed: %s" % exc)

    def _type_text(self, value: str, *, text: str, by: Any, timeout: float) -> ActionResult:
        try:
            element = self._find_element(value, by=by, timeout=timeout)
            clear = getattr(element, "clear", None)
            if callable(clear):
                clear()
            send = getattr(element, "send_keys", None) or getattr(element, "set_value", None)
            if not callable(send):
                return ActionResult(False, "element does not support typing")
            send(text)
            return ActionResult(True, "type_text", data={"selector": value})
        except Exception as exc:
            return ActionResult(False, "type_text failed: %s" % exc)

    def _wait_for_element(self, value: str, *, by: Any, timeout: float) -> ActionResult:
        try:
            element = self._find_element(value, by=by, timeout=timeout)
            return ActionResult(True, "wait_for_element", data=element)
        except Exception as exc:
            return ActionResult(False, "timed out waiting for element: %s" % exc)



    def _press_keycode(self, **kwargs: Any) -> ActionResult:
        code = kwargs.get("keycode", kwargs.get("code", 66))
        try:
            code_i = int(code)
        except Exception:
            return ActionResult(False, "keycode must be int")
        press = getattr(self.driver, "press_keycode", None)
        if callable(press):
            try:
                press(code_i)
                return ActionResult(True, "press_keycode", data={"keycode": code_i})
            except Exception as exc:
                return ActionResult(False, "press_keycode failed: %s" % exc)
        execute_script = getattr(self.driver, "execute_script", None)
        if callable(execute_script):
            try:
                execute_script("mobile: pressKey", {"keycode": code_i})
                return ActionResult(True, "press_keycode", data={"keycode": code_i})
            except Exception as exc:
                return ActionResult(False, "press_keycode failed: %s" % exc)
        return ActionResult(False, "driver does not support keycode press")

    def _confirm_search(self, **kwargs: Any) -> ActionResult:
        selector = kwargs.get("selector")
        if selector is not None:
            tapped = self._with_selector_fallbacks("tap", {"selector": selector, "timeout": kwargs.get("timeout", 2.0)})
            if tapped.success:
                return ActionResult(True, "confirm_search", data={"via": "tap"})
        keycode = kwargs.get("keycode", 66)
        pressed = self._press_keycode(keycode=keycode)
        if pressed.success:
            return ActionResult(True, "confirm_search", data={"via": "keycode", "keycode": keycode})
        # Not fatal for offline fakes: treat soft-fail as success with warning so steps can continue
        # only if both failed - still fail.
        return ActionResult(False, "confirm_search failed: no search button and keycode unavailable")

    def _dismiss_dialogs(self, **kwargs: Any) -> ActionResult:
        selector = kwargs.get("selector")
        max_attempts = _numeric_parameter(kwargs, "max_attempts", 3, cast=int, minimum=1)
        dismissed = 0
        for _ in range(max_attempts):
            result = self._with_selector_fallbacks(
                "tap",
                {
                    "selector": selector,
                    "timeout": _numeric_parameter(kwargs, "timeout", 1.0, minimum=0.0),
                },
            )
            if not result.success:
                break
            dismissed += 1
            time.sleep(0.2)
        # Success even if nothing to dismiss - this is best-effort hygiene.
        return ActionResult(True, "dismiss_dialogs", data={"dismissed": dismissed})

def device_config_from_env(env: Optional[dict] = None, *, base: Optional[DianpingDeviceConfig] = None) -> DianpingDeviceConfig:
    source = env if env is not None else os.environ
    base = base or DianpingDeviceConfig()

    def _get(name: str, default: Optional[str] = None) -> Optional[str]:
        value = source.get(name)
        if value is None or str(value).strip() == "":
            return default
        return str(value).strip()

    port_raw = _get("DIANPING_APPIUM_PORT", str(base.port))
    try:
        port = int(port_raw) if port_raw is not None else base.port
    except ValueError as exc:
        raise ValueError("DIANPING_APPIUM_PORT must be an integer") from exc

    no_reset_raw = (_get("DIANPING_NO_RESET", "1" if base.no_reset else "0") or "1").lower()
    return DianpingDeviceConfig(
        app_id=_get("DIANPING_APP_ID", base.app_id) or base.app_id,
        activity=_get("DIANPING_APP_ACTIVITY", base.activity) or base.activity,
        host=_get("DIANPING_APPIUM_HOST", base.host) or base.host,
        port=port,
        path=_get("DIANPING_APPIUM_PATH", base.path) or base.path,
        udid=_get("DIANPING_DEVICE_UDID", base.udid),
        device_name=_get("DIANPING_DEVICE_NAME", base.device_name) or base.device_name,
        platform_version=_get("DIANPING_PLATFORM_VERSION", base.platform_version),
        no_reset=no_reset_raw in {"1", "true", "yes", "on"},
        auto_grant_permissions=base.auto_grant_permissions,
        new_command_timeout=base.new_command_timeout,
        artifact_root=_get("DIANPING_ARTIFACT_ROOT", base.artifact_root) or base.artifact_root,
    )


def build_session_factory(
    device: Optional[DianpingDeviceConfig] = None,
    *,
    env: Optional[dict] = None,
    driver_factory: Optional[Callable[[], Any]] = None,
    driver: Optional[str] = None,
    slider_solver: Optional[Callable[[Any], Any]] = None,
) -> Callable[[], Any]:
    config = device_config_from_env(env, base=device)
    source = env if env is not None else os.environ
    # uia2 is the production driver (README); Appium remains an opt-in path
    # for local experiments, never the silent default.
    selected = str(driver or source.get("DIANPING_DRIVER") or "uia2").strip().lower()
    if selected == "uia2":
        return build_uia2_session_factory(config, slider_solver=slider_solver)
    if selected != "appium":
        raise ValueError("unsupported dianping driver: %s" % selected)

    def factory() -> DianpingAppiumSession:
        driver = driver_factory() if driver_factory is not None else create_appium_driver(config)
        identifier = config.udid or config.device_name or "dianping-device"
        return DianpingAppiumSession(
            driver=driver,
            identifier=str(identifier),
            artifact_root=Path(config.artifact_root),
            slider_solver=slider_solver,
            captcha_window_seconds=config.captcha_window_seconds,
        )

    return factory


# --- uiautomator2 driver (no Appium server) --------------------------------

_UIA2_UNSUPPORTED_TOKENS = ("instance(", "childSelector", "fromParent")

# Single-method UiSelector constructs that map onto kit uia2 ``by`` keys.
_UIA2_METHOD_MAP = {
    "text": "text",
    "textContains": "text-contains",
    "description": "description",
    "descriptionContains": "description-contains",
    "resourceId": "id",
    "className": "class",
}

_UIA2_METHOD_RE = re.compile(r'\.(\w+)\(\s*"([^"]*)"\s*\)')

_PHOTO_IMAGE_RESOURCE_ID = "com.dianping.v1:id/ugc_album_item_photo_imageView"
_PHOTO_SELECT_RESOURCE_ID = "com.dianping.v1:id/ugc_album_item_select_layout"
_PHOTO_SELECT_BADGE_RESOURCE_ID = "com.dianping.v1:id/ugc_album_item_select"
# Leftover same-day thumbnails to clear before attaching. The cap keeps a
# mis-detected element from turning the cleanup into an unbounded delete loop.
_MAX_EDITOR_PHOTO_CLEARS = 6
# How long to wait for the review editor after tapping the 写评价 CTA.
_EDITOR_OPEN_TIMEOUT_SECONDS = 6.0


def _shell_text(result: Any) -> str:
    """Normalize uiautomator2 ``ShellResponse`` / str / bytes into stripped text.

    ``Device.shell`` returns a NamedTuple ``(output, exit_code)`` with no
    ``strip``; calling ``.strip()`` on it raises AttributeError and the
    gallery-prep poll would then spin until the 20s deadline.
    """
    if result is None:
        return ""
    output = getattr(result, "output", None)
    if output is None:
        output = result[0] if isinstance(result, tuple) and result else result
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    return str(output).strip()


def _media_field(row: str, field: str) -> str:
    """Parse ``field=...`` from a ``content query`` row."""
    marker = "%s=" % field
    if marker not in row:
        return ""
    return row.split(marker, 1)[1].split(",", 1)[0].strip()


def _media_display_name(row: str) -> str:
    """Parse ``_display_name=...`` from a ``content query`` row."""
    return _media_field(row, "_display_name")


def _picker_header_album(source: str) -> Optional[str]:
    """Album title in the Picasso picker chrome (y ~ 103), not the dropdown list.

    2026-09 live: the header 「最近项目」 sits at ``[430,103][610,156]``. Dropdown
    rows (Camera, downloads, …) start at y>=192, so a y<200 cut keeps the
    title distinct from the list. Clock / status bar nodes sit above y=68.
    """
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return None
    skip = {"全部", "照片", "视频", "相册", "拍摄", "下一步", "确定", "完成"}
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        if not text or text in skip or text.isdigit():
            continue
        rect = _bounds_rect(node.get("bounds") or "")
        if rect is None:
            continue
        if 68 <= rect["y"] < 200 and rect["height"] < 120:
            return text
    return None


def _bounds_rect(bounds: str) -> Optional[Dict[str, int]]:
    match = _BOUNDS_RE.match(bounds or "")
    if match is None:
        return None
    x1, y1, x2, y2 = (int(part) for part in match.groups())
    if x2 <= x1 or y2 <= y1:
        return None
    return {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}


_EDITOR_PHOTO_SKIP_LABELS = ("添加图", "说评价", "发布", "取消", "存草稿")


def editor_attached_photo_rects(source: str) -> List[Dict[str, int]]:
    """Clickable editor thumbnails that already have a numbered badge.

    2026-09-21 Picasso editor: leftover same-day review photos are
    clickable FrameLayouts in the photo row (y ~1087–1340 on 1080×2400)
    with a digit TextView overlay. The add card (添加图/视频) and voice
    card (说评价) sit in the same row and must not be treated as
    attached. The wrapping row FrameLayout is also clickable and is
    skipped because it is far wider than a thumbnail.
    """
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return []
    parent_of: Dict[ET.Element, ET.Element] = {}
    for node in root.iter():
        for child in list(node):
            parent_of[child] = node

    def nearest_clickable(node: ET.Element) -> Optional[ET.Element]:
        current: Optional[ET.Element] = node
        while current is not None:
            if (current.get("clickable") or "").lower() == "true":
                return current
            current = parent_of.get(current)
        return None

    def subtree_labels(node: ET.Element) -> str:
        parts = []
        for child in node.iter("node"):
            parts.append(child.get("text") or "")
            parts.append(child.get("content-desc") or "")
        return "".join(parts)

    seen = set()
    rects: List[Dict[str, int]] = []
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        if not text.isdigit():
            continue
        host = nearest_clickable(node)
        if host is None:
            continue
        labels = subtree_labels(host)
        if any(skip in labels for skip in _EDITOR_PHOTO_SKIP_LABELS):
            continue
        rect = _bounds_rect(host.get("bounds") or "")
        if rect is None:
            continue
        if not (80 <= rect["width"] <= 400 and 80 <= rect["height"] <= 400):
            continue
        if not (400 <= rect["y"] <= 2000):
            continue
        key = (rect["x"], rect["y"], rect["width"], rect["height"])
        if key in seen:
            continue
        seen.add(key)
        rects.append(rect)
    rects.sort(key=lambda item: item["x"])
    return rects


def _node_matches_selector(node: ET.Element, by: str, value: str) -> bool:
    text = node.get("text") or ""
    desc = node.get("content-desc") or ""
    rid = node.get("resource-id") or ""
    cls = node.get("class") or ""
    if by == "text":
        return text == value
    if by == "text-contains":
        return value in text
    if by == "description":
        return desc == value
    if by == "description-contains":
        return value in desc
    if by == "id":
        return rid == value
    if by == "class":
        return cls == value
    return False


def clickable_ancestor_rect(
    source: str, by: str, value: str
) -> Optional[Dict[str, int]]:
    """Nearest clickable ancestor of a Picasso chrome label.

    2026-09 Picasso chrome: 「写评价」, 「添加图/视频」, 「下一步」 and
    「确定」 are non-clickable TextViews. Their parent FrameLayout is the
    real target.
    """
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return None
    target = None
    for node in root.iter("node"):
        if _node_matches_selector(node, by, value):
            target = node
            break
    if target is None:
        return None
    parent_of = {}
    for node in root.iter():
        for child in list(node):
            parent_of[child] = node
    current: Optional[ET.Element] = target
    while current is not None:
        if (current.get("clickable") or "").lower() == "true":
            rect = _bounds_rect(current.get("bounds") or "")
            if rect is not None:
                return rect
        current = parent_of.get(current)
    return _bounds_rect(target.get("bounds") or "")


def preferred_tap_rect(
    source: str, by: str, value: str
) -> Optional[Dict[str, int]]:
    """Tap target for Picasso labels, shrinking oversized card ancestors.

    2026-09-21 shop draft card: 「完善评价」 is a non-clickable TextView
    whose nearest clickable ancestor is the full-width card
    ``[0,1447][1080,1664]``. The card centre misses the orange button;
    tap the label bounds instead when the ancestor is far larger.
    """
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return clickable_ancestor_rect(source, by, value)
    target = None
    for node in root.iter("node"):
        if _node_matches_selector(node, by, value):
            target = node
            break
    if target is None:
        return None
    label = _bounds_rect(target.get("bounds") or "")
    ancestor = clickable_ancestor_rect(source, by, value)
    if label is None:
        return ancestor
    if ancestor is None:
        return label
    if label["width"] >= 400:
        # A wide label is a control surface in its own right (the home search
        # bar spans [25,186][1055,286]). Its padded app-bar ancestor starts at
        # the status bar, so the ancestor centre lands on dead chrome and the
        # gesture is swallowed (live 2026-09-23).
        return label
    too_wide = ancestor["width"] > max(700, label["width"] * 2)
    too_tall = ancestor["height"] > max(400, label["height"] * 3)
    if too_wide or too_tall:
        return label
    return ancestor


def shop_result_candidates(shop_name: str, configured: Any) -> Tuple[str, ...]:
    """Search-result row locators, name-anchored first.

    2026-09-23 live: this build renders a search-result row as a clickable
    card around the shop-name TextView; no node carries the configured
    「店铺」 description, and the card centre lands on a deal tile. Anchoring
    on the shop name text keeps the wait and the tap on the row header.
    """
    candidates: List[str] = []
    name = str(shop_name or "").strip()
    if name:
        candidates.append('uiautomator:new UiSelector().textContains("%s")' % name)
    if configured is not None:
        candidates.extend(as_selector_list(configured))
    return tuple(candidates)


# Resource-id fragments that mark the search toolbar instead of a result row.
_SEARCH_HEADER_RID_TOKENS = ("search_header", "search_view", "search_keyword")


def shop_row_tap_rect(source: str, shop_name: str) -> Optional[Dict[str, int]]:
    """Tap target for the search-result row, never the header query box.

    The results page keeps the typed query in its search header, so a plain
    ``textContains(shop_name)`` matches the toolbar before any result row and
    the tap reopens the suggestion page (live 2026-09-23). Skip every match
    that lives under the search header or is an EditText, and prefer an exact
    name over a partial one.
    """
    name = str(shop_name or "").strip()
    if not source or not name:
        return None
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return None
    parent_of: Dict[ET.Element, ET.Element] = {}
    for node in root.iter():
        for child in list(node):
            parent_of[child] = node

    def _row_rect(node: ET.Element) -> Optional[Dict[str, int]]:
        chain: List[ET.Element] = []
        current: Optional[ET.Element] = node
        while current is not None:
            chain.append(current)
            current = parent_of.get(current)
        for ancestor in chain:
            rid = ancestor.get("resource-id") or ""
            if any(token in rid for token in _SEARCH_HEADER_RID_TOKENS):
                return None
        if (node.get("class") or "").endswith("EditText"):
            return None
        # Tap the name label, not the clickable card: the card spans the
        # whole entry and its centre lands on a deal tile (live 2026-09-23);
        # the row header is the proven shop-page entry.
        label = _bounds_rect(node.get("bounds") or "")
        if label is not None:
            return label
        for ancestor in chain:
            if (ancestor.get("clickable") or "").lower() == "true":
                rect = _bounds_rect(ancestor.get("bounds") or "")
                if rect is not None:
                    return rect
        return None

    for exact in (True, False):
        for node in root.iter("node"):
            text = node.get("text") or ""
            if (text == name) if exact else (name in text):
                rect = _row_rect(node)
                if rect is not None:
                    return rect
    return None


def shop_page_has_review_entry(source: str, shop_name: str) -> bool:
    """True when the restored shop page already shows a review CTA."""
    if not source or not shop_name:
        return False
    if shop_name not in source:
        return False
    return any(
        label in source for label in ("完善评价", "编辑评价", "写评价")
    )


_PENDING_CTA_LABELS = ("评价", "写评价", "评价订单")


def pending_review_row_rect(
    source: str, shop_name: str
) -> Optional[Dict[str, int]]:
    """Tap target for a 待评价 row's review CTA on the pending list.

    The list can show several orders, so a tap must be anchored to the
    target shop: find the shop-name label whose vertical band contains an
    评价-family button and return that button's rect (never the shop label
    itself — tapping the row body opens the order/shop page, not the
    editor). Exact name matches win over partial ones.
    """
    name = str(shop_name or "").strip()
    if not source or not name:
        return None
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return None

    ctas: List[Tuple[Dict[str, int], str]] = []
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        if not text:
            continue
        if any(text == label or (label != "评价" and label in text)
               for label in _PENDING_CTA_LABELS):
            rect = _bounds_rect(node.get("bounds") or "")
            if rect is not None:
                ctas.append((rect, text))
    if not ctas:
        return None

    for exact in (True, False):
        name_rect = None
        for node in root.iter("node"):
            text = (node.get("text") or "").strip()
            if (text == name) if exact else (bool(text) and name in text):
                candidate = _bounds_rect(node.get("bounds") or "")
                if candidate is not None:
                    name_rect = candidate
                    break
        if name_rect is None:
            continue
        name_mid = name_rect["y"] + name_rect["height"] / 2
        best: Optional[Tuple[Dict[str, int], int]] = None
        for rect, _text in ctas:
            cta_mid = rect["y"] + rect["height"] / 2
            if abs(cta_mid - name_mid) <= max(name_rect["height"], rect["height"]):
                distance = abs(cta_mid - name_mid)
                if best is None or distance < best[1]:
                    best = (rect, distance)
        if best is not None:
            return best[0]
    return None


def review_editor_is_open(source: str) -> bool:
    """True when Dianping is already on the Picasso review editor.

    2026-09-21 live: a failed rate left DPPicassoBoxActivity restored on
    relaunch. That page has 添加图/视频 / 已写N个字 / 取消 / 完成 and does
    not have 写评价. Searching from there types into the wrong field.
    """
    if not source:
        return False
    if "添加图/视频" in source:
        return True
    return "已写" in source and "个字" in source


# The overall bar's five graded labels (2026-09-23 live editor).
_OVERALL_RATING_LABELS = ("很糟糕", "较差", "一般", "还可以", "很棒", "超预期")
_DIMENSION_RATING_LABELS = ("口味", "环境", "服务")


def editor_has_dimension_rows(source: str) -> bool:
    """True when the editor exposes per-dimension rows (口味/环境/服务).

    The 2026-09-23 live editor shows only the overall bar; older builds also
    render 口味/环境/服务 rows. When they are absent, a dimension rate has
    nothing to anchor on and the step should be skipped, not failed.
    """
    try:
        root = ET.fromstring(source)
    except (ET.ParseError, TypeError):
        return False
    dims = set(_DIMENSION_RATING_LABELS)
    return any(
        (node.get("text") or "").strip() in dims for node in root.iter("node")
    )



def overall_rating_bar_visible(source: str) -> bool:
    """True when the 很糟糕..超预期 overall bar is in the tree.

    Same-day overwrite (完善评价 / 编辑评价) keeps the previous stars and
    never inflates that bar (live 2026-09-21). 口味/环境/服务 on that
    chrome are topic chips, not dimension rows.
    """
    if not source:
        return False
    return any(label in source for label in _OVERALL_RATING_LABELS)


# The overall card (2026-09-23 live editor): the five caption labels
# (很糟糕..很棒) at y~250-293 are dead text — tapping one changes nothing. The
# real control is the row of five star ImageViews below them (y~295-420),
# one full-card clickable region that maps x to a star. Tapping the Nth
# star's centre rates and expands the card to reveal 口味/环境/服务.
#
# Each caption also carries its own small ImageView icon on the caption
# line, so "a row of five images near the captions" is ambiguous: on the
# 2026-09-23 device the icon row sits at cy 271.5 and the star row at 357.5.
# The star row is the topmost five-image row whose centre is BELOW the
# caption text (captions bottom y=292 excludes the icons; the dimension
# strips at 511.5/635.5/759.5 are lower still and never the topmost).
_OVERALL_STAR_ROW_MIN_MEMBERS = 5
# The star strip sits ~65px under the captions; a five-image row much
# further down is a dimension strip or unrelated art, not the overall bar.
_OVERALL_STAR_ROW_MAX_DROP_PX = 200.0
# A dimension row's stars are vertically centred on its label's text line
# (2026-09-23 live: 口味 label y 491-533, stars cy 511.5).
_DIMENSION_STAR_ROW_Y_TOLERANCE_PX = 45.0
# The bands and config constants were measured on a 1080px-wide device
# (OnePlus 7T). Dumps carry the real screen width on the <hierarchy> root,
# so pixel tolerances scale with it instead of silently assuming 1080px.
_GEOMETRY_REFERENCE_WIDTH_PX = 1080.0


def _hierarchy_root(source: str) -> Optional[ET.Element]:
    """Parse a dump, returning None for empty or malformed input."""
    if not source:
        return None
    try:
        return ET.fromstring(source)
    except (ET.ParseError, TypeError):
        return None


def _screen_width_from_source(source: str) -> Optional[int]:
    root = _hierarchy_root(source)
    if root is None:
        return None
    try:
        width = int(root.get("width") or "")
    except (TypeError, ValueError):
        return None
    return width or None


def device_geometry_scale(source: str) -> float:
    """Scale for pixel geometry on the dump's device (1.0 at 1080px width)."""
    width = _screen_width_from_source(source)
    if not width:
        return 1.0
    return width / _GEOMETRY_REFERENCE_WIDTH_PX


def _rect_midpoint(rect: Dict[str, int]) -> Tuple[int, int]:
    """Integer centre of a rect (floor midpoints, deterministic)."""
    return (
        rect["x"] + rect["width"] // 2,
        rect["y"] + rect["height"] // 2,
    )


def _image_view_rects(root: ET.Element) -> List[Dict[str, int]]:
    """Bounds of every ImageView in the dump, in document order."""
    rects: List[Dict[str, int]] = []
    for node in root.iter("node"):
        if not (node.get("class") or "").endswith("ImageView"):
            continue
        rect = _bounds_rect(node.get("bounds") or "")
        if rect is not None:
            rects.append(rect)
    return rects


def _row_groups(
    rects: List[Dict[str, int]], tolerance: float = 12.0
) -> List[Tuple[float, List[Dict[str, int]]]]:
    """Bucket rects into horizontal rows keyed by y-centre.

    Elements on one line are given as separate nodes in no particular
    order, so rows are recovered by clustering rather than trusted from
    the tree shape.
    """
    groups: List[Tuple[float, List[Dict[str, int]]]] = []
    for rect in sorted(rects, key=lambda r: r["y"] + r["height"] / 2):
        cy = rect["y"] + rect["height"] / 2
        for index, (group_cy, members) in enumerate(groups):
            if abs(group_cy - cy) <= tolerance:
                members.append(rect)
                groups[index] = (
                    sum(r["y"] + r["height"] / 2 for r in members) / len(members),
                    members,
                )
                break
        else:
            groups.append((cy, [rect]))
    return groups


def overall_star_row_rects(source: str) -> Tuple[Tuple[int, int], ...]:
    """(x, y) centres of the overall star row, left to right.

    Empty tuple when the star row isn't in the dump (keyboard covers the
    editor, the wrong page, offline fakes with no hierarchy).
    """
    root = _hierarchy_root(source)
    if root is None:
        return ()
    caption_bottom = 0
    for node in root.iter("node"):
        if (node.get("text") or "").strip() not in _OVERALL_RATING_LABELS:
            continue
        rect = _bounds_rect(node.get("bounds") or "")
        if rect is not None:
            caption_bottom = max(caption_bottom, rect["y"] + rect["height"])
    if caption_bottom <= 0:
        return ()
    scale = device_geometry_scale(source)
    candidates = [
        (cy, members)
        for cy, members in _row_groups(_image_view_rects(root), tolerance=12.0 * scale)
        if len(members) >= _OVERALL_STAR_ROW_MIN_MEMBERS
        # The caption icons sit on the caption line itself; the stars below it.
        and cy > caption_bottom - 1
        and cy <= caption_bottom + _OVERALL_STAR_ROW_MAX_DROP_PX * scale
    ]
    if not candidates:
        return ()
    _cy, members = min(candidates, key=lambda group: group[0])
    return tuple(sorted(_rect_midpoint(rect) for rect in members))


def dimension_star_row_rects(
    source: str, label_rect: Dict[str, int]
) -> Tuple[Tuple[int, int], ...]:
    """(x, y) centres of the five-star strip sharing a segment label's line.

    The 2026-09-23 live editor draws each dimension row (口味/环境/服务) as
    a label plus a strip of five star ImageViews centred on the label's text
    line, so the geometry is derived from the dump instead of the older
    measured constants (kept in config only as a fallback when the dump
    cannot supply the strip).
    """
    root = _hierarchy_root(source)
    if root is None or not label_rect:
        return ()
    tolerance = _DIMENSION_STAR_ROW_Y_TOLERANCE_PX * device_geometry_scale(source)
    low = label_rect["y"] - tolerance
    high = label_rect["y"] + label_rect["height"] + tolerance
    points = [
        _rect_midpoint(rect)
        for rect in _image_view_rects(root)
        if low <= rect["y"] + rect["height"] / 2 <= high
    ]
    points.sort(key=lambda point: point[0])
    return tuple(points)


def review_publish_chrome_visible(source: str) -> bool:
    """True when the editor bottom bar already shows 发布."""
    return bool(source) and "发布" in source


def review_ime_toolbar_visible(source: str) -> bool:
    """True when the Picasso IME toolbar (完成 next to 已写) is up."""
    return bool(source) and "完成" in source and "已写" in source


def should_skip_rating(source: str) -> bool:
    """Skip stars on same-day overwrite chrome that has no overall bar.

    Empty dumps must not skip: offline fakes have no hierarchy, and the
    rate path still has to exercise label geometry.
    """
    if overall_rating_bar_visible(source):
        return False
    return (
        review_editor_is_open(source)
        or review_publish_chrome_visible(source)
        or dish_edit_is_open(source)
    )


def dish_edit_is_open(source: str) -> bool:
    """True on the Picasso 识别菜品 / dish-edit sheet.

    2026-09-21 overwrite: tapping a leftover editor tile opens this
    preview instead of a delete confirm. 添加图/视频 is absent here.
    The leftover 「确认删除这张图片吗？」 sheet is still dish-edit.
    """
    if not source:
        return False
    return "识别菜品" in source or "确认删除这张图片吗" in source


def dish_edit_filmstrip_rects(source: str) -> List[Dict[str, int]]:
    """Attached thumbnails on the dish-edit filmstrip, excluding 上传照片."""
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return []
    rects: List[Dict[str, int]] = []
    seen = set()
    for node in root.iter("node"):
        if (node.get("clickable") or "").lower() != "true":
            continue
        if (node.get("content-desc") or "") == "上传照片":
            continue
        rect = _bounds_rect(node.get("bounds") or "")
        if rect is None:
            continue
        if not (1880 <= rect["y"] <= 2160):
            continue
        if not (80 <= rect["width"] <= 180 and 80 <= rect["height"] <= 180):
            continue
        key = (rect["x"], rect["y"], rect["width"], rect["height"])
        if key in seen:
            continue
        seen.add(key)
        rects.append(rect)
    rects.sort(key=lambda item: item["x"])
    return rects


def dish_edit_delete_confirm_rect(source: str) -> Optional[Dict[str, int]]:
    """Orange 「确认删除」 button bounds; never the dialog title.

    Live Picasso (2026-09-21): the title is 「确认删除这张图片吗？」 and the
    orange control is a clickable TextView whose text is exactly 「确认删除」
    at ``[568,1211][872,1324]``. Substring matching the dump would hit the
    title first and tap empty space, leaving the dialog up.
    """
    return preferred_tap_rect(source, "text", "确认删除")


def dish_edit_trash_rect(source: str) -> Optional[Dict[str, int]]:
    """Trash control on the dish-edit preview (right of 识别菜品)."""
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return None
    recognize = None
    for node in root.iter("node"):
        if (node.get("text") or "") == "识别菜品":
            recognize = _bounds_rect(node.get("bounds") or "")
            break
    if recognize is None:
        return None
    for node in root.iter("node"):
        if (node.get("clickable") or "").lower() != "true":
            continue
        if "ImageView" not in (node.get("class") or ""):
            continue
        rect = _bounds_rect(node.get("bounds") or "")
        if rect is None:
            continue
        if rect["x"] < 800:
            continue
        if abs(rect["y"] - recognize["y"]) > 80:
            continue
        return rect
    return None


def translate_uiautomator_selector(selector: Any) -> Optional[Tuple[str, str]]:
    """Translate a dianping locator string into a kit uia2 ``(by, value)`` pair.

    Supported forms: ``id:<resource-id>``, ``~description``, ``xpath:...``,
    bare ``//xpath``, plain text, and single-method UiSelector chains such as
    ``uiautomator:new UiSelector().text("确定")``. Returns ``None`` for
    constructs uiautomator2 cannot express (instance/childSelector/fromParent
    or multi-method chains) so callers can skip the candidate; a missing
    candidate is never an error because locator lists carry fallbacks.
    """
    if not isinstance(selector, str):
        return None
    text = selector.strip()
    if not text:
        return None
    if text.startswith("id:"):
        return ("id", text[3:].strip())
    if text.startswith("~"):
        return ("description", text[1:].strip())
    if text.startswith("xpath:"):
        return ("xpath", text[6:].strip())
    if text.startswith("//"):
        return ("xpath", text)
    if text.startswith("uiautomator:"):
        body = text[len("uiautomator:"):].strip()
        if "new UiSelector()" not in body:
            return None
        if any(token in body for token in _UIA2_UNSUPPORTED_TOKENS):
            return None
        matches = _UIA2_METHOD_RE.findall(body)
        if len(matches) != 1:
            return None
        method, argument = matches[0]
        mapped = _UIA2_METHOD_MAP.get(method)
        if mapped is None:
            return None
        return (mapped, argument)
    return ("text", text)


class DianpingUia2Session:
    """uiautomator2-backed DriverSession for dianping workflows.

    Delegates primitives and artifact capture to the kit ``adapters.uia2``
    session (imported lazily at factory time, never at module import, so the
    app stays importable without the kit adapter) and adds the dianping
    business actions: dialogs, search confirmation, and label-anchored
    rating (the 2026-09 editor exposes no stable star ids).
    """

    _SLIDER_GUARDED_ACTIONS = DianpingAppiumSession._SLIDER_GUARDED_ACTIONS

    def __init__(
        self,
        kit_session: Any,
        *,
        captcha_window_seconds: float = 0.0,
        slider_solver: Optional[Callable[[Any], Any]] = None,
    ):
        self._session = kit_session
        self.info = kit_session.info
        self.captcha_window_seconds = _coerce_number(
            "captcha_window_seconds", captcha_window_seconds, 0.0, minimum=0.0
        )
        self.slider_solver = slider_solver
        self._manual_window_active = False
        self._slider_guard_active = False

    def start(self) -> None:
        self._session.start()

    def stop(self) -> None:
        self._session.stop()

    def capture_artifact(self, artifact_type: str, name: str) -> ArtifactHandle:
        return self._session.capture_artifact(artifact_type, name)

    def _dump_failure(self, label: str) -> None:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(label))[:40] or "failure"
        stamp = str(int(time.time()))
        try:
            self.capture_artifact("screenshot", "fail-%s-%s.png" % (safe, stamp))
        except Exception:
            pass
        try:
            self.capture_artifact("page_source", "fail-%s-%s.xml" % (safe, stamp))
        except Exception:
            pass

    def execute_action(self, action_name: str, **kwargs: Any) -> ActionResult:
        started = time.time()
        print("[dianping-uia2] >> %s" % action_name, flush=True)
        try:
            result = self._run_action(action_name, kwargs)
        except ActionParameterError as exc:
            result = ActionResult(False, "%s: %s" % (action_name, exc))
        if result.success and action_name in self._SLIDER_GUARDED_ACTIONS:
            result = self._guard_slider(action_name, result, kwargs)
        print(
            "[dianping-uia2] << %s: %s (%.1fs)"
            % (action_name, "ok" if result.success else "FAIL", time.time() - started),
            flush=True,
        )
        if not result.success:
            print("[dianping-uia2] failure detail: %s" % result.message[:400], flush=True)
            self._dump_failure(action_name)
        return result

    def _run_action(self, action_name: str, kwargs: Dict[str, Any]) -> ActionResult:
        if action_name == "launch_app":
            result = self._session.execute_action("launch_app", **kwargs)
            if result.success:
                self._ensure_screen_on()
                time.sleep(_numeric_parameter(kwargs, "settle_seconds", 2.0, minimum=0.0))
            return result
        if action_name == "dismiss_dialogs":
            return self._dismiss_dialogs(**kwargs)
        if action_name == "confirm_search":
            return self._confirm_search(**kwargs)
        if action_name == "navigate_to_review_editor":
            return self._navigate_to_review_editor(**kwargs)
        if action_name == "hide_keyboard":
            return self._hide_keyboard(**kwargs)
        if action_name == "rate":
            return self._rate(**kwargs)
        if action_name == "element_bounds":
            return self._element_bounds(**kwargs)
        if action_name == "pick_photos":
            return self._pick_photos_uia2(**kwargs)
        if action_name == "tap":
            result = self._tap_with_clickable_parent(kwargs)
        elif action_name == "type_text":
            if dish_edit_is_open(self._hierarchy_source()):
                return ActionResult(True, "type_text skipped; dish-edit already has copy")
            result = self._with_translated_candidates(action_name, kwargs)
        elif action_name == "wait_for_element":
            result = self._with_translated_candidates(action_name, kwargs)
        else:
            result = self._session.execute_action(action_name, **kwargs)
        if (
            not result.success
            and action_name in {"tap", "type_text", "wait_for_element"}
            and self.captcha_window_seconds > 0
            and not self._manual_window_active
        ):
            result = self._retry_after_manual_window(action_name, kwargs, result)
        return result

    def _guard_slider(self, action_name: str, result: ActionResult, kwargs: Dict[str, Any]) -> ActionResult:
        """Detect a risk-control slider that appeared during an action.

        Mirrors the Appium session guard; uia2 exposes the same uiautomator
        hierarchy XML and a coordinate swipe, so detection and solve rules are
        shared rather than reimplemented.
        """
        if self._slider_guard_active:
            return result
        if not page_source_indicates_slider(self._hierarchy_source()):
            return result
        self._slider_guard_active = True
        try:
            solve = self._attempt_slider_solve()
            if not solve.success:
                return ActionResult(
                    False,
                    "slider challenge detected during %s; %s" % (action_name, solve.message),
                )
            retry = self.execute_action(action_name, **kwargs)
            if not retry.success:
                return ActionResult(
                    False,
                    "slider solved but %s retry failed: %s" % (action_name, retry.message),
                )
            return ActionResult(True, "%s (slider solved; action retried)" % action_name)
        finally:
            self._slider_guard_active = False

    def _attempt_slider_solve(self) -> ActionResult:
        if self.slider_solver is None:
            return ActionResult(
                False,
                "no slider solver configured; rerun with --enable-slidex "
                "(requires slidex android_screenshot_bytes slider support)",
            )
        try:
            image = self._slider_screenshot_bytes()
            solution = self.slider_solver(image)
            if inspect.isawaitable(solution):
                solution = _await_in_worker_thread(solution)
        except Exception as exc:
            return ActionResult(False, "slider solve errored: %s" % exc)
        params, error = _slider_solution_params(solution)
        if error is not None:
            return error
        return self._perform_slider_swipe(**params)

    def _slider_screenshot_bytes(self) -> bytes:
        driver = getattr(self._session, "driver", None)
        capture = getattr(driver, "screenshot", None) if driver is not None else None
        if not callable(capture):
            raise RuntimeError("u2 driver cannot capture screenshots")
        image = capture()
        if isinstance(image, (bytes, bytearray)):
            return bytes(image)
        save = getattr(image, "save", None)
        if not callable(save):
            raise RuntimeError("u2 screenshot is neither bytes nor a saveable image")
        buffer = io.BytesIO()
        save(buffer, format="PNG")
        return buffer.getvalue()

    def _perform_slider_swipe(
        self,
        *,
        gap_x: Any = None,
        offset_px: Any = None,
        scale: float = 1.0,
    ) -> ActionResult:
        handle = locate_slider_handle(self._hierarchy_source())
        if handle is None:
            return ActionResult(False, "slider handle not located in page source")
        driver = getattr(self._session, "driver", None)
        swipe = getattr(driver, "swipe", None) if driver is not None else None
        if not callable(swipe):
            return ActionResult(False, "driver does not support coordinate swipe")
        distance, error = _slider_drag_distance(handle[0], gap_x, offset_px, scale)
        if error is not None:
            return error
        start_x, start_y = handle
        try:
            # u2's swipe duration is in seconds, not Appium's milliseconds.
            swipe(int(start_x), int(start_y), int(start_x + distance), int(start_y), 0.6)
        except Exception as exc:
            return ActionResult(False, "slider swipe failed: %s" % exc)
        return ActionResult(True, "slider swiped %d px" % distance)

    def _with_translated_candidates(
        self, action_name: str, kwargs: Dict[str, Any]
    ) -> ActionResult:
        """Run a selector action over all translated candidates in order.

        SelectorValue tuples carry fallbacks (e.g. the new search bar id,
        then ~搜索, then legacy ids); each string candidate is translated
        into the kit ``by`` vocabulary and tried until one succeeds.

        Page transitions race the lookup (u2 resolves lazily, so an instant
        wait_for_element hit can go stale before the action runs), so a
        missing-element failure is retried once after a short settle.
        """
        selector = kwargs.get("selector")
        candidates = as_selector_list(selector) if selector is not None else []
        errors = []
        for attempt in range(2):
            for candidate in candidates:
                translated = translate_uiautomator_selector(candidate)
                if translated is None:
                    if attempt == 0:
                        errors.append("%s: untranslatable" % candidate)
                    continue
                by, value = translated
                call_kwargs = dict(kwargs)
                call_kwargs["selector"] = value
                call_kwargs["by"] = by
                result = self._session.execute_action(action_name, **call_kwargs)
                if result.success:
                    return result
                errors.append("%s: %s" % (candidate, result.message))
            if attempt == 0 and candidates:
                time.sleep(2.0)
        if not candidates:
            return self._session.execute_action(action_name, **kwargs)
        return ActionResult(
            False,
            "%s failed for all selectors: %s" % (action_name, " | ".join(errors)),
        )

    def _tap_with_clickable_parent(self, kwargs: Dict[str, Any]) -> ActionResult:
        """Tap a Picasso chrome label via its clickable ancestor.

        Kit tap on the TextView reports success (u2 click is just a gesture at
        the label bounds) but the 2026-09 shop/editor chrome never receives it:
        「写评价」 and 「添加图/视频」 are ``clickable=false``. The nearest
        clickable FrameLayout is the real control. Fall back to a normal kit
        tap when hierarchy dump is unavailable (offline fakes).
        """
        selector = kwargs.get("selector")
        candidates = as_selector_list(selector) if selector is not None else []
        driver = getattr(self._session, "driver", None)
        dump = getattr(driver, "dump_hierarchy", None) if driver is not None else None
        click = getattr(driver, "click", None) if driver is not None else None
        source = ""
        if callable(dump) and callable(click):
            try:
                dumped = dump()
            except Exception as exc:
                _log_swallowed("uia2 hierarchy dump for tap fallback", exc)
                dumped = ""
            if isinstance(dumped, str):
                source = dumped
        if source:
            for candidate in candidates:
                translated = translate_uiautomator_selector(candidate)
                if translated is None:
                    continue
                by, value = translated
                rect = preferred_tap_rect(source, by, value)
                if rect is None:
                    continue
                x = rect["x"] + rect["width"] // 2
                y = rect["y"] + rect["height"] // 2
                try:
                    click(int(x), int(y))
                    return ActionResult(
                        True,
                        "tap clickable parent at (%d, %d)" % (int(x), int(y)),
                        data={"x": int(x), "y": int(y), "selector": value},
                    )
                except Exception as exc:
                    return ActionResult(
                        False, "clickable-parent tap failed: %s" % exc
                    )
        return self._with_translated_candidates("tap", kwargs)

    def _tap_shop_row(self, shop_name: str, fallback_selector: Any) -> ActionResult:
        """Tap the search-result row, steering clear of the header query box.

        The results page shows the typed query in its search header, which
        matches the same textContains selector as the row; a plain label tap
        lands on the toolbar and reopens the suggestion page (live 2026-09-23).
        """
        rect = shop_row_tap_rect(self._dump_source(), shop_name)
        if rect is not None:
            x = rect["x"] + rect["width"] // 2
            y = rect["y"] + rect["height"] // 2
            click = getattr(self._session.driver, "click", None)
            if callable(click):
                try:
                    click(int(x), int(y))
                    return ActionResult(
                        True,
                        "tap shop row at (%d, %d)" % (int(x), int(y)),
                        data={"x": int(x), "y": int(y)},
                    )
                except Exception as exc:
                    return ActionResult(False, "shop row tap failed: %s" % exc)
        return self._tap_with_clickable_parent({"selector": fallback_selector})

    def _wait_for_shop_row(self, shop_name: str, timeout: float) -> ActionResult:
        """Poll until a real result-row card exists on the results page.

        The header query box also contains the shop name, so a plain text
        wait is satisfied before the row renders and the tap then misses
        (live 2026-09-23); gate on the same header-immune rect both waits
        and taps use.
        """
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            if shop_row_tap_rect(self._dump_source(), shop_name) is not None:
                return ActionResult(True, "shop result row present")
            time.sleep(0.5)
        return ActionResult(
            False,
            "timed out waiting for shop result row (%.1fs)" % float(timeout),
        )

    def _wait_for_picker(self, timeout: float = 8.0) -> bool:
        deadline = time.time() + max(timeout, 0.1)
        while time.time() < deadline:
            if self._picker_is_open():
                return True
            time.sleep(0.4)
        return self._picker_is_open()

    def _picker_is_open(self) -> bool:
        """True only when photo tiles are actually in the tree.

        下一步 chrome can inflate before ``photo_imageView``; treating the
        label as "open" raced a half-drawn sheet and then confirmed nothing.
        """
        if self._uia2_widget_exists("id", _PHOTO_SELECT_RESOURCE_ID):
            return True
        if self._uia2_widget_exists("id", _PHOTO_IMAGE_RESOURCE_ID):
            return True
        driver = getattr(self._session, "driver", None)
        dump = getattr(driver, "dump_hierarchy", None) if driver is not None else None
        if not callable(dump):
            return False
        try:
            source = dump()
        except Exception as exc:
            # A broken dump means "cannot see any tiles", so report the picker
            # as closed rather than risk tapping a half-drawn sheet; the log
            # keeps a live run diagnosable.
            _log_swallowed("uia2 picker dump", exc)
            return False
        if not isinstance(source, str):
            return False
        return (
            _PHOTO_SELECT_RESOURCE_ID in source
            or _PHOTO_IMAGE_RESOURCE_ID in source
        )

    def _hierarchy_source(self) -> str:
        return self._dump_source()

    def _wait_for_marker(self, candidates: Any, timeout: float) -> ActionResult:
        """Poll the live hierarchy until a candidate node really exists.

        The kit uia2 wait resolves selectors lazily and reports success
        without touching the tree, so a page transition races the next tap
        and the flow types/taps on the page it just left (live 2026-09-23).
        """
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            source = self._hierarchy_source()
            try:
                root = ET.fromstring(source) if source else None
            except (ET.ParseError, TypeError):
                root = None
            for candidate in as_selector_list(candidates) if candidates is not None else []:
                translated = translate_uiautomator_selector(candidate)
                if translated is None:
                    continue
                by, value = translated
                if root is not None and any(
                    _node_matches_selector(node, by, value) for node in root.iter("node")
                ):
                    return ActionResult(True, "marker present: %s" % value)
            time.sleep(0.5)
        return ActionResult(
            False, "timed out waiting for page marker (%.1fs)" % float(timeout)
        )

    def _navigate_to_review_editor(self, **kwargs: Any) -> ActionResult:
        """Open the review editor from home search or a restored shop page.

        2026-09-21 live: launching Dianping restored PexusPoiActivity on the
        target shop. The workflow then typed into the shop-page 搜索栏 and
        failed because search_keyword_edit is not on that page.
        """
        shop_name = str(kwargs.get("shop_name") or "")
        write_selector = kwargs.get("write_selector")
        source = self._hierarchy_source()
        if not source:
            return ActionResult(
                False, "navigate_to_review_editor: empty hierarchy after wake"
            )
        if dish_edit_is_open(source):
            return ActionResult(True, "navigate_to_review_editor already in dish-edit")
        if review_editor_is_open(source):
            return ActionResult(True, "navigate_to_review_editor already in review editor")
        if shop_page_has_review_entry(source, shop_name):
            tap = self._tap_with_clickable_parent({"selector": write_selector})
            if tap.success:
                return ActionResult(
                    True, "navigate_to_review_editor via restored shop page"
                )
            return tap
        # Preferred entry (2026-10-16): the 我的 tab's 待评价 list — reviews
        # started there are tied to the actual order. Any miss (tab absent,
        # target shop not pending) backs out and falls through to the
        # home-search path below.
        pending = self._navigate_via_pending_review(shop_name)
        if pending.success:
            return pending
        print(
            "[dianping-uia2] navigate: pending-review entry unavailable (%s); "
            "falling back to search" % pending.message,
            flush=True,
        )
        # A relaunch can restore the app mid-search, sitting on the results
        # page that already shows the target row. The search-bar selectors are
        # not on that page and the kit wait/tap report success for absent
        # elements, so restarting the search would no-op and dead-end on the
        # input marker. Skip straight to the row tap when we are here.
        if self._results_page_open(source, shop_name, kwargs):
            print("[dianping-uia2] navigate: restored search results page", flush=True)
            return self._advance_from_search_results(shop_name, kwargs)
        wait = self._with_translated_candidates(
            "wait_for_element",
            {"selector": kwargs.get("search_bar"), "timeout": 10.0},
        )
        if not wait.success:
            # Warm starts can land on any page (live 2026-10-16: the 我的 tab
            # made this wait fail on all 8 search-bar selectors); BACK walks
            # toward home, where the search bar lives.
            recovered = self._back_to_home_search(kwargs)
            if not recovered.success:
                return wait
            print(
                "[dianping-uia2] navigate: BACK unwind reached home search",
                flush=True,
            )
        tap = self._tap_with_clickable_parent({"selector": kwargs.get("search_bar")})
        if not tap.success:
            return tap
        print("[dianping-uia2] navigate: search bar tapped (%s)" % tap.message, flush=True)
        wait = self._wait_for_marker(kwargs.get("search_input"), 8.0)
        if not wait.success:
            return wait
        print("[dianping-uia2] navigate: search page ready", flush=True)
        typed = self._with_translated_candidates(
            "type_text",
            {"selector": kwargs.get("search_input"), "text": shop_name},
        )
        if not typed.success:
            return typed
        confirmed = self._confirm_search(
            selector=kwargs.get("search_confirm"),
            keycode=66,
        )
        if not confirmed.success:
            return confirmed
        print("[dianping-uia2] navigate: search confirmed (%s)" % confirmed.message, flush=True)
        wait = self._wait_for_marker(kwargs.get("search_results_marker"), 12.0)
        if not wait.success:
            return wait
        print("[dianping-uia2] navigate: results page ready", flush=True)
        return self._advance_from_search_results(shop_name, kwargs)

    _PENDING_TAB = ('uiautomator:new UiSelector().text("我的")',)
    _PENDING_ENTRY = (
        'uiautomator:new UiSelector().textContains("待评价")',
        'uiautomator:new UiSelector().textContains("待点评")',
    )
    _PENDING_ROW_CTA = (
        'uiautomator:new UiSelector().text("评价")',
        'uiautomator:new UiSelector().text("写评价")',
        'uiautomator:new UiSelector().textContains("评价")',
    )
    _EDITOR_OPEN_MARKER = (
        'uiautomator:new UiSelector().textContains("添加图")',
        'uiautomator:new UiSelector().text("发布")',
    )

    def _marker_present_now(self, candidates: Any) -> bool:
        """True when a candidate already exists in the current hierarchy.

        The tap helpers fall back to a kit tap when the dump lookup misses,
        and that tap fires blind at the page it cannot see — so gating the
        pending-review path on this check keeps an absent 我的 tab from
        costing a stray click plus the marker wait.
        """
        source = self._hierarchy_source()
        if not source:
            return False
        try:
            root = ET.fromstring(source)
        except (ET.ParseError, TypeError):
            return False
        for candidate in as_selector_list(candidates) if candidates is not None else []:
            translated = translate_uiautomator_selector(candidate)
            if translated is None:
                continue
            by, value = translated
            if any(_node_matches_selector(node, by, value) for node in root.iter("node")):
                return True
        return False

    def _navigate_via_pending_review(self, shop_name: str) -> ActionResult:
        """Reach the review editor through 我的 → 待评价 → the shop's row CTA.

        Reviews opened from the pending list are tied to the actual order, so
        this entry is preferred over home search (2026-10-16). Every step
        waits on a real hierarchy marker; on any miss the page stack is
        unwound with BACK and a False result hands control back to the
        search-based path.
        """
        if not self._marker_present_now(self._PENDING_TAB):
            return ActionResult(False, "我的 tab not on the current page")
        tap = self._tap_with_clickable_parent({"selector": self._PENDING_TAB})
        if not tap.success:
            return ActionResult(False, "我的 tab not tapped: %s" % tap.message)
        wait = self._wait_for_marker(self._PENDING_ENTRY, 8.0)
        if not wait.success:
            self._press_back_quietly()
            return ActionResult(False, "待评价 entry not found on 我的 tab")
        tap = self._tap_with_clickable_parent({"selector": self._PENDING_ENTRY})
        if not tap.success:
            self._press_back_quietly()
            return ActionResult(False, "待评价 tap failed: %s" % tap.message)
        print("[dianping-uia2] navigate: pending-review list open", flush=True)

        # The pending list shows consumed orders, not necessarily the target
        # shop; only commit when the shop's row CTA is actually on screen.
        row = self._wait_for_pending_shop_row(shop_name, 8.0)
        if not row.success:
            self._press_back_quietly()
            return ActionResult(
                False, "shop not in pending list: %s" % shop_name
            )
        tap = self._tap_pending_shop_row(shop_name)
        if not tap.success:
            self._press_back_quietly()
            return tap
        print(
            "[dianping-uia2] navigate: pending row CTA tapped (%s)" % tap.message,
            flush=True,
        )
        opened = self._wait_for_marker(self._EDITOR_OPEN_MARKER, 15.0)
        if not opened.success:
            self._press_back_quietly()
            return ActionResult(
                False, "pending-review CTA did not open the editor"
            )
        return ActionResult(
            True, "navigate_to_review_editor via 我的/待评价",
            data={"shop": shop_name},
        )

    def _wait_for_pending_shop_row(self, shop_name: str, timeout: float):
        """Poll for the target shop's 评价 CTA inside the pending list.

        The CTA is a small button beside the shop row; requiring both the
        shop-name text and an评价-family button in the same window avoids
        tapping an评价 entry for a different order.
        """
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            source = self._hierarchy_source()
            rect = pending_review_row_rect(source, shop_name)
            if rect is not None:
                return ActionResult(
                    True,
                    "pending row ready",
                    data=dict(rect),
                )
            time.sleep(0.5)
        return ActionResult(False, "pending row not on screen: %s" % shop_name)

    def _tap_pending_shop_row(self, shop_name: str) -> ActionResult:
        driver = getattr(self._session, "driver", None)
        click = getattr(driver, "click", None) if driver is not None else None
        if not callable(click):
            return ActionResult(False, "no coordinate click available")
        source = self._hierarchy_source()
        rect = pending_review_row_rect(source, shop_name)
        if rect is None:
            return ActionResult(False, "pending row vanished before tap")
        x = rect["x"] + rect["width"] // 2
        y = rect["y"] + rect["height"] // 2
        try:
            click(int(x), int(y))
        except Exception as exc:
            return ActionResult(False, "pending row tap failed: %s" % exc)
        return ActionResult(
            True, "pending row CTA tap at (%d, %d)" % (int(x), int(y)),
            data={"x": int(x), "y": int(y)},
        )

    def _press_back_quietly(self) -> None:
        driver = getattr(self._session, "driver", None)
        press = getattr(driver, "press", None) if driver is not None else None
        if callable(press):
            try:
                press("back")
            except Exception as exc:
                _log_swallowed("uia2 press_back unwind", exc)
        time.sleep(0.8)

    def _back_to_home_search(self, kwargs: Dict[str, Any]) -> ActionResult:
        """BACK-unwind a warm start that landed on a non-home page.

        The search bar only exists on home, so a warm start elsewhere (live
        2026-10-16: the 我的 tab) hard-failed the search-bar wait. A couple of
        BACK presses reach home; the editor-chrome guard keeps a stray BACK
        from discarding an open editor.
        """
        source = self._hierarchy_source()
        if (
            review_editor_is_open(source)
            or dish_edit_is_open(source)
            or review_publish_chrome_visible(source)
        ):
            return ActionResult(False, "refusing BACK with editor chrome visible")
        for _ in range(2):
            self._press_back_quietly()
            wait = self._with_translated_candidates(
                "wait_for_element",
                {"selector": kwargs.get("search_bar"), "timeout": 6.0},
            )
            if wait.success:
                return wait
        return ActionResult(False, "home search bar not reached via BACK")

    def _results_page_open(
        self, source: str, shop_name: str, kwargs: Dict[str, Any]
    ) -> bool:
        """True when the current page is the search results list for the shop.

        Requires both the results chrome (the tab/description markers the
        suggestion page lacks) and the target row's tap rectangle, so a plain
        shop-name text match elsewhere can't route here by accident.
        """
        if not source:
            return False
        try:
            root = ET.fromstring(source)
        except (ET.ParseError, TypeError):
            return False
        markers = kwargs.get("search_results_marker")
        chrome = False
        for candidate in as_selector_list(markers) if markers is not None else []:
            translated = translate_uiautomator_selector(candidate)
            if translated is None:
                continue
            by, value = translated
            if any(_node_matches_selector(node, by, value) for node in root.iter("node")):
                chrome = True
                break
        return chrome and shop_row_tap_rect(source, shop_name) is not None

    def _advance_from_search_results(
        self, shop_name: str, kwargs: Dict[str, Any]
    ) -> ActionResult:
        """From an on-screen results page, tap the target row and open the
        review editor. Shared by the searched path and the restored-results
        path so both wait on the same real-rect checks."""
        write_selector = kwargs.get("write_selector")
        shop_result = shop_result_candidates(shop_name, kwargs.get("shop_result"))
        row = self._wait_for_shop_row(shop_name, 12.0)
        if not row.success:
            return row
        print("[dianping-uia2] navigate: shop row ready", flush=True)
        tap = self._tap_shop_row(shop_name, shop_result)
        if not tap.success:
            return tap
        print("[dianping-uia2] navigate: shop row tapped (%s)" % tap.message, flush=True)
        # The shop page can render slowly (live 2026-09-23: a 部分服务当前不可用
        # notice delayed the review CTA past 10s), so allow a generous wait.
        wait = self._wait_for_marker(write_selector, 25.0)
        if not wait.success:
            return wait
        print("[dianping-uia2] navigate: write CTA ready", flush=True)
        tap = self._tap_with_clickable_parent({"selector": write_selector})
        if not tap.success:
            return tap
        print("[dianping-uia2] navigate: write CTA tapped (%s)" % tap.message, flush=True)
        opened = self._wait_for_marker(
            (
                'uiautomator:new UiSelector().textContains("添加图")',
                'uiautomator:new UiSelector().text("发布")',
            ),
            15.0,
        )
        if not opened.success:
            return ActionResult(
                False,
                "navigate_to_review_editor: write tap did not open the editor",
            )
        return ActionResult(True, "navigate_to_review_editor via search")

    def _confirm_search(self, **kwargs: Any) -> ActionResult:
        selector = kwargs.get("selector")
        candidates = as_selector_list(selector) if selector is not None else []
        # Prefer a coordinate tap on the live button. A kit tap on the
        # suggestion page's 搜索 TextView resolves lazily and reports success
        # while the app stays on SearchIndexActivity (live 2026-09-23), so the
        # results wait then times out with the keyword still in the box.
        driver = getattr(self._session, "driver", None)
        dump = getattr(driver, "dump_hierarchy", None) if driver is not None else None
        click = getattr(driver, "click", None) if driver is not None else None
        source = ""
        if callable(dump) and callable(click):
            try:
                dumped = dump()
            except Exception as exc:
                _log_swallowed("uia2 hierarchy dump for tap fallback", exc)
                dumped = ""
            if isinstance(dumped, str):
                source = dumped
        if source:
            for candidate in candidates:
                translated = translate_uiautomator_selector(candidate)
                if translated is None:
                    continue
                by, value = translated
                rect = preferred_tap_rect(source, by, value)
                if rect is None:
                    continue
                x = rect["x"] + rect["width"] // 2
                y = rect["y"] + rect["height"] // 2
                try:
                    click(int(x), int(y))
                    return ActionResult(
                        True,
                        "confirm_search tap at (%d, %d)" % (int(x), int(y)),
                        data={"x": int(x), "y": int(y), "selector": value},
                    )
                except Exception as exc:
                    return ActionResult(False, "confirm_search tap failed: %s" % exc)
        for candidate in candidates:
            translated = translate_uiautomator_selector(candidate)
            if translated is None:
                continue
            by, value = translated
            result = self._session.execute_action("tap", selector=value, by=by)
            if result.success:
                return result
        # ENTER fallback: the kit uia2 adapter passes unknown actions to the
        # uiautomator2 device, which exposes press_key.
        press = getattr(self._session.driver, "press_key", None)
        if callable(press):
            keycode = kwargs.get("keycode")
            if isinstance(keycode, bool) or not isinstance(keycode, (int, float)):
                return ActionResult(False, "confirm_search keycode must be numeric")
            press_result = self._session.execute_action("press_key", int(keycode))
            if press_result.success:
                return ActionResult(True, "confirm_search via keycode")
        return ActionResult(False, "confirm_search failed for all selectors")

    def _hide_keyboard(self, **kwargs: Any) -> ActionResult:
        """Dismiss the IME so the overall rating bar is visible.

        2026-09-21 editor: type_text leaves the keyboard covering 超预期.
        Prefer the Picasso toolbar 「完成」; fall back to BACK.
        Once 发布 is already on screen, BACK would leave the editor.
        """
        source = self._hierarchy_source()
        if dish_edit_is_open(source) or (
            review_publish_chrome_visible(source) and not review_ime_toolbar_visible(source)
        ):
            return ActionResult(True, "hide_keyboard skipped; editor chrome visible")
        tap = self._tap_with_clickable_parent(
            {
                "selector": (
                    'uiautomator:new UiSelector().text("完成")',
                    "~完成",
                )
            }
        )
        if tap.success:
            time.sleep(0.4)
            return ActionResult(True, "hide_keyboard via 完成")
        press = getattr(self._session.driver, "press", None) or getattr(
            self._session.driver, "press_key", None
        )
        if callable(press):
            try:
                press("back")
                time.sleep(0.4)
                return ActionResult(True, "hide_keyboard via BACK")
            except Exception:
                try:
                    press(4)
                    time.sleep(0.4)
                    return ActionResult(True, "hide_keyboard via BACK")
                except Exception as exc:
                    return ActionResult(False, "hide_keyboard BACK failed: %s" % exc)
        return ActionResult(True, "hide_keyboard skipped")

    def _label_rect_from_source(
        self, candidates: List[str], source: Optional[str] = None
    ) -> Optional[Dict[str, int]]:
        """Resolve a rating label's geometry from the live hierarchy dump.

        Our own dump is preferred: ``preferred_tap_rect`` yields the exact
        node rectangle with no extra round trip, and it is the path proven on
        the 2026-09-23 device. The kit ``element_bounds`` action is the
        fallback for when no hierarchy is available (offline fakes, a failed
        dump); it reads the element snapshot, so it answers correctly as long
        as the driver can resolve the selector.
        """
        if source is None:
            source = self._hierarchy_source()
        if source:
            for candidate in candidates:
                translated = translate_uiautomator_selector(candidate)
                if translated is None:
                    continue
                by, value = translated
                rect = preferred_tap_rect(source, by, value)
                if rect is not None:
                    return rect
        for candidate in candidates:
            translated = translate_uiautomator_selector(candidate)
            if translated is None:
                continue
            by, value = translated
            result = self._session.execute_action(
                "element_bounds", selector=value, by=by
            )
            if result.success and isinstance(result.data, dict):
                return result.data
        return None

    def _rate(self, **kwargs: Any) -> ActionResult:
        source = self._hierarchy_source()
        if should_skip_rating(source):
            return ActionResult(
                True,
                "rate skipped; overall bar not on overwrite chrome",
                data={"dimension": kwargs.get("dimension"), "value": kwargs.get("value")},
            )
        anchor = kwargs.get("anchor")
        if anchor not in {"overall", "dimension_row"}:
            return ActionResult(False, "uia2 rate requires a label anchor")
        selector = kwargs.get("selector")
        candidates = as_selector_list(selector) if selector is not None else []
        try:
            numeric_value = int(kwargs.get("value"))
        except (TypeError, ValueError):
            return ActionResult(False, "rate requires a numeric value")
        if not 1 <= numeric_value <= 5:
            return ActionResult(False, "rating value must be 1-5")
        # Overall bar: a row of five star ImageViews under dead caption labels
        # (很糟糕..很棒 are not touch targets). The star row is one clickable
        # region bucketed by x; tap the Nth star centre, read from the dump
        # (2026-09-23 live). The caption selector is carried by the caller but
        # only needed as a fallback when the star row cannot be parsed.
        if anchor == "overall":
            stars = overall_star_row_rects(source)
            if len(stars) < numeric_value:
                hidden = self._hide_keyboard()
                if hidden.success:
                    source = self._hierarchy_source()
                    stars = overall_star_row_rects(source)
            if len(stars) < numeric_value:
                return ActionResult(False, "overall rating bar not found on uia2")
            x, y = stars[numeric_value - 1]
            try:
                result = self._session.execute_action(
                    "swipe",
                    start_x=x,
                    start_y=y,
                    end_x=x,
                    end_y=y,
                    duration=0.08,
                )
            except Exception as exc:
                return ActionResult(False, "uia2 overall rate failed: %s" % exc)
            if not result.success:
                return result
            return ActionResult(
                True, "uia2 overall rating set (%d star)" % numeric_value
            )
        # Dimension rows (口味/环境/服务): a 5-star strip on the row label's
        # line. Resolve the row label's bounds, then prefer the star strip's
        # own geometry from the dump; fall back to the measured strip
        # constants only when the dump cannot supply it.
        label_rect = self._label_rect_from_source(candidates, source)
        if label_rect is None:
            if not editor_has_dimension_rows(source):
                return ActionResult(
                    True,
                    "dimension rate skipped; editor has no %s row"
                    % kwargs.get("dimension"),
                    data={
                        "dimension": kwargs.get("dimension"),
                        "value": kwargs.get("value"),
                    },
                )
            return ActionResult(False, "dimension rating label not found on uia2")
        stars = dimension_star_row_rects(source, label_rect)
        if len(stars) >= numeric_value:
            x, y = stars[numeric_value - 1]
        else:
            from automation_app_dianping.config import default_selectors

            selectors = default_selectors()
            # Older editors' measured strip: first star centre 236, pitch 144
            # (scaled to the dump's real screen width).
            scale = device_geometry_scale(source)
            x = int(
                (
                    selectors.rating_dim_star_origin_px
                    + selectors.rating_dim_star_pitch_px * (numeric_value - 1)
                )
                * scale
            )
            y = int(label_rect["y"] + label_rect["height"] / 2)
        try:
            result = self._session.execute_action(
                "swipe",
                start_x=x,
                start_y=y,
                end_x=x,
                end_y=y,
                duration=0.08,
            )
        except Exception as exc:
            return ActionResult(False, "uia2 rate swipe failed: %s" % exc)
        if not result.success:
            return result
        return ActionResult(True, "uia2 star tapped at (%d, %d)" % (x, y))

    def _element_bounds(self, **kwargs: Any) -> ActionResult:
        selector = kwargs.get("selector")
        for candidate in as_selector_list(selector) if selector is not None else []:
            translated = translate_uiautomator_selector(candidate)
            if translated is None:
                continue
            by, value = translated
            result = self._session.execute_action(
                "element_bounds", selector=value, by=by
            )
            if result.success:
                return result
        return ActionResult(False, "element_bounds failed for all selectors")

    def _pick_photos_uia2(self, **kwargs: Any) -> ActionResult:
        """Attach review photos on the 2026-09 editor.

        Each photo must be a host-side file path. It is staged into an isolated
        ``DianpingAuto`` album (not Camera / 最近项目): Picasso's 最近项目 mix
        is not MediaStore datetaken order, and Camera tile 0 is a private
        family photo (observed 2026-09-21). Same-day 编辑评价 keeps leftover
        thumbnails from the previous publish; those are cleared first so the
        new review is only the staged file. After add, the picker must switch
        to that album before any checkbox tap; selecting instance 0 on
        最近项目 attaches a downloads/lab image. Then the first
        ``len(photos)`` checkboxes in that album are selected and confirmed.
        """
        photos = kwargs.get("photos") or []
        if not photos:
            return ActionResult(True, "pick_photos: nothing to attach")
        # Stage oldest first so each push is indexed-first at its moment,
        # and photos[0] (newest EXIF) lands as picker photo-tile 0.
        count = len(photos)
        for rank in range(count - 1, -1, -1):
            prep = self._prepare_gallery_photo(str(photos[rank]), recency_rank=rank)
            if not prep.success:
                return ActionResult(
                    False,
                    "pick_photos: gallery prep failed for %s: %s"
                    % (photos[rank], prep.message),
                )
        cleared = self._clear_existing_editor_photos()
        if not cleared.success:
            return cleared
        after_editor = self._dump_source()
        if dish_edit_is_open(after_editor) or dish_edit_delete_confirm_rect(after_editor):
            extra = self._clear_dish_edit_photos()
            if not extra.success:
                return extra
        opened = self._open_photo_picker(kwargs.get("add_selector"))
        if not opened.success:
            return opened
        switched = self._switch_to_staging_album()
        if not switched.success:
            return switched
        if not self._header_album_is(self._GALLERY_ALBUM):
            return ActionResult(
                False,
                "pick_photos: refused to select outside %s" % self._GALLERY_ALBUM,
            )
        # Live 2026-10-16: the first tile tap right after the album switch did
        # not stick; give the grid a beat to settle before selecting.
        time.sleep(0.4)
        thumb_selector = kwargs.get("thumbnail_selector")
        selected = 0
        for index in range(count):
            tap = self._pick_photo_tile(thumb_selector, index)
            if not tap.success:
                # Surface the per-tile reason (absent vs not-selected) instead
                # of discarding it behind a bare count.
                return ActionResult(
                    False,
                    "pick_photos: attached %d of %d photo tile(s): %s"
                    % (selected, count, tap.message),
                )
            selected += 1
            time.sleep(0.4)
        if selected != count:
            return ActionResult(
                False,
                "pick_photos: attached %d of %d photo tile(s)" % (selected, count),
            )
        confirm = self._confirm_picked_photos(kwargs.get("confirm_selector"))
        if not confirm.success:
            return confirm
        return ActionResult(
            True, "pick_photos: attached %d photo(s)" % selected
        )

    _GALLERY_DIR = "/sdcard/Pictures/DianpingAuto"
    _GALLERY_ALBUM = "DianpingAuto"
    _PUSH_PREFIX = "IMG99999999_"
    _ALBUM_DROPDOWN_CANDIDATES = (
        "最近项目",
        "Camera",
        "Pictures",
        "downloads",
        "Screenshots",
        "WeiXin",
    )

    def _clear_existing_editor_photos(self) -> ActionResult:
        """Remove leftover numbered thumbnails before attaching staged photos.

        Same-day 编辑评价 (2026-09-21) keeps the previous review's tiles.
        Tapping the thumbnail opens a preview whose 删除/移除 control
        actually drops it. The dump has no dedicated delete node on the
        editor itself, so we tap the badge tile's top-right (the × overlay
        on 2026-09 chrome) first, then any 删除/移除 that appears on the
        preview.

        Two guards keep this from deleting blind: the delete label is only
        tapped after the tile tap demonstrably changed the page (a tap that
        changes nothing never reaches a delete control), and at most
        ``_MAX_EDITOR_PHOTO_CLEARS`` tiles are removed per run. A numbered
        tile that remains fails the step with screenshot/page_source
        evidence — publishing leftovers would mix lab/ginkgo shots with the
        staged noodle.
        """
        driver = getattr(self._session, "driver", None)
        click = getattr(driver, "click", None) if driver is not None else None
        if not callable(click):
            return ActionResult(True, "clear editor photos: no click driver")
        removed = 0
        for _ in range(_MAX_EDITOR_PHOTO_CLEARS):
            source = self._dump_source()
            rects = editor_attached_photo_rects(source) if source else []
            if not rects:
                return ActionResult(
                    True, "cleared %d leftover editor photo(s)" % removed
                )
            rect = rects[0]
            corner_x = rect["x"] + max(rect["width"] - 18, rect["width"] * 3 // 4)
            corner_y = rect["y"] + min(18, max(rect["height"] // 8, 8))
            center_x = rect["x"] + rect["width"] // 2
            center_y = rect["y"] + rect["height"] // 2
            dropped = False
            for x, y in ((corner_x, corner_y), (center_x, center_y)):
                try:
                    click(int(x), int(y))
                except Exception as exc:
                    return ActionResult(
                        False, "clear editor photos: tile tap failed: %s" % exc
                    )
                time.sleep(0.6)
                after = self._dump_source() or ""
                if dish_edit_is_open(after):
                    return ActionResult(True, "leftover opened dish-edit")
                if not after or after == source:
                    # The tap hit nothing: never tap a delete control blind.
                    continue
                self._confirm_editor_photo_delete(after)
                remaining = editor_attached_photo_rects(self._dump_source() or "")
                if len(remaining) < len(rects):
                    dropped = True
                    break
            if not dropped:
                self._dump_failure("clear_editor_photos")
                return ActionResult(
                    False,
                    "clear editor photos: leftover tile did not drop "
                    "(still %d)" % len(rects),
                )
            removed += 1
        leftover = editor_attached_photo_rects(self._dump_source() or "")
        if leftover:
            self._dump_failure("clear_editor_photos")
            return ActionResult(
                False,
                "clear editor photos: %d tile(s) remain after the %d-photo cap"
                % (len(leftover), _MAX_EDITOR_PHOTO_CLEARS),
            )
        return ActionResult(True, "cleared %d leftover editor photo(s)" % removed)

    def _open_photo_picker(self, add_selector: Any) -> ActionResult:
        """Open the album picker from the editor or the dish-edit plus tile."""
        if dish_edit_is_open(self._dump_source()):
            add = self._tap_dish_edit_plus()
            if not add.success:
                return add
            if self._wait_for_picker(timeout=8.0):
                return ActionResult(True, "picker via dish-edit plus")
            return ActionResult(
                False, "pick_photos: dish-edit plus did not open picker"
            )
        for attempt in range(2):
            add = self._tap_with_clickable_parent({"selector": add_selector})
            if not add.success:
                return ActionResult(
                    False, "pick_photos: add button not found: %s" % add.message
                )
            if self._wait_for_picker(timeout=8.0):
                return ActionResult(True, "picker via add button")
            if attempt == 0:
                time.sleep(0.8)
        return ActionResult(False, "pick_photos: add button did not open picker")

    def _click_rect(self, rect: Dict[str, int]) -> ActionResult:
        driver = getattr(self._session, "driver", None)
        click = getattr(driver, "click", None) if driver is not None else None
        if not callable(click):
            return ActionResult(False, "no click driver")
        x = rect["x"] + rect["width"] // 2
        y = rect["y"] + rect["height"] // 2
        try:
            click(int(x), int(y))
        except Exception as exc:
            return ActionResult(False, "click failed: %s" % exc)
        return ActionResult(True, "clicked (%d, %d)" % (int(x), int(y)))

    def _clear_dish_edit_photos(self) -> ActionResult:
        """Delete every filmstrip thumbnail on the 识别菜品 sheet.

        Trash opens 「确认删除这张图片吗？」; the orange control is
        「确认删除」, not the toolbar 「确定」. A leftover dialog from a
        previous run is confirmed first so we do not tap through it.
        """
        removed = 0
        for _ in range(8):
            source = self._dump_source()
            if dish_edit_delete_confirm_rect(source) is not None:
                before = dish_edit_filmstrip_rects(source)
                confirmed = self._confirm_dish_edit_photo_delete()
                if not confirmed.success:
                    return confirmed
                if before:
                    dropped = self._wait_dish_edit_count_drop(len(before), timeout=3.0)
                    if not dropped:
                        remaining = dish_edit_filmstrip_rects(self._dump_source())
                        return ActionResult(
                            False,
                            "clear dish-edit photos: leftover tile did not drop "
                            "(still %d)" % len(remaining),
                        )
                removed += 1
                continue
            if not dish_edit_is_open(source):
                return ActionResult(
                    True, "cleared %d dish-edit photo(s)" % removed
                )
            rects = dish_edit_filmstrip_rects(source)
            if not rects:
                return ActionResult(
                    True, "cleared %d dish-edit photo(s)" % removed
                )
            tapped = self._click_rect(rects[0])
            if not tapped.success:
                return ActionResult(
                    False, "clear dish-edit photos: %s" % tapped.message
                )
            time.sleep(0.4)
            trash = dish_edit_trash_rect(self._dump_source())
            if trash is None:
                return ActionResult(False, "clear dish-edit photos: trash not found")
            dumped = self._click_rect(trash)
            if not dumped.success:
                return dumped
            confirmed = self._confirm_dish_edit_photo_delete()
            if not confirmed.success:
                return confirmed
            if not self._wait_dish_edit_count_drop(len(rects), timeout=3.0):
                remaining = dish_edit_filmstrip_rects(self._dump_source())
                return ActionResult(
                    False,
                    "clear dish-edit photos: leftover tile did not drop "
                    "(still %d)" % len(remaining),
                )
            removed += 1
        leftover = dish_edit_filmstrip_rects(self._dump_source())
        if leftover:
            return ActionResult(
                False,
                "clear dish-edit photos: %d leftover tile(s) remain" % len(leftover),
            )
        return ActionResult(True, "cleared %d dish-edit photo(s)" % removed)

    def _tap_dish_edit_plus(self) -> ActionResult:
        """Open the album picker from the dish-edit 上传照片 tile."""
        source = self._dump_source()
        rect = preferred_tap_rect(source, "description", "上传照片")
        if rect is None:
            return ActionResult(False, "dish-edit plus not found")
        tapped = self._click_rect(rect)
        if not tapped.success:
            return tapped
        time.sleep(0.6)
        return ActionResult(True, "tapped dish-edit plus")

    def _wait_dish_edit_count_drop(self, before: int, timeout: float = 3.0) -> bool:
        deadline = time.time() + max(timeout, 0.1)
        while time.time() < deadline:
            remaining = dish_edit_filmstrip_rects(self._dump_source())
            if len(remaining) < before:
                return True
            time.sleep(0.25)
        return len(dish_edit_filmstrip_rects(self._dump_source())) < before

    def _confirm_dish_edit_photo_delete(self) -> ActionResult:
        """Confirm Picasso's 确认删除这张图片吗 dialog.

        The orange control is 「确认删除」, not the toolbar 「确定」 and not
        「考虑一下」. Tap the exact button bounds and retry if the dialog
        stays up — a leftover dialog from a previous run is the first
        thing to dismiss, not another trash tap.
        """
        deadline = time.time() + 4.0
        taps = 0
        while time.time() < deadline:
            source = self._dump_source()
            rect = dish_edit_delete_confirm_rect(source)
            if rect is not None:
                tapped = self._click_rect(rect)
                if not tapped.success:
                    return ActionResult(
                        False,
                        "clear dish-edit photos: confirm tap failed: %s" % tapped.message,
                    )
                taps += 1
                gone_until = time.time() + 1.2
                while time.time() < gone_until:
                    if dish_edit_delete_confirm_rect(self._dump_source()) is None:
                        return ActionResult(True, "confirmed dish-edit delete")
                    time.sleep(0.2)
                if taps >= 3:
                    return ActionResult(
                        False,
                        "clear dish-edit photos: delete dialog stuck after confirm",
                    )
                continue
            if "确认删除这张图片吗" not in source:
                return ActionResult(True, "no dish-edit delete dialog")
            time.sleep(0.2)
        return ActionResult(False, "clear dish-edit photos: delete dialog stuck")

    def _confirm_editor_photo_delete(self, source: str) -> None:
        """Tap 删除/移除 only while a photo preview is showing.

        ``source`` is the post-tap dump. The editor's own chrome also carries
        删除/移除 labels; tapping one there would touch the review, not a
        leftover thumbnail, so the confirm is skipped while the editor's
        发布 bar is still on screen.
        """
        if not source or review_publish_chrome_visible(source):
            return
        for label in ("删除", "移除"):
            if not self._uia2_widget_exists("text", label):
                continue
            tap = self._tap_with_clickable_parent(
                {
                    "selector": (
                        'uiautomator:new UiSelector().text("%s")' % label,
                    )
                }
            )
            if tap.success:
                time.sleep(0.5)
                return

    @staticmethod
    def _push_file(device: Any, local: str, remote: str) -> None:
        """Push ``local`` onto the device. u2 Device has ``push``, not ``sync``.

        2026-09 live: ``Device.sync`` is absent; ``Device.push(src, dst)`` and
        ``Device.adb_device.sync.push`` both work. Prefer the Device API so a
        duck-typed fake only needs ``push``.
        """
        pusher = getattr(device, "push", None)
        if callable(pusher):
            pusher(local, remote)
            return
        sync = getattr(device, "sync", None)
        sync_push = getattr(sync, "push", None) if sync is not None else None
        if callable(sync_push):
            sync_push(local, remote)
            return
        adb_device = getattr(device, "adb_device", None)
        adb_sync = getattr(adb_device, "sync", None) if adb_device is not None else None
        adb_push = getattr(adb_sync, "push", None) if adb_sync is not None else None
        if callable(adb_push):
            adb_push(local, remote)
            return
        raise AttributeError("driver does not support file push")

    def _prepare_gallery_photo(self, host_path: str, recency_rank: int = 0) -> ActionResult:
        """Stage one host image into the isolated ``DianpingAuto`` album.

        2026-09-21 live: MediaStore datetaken-first is not Picasso 最近项目
        order, and Camera tile 0 is a private family photo. Staging into a
        dedicated folder means the picker can switch to that album and the
        only selectable tiles are the files we pushed.

        Steps:

        1. rewrite EXIF DateTimeOriginal/DateTime to now minus
           ``recency_rank`` seconds-pairs (a plain ``adb push`` carries no
           EXIF, so MediaProvider indexes ``datetaken`` as NULL);
        2. mkdir the isolated album, push ``IMG99999999_<name>``, media-scan;
        3. poll until the row is in ``DianpingAuto`` AND tops that album by
           datetaken; otherwise fail instead of picking a private tile.
        """
        device = getattr(self._session, "driver", None)
        if device is None or not hasattr(device, "shell"):
            return ActionResult(False, "gallery prep: no adb-capable driver")
        source = Path(host_path)
        if not source.is_file():
            return ActionResult(False, "gallery prep: host file missing: %s" % host_path)
        try:
            import io

            from PIL import Image
        except ImportError:
            return ActionResult(False, "gallery prep: Pillow unavailable")
        try:
            image = Image.open(source)
            exif = image.getexif()
            captured = time.time() - max(int(recency_rank), 0) * 2
            timestamp = time.strftime("%Y:%m:%d %H:%M:%S", time.localtime(captured))
            exif[36867] = timestamp
            exif[306] = timestamp
            # The album/MEDIA_SCANNER contract is JPEG (datetaken EXIF). A
            # generated PNG may carry alpha (RGBA/LA/P), which JPEG cannot
            # encode — flatten to RGB so any resolved source stages cleanly.
            if image.mode not in ("RGB", "L", "CMYK"):
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", exif=exif, quality=85)
        except Exception as exc:
            return ActionResult(False, "gallery prep: EXIF rewrite failed: %s" % exc)

        display_name = self._PUSH_PREFIX + source.name
        remote = "%s/%s" % (self._GALLERY_DIR, display_name)
        staging = None
        try:
            staging = source.with_name("staged-" + display_name)
            staging.write_bytes(buffer.getvalue())
            device.shell(["mkdir", "-p", self._GALLERY_DIR])
            self._push_file(device, str(staging), remote)
            device.shell(
                [
                    "am", "broadcast", "-a",
                    "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                    "-d", "file://" + remote,
                ]
            )
        except Exception as exc:
            return ActionResult(False, "gallery prep: push/scan failed: %s" % exc)
        finally:
            if staging is not None:
                try:
                    staging.unlink()
                except OSError:
                    pass

        deadline = time.time() + 20.0
        while time.time() < deadline:
            try:
                row = _shell_text(
                    device.shell(
                        [
                            "content", "query",
                            "--uri", "content://media/external/images/media",
                            "--projection", "_display_name:bucket_display_name:datetaken",
                            "--where",
                            "_display_name='%s' AND bucket_display_name='%s'"
                            % (display_name, self._GALLERY_ALBUM),
                        ]
                    )
                )
                if (
                    row
                    and "datetaken=NULL" not in row
                    and _media_field(row, "bucket_display_name") == self._GALLERY_ALBUM
                ):
                    top = _shell_text(
                        device.shell(
                            [
                                "content", "query",
                                "--uri", "content://media/external/images/media",
                                "--projection", "_display_name:datetaken",
                                "--where",
                                "bucket_display_name='%s'" % self._GALLERY_ALBUM,
                                "--sort", "datetaken DESC",
                            ]
                        )
                    ).splitlines()
                    if top and _media_display_name(top[0]) == display_name:
                        return ActionResult(
                            True,
                            "gallery prep: %s indexed first in %s"
                            % (display_name, self._GALLERY_ALBUM),
                            data={
                                "display_name": display_name,
                                "remote": remote,
                                "album": self._GALLERY_ALBUM,
                            },
                        )
            except Exception:
                pass
            time.sleep(1.0)
        return ActionResult(
            False,
            "gallery prep: %s not indexed first within 20s" % display_name,
        )

    def _dump_once(self) -> str:
        driver = getattr(self._session, "driver", None)
        dump = getattr(driver, "dump_hierarchy", None) if driver is not None else None
        if not callable(dump):
            return ""
        try:
            source = dump()
        except Exception as exc:
            _log_swallowed("uia2 dump_hierarchy", exc)
            return ""
        return source if isinstance(source, str) else ""

    def _ensure_screen_on(self) -> None:
        """Wake the panel; a black dump looks like home and starts a shop search."""
        driver = getattr(self._session, "driver", None)
        if driver is None:
            return
        info = getattr(driver, "info", None)
        if callable(info):
            try:
                info = info()
            except Exception:
                info = None
        on = True
        if isinstance(info, dict):
            if "displayOn" in info:
                on = bool(info.get("displayOn"))
            elif "screenOn" in info:
                on = bool(info.get("screenOn"))
        if on:
            return
        screen_on = getattr(driver, "screen_on", None)
        if callable(screen_on):
            try:
                screen_on()
                return
            except Exception:
                pass
        shell = getattr(driver, "shell", None)
        if callable(shell):
            try:
                shell("input keyevent 224")
            except Exception:
                pass

    def _dump_source(self) -> str:
        source = self._dump_once()
        if source:
            return source
        self._ensure_screen_on()
        time.sleep(0.4)
        return self._dump_once()

    def _header_album_is(self, name: str) -> bool:
        source = self._dump_source()
        if not source:
            return False
        return _picker_header_album(source) == name

    def _switch_to_staging_album(self) -> ActionResult:
        """Open the album dropdown and enter the isolated staging album.

        Must happen before any checkbox tap. 最近项目 and Camera both lead
        with tiles that are not the staged file (downloads lab photo /
        private family photos, 2026-09-21).
        """
        if self._header_album_is(self._GALLERY_ALBUM):
            return ActionResult(True, "picker already on %s" % self._GALLERY_ALBUM)
        opened = self._open_album_dropdown()
        if not opened.success:
            return opened
        deadline = time.time() + 8.0
        while time.time() < deadline:
            if self._uia2_widget_exists("text", self._GALLERY_ALBUM):
                tap = self._tap_with_clickable_parent(
                    {
                        "selector": (
                            'uiautomator:new UiSelector().text("%s")'
                            % self._GALLERY_ALBUM,
                        )
                    }
                )
                if tap.success:
                    settled = time.time() + 4.0
                    while time.time() < settled:
                        if self._header_album_is(self._GALLERY_ALBUM):
                            return ActionResult(
                                True, "switched picker to %s" % self._GALLERY_ALBUM
                            )
                        time.sleep(0.3)
            self._scroll_album_list()
            time.sleep(0.4)
        header = _picker_header_album(self._dump_source()) or "?"
        return ActionResult(
            False,
            "pick_photos: could not switch to %s (header=%s)"
            % (self._GALLERY_ALBUM, header),
        )

    def _open_album_dropdown(self) -> ActionResult:
        source = self._dump_source()
        header = _picker_header_album(source) if source else None
        labels = []
        if header:
            labels.append(header)
        for label in self._ALBUM_DROPDOWN_CANDIDATES:
            if label not in labels:
                labels.append(label)
        tap = self._tap_with_clickable_parent(
            {
                "selector": tuple(
                    'uiautomator:new UiSelector().text("%s")' % label
                    for label in labels
                )
            }
        )
        if not tap.success:
            return ActionResult(
                False, "pick_photos: album dropdown not found: %s" % tap.message
            )
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if self._uia2_widget_exists("text", self._GALLERY_ALBUM):
                return ActionResult(True, "album dropdown open")
            if self._uia2_widget_exists("text", "Camera") or self._uia2_widget_exists(
                "text", "downloads"
            ):
                return ActionResult(True, "album dropdown open")
            time.sleep(0.3)
        return ActionResult(False, "pick_photos: album dropdown did not open")

    def _scroll_album_list(self) -> None:
        driver = getattr(self._session, "driver", None)
        swipe = getattr(driver, "swipe", None)
        if not callable(swipe):
            return
        try:
            swipe(540, 1600, 540, 800, 0.3)
        except Exception as exc:
            _log_swallowed("uia2 album list swipe", exc)

    def _pick_photo_tile(self, thumb_selector: Any, index: int) -> ActionResult:
        """Select photo-tile ``index`` via the checkbox, skipping videos.

        2026-09 最近项目 lays videos first (``ugc_album_item_video_thumbnail_image``)
        then photos. Tapping ``photo_imageView`` opens a preview sheet; the
        real select hit target is ``ugc_album_item_select_layout``. Prefer
        that resourceId, then photo_imageView, then className. A class-only
        ImageView.instance(0) hits a video. The kit translator rejects
        instance() chains, so drive u2 directly. Success requires the badge
        to show a selection number — otherwise 下一步 closes with 0 photos.
        """
        resource_ids: List[str] = []
        class_name = None
        for candidate in as_selector_list(thumb_selector) if thumb_selector else []:
            if not isinstance(candidate, str):
                continue
            if 'resourceId("' in candidate:
                rid = candidate.split('resourceId("', 1)[1].split('")', 1)[0]
                if rid and rid not in resource_ids:
                    resource_ids.append(rid)
            elif class_name is None and 'className("' in candidate:
                class_name = candidate.split('className("', 1)[1].split('")', 1)[0]
        ordered: List[str] = []
        for rid in (_PHOTO_SELECT_RESOURCE_ID, _PHOTO_IMAGE_RESOURCE_ID):
            if rid in resource_ids:
                ordered.append(rid)
        for rid in resource_ids:
            if rid not in ordered:
                ordered.append(rid)
        lookups = [{"resourceId": rid, "instance": index} for rid in ordered]
        if not lookups and class_name:
            lookups = [{"className": class_name, "instance": index}]
        if not lookups:
            lookups = [{"resourceId": _PHOTO_SELECT_RESOURCE_ID, "instance": index}]
        last_miss = "photo tile instance %d absent" % index
        attempts = 0
        for lookup in lookups:
            for _ in range(2):
                # The grid can still be settling when a tap lands (live
                # 2026-10-16: the tile was visible in the dump yet the click
                # never stuck); retry the same selector before falling back to
                # the next candidate instead of giving up after one miss.
                try:
                    widget = self._session.driver(**lookup)
                    if not bool(getattr(widget, "exists", False)):
                        last_miss = "photo tile instance %d absent" % index
                        break
                    widget.click()
                except Exception as exc:
                    return ActionResult(False, "photo tile tap failed: %s" % exc)
                attempts += 1
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    if self._photo_tile_is_selected(index):
                        return ActionResult(
                            True,
                            "selected photo tile %d (attempt %d)" % (index, attempts),
                        )
                    time.sleep(0.3)
                last_miss = "photo tile %d was not selected (attempt %d)" % (
                    index,
                    attempts,
                )
        # Live 2026-10-16: the run failed while a later probe found the tile —
        # record whether the selector is in the tree so the next run tells
        # "absent from tree" apart from "present but taps did not stick".
        dump = getattr(self._session.driver, "dump_hierarchy", None)
        tile_in_dump = None
        if callable(dump):
            try:
                tile_in_dump = _PHOTO_SELECT_RESOURCE_ID in (dump() or "")
            except Exception:
                tile_in_dump = None
        verdict = "unknown" if tile_in_dump is None else ("yes" if tile_in_dump else "no")
        return ActionResult(
            False, "%s (select_layout in dump: %s)" % (last_miss, verdict)
        )

    def _photo_tile_is_selected(self, index: int) -> bool:
        driver = getattr(self._session, "driver", None)
        if not callable(driver):
            return True
        try:
            badge = driver(
                resourceId=_PHOTO_SELECT_BADGE_RESOURCE_ID, instance=index
            )
            if not bool(getattr(badge, "exists", False)):
                return False
            info = getattr(badge, "info", None)
            if callable(info):
                info = info()
            text = ""
            if isinstance(info, dict):
                text = str(info.get("text") or "")
            return bool(text.strip().isdigit())
        except Exception:
            return False

    def _confirm_picked_photos(self, confirm_selector: Any) -> ActionResult:
        """Advance picker confirm (下一步) then dish-edit confirm (确定).

        2026-09 Picasso: 「下一步」/「确定」 are non-clickable TextViews; kit
        tap on the label reports success but the parent FrameLayout never
        receives it (same as 写评价 / 添加图/视频). Wait for the chrome after
        the tile tap — the bottom bar inflates after selection — then tap
        the clickable ancestor.
        """
        candidates = as_selector_list(confirm_selector) if confirm_selector else []
        tapped: List[str] = []
        for _ in range(2):
            hit = None
            deadline = time.time() + 6.0
            while time.time() < deadline and hit is None:
                for candidate in candidates:
                    translated = translate_uiautomator_selector(candidate)
                    if translated is None:
                        continue
                    _by, value = translated
                    if value in tapped:
                        continue
                    if not self._uia2_widget_exists(_by, value):
                        continue
                    result = self._tap_with_clickable_parent({"selector": candidate})
                    if not result.success:
                        continue
                    gone_until = time.time() + 3.0
                    while time.time() < gone_until:
                        if not self._uia2_widget_exists(_by, value):
                            hit = value
                            break
                        time.sleep(0.3)
                    if hit is not None:
                        break
                if hit is None:
                    time.sleep(0.4)
            if hit is None:
                break
            tapped.append(hit)
            time.sleep(0.6)
        if not tapped:
            return ActionResult(False, "pick_photos: confirm not found")
        return ActionResult(
            True, "pick_photos: confirmed via %s" % " -> ".join(tapped)
        )

    def _uia2_widget_exists(self, by: str, value: str) -> bool:
        driver = getattr(self._session, "driver", None)
        if not callable(driver):
            return True
        kwargs = {
            "text": {"text": value},
            "text-contains": {"textContains": value},
            "description": {"description": value},
            "description-contains": {"descriptionContains": value},
            "id": {"resourceId": value},
            "class": {"className": value},
        }.get(by)
        if kwargs is None:
            return True
        try:
            return bool(getattr(driver(**kwargs), "exists", False))
        except Exception as exc:
            # Fail closed: a driver hiccup must not read as "widget is gone",
            # or the flow would believe a cleared tile/photo it never saw.
            _log_swallowed("uia2 widget_exists(%s:%s)" % (by, value), exc)
            return True

    def _retry_after_manual_window(
        self, action_name: str, kwargs: Dict[str, Any], failure: ActionResult
    ) -> ActionResult:
        """Keep re-attempting a blocked action while a human clears a
        risk-control challenge that the accessibility tree cannot see."""
        print(
            "[dianping] action %s blocked; solve the challenge on the device, "
            "retrying for %.0fs..." % (action_name, self.captcha_window_seconds),
            flush=True,
        )
        self._manual_window_active = True
        try:
            deadline = time.time() + self.captcha_window_seconds
            attempt = 0
            while time.time() < deadline:
                time.sleep(min(5.0, max(1.0, deadline - time.time())))
                attempt += 1
                if action_name == "tap":
                    retry = self._tap_with_clickable_parent(kwargs)
                elif action_name in {"type_text", "wait_for_element"}:
                    retry = self._with_translated_candidates(action_name, kwargs)
                else:
                    retry = self._session.execute_action(action_name, **kwargs)
                if retry.success:
                    print(
                        "[dianping] action %s recovered after manual window "
                        "(attempt %d)" % (action_name, attempt),
                        flush=True,
                    )
                    return ActionResult(
                        True,
                        "%s (recovered after manual captcha window)" % action_name,
                        data=retry.data,
                    )
            print("[dianping] manual window expired for %s" % action_name, flush=True)
            return failure
        finally:
            self._manual_window_active = False

    def _dismiss_dialogs(self, **kwargs: Any) -> ActionResult:
        if dish_edit_is_open(self._hierarchy_source()):
            return ActionResult(True, "dismiss_dialogs skipped; dish-edit open")
        selector = kwargs.get("selector")
        max_attempts = _numeric_parameter(kwargs, "max_attempts", 3, cast=int, minimum=1)
        candidates = []
        for candidate in as_selector_list(selector) if selector is not None else []:
            translated = translate_uiautomator_selector(candidate)
            if translated is not None:
                candidates.append(translated)
        dismissed = 0
        for _ in range(max_attempts):
            hit = False
            for by, value in candidates:
                result = self._session.execute_action("tap", selector=value, by=by)
                if result.success:
                    dismissed += 1
                    hit = True
                    break
            if not hit:
                break
        # Best-effort hygiene, mirroring the Appium session: success even
        # when no dialog was present.
        return ActionResult(True, "dismiss_dialogs", data={"dismissed": dismissed})


def _import_kit_uia2_session():
    from adapters.uia2 import Uia2Session

    return Uia2Session


def _connect_uia2(udid: Optional[str]):
    try:
        import uiautomator2 as u2
    except ImportError as exc:
        raise ImportError(
            "uiautomator2 is required for the dianping uia2 driver; "
            "pip install 'uiautomator2>=3,<4'"
        ) from exc
    return u2.connect(udid)


def build_uia2_session_factory(
    config: DianpingDeviceConfig,
    *,
    slider_solver: Optional[Callable[[Any], Any]] = None,
) -> Callable[[], DianpingUia2Session]:
    """Zero-arg factory connecting over adb directly (no Appium server)."""

    def factory() -> DianpingUia2Session:
        kit_session_cls = _import_kit_uia2_session()
        device = _connect_uia2(config.udid)
        # u2's implicit element wait defaults to 20s, so every tap/type on a
        # missing selector burned the full 20s before falling through to the
        # next candidate. The workflow already gates each action with an
        # explicit wait_for_element, so a short implicit wait is enough.
        try:
            device.settings["wait_timeout"] = 8.0
        except Exception:
            pass
        identifier = str(config.udid or config.device_name or "dianping-uia2")
        return DianpingUia2Session(
            kit_session_cls(
                device,
                identifier=identifier,
                artifact_root=Path(config.artifact_root),
            ),
            captcha_window_seconds=config.captcha_window_seconds,
            slider_solver=slider_solver,
        )

    return factory
