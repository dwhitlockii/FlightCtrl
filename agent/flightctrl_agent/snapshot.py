import time
from typing import Dict, List, Optional

from .collectors import (
    DiskIoState,
    detect_platform,
    detect_privilege_level,
    detect_container,
    get_host_id,
    collect_cpu,
    collect_memory,
    collect_disk_usage,
    collect_disk_io,
    collect_network,
    collect_firewall_linux,
    collect_firewall_macos,
    collect_firewall_windows,
)
from .collectors.common import collect_process_stats, unavailable_entry


def _merge_unavailable(entries: List[Dict[str, str]], extra: List[Dict[str, str]]) -> None:
    for item in extra:
        entries.append(item)


def _collect_firewall(platform_key: str):
    if platform_key == "windows":
        return collect_firewall_windows()
    if platform_key == "macos":
        return collect_firewall_macos()
    if platform_key == "linux":
        return collect_firewall_linux()
    return collect_firewall_linux()


def collect_snapshot(state: DiskIoState) -> Dict:
    timestamp = time.time()
    platform_key = detect_platform()
    host_id = get_host_id()
    privilege_level = detect_privilege_level()

    cpu_top, mem_top, proc_unavailable = collect_process_stats()
    cpu = collect_cpu(platform_key, cpu_top)
    memory = collect_memory(mem_top)
    disk_usage = collect_disk_usage()
    disk_io = collect_disk_io(state)
    network = collect_network()
    firewall = _collect_firewall(platform_key)
    if firewall.data and firewall.last_success_at is None:
        firewall.last_success_at = timestamp

    unavailable: List[Dict[str, str]] = []
    _merge_unavailable(unavailable, proc_unavailable)
    _merge_unavailable(unavailable, cpu.unavailable)
    _merge_unavailable(unavailable, memory.unavailable)
    _merge_unavailable(unavailable, disk_usage.unavailable)
    _merge_unavailable(unavailable, disk_io.unavailable)
    _merge_unavailable(unavailable, network.unavailable)
    _merge_unavailable(unavailable, firewall.unavailable)

    if detect_container():
        unavailable.append(unavailable_entry(
            "host_telemetry",
            "Agent appears to be running inside a container",
            "Run the agent directly on the host OS to avoid container-scoped telemetry.",
        ))

    collectors_by_subsystem = {
        "cpu": cpu.collectors,
        "memory": memory.collectors,
        "disk": disk_usage.collectors,
        "disk_io": disk_io.collectors,
        "network_flows": network.collectors,
        "firewall_state": firewall.collectors,
    }
    collectors = sorted({c for items in collectors_by_subsystem.values() for c in items})

    last_success_at = {
        "cpu": cpu.last_success_at,
        "memory": memory.last_success_at,
        "disk": disk_usage.last_success_at,
        "disk_io": disk_io.last_success_at,
        "network_flows": network.last_success_at,
        "firewall_state": firewall.last_success_at,
    }

    disk_payload: Optional[Dict] = None
    if disk_usage.data or disk_io.data:
        disk_payload = {
            "usage": disk_usage.data,
            "io": disk_io.data,
        }
    network_payload = network.data
    firewall_payload = firewall.data

    payload = {
        "timestamp": timestamp,
        "platform": platform_key,
        "host_id": host_id,
        "source": "external",
        "cpu": cpu.data,
        "memory": memory.data,
        "disk": disk_payload,
        "network": network_payload,
        "firewall": firewall_payload,
        "provenance": {
            "platform": platform_key,
            "host_id": host_id,
            "privilege_level": privilege_level,
            "collectors": collectors,
            "collectors_by_subsystem": collectors_by_subsystem,
            "last_success_at": {k: v for k, v in last_success_at.items() if v is not None},
        },
        "unavailable": unavailable,
    }
    return payload
