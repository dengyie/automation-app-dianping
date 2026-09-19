"""CLI wiring tests (offline; run_live is stubbed)."""
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
