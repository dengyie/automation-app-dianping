"""CLI entry for offline helpers and authorized live device runs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _print_result(result) -> int:
    payload = {
        "success": bool(getattr(result, "success", False)),
        "state": str(getattr(getattr(result, "state", None), "value", getattr(result, "state", None))),
        "error": getattr(result, "error", None),
        "actions": [
            {"message": getattr(a, "message", None), "success": getattr(a, "success", None)}
            for a in (getattr(result, "actions", None) or [])
        ],
        "artifacts": [
            {"type": getattr(a, "artifact_type", None), "path": str(getattr(a, "path", ""))}
            for a in (getattr(result, "artifacts", None) or [])
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["success"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m automation_app_dianping")
    sub = parser.add_subparsers(dest="command", required=True)

    live = sub.add_parser("live", help="Authorized live device run")
    live.add_argument("--mode", choices=["smoke", "publish"], default="smoke")
    live.add_argument("--draft-id", default=None)
    live.add_argument("--shop-name", default=None)
    live.add_argument("--content", default=None)
    live.add_argument("--data-dir", default="data")
    live.add_argument("--city", default="shanghai")
    live.add_argument("--app-id", default="com.dianping.v1")
    live.add_argument("--udid", default=None)
    live.add_argument("--appium-host", default=None)
    live.add_argument("--appium-port", type=int, default=None)
    live.add_argument("--enable-slidex", action="store_true")
    live.add_argument("--mark-published", action="store_true")

    prep = sub.add_parser("prepare-checklist")
    prep.add_argument("--data-dir", default="data")
    prep.add_argument("--json", action="store_true")
    prep.add_argument("--output", default=None)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--appium-host", default="127.0.0.1")
    doctor.add_argument("--appium-port", type=int, default=4723)
    return parser


def _apply_live_env(args, env: dict) -> dict:
    updated = dict(env)
    if args.udid:
        updated["DIANPING_DEVICE_UDID"] = args.udid
        updated["DIANPING_DEVICE_NAME"] = args.udid
    if args.appium_host:
        updated["DIANPING_APPIUM_HOST"] = args.appium_host
    if args.appium_port is not None:
        updated["DIANPING_APPIUM_PORT"] = str(args.appium_port)
    if args.app_id:
        updated["DIANPING_APP_ID"] = args.app_id
    return updated


def cmd_live(args) -> int:
    from automation_app_dianping.live import run_live

    return _print_result(
        run_live(
            mode=args.mode,
            draft_id=args.draft_id,
            data_dir=args.data_dir,
            city=args.city,
            app_id=args.app_id,
            enable_slidex=args.enable_slidex,
            shop_name=args.shop_name,
            content=args.content,
            env=_apply_live_env(args, os.environ),
            mark_published=args.mark_published,
        )
    )


def cmd_prepare(args) -> int:
    from automation_app_dianping.services import prepare_publish_checklist

    payload = prepare_publish_checklist(
        data_dir=Path(args.data_dir),
        as_json=args.json,
        output=Path(args.output) if args.output else None,
    )
    print(json.dumps({"count": payload["count"], "path": payload["path"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_doctor(args) -> int:
    report = {
        "live_flag": os.environ.get("DIANPING_LIVE_E2E"),
        "appium_python_client": False,
        "appium_server": False,
        "adb_devices": [],
        "hints": [],
    }
    try:
        import appium  # noqa: F401

        report["appium_python_client"] = True
    except Exception:
        report["hints"].append('pip install "Appium-Python-Client>=4"')
    try:
        import urllib.request

        with urllib.request.urlopen("http://%s:%s/status" % (args.appium_host, args.appium_port), timeout=2) as resp:
            report["appium_server"] = resp.status == 200
    except Exception:
        report["hints"].append("Start Appium on %s:%s" % (args.appium_host, args.appium_port))
    try:
        import subprocess

        out = subprocess.check_output(["adb", "devices"], text=True, timeout=3)
        report["adb_devices"] = [line.strip() for line in out.splitlines()[1:] if line.strip()]
        if not report["adb_devices"]:
            report["hints"].append("No adb devices connected")
    except Exception:
        report["hints"].append("adb not found")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ready = report["appium_python_client"] and report["appium_server"] and bool(report["adb_devices"])
    return 0 if ready else 2


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "live":
        return cmd_live(args)
    if args.command == "prepare-checklist":
        return cmd_prepare(args)
    if args.command == "doctor":
        return cmd_doctor(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
