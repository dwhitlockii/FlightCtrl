from typing import Dict, List

from .common import CollectorResult, run_command, unavailable_entry


def _truncate(raw: str, limit: int = 4000) -> str:
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "\n..."


def _parse_firewall_state(output: str) -> List[bool]:
    states: List[bool] = []
    for line in output.splitlines():
        if line.strip().lower().startswith("state"):
            if "on" in line.lower():
                states.append(True)
            elif "off" in line.lower():
                states.append(False)
    return states


def collect_firewall_windows() -> CollectorResult:
    collectors = ["netsh"]
    unavailable: List[Dict[str, str]] = []
    enabled = None
    rule_count = None
    code, stdout, stderr = run_command(["netsh", "advfirewall", "show", "allprofiles"])
    if code != 0:
        unavailable.append(unavailable_entry(
            "firewall_state",
            stderr or "netsh advfirewall show allprofiles failed",
            "Run the agent as Administrator and ensure Windows Defender Firewall is enabled.",
        ))
    else:
        states = _parse_firewall_state(stdout)
        if states:
            enabled = any(states) and not all(state is False for state in states)
    code_rules, stdout_rules, stderr_rules = run_command([
        "netsh",
        "advfirewall",
        "firewall",
        "show",
        "rule",
        "name=all",
    ], timeout=8)
    if code_rules != 0:
        unavailable.append(unavailable_entry(
            "firewall_rules",
            stderr_rules or "netsh advfirewall firewall show rule name=all failed",
            "Run the agent as Administrator and allow netsh to enumerate rules.",
        ))
    else:
        rule_count = len([line for line in stdout_rules.splitlines() if line.strip().lower().startswith("rule name")])
    data = {
        "enabled": enabled,
        "backend": "windows_defender_firewall",
        "rule_count": rule_count,
        "raw": _truncate((stdout or "") + "\n" + (stdout_rules or "")),
    }
    return CollectorResult(data, unavailable, collectors, None)
