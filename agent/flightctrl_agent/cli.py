import argparse
import json
import os
import sys
import time
from typing import Dict, Optional
from urllib import request, error

from .snapshot import collect_snapshot
from .collectors import DiskIoState, detect_platform, detect_privilege_level

BACKEND_ENV = "FLIGHTCTRL_BACKEND_URL"
INTERVAL_ENV = "FLIGHTCTRL_INTERVAL"
TOKEN_ENV = "FLIGHTCTRL_TOKEN"
TELEMETRY_KEY_ENV = "FLIGHTCTRL_TELEMETRY_KEY"


def _log(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"[flightctrl-agent] {timestamp} {message}", flush=True)


def _post_payload(url: str, payload: Dict, token: Optional[str], telemetry_key: Optional[str]) -> None:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if telemetry_key:
        headers["X-Telemetry-Key"] = telemetry_key
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers=headers)
    try:
        with request.urlopen(req, timeout=6) as resp:
            if resp.status >= 300:
                _log(f"ingest failed: {resp.status}")
    except error.HTTPError as exc:
        _log(f"ingest error: {exc.code} {exc.reason}")
    except Exception as exc:
        _log(f"ingest error: {exc}")


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FlightCtrl Host Telemetry Agent")
    parser.add_argument(
        "--backend",
        default=os.getenv(BACKEND_ENV, "http://127.0.0.1:8000"),
        help="Backend base URL (default from FLIGHTCTRL_BACKEND_URL)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv(INTERVAL_ENV, "2")),
        help="Polling interval seconds (default from FLIGHTCTRL_INTERVAL)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv(TOKEN_ENV),
        help="Admin JWT token for ingest (default from FLIGHTCTRL_TOKEN; prefer telemetry key)",
    )
    parser.add_argument(
        "--telemetry-key",
        default=os.getenv(TELEMETRY_KEY_ENV),
        help="Telemetry API key for X-Telemetry-Key (default from FLIGHTCTRL_TELEMETRY_KEY)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Collect and send a single snapshot, then exit.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list] = None) -> None:
    args = parse_args(argv)
    backend = args.backend.rstrip("/")
    url = f"{backend}/api/telemetry/ingest"
    interval = max(args.interval, 0.5)
    platform_key = detect_platform()
    privilege = detect_privilege_level()
    _log(f"starting agent platform={platform_key} privilege={privilege} backend={backend}")
    if not args.token and not args.telemetry_key:
        _log("no auth provided: set FLIGHTCTRL_TELEMETRY_KEY (recommended) or FLIGHTCTRL_TOKEN if backend requires auth")
    state = DiskIoState()
    while True:
        payload = collect_snapshot(state)
        _post_payload(url, payload, args.token, args.telemetry_key)
        if args.once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
