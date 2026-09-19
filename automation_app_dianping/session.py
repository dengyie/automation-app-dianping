"""Live Android/Appium session wiring for Dianping."""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import inspect
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from automation_core.drivers import ActionResult, ArtifactHandle, SessionInfo

from automation_app_dianping.config import DianpingDeviceConfig, as_selector_list


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


class DianpingAppiumSession:
    """DriverSession-compatible Appium session with multi-selector support."""

    _SLIDER_GUARDED_ACTIONS = frozenset(
        {"tap", "type_text", "wait_for_element", "confirm_search", "rate", "pick_photos"}
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
        self.captcha_window_seconds = float(captcha_window_seconds)
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
        if action_name == "rate":
            result = self._rate(**kwargs)
        elif action_name == "pick_photos":
            result = self._pick_photos(**kwargs)
        elif action_name == "launch_app":
            result = self._launch_app(**kwargs)
        elif action_name == "confirm_search":
            result = self._confirm_search(**kwargs)
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
        except Exception:
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
        if isinstance(solution, dict) and solution.get("gap_offset_px") is not None:
            try:
                offset = int(solution["gap_offset_px"])
            except (TypeError, ValueError):
                return ActionResult(False, "slider solver returned invalid gap_offset_px")
        elif isinstance(solution, (int, float)) and not isinstance(solution, bool):
            offset = int(solution)
        else:
            return ActionResult(False, "slider solver produced no solution")
        if offset <= 0:
            return ActionResult(False, "slider solver returned non-positive gap_offset_px")
        return self._perform_slider_swipe(offset)

    def _perform_slider_swipe(self, offset_px: int) -> ActionResult:
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
        start_x, start_y = handle
        try:
            swipe(int(start_x), int(start_y), int(start_x + offset_px), int(start_y), 600)
        except Exception as exc:
            return ActionResult(False, "slider swipe failed: %s" % exc)
        return ActionResult(True, "slider swiped %d px" % offset_px)

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
                )
                y = rect["y"] + rect["height"] + selectors.rating_overall_star_gap_px
            else:
                x = (
                    selectors.rating_dim_star_origin_px
                    + selectors.rating_dim_star_pitch_px * (numeric_value - 1)
                    + selectors.rating_star_tap_fraction * selectors.rating_star_width_px
                )
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

    def _launch_app(self, **kwargs: Any) -> ActionResult:
        app_id = kwargs.get("app_id")
        if not app_id:
            return ActionResult(False, "missing required parameter: app_id")
        activate = getattr(self.driver, "activate_app", None)
        if not callable(activate):
            return ActionResult(False, "driver does not support app launch")
        try:
            activate(app_id)
            time.sleep(float(kwargs.get("settle_seconds", 2.0)))
            return ActionResult(True, "launch_app")
        except Exception as exc:
            return ActionResult(False, "launch_app failed: %s" % exc)

    def _with_selector_fallbacks(self, action_name: str, kwargs: Dict[str, Any]) -> ActionResult:
        selector = kwargs.get("selector")
        candidates = as_selector_list(selector) if selector is not None else []
        if not candidates and isinstance(selector, str):
            candidates = [selector]
        if not candidates:
            return ActionResult(False, "missing required parameter: selector")
        timeout = float(kwargs.get("timeout", 8.0 if action_name == "wait_for_element" else 5.0))
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
        max_attempts = int(kwargs.get("max_attempts", 3) or 3)
        dismissed = 0
        for _ in range(max(max_attempts, 1)):
            result = self._with_selector_fallbacks(
                "tap",
                {"selector": selector, "timeout": float(kwargs.get("timeout", 1.0))},
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
    selected = str(driver or source.get("DIANPING_DRIVER") or "appium").strip().lower()
    if selected == "uia2":
        return build_uia2_session_factory(config)
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

    def __init__(self, kit_session: Any, *, captcha_window_seconds: float = 0.0):
        self._session = kit_session
        self.info = kit_session.info
        self.captcha_window_seconds = float(captcha_window_seconds)
        self._manual_window_active = False

    def start(self) -> None:
        self._session.start()

    def stop(self) -> None:
        self._session.stop()

    def capture_artifact(self, artifact_type: str, name: str) -> ArtifactHandle:
        return self._session.capture_artifact(artifact_type, name)

    def execute_action(self, action_name: str, **kwargs: Any) -> ActionResult:
        started = time.time()
        print("[dianping-uia2] >> %s" % action_name, flush=True)
        result = self._run_action(action_name, kwargs)
        print(
            "[dianping-uia2] << %s: %s (%.1fs)"
            % (action_name, "ok" if result.success else "FAIL", time.time() - started),
            flush=True,
        )
        if not result.success:
            print("[dianping-uia2] failure detail: %s" % result.message[:400], flush=True)
        return result

    def _run_action(self, action_name: str, kwargs: Dict[str, Any]) -> ActionResult:
        if action_name == "launch_app":
            result = self._session.execute_action("launch_app", **kwargs)
            if result.success:
                try:
                    time.sleep(float(kwargs.get("settle_seconds", 2.0)))
                except (TypeError, ValueError):
                    return ActionResult(False, "settle_seconds must be a number")
            return result
        if action_name == "dismiss_dialogs":
            return self._dismiss_dialogs(**kwargs)
        if action_name == "confirm_search":
            return self._confirm_search(**kwargs)
        if action_name == "rate":
            return self._rate(**kwargs)
        if action_name == "element_bounds":
            return self._element_bounds(**kwargs)
        if action_name in {"tap", "type_text", "wait_for_element"}:
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

    def _with_translated_candidates(
        self, action_name: str, kwargs: Dict[str, Any]
    ) -> ActionResult:
        """Run a selector action over all translated candidates in order.

        SelectorValue tuples carry fallbacks (e.g. the new search bar id,
        then ~搜索, then legacy ids); each string candidate is translated
        into the kit ``by`` vocabulary and tried until one succeeds.
        """
        selector = kwargs.get("selector")
        candidates = as_selector_list(selector) if selector is not None else []
        errors = []
        for candidate in candidates:
            translated = translate_uiautomator_selector(candidate)
            if translated is None:
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
        if not candidates:
            return self._session.execute_action(action_name, **kwargs)
        return ActionResult(
            False,
            "%s failed for all selectors: %s" % (action_name, " | ".join(errors)),
        )

    def _confirm_search(self, **kwargs: Any) -> ActionResult:
        selector = kwargs.get("selector")
        for candidate in as_selector_list(selector) if selector is not None else []:
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

    def _rate(self, **kwargs: Any) -> ActionResult:
        anchor = kwargs.get("anchor")
        if anchor not in {"overall", "dimension_row"}:
            return ActionResult(False, "uia2 rate requires a label anchor")
        selector = kwargs.get("selector")
        candidates = as_selector_list(selector) if selector is not None else []
        label_rect = None
        for candidate in candidates:
            translated = translate_uiautomator_selector(candidate)
            if translated is None:
                continue
            by, value = translated
            result = self._session.execute_action(
                "element_bounds", selector=value, by=by
            )
            if result.success and isinstance(result.data, dict):
                label_rect = result.data
                break
        if label_rect is None:
            return ActionResult(False, "rate anchor label not found on uia2")
        from automation_app_dianping.config import default_selectors

        try:
            numeric_value = int(kwargs.get("value"))
        except (TypeError, ValueError):
            return ActionResult(False, "rate requires a numeric value")
        if not 1 <= numeric_value <= 5:
            return ActionResult(False, "rating value must be 1-5")
        selectors = default_selectors()
        if anchor == "overall":
            x = (
                selectors.rating_overall_star_origin_px
                + selectors.rating_overall_star_pitch_px * (numeric_value - 1)
                + selectors.rating_star_tap_fraction * selectors.rating_star_width_px
            )
            y = label_rect["y"] + label_rect["height"] + selectors.rating_overall_star_gap_px
        else:
            x = (
                selectors.rating_dim_star_origin_px
                + selectors.rating_dim_star_pitch_px * (numeric_value - 1)
                + selectors.rating_star_tap_fraction * selectors.rating_star_width_px
            )
            y = label_rect["y"] + label_rect["height"] / 2
        try:
            result = self._session.execute_action(
                "swipe",
                start_x=int(x),
                start_y=int(y),
                end_x=int(x),
                end_y=int(y),
                duration=0.08,
            )
        except Exception as exc:
            return ActionResult(False, "uia2 rate swipe failed: %s" % exc)
        if not result.success:
            return result
        if anchor == "overall":
            self._resolve_half_star_popup(numeric_value)
        return ActionResult(True, "uia2 star tapped at (%d, %d)" % (int(x), int(y)))

    def _resolve_half_star_popup(self, value: int) -> None:
        """Pick the exact integer if the tap split a star (best effort)."""
        try:
            by, popup_value = translate_uiautomator_selector(
                'uiautomator:new UiSelector().text("%s星")' % value
            )
            self._session.execute_action(
                "tap", selector=popup_value, by=by
            )
        except Exception:
            pass

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
                if action_name in {"tap", "type_text", "wait_for_element"}:
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
        selector = kwargs.get("selector")
        max_attempts = int(kwargs.get("max_attempts", 3) or 3)
        candidates = []
        for candidate in as_selector_list(selector) if selector is not None else []:
            translated = translate_uiautomator_selector(candidate)
            if translated is not None:
                candidates.append(translated)
        dismissed = 0
        for _ in range(max(max_attempts, 1)):
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
) -> Callable[[], DianpingUia2Session]:
    """Zero-arg factory connecting over adb directly (no Appium server)."""

    def factory() -> DianpingUia2Session:
        kit_session_cls = _import_kit_uia2_session()
        device = _connect_uia2(config.udid)
        identifier = str(config.udid or config.device_name or "dianping-uia2")
        return DianpingUia2Session(
            kit_session_cls(
                device,
                identifier=identifier,
                artifact_root=Path(config.artifact_root),
            ),
            captcha_window_seconds=config.captcha_window_seconds,
        )

    return factory
