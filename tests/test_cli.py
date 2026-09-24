"""CLI wiring tests (offline; run_live is stubbed)."""
import json
from types import SimpleNamespace

from automation_app_dianping import cli


def _capture_run_live(monkeypatch, captured):
    import automation_app_dianping.live as live_module

    def fake_run_live(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(success=True)

    monkeypatch.setattr(live_module, "run_live", fake_run_live)


def test_live_command_forwards_udid_as_device_config(monkeypatch):
    captured = {}
    _capture_run_live(monkeypatch, captured)

    exit_code = cli.main(
        ["live", "--mode", "smoke", "--driver", "uia2", "--udid", "1.2.3.4:5555"]
    )

    assert exit_code == 0
    device = captured["device"]
    assert device is not None
    assert device.udid == "1.2.3.4:5555"
    assert device.host == "127.0.0.1"
    assert device.port == 4723


def test_live_command_forwards_appium_endpoint(monkeypatch):
    captured = {}
    _capture_run_live(monkeypatch, captured)

    cli.main(
        [
            "live",
            "--mode",
            "smoke",
            "--appium-host",
            "10.0.0.2",
            "--appium-port",
            "5000",
        ]
    )

    device = captured["device"]
    assert device is not None
    assert device.host == "10.0.0.2"
    assert device.port == 5000


def test_live_command_without_targeting_keeps_device_none(monkeypatch):
    captured = {}
    _capture_run_live(monkeypatch, captured)

    cli.main(["live", "--mode", "smoke"])

    assert captured["device"] is None


def test_print_result_surfaces_runtime_failure():
    import io
    import json

    from types import SimpleNamespace

    result = SimpleNamespace(
        success=False,
        failure=SimpleNamespace(category="INFRASTRUCTURE", code="session_start", message="boom"),
    )
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = cli._print_result(result)
    payload = json.loads(buffer.getvalue())

    assert exit_code == 1
    assert payload["failure"]["code"] == "session_start"
    assert payload["failure"]["message"] == "boom"


def test_apply_live_env_maps_every_override(monkeypatch):
    args = SimpleNamespace(
        driver="uia2", udid="1.2.3.4:5555", appium_host="10.0.0.2",
        appium_port=5000, app_id="com.dianping.v1",
    )
    env = cli._apply_live_env(args, {"KEEP": "1"})

    assert env["KEEP"] == "1"
    assert env["DIANPING_DRIVER"] == "uia2"
    assert env["DIANPING_DEVICE_UDID"] == "1.2.3.4:5555"
    assert env["DIANPING_DEVICE_NAME"] == "1.2.3.4:5555"
    assert env["DIANPING_APPIUM_HOST"] == "10.0.0.2"
    assert env["DIANPING_APPIUM_PORT"] == "5000"
    assert env["DIANPING_APP_ID"] == "com.dianping.v1"


def test_apply_live_env_leaves_unset_args_alone(monkeypatch):
    args = SimpleNamespace(
        driver=None, udid=None, appium_host=None, appium_port=None, app_id=None
    )
    env = cli._apply_live_env(args, {"KEEP": "1"})

    assert env == {"KEEP": "1"}


def test_live_command_forwards_captcha_window(monkeypatch):
    captured = {}
    _capture_run_live(monkeypatch, captured)

    cli.main(["live", "--mode", "smoke", "--captcha-window", "30"])

    device = captured["device"]
    assert device is not None
    assert device.captcha_window_seconds == 30.0


def test_cmd_prepare_prints_count_and_path(monkeypatch, capsys):
    import automation_app_dianping.services as services

    monkeypatch.setattr(
        services,
        "prepare_publish_checklist",
        lambda **kwargs: {"count": 3, "path": "data/checklist.json"},
    )

    exit_code = cli.cmd_prepare(
        SimpleNamespace(data_dir="data", json=False, output=None)
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload == {"count": 3, "path": "data/checklist.json"}


def test_cmd_doctor_reports_ready(monkeypatch, capsys):
    import sys
    import types

    # Force the appium import to succeed without the real package.
    monkeypatch.setitem(sys.modules, "appium", types.ModuleType("appium"))

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda url, timeout=0: _Response()
    )
    monkeypatch.setattr(
        "subprocess.check_output",
        lambda *args, **kwargs: "List of devices attached\n1.2.3.4\tdevice\n",
    )

    exit_code = cli.cmd_doctor(
        SimpleNamespace(appium_host="127.0.0.1", appium_port=4723)
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["appium_python_client"] is True
    assert report["appium_server"] is True
    assert "1.2.3.4" in report["adb_devices"][0]


def test_cmd_doctor_reports_missing_pieces(monkeypatch, capsys):
    import sys

    # None in sys.modules makes ``import appium`` raise, exactly like a
    # machine without the client installed.
    monkeypatch.setitem(sys.modules, "appium", None)
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda url, timeout=0: (_ for _ in ()).throw(OSError("no server"))
    )
    monkeypatch.setattr(
        "subprocess.check_output", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("adb missing"))
    )

    exit_code = cli.cmd_doctor(
        SimpleNamespace(appium_host="127.0.0.1", appium_port=4723)
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert report["appium_python_client"] is False
    assert report["appium_server"] is False
    assert report["adb_devices"] == []
    assert any("pip install" in hint for hint in report["hints"])


def test_main_dispatches_prepare_and_doctor(monkeypatch):
    monkeypatch.setattr(cli, "cmd_prepare", lambda args: 5)
    monkeypatch.setattr(cli, "cmd_doctor", lambda args: 7)

    assert cli.main(["prepare-checklist"]) == 5
    assert cli.main(["doctor"]) == 7


def test_cmd_doctor_warns_when_no_device_attached(monkeypatch, capsys):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "appium", types.ModuleType("appium"))

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda url, timeout=0: _Response()
    )
    monkeypatch.setattr(
        "subprocess.check_output",
        lambda *args, **kwargs: "List of devices attached\n",
    )

    exit_code = cli.cmd_doctor(
        SimpleNamespace(appium_host="127.0.0.1", appium_port=4723)
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert report["adb_devices"] == []
    assert any("No adb devices" in hint for hint in report["hints"])
