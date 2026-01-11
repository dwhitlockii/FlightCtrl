import shutil
from typing import Any, Dict, List

from .common import CollectorResult, run_command, unavailable_entry, parse_json


def _truncate(raw: str, limit: int = 4000) -> str:
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "\n..."


def _ufw_status() -> CollectorResult:
    collectors = ["ufw"]
    unavailable: List[Dict[str, str]] = []
    code, stdout, stderr = run_command(["ufw", "status"])
    if code != 0:
        reason = stderr or "ufw status failed"
        unavailable.append(unavailable_entry(
            "firewall_state",
            reason,
            "Run the agent with sudo and ensure ufw is installed.",
        ))
        return CollectorResult(None, unavailable, collectors, None)
    enabled = None
    for line in stdout.splitlines():
        if line.lower().startswith("status:"):
            enabled = "active" in line.lower()
            break
    code_rules, stdout_rules, stderr_rules = run_command(["ufw", "status", "numbered"])
    rule_count = None
    if code_rules == 0:
        rule_count = len([line for line in stdout_rules.splitlines() if line.strip().startswith("[")])
    else:
        unavailable.append(unavailable_entry(
            "firewall_rules",
            stderr_rules or "ufw status numbered failed",
            "Run the agent with sudo and ensure ufw is installed.",
        ))
    data = {
        "enabled": enabled,
        "backend": "ufw",
        "rule_count": rule_count,
        "raw": _truncate(stdout_rules or stdout),
    }
    return CollectorResult(data, unavailable, collectors, None)


def _nft_status() -> CollectorResult:
    collectors = ["nft"]
    unavailable: List[Dict[str, str]] = []
    code, stdout, stderr = run_command(["nft", "-j", "list", "ruleset"])
    raw = stdout
    rule_count = None
    if code == 0:
        data = parse_json(stdout)
        if data and isinstance(data.get("nftables"), list):
            rule_count = len([item for item in data["nftables"] if "rule" in item])
        enabled = True
        return CollectorResult({
            "enabled": enabled,
            "backend": "nftables",
            "rule_count": rule_count,
            "raw": _truncate(raw),
        }, unavailable, collectors, None)
    code_txt, stdout_txt, stderr_txt = run_command(["nft", "list", "ruleset"])
    if code_txt != 0:
        unavailable.append(unavailable_entry(
            "firewall_state",
            stderr_txt or stderr or "nft list ruleset failed",
            "Run the agent with sudo and ensure nftables is installed.",
        ))
        return CollectorResult(None, unavailable, collectors, None)
    lines = [line for line in stdout_txt.splitlines() if line.strip().startswith("rule")]
    rule_count = len(lines) if lines else None
    if rule_count is None:
        unavailable.append(unavailable_entry(
            "firewall_rules",
            "Unable to parse nftables rules",
            "Run the agent with sudo and ensure nftables is installed.",
        ))
    return CollectorResult({
        "enabled": True,
        "backend": "nftables",
        "rule_count": rule_count,
        "raw": _truncate(stdout_txt),
    }, unavailable, collectors, None)


def _iptables_status() -> CollectorResult:
    collectors = ["iptables"]
    unavailable: List[Dict[str, str]] = []
    code, stdout, stderr = run_command(["iptables", "-S"])
    if code != 0:
        unavailable.append(unavailable_entry(
            "firewall_state",
            stderr or "iptables -S failed",
            "Run the agent with sudo and ensure iptables is installed.",
        ))
        return CollectorResult(None, unavailable, collectors, None)
    lines = [line for line in stdout.splitlines() if line.strip().startswith("-A")]
    rule_count = len(lines) if lines else 0
    data = {
        "enabled": None,
        "backend": "iptables",
        "rule_count": rule_count,
        "raw": _truncate(stdout),
    }
    unavailable.append(unavailable_entry(
        "firewall_state",
        "iptables does not expose a simple enabled/disabled state",
        "Use ufw or nftables for explicit status reporting.",
    ))
    return CollectorResult(data, unavailable, collectors, None)


def collect_firewall_linux() -> CollectorResult:
    if shutil.which("ufw"):
        return _ufw_status()
    if shutil.which("nft"):
        return _nft_status()
    if shutil.which("iptables"):
        return _iptables_status()
    unavailable = [unavailable_entry(
        "firewall_state",
        "No firewall tooling detected",
        "Install ufw, nftables, or iptables and run with sudo.",
    )]
    return CollectorResult({
        "enabled": None,
        "backend": None,
        "rule_count": None,
        "raw": None,
    }, unavailable, [], None)
