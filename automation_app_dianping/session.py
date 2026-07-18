"""Live Android/Appium session wiring for Dianping."""

from __future__ import annotations

import os
import time
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
    if device.udid:
        options.udid = device.udid
    if device.platform_version:
        options.platform_version = device.platform_version
    server_url = "http://%s:%s%s" % (device.host, device.port, device.path or "/")
    return appium_webdriver.Remote(command_executor=server_url, options=options)


class DianpingAppiumSession:
    """DriverSession-compatible Appium session with multi-selector support."""

    def __init__(self, driver: Any, *, identifier: str = "dianping-appium", artifact_root: Optional[Path] = None):
        self.driver = driver
        self.info = SessionInfo(driver_name="appium", platform="android", identifier=identifier)
        self.artifact_root = Path(artifact_root or "artifacts/dianping-live")
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self._started = False

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

    def execute_action(self, action_name: str, **kwargs: Any) -> ActionResult:
        if action_name == "rate":
            return self._rate(**kwargs)
        if action_name == "pick_photos":
            return self._pick_photos(**kwargs)
        if action_name == "launch_app":
            return self._launch_app(**kwargs)
        if action_name in {"tap", "type_text", "wait_for_element"}:
            return self._with_selector_fallbacks(action_name, kwargs)
        failed = ActionResult(False, "unsupported appium action: %s" % action_name)
        return self._maybe_fallback(action_name, kwargs, failed)

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
        result = self.execute_action("tap", selector=selector)
        if result.success:
            return ActionResult(
                True,
                "rate",
                data={"dimension": kwargs.get("dimension"), "value": kwargs.get("value")},
            )
        return self._maybe_fallback("rate", kwargs, result)

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
) -> Callable[[], DianpingAppiumSession]:
    config = device_config_from_env(env, base=device)

    def factory() -> DianpingAppiumSession:
        driver = driver_factory() if driver_factory is not None else create_appium_driver(config)
        identifier = config.udid or config.device_name or "dianping-device"
        return DianpingAppiumSession(driver=driver, identifier=str(identifier), artifact_root=Path(config.artifact_root))

    return factory
