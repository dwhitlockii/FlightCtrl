from typing import Dict, List

from .common import CollectorResult, run_command, unavailable_entry


def _truncate(raw: str, limit: int = 4000) -> str:
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "\n..."


def collect_firewall_macos() -> CollectorResult:
    collectors = ["pfctl"]
    unavailable: List[Dict[str, str]] = []
    enabled = None
    rule_count = None
    code, stdout, stderr = run_command(["pfctl", "-s", "info"])
    if code != 0:
        unavailable.append(unavailable_entry(
            "firewall_state",
            stderr or "pfctl -s info failed",
            "Run the agent with sudo and ensure pf is enabled.",
        ))
    else:
        for line in stdout.splitlines():
            if line.lower().startswith("status:"):
                enabled = "enabled" in line.lower()
                break
    code_rules, stdout_rules, stderr_rules = run_command(["pfctl", "-sr"])
    if code_rules != 0:
        unavailable.append(unavailable_entry(
            "firewall_rules",
            stderr_rules or "pfctl -sr failed",
            "Run the agent with sudo and enable pf rules.",
        ))
    else:
        rule_lines = [line for line in stdout_rules.splitlines() if line.strip()]
        rule_count = len(rule_lines)
    data = {
        "enabled": enabled,
        "backend": "pf",
        "rule_count": rule_count,
        "raw": _truncate((stdout_rules or "") + "\n" + (stdout or "")),
    }
    return CollectorResult(data, unavailable, collectors, None)
