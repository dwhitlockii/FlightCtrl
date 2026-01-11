import os
import platform
import time
import uuid
import json
import subprocess
import socket
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    import psutil
except ImportError:  # pragma: no cover - runtime dependency
    psutil = None


@dataclass
class CollectorResult:
    data: Optional[Dict[str, Any]]
    unavailable: List[Dict[str, str]]
    collectors: List[str]
    last_success_at: Optional[float]


@dataclass
class DiskIoState:
    last_counters: Any = None
    last_ts: Optional[float] = None


def unavailable_entry(metric: str, reason: str, remediation: str) -> Dict[str, str]:
    return {"metric": metric, "reason": reason, "remediation": remediation}


def detect_platform() -> str:
    system = platform.system().lower()
    if system.startswith("darwin"):
        return "macos"
    if system.startswith("windows"):
        return "windows"
    if system.startswith("linux"):
        return "linux"
    return system or "unknown"


def detect_privilege_level() -> str:
    if os.name == "nt":
        try:
            import ctypes
            return "elevated" if ctypes.windll.shell32.IsUserAnAdmin() else "user"
        except Exception:
            return "unknown"
    try:
        return "elevated" if os.geteuid() == 0 else "user"
    except AttributeError:
        return "unknown"


def detect_container() -> bool:
    if os.name == "nt":
        return False
    if os.path.exists("/.dockerenv"):
        return True
    cgroup_path = "/proc/1/cgroup"
    if os.path.exists(cgroup_path):
        try:
            content = open(cgroup_path, "r", encoding="utf-8").read()
        except Exception:
            return False
        for marker in ("docker", "containerd", "kubepods", "lxc"):
            if marker in content:
                return True
    return False


def get_host_id() -> str:
    host = platform.node() or "unknown"
    try:
        mac = uuid.getnode()
    except Exception:
        mac = None
    if mac:
        return f"{host}-{mac:012x}"
    return host


def run_command(args: List[str], timeout: int = 4) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def collect_process_stats(limit: int = 5) -> Tuple[Optional[List[Dict[str, Any]]], Optional[List[Dict[str, Any]]], List[Dict[str, str]]]:
    unavailable: List[Dict[str, str]] = []
    if not psutil:
        unavailable.append(unavailable_entry(
            "cpu_top_processes",
            "psutil not installed",
            "Install psutil to collect top processes.",
        ))
        unavailable.append(unavailable_entry(
            "memory_top_processes",
            "psutil not installed",
            "Install psutil to collect top processes.",
        ))
        return None, None, unavailable
    cpu_entries: List[Dict[str, Any]] = []
    mem_entries: List[Dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            info = proc.info
            name = info.get("name") or str(info.get("pid"))
            cpu_percent = proc.cpu_percent(interval=None)
            mem_info = proc.memory_info()
            rss = getattr(mem_info, "rss", None)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue
        cpu_entries.append({"pid": info.get("pid"), "name": name, "cpu_percent": cpu_percent})
        if rss is not None:
            mem_entries.append({"pid": info.get("pid"), "name": name, "rss": rss})
    cpu_entries.sort(key=lambda item: item.get("cpu_percent", 0), reverse=True)
    mem_entries.sort(key=lambda item: item.get("rss", 0), reverse=True)
    cpu_top = cpu_entries[:limit] if cpu_entries else []
    mem_top = mem_entries[:limit] if mem_entries else []
    if not cpu_top:
        unavailable.append(unavailable_entry(
            "cpu_top_processes",
            "No process CPU stats available",
            "Run with elevated privileges for full process visibility.",
        ))
    if not mem_top:
        unavailable.append(unavailable_entry(
            "memory_top_processes",
            "No process memory stats available",
            "Run with elevated privileges for full process visibility.",
        ))
    return cpu_top or None, mem_top or None, unavailable


def collect_cpu(platform_key: str, top_processes: Optional[List[Dict[str, Any]]]) -> CollectorResult:
    unavailable: List[Dict[str, str]] = []
    collectors: List[str] = []
    if not psutil:
        unavailable.append(unavailable_entry(
            "cpu",
            "psutil not installed",
            "Install psutil to collect CPU metrics.",
        ))
        return CollectorResult(None, unavailable, collectors, None)
    collectors.append("psutil")
    per_core = psutil.cpu_percent(interval=0.1, percpu=True)
    if per_core:
        usage_percent = round(sum(per_core) / len(per_core), 2)
    else:
        usage_percent = psutil.cpu_percent(interval=0.1)
        unavailable.append(unavailable_entry(
            "cpu_per_core",
            "Per-core CPU usage unavailable",
            "Upgrade psutil for per-core CPU stats.",
        ))
    load_avg = None
    if platform_key != "windows" and hasattr(os, "getloadavg"):
        try:
            load_avg = list(os.getloadavg())
        except OSError:
            unavailable.append(unavailable_entry(
                "cpu_load_avg",
                "Load average not available",
                "Run on a platform that supports load average.",
            ))
    else:
        unavailable.append(unavailable_entry(
            "cpu_load_avg",
            "Load average not available on this platform",
            "Use per-core CPU usage or run on Linux/macOS.",
        ))
    data = {
        "usage_percent": usage_percent,
        "per_core_percent": per_core or None,
        "load_avg": load_avg,
    }
    if top_processes is not None:
        data["top_processes"] = top_processes
    return CollectorResult(data, unavailable, collectors, time.time())


def collect_memory(top_processes: Optional[List[Dict[str, Any]]]) -> CollectorResult:
    unavailable: List[Dict[str, str]] = []
    collectors: List[str] = []
    if not psutil:
        unavailable.append(unavailable_entry(
            "memory",
            "psutil not installed",
            "Install psutil to collect memory metrics.",
        ))
        return CollectorResult(None, unavailable, collectors, None)
    collectors.append("psutil")
    try:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
    except Exception as exc:
        unavailable.append(unavailable_entry(
            "memory",
            f"Memory metrics unavailable: {exc}",
            "Run the agent with sufficient privileges.",
        ))
        return CollectorResult(None, unavailable, collectors, None)
    data = {
        "total": mem.total,
        "used": mem.used,
        "available": mem.available,
        "free": mem.free,
        "percent": mem.percent,
        "swap_total": swap.total,
        "swap_used": swap.used,
        "swap_free": swap.free,
        "swap_percent": swap.percent,
    }
    if top_processes is not None:
        data["top_processes"] = top_processes
    return CollectorResult(data, unavailable, collectors, time.time())


def _disk_root() -> str:
    if os.name == "nt":
        return os.getenv("SystemDrive", "C:") + "\\"
    return "/"


def collect_disk_usage() -> CollectorResult:
    unavailable: List[Dict[str, str]] = []
    collectors: List[str] = []
    if not psutil:
        unavailable.append(unavailable_entry(
            "disk",
            "psutil not installed",
            "Install psutil to collect disk usage.",
        ))
        return CollectorResult(None, unavailable, collectors, None)
    collectors.append("psutil")
    try:
        usage = psutil.disk_usage(_disk_root())
    except Exception as exc:
        unavailable.append(unavailable_entry(
            "disk",
            f"Disk usage unavailable: {exc}",
            "Run the agent with sufficient privileges.",
        ))
        return CollectorResult(None, unavailable, collectors, None)
    data = {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": usage.percent,
    }
    return CollectorResult(data, unavailable, collectors, time.time())


def collect_disk_io(state: DiskIoState) -> CollectorResult:
    unavailable: List[Dict[str, str]] = []
    collectors: List[str] = []
    if not psutil:
        unavailable.append(unavailable_entry(
            "disk_iops",
            "psutil not installed",
            "Install psutil to collect disk I/O.",
        ))
        unavailable.append(unavailable_entry(
            "disk_throughput",
            "psutil not installed",
            "Install psutil to collect disk throughput.",
        ))
        return CollectorResult(None, unavailable, collectors, None)
    collectors.append("psutil")
    counters = psutil.disk_io_counters()
    if not counters:
        unavailable.append(unavailable_entry(
            "disk_iops",
            "disk_io_counters unavailable",
            "Run the agent with sufficient privileges.",
        ))
        unavailable.append(unavailable_entry(
            "disk_throughput",
            "disk_io_counters unavailable",
            "Run the agent with sufficient privileges.",
        ))
        return CollectorResult(None, unavailable, collectors, None)
    now = time.time()
    if state.last_counters is None or state.last_ts is None:
        state.last_counters = counters
        state.last_ts = now
        unavailable.append(unavailable_entry(
            "disk_iops",
            "Insufficient history to compute IOPS",
            "Wait for the next sampling interval.",
        ))
        unavailable.append(unavailable_entry(
            "disk_throughput",
            "Insufficient history to compute throughput",
            "Wait for the next sampling interval.",
        ))
        return CollectorResult({
            "read_bytes_per_sec": None,
            "write_bytes_per_sec": None,
            "read_ops_per_sec": None,
            "write_ops_per_sec": None,
            "iops": None,
            "throughput_bytes_per_sec": None,
            "throughput_mb": None,
        }, unavailable, collectors, None)
    elapsed = max(now - state.last_ts, 0.1)
    read_bytes = counters.read_bytes - state.last_counters.read_bytes
    write_bytes = counters.write_bytes - state.last_counters.write_bytes
    read_count = counters.read_count - state.last_counters.read_count
    write_count = counters.write_count - state.last_counters.write_count
    read_bps = read_bytes / elapsed
    write_bps = write_bytes / elapsed
    read_ops = read_count / elapsed
    write_ops = write_count / elapsed
    iops = read_ops + write_ops
    throughput_bps = read_bps + write_bps
    state.last_counters = counters
    state.last_ts = now
    data = {
        "read_bytes_per_sec": round(read_bps, 2),
        "write_bytes_per_sec": round(write_bps, 2),
        "read_ops_per_sec": round(read_ops, 2),
        "write_ops_per_sec": round(write_ops, 2),
        "iops": round(iops, 2),
        "throughput_bytes_per_sec": round(throughput_bps, 2),
        "throughput_mb": round(throughput_bps / (1024 * 1024), 2),
    }
    return CollectorResult(data, unavailable, collectors, now)


def _addr_to_tuple(addr: Any) -> Tuple[Optional[str], Optional[int]]:
    if not addr:
        return None, None
    if isinstance(addr, tuple):
        return addr[0], addr[1]
    return getattr(addr, "ip", None), getattr(addr, "port", None)


def collect_network() -> CollectorResult:
    unavailable: List[Dict[str, str]] = []
    collectors: List[str] = []
    if not psutil:
        unavailable.append(unavailable_entry(
            "network_flows",
            "psutil not installed",
            "Install psutil to collect network flows.",
        ))
        unavailable.append(unavailable_entry(
            "network_listeners",
            "psutil not installed",
            "Install psutil to collect network listeners.",
        ))
        return CollectorResult(None, unavailable, collectors, None)
    collectors.append("psutil")
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError) as exc:
        unavailable.append(unavailable_entry(
            "network_flows",
            f"Access denied to network connections: {exc}",
            "Run the agent with elevated privileges.",
        ))
        unavailable.append(unavailable_entry(
            "network_listeners",
            f"Access denied to network connections: {exc}",
            "Run the agent with elevated privileges.",
        ))
        return CollectorResult(None, unavailable, collectors, None)
    except Exception as exc:
        unavailable.append(unavailable_entry(
            "network_flows",
            f"Network connections unavailable: {exc}",
            "Run the agent with elevated privileges.",
        ))
        unavailable.append(unavailable_entry(
            "network_listeners",
            f"Network connections unavailable: {exc}",
            "Run the agent with elevated privileges.",
        ))
        return CollectorResult(None, unavailable, collectors, None)
    flows_map: Dict[str, Dict[str, Any]] = {}
    listeners: List[Dict[str, Any]] = []
    total_connections = 0
    tcp_connections = 0
    udp_connections = 0
    now = time.time()
    for conn in conns:
        proto = "tcp" if conn.type == socket.SOCK_STREAM else "udp"
        if proto == "tcp":
            tcp_connections += 1
        else:
            udp_connections += 1
        local_ip, local_port = _addr_to_tuple(conn.laddr)
        remote_ip, remote_port = _addr_to_tuple(conn.raddr)
        if not remote_ip:
            if local_port is not None:
                listeners.append({
                    "local_address": local_ip,
                    "local_port": local_port,
                    "protocol": proto,
                })
            continue
        total_connections += 1
        entry = flows_map.get(remote_ip)
        if not entry:
            entry = {
                "remote": remote_ip,
                "connections": 0,
                "remote_ports": set(),
                "local_ports": set(),
                "last_seen": now,
            }
            flows_map[remote_ip] = entry
        entry["connections"] += 1
        if remote_port is not None:
            entry["remote_ports"].add(remote_port)
        if local_port is not None:
            entry["local_ports"].add(local_port)
        entry["last_seen"] = now
    flows = []
    for entry in flows_map.values():
        entry["remote_ports"] = sorted(entry["remote_ports"])
        entry["local_ports"] = sorted(entry["local_ports"])
        flows.append(entry)
    flows.sort(key=lambda item: item.get("connections", 0), reverse=True)
    summary = {
        "total_connections": total_connections,
        "total_listeners": len(listeners),
        "tcp_connections": tcp_connections,
        "udp_connections": udp_connections,
    }
    data = {
        "flows": flows,
        "listeners": listeners,
        "summary": summary,
    }
    return CollectorResult(data, unavailable, collectors, now)


def parse_json(payload: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(payload)
    except Exception:
        return None
