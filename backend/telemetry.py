import os
import time
import platform
import ipaddress
import subprocess
from threading import Lock
from typing import Dict, List, Optional

try:
    import psutil
except ImportError:
    psutil = None


class TelemetryStore:
    def __init__(
        self,
        sample_interval: int = 5,
        history_seconds: int = 3600,
        flow_ttl: int = 5,
        disk_history_limit: int = 200,
        external_ttl: int = 10,
        firewall_log_path: Optional[str] = None,
    ):
        self.sample_interval = max(sample_interval, 1)
        self.history_seconds = max(history_seconds, 60)
        self.flow_ttl = max(flow_ttl, 1)
        self.disk_history_limit = max(disk_history_limit, 50)
        self.external_ttl = max(external_ttl, 1)
        self.firewall_log_path = firewall_log_path or os.getenv("FIREWALL_LOG_PATH", "")

        self._lock = Lock()
        self._latest_detail: Optional[Dict] = None
        self._latest_metrics_ts: float = 0.0
        self._metrics_history: List[Dict] = []
        self._disk_io_history: List[Dict] = []
        self._last_disk_counters = None
        self._last_disk_ts: Optional[float] = None
        self._last_net_counters = None
        self._last_net_ts: Optional[float] = None
        self._flow_cache = {"ts": 0.0, "flows": []}
        self._firewall_events: List[Dict] = []
        self._firewall_log_pos = 0
        self._firewall_log_inode: Optional[int] = None
        self._external_metrics_ts: Optional[float] = None
        self._external_disk_ts: Optional[float] = None
        self._external_flows_ts: Optional[float] = None
        self._external_flows: Optional[List[Dict]] = None
        self._external_disk_io: Optional[Dict] = None
        self._external_host: Optional[str] = None
        self._external_host_ip: Optional[str] = None
        self._external_seen: bool = False
        self._external_provenance: Optional[Dict] = None
        self._firewall_rules_ts: Optional[float] = None
        self._external_snapshot_ts: Optional[float] = None
        self._external_platform: Optional[str] = None
        self._external_host_id: Optional[str] = None
        self._external_unavailable: List[Dict] = []
        self._external_cpu: Optional[Dict] = None
        self._external_memory: Optional[Dict] = None
        self._external_disk: Optional[Dict] = None
        self._external_disk_io_detail: Optional[Dict] = None
        self._external_network: Optional[Dict] = None
        self._external_firewall: Optional[Dict] = None

    def _external_fresh(self, ts: Optional[float]) -> bool:
        return ts is not None and (time.time() - ts) <= self.external_ttl

    def ingest_external(self, payload: Dict) -> None:
        now = payload.get("ts") or time.time()
        self._external_seen = True
        provenance = payload.get("provenance")
        if isinstance(provenance, dict):
            self._external_provenance = provenance
        self._external_snapshot_ts = now
        unavailable = payload.get("unavailable")
        if isinstance(unavailable, list):
            self._external_unavailable = list(unavailable)
        host = payload.get("host")
        if host:
            self._external_host = host
        host_ip = payload.get("host_ip")
        if host_ip:
            self._external_host_ip = host_ip
        metrics = payload.get("metrics")
        if metrics:
            memory = metrics.get("memory") if isinstance(metrics, dict) else None
            disk = metrics.get("disk") if isinstance(metrics, dict) else None
            self._latest_detail = {
                "cpu": metrics.get("cpu"),
                "memory": memory,
                "disk": disk,
                "source": "external",
            }
            self._latest_metrics_ts = now
            self._external_metrics_ts = now
            mem_percent = memory.get("percent") if isinstance(memory, dict) else None
            disk_percent = disk.get("percent") if isinstance(disk, dict) else None
            self._metrics_history.append({
                "ts": now,
                "cpu": metrics.get("cpu"),
                "mem": mem_percent,
                "disk": disk_percent,
            })
            cutoff = now - self.history_seconds
            self._metrics_history = [p for p in self._metrics_history if p["ts"] >= cutoff]
        disk_io = payload.get("disk_io")
        if isinstance(disk_io, dict):
            point = dict(disk_io)
            point.setdefault("ts", now)
            point.setdefault("source", "external")
            self._external_disk_io = point
            self._external_disk_ts = point["ts"]
            self._disk_io_history.append(point)
            self._disk_io_history = self._disk_io_history[-self.disk_history_limit :]
        flows = payload.get("flows")
        if flows is not None:
            self._external_flows = list(flows)
            self._external_flows_ts = now

    def ingest_external_snapshot(self, payload: Dict) -> None:
        now = payload.get("timestamp") or time.time()
        self._external_seen = True
        self._external_snapshot_ts = now
        self._external_platform = payload.get("platform")
        self._external_host_id = payload.get("host_id")
        provenance = payload.get("provenance")
        if isinstance(provenance, dict):
            self._external_provenance = provenance
        unavailable = payload.get("unavailable")
        if isinstance(unavailable, list):
            self._external_unavailable = list(unavailable)
        else:
            self._external_unavailable = []
        self._external_cpu = payload.get("cpu") if isinstance(payload.get("cpu"), dict) else None
        self._external_memory = payload.get("memory") if isinstance(payload.get("memory"), dict) else None
        self._external_disk = payload.get("disk") if isinstance(payload.get("disk"), dict) else None
        self._external_network = payload.get("network") if isinstance(payload.get("network"), dict) else None
        self._external_firewall = payload.get("firewall") if isinstance(payload.get("firewall"), dict) else None
        if self._external_cpu or self._external_memory or self._external_disk:
            self._latest_detail = {
                "cpu": (self._external_cpu or {}).get("usage_percent"),
                "memory": self._external_memory,
                "disk": (self._external_disk or {}).get("usage"),
                "source": "external",
            }
        disk_io = None
        if isinstance(self._external_disk, dict):
            disk_io = self._external_disk.get("io")
        if isinstance(disk_io, dict):
            self._external_disk_io_detail = dict(disk_io)
            self._external_disk_ts = now
            point = dict(self._external_disk_io_detail)
            point.setdefault("ts", now)
            point.setdefault("source", "external")
            self._disk_io_history.append(point)
            self._disk_io_history = self._disk_io_history[-self.disk_history_limit :]
        self._external_metrics_ts = now if (self._external_cpu or self._external_memory or self._external_disk) else None
        if self._external_metrics_ts:
            cpu_val = (self._external_cpu or {}).get("usage_percent")
            mem_percent = (self._external_memory or {}).get("percent")
            disk_usage = (self._external_disk or {}).get("usage")
            disk_percent = disk_usage.get("percent") if isinstance(disk_usage, dict) else None
            self._metrics_history.append({
                "ts": now,
                "cpu": cpu_val,
                "mem": mem_percent,
                "disk": disk_percent,
            })
            cutoff = now - self.history_seconds
            self._metrics_history = [p for p in self._metrics_history if p["ts"] >= cutoff]
        if isinstance(self._external_network, dict) and self._external_network.get("flows") is not None:
            self._external_flows = list(self._external_network.get("flows", []))
            self._external_flows_ts = now

    def sample(self) -> Optional[Dict]:
        with self._lock:
            metrics = self._collect_metrics_locked()
            self._collect_disk_io_locked()
            self._ingest_firewall_log_locked()
            return metrics

    def get_metrics_detail(self) -> Optional[Dict]:
        with self._lock:
            now = time.time()
            if self._external_fresh(self._external_snapshot_ts) and (self._external_cpu or self._external_memory or self._external_disk):
                cpu = self._external_cpu or {}
                memory = self._external_memory
                disk = None
                if isinstance(self._external_disk, dict):
                    disk = self._external_disk.get("usage") or self._external_disk.get("usage_bytes")
                return {
                    "cpu": cpu.get("usage_percent"),
                    "cpu_per_core": cpu.get("per_core_percent"),
                    "load_avg": cpu.get("load_avg"),
                    "memory": memory,
                    "disk": disk,
                    "source": "external",
                }
            if self._latest_detail and self._latest_detail.get("source") == "external":
                metrics = self._collect_metrics_locked()
                if isinstance(metrics, dict):
                    metrics.setdefault("source", "local")
                return metrics
            if now - self._latest_metrics_ts > self.sample_interval:
                metrics = self._collect_metrics_locked()
                if isinstance(metrics, dict):
                    metrics.setdefault("source", "local")
                return metrics
            return self._latest_detail

    def get_metrics_history(
        self,
        from_ts: Optional[float],
        to_ts: Optional[float],
        resolution: int,
    ) -> List[Dict]:
        with self._lock:
            if not self._metrics_history:
                self._collect_metrics_locked()
            now = time.time() if to_ts is None else to_ts
            start = from_ts or max(now - self.history_seconds, 0)
            bucket = max(int(resolution), 15)
            points = [p for p in self._metrics_history if start <= p["ts"] <= now]
            if not points:
                return []
            buckets: Dict[int, Dict] = {}
            for p in points:
                idx = int((p["ts"] - start) / bucket)
                slot = buckets.setdefault(idx, {"ts": start + idx * bucket, "cpu": 0.0, "mem": 0.0, "disk": 0.0, "count": 0})
                slot["cpu"] += p.get("cpu") or 0.0
                slot["mem"] += p.get("mem") or 0.0
                slot["disk"] += p.get("disk") or 0.0
                slot["count"] += 1
            results = []
            for idx in sorted(buckets.keys()):
                slot = buckets[idx]
                count = max(slot["count"], 1)
                results.append({
                    "ts": slot["ts"],
                    "cpu": round(slot["cpu"] / count, 2),
                    "mem": round(slot["mem"] / count, 2),
                    "disk": round(slot["disk"] / count, 2),
                })
            return results

    def get_metrics_samples(self, limit: int = 300) -> List[Dict]:
        with self._lock:
            return list(self._metrics_history[-limit:])

    def get_network_flows(self, firewall_rules: List[Dict]) -> Dict:
        now = time.time()
        with self._lock:
            if self._external_fresh(self._external_snapshot_ts) and isinstance(self._external_network, dict):
                flows = self._external_network.get("flows")
                return {
                    "host": self._external_host_id or self._external_host or platform.node(),
                    "host_ip": self._external_host_ip,
                    "source": "external",
                    "flows": list(flows) if isinstance(flows, list) else [],
                    "listeners": self._external_network.get("listeners"),
                    "summary": self._external_network.get("summary"),
                }
            if self._external_seen and self._external_snapshot_ts:
                return {
                    "host": self._external_host_id or self._external_host or platform.node(),
                    "host_ip": self._external_host_ip,
                    "source": "external",
                    "note": "external flows unavailable",
                    "flows": [],
                    "listeners": [],
                }
            if now - self._flow_cache["ts"] <= self.flow_ttl:
                return {"host": platform.node(), "source": "local", "flows": list(self._flow_cache["flows"])}
        flows = self._collect_network_flows(firewall_rules)
        with self._lock:
            self._flow_cache = {"ts": now, "flows": flows}
        return {"host": platform.node(), "source": "local", "flows": flows}

    def get_disk_io(self) -> Dict:
        with self._lock:
            if self._external_fresh(self._external_snapshot_ts):
                if self._external_disk_io_detail:
                    return {"latest": dict(self._external_disk_io_detail), "history": list(self._disk_io_history), "source": "external"}
                return {
                    "latest": {
                        "iops": None,
                        "throughput_mb": None,
                        "note": "disk I/O data missing from external agent",
                    },
                    "history": [],
                    "source": "external",
                }
            point = self._collect_disk_io_locked()
            history = list(self._disk_io_history)
        return {"latest": point, "history": history, "source": "local"}

    def get_firewall_events(self, manual_events: List[Dict], limit: int = 50) -> List[Dict]:
        with self._lock:
            self._ingest_firewall_log_locked()
            combined = list(manual_events) + list(self._firewall_events)
        combined.sort(key=lambda x: x.get("ts", 0), reverse=True)
        return combined[: max(limit, 1)]

    def get_firewall_rules(self) -> List[Dict]:
        system = platform.system().lower()
        if system == "linux":
            rules = self._firewall_rules_linux()
        elif system == "darwin":
            rules = self._firewall_rules_macos()
        elif system == "windows":
            rules = self._firewall_rules_windows()
        else:
            rules = []
        if rules:
            self._firewall_rules_ts = time.time()
        return rules

    def get_last_success_times(self) -> Dict[str, Optional[float]]:
        with self._lock:
            return {
                "cpu": self._external_metrics_ts or self._latest_metrics_ts or None,
                "memory": self._external_metrics_ts or self._latest_metrics_ts or None,
                "disk": self._external_metrics_ts or self._latest_metrics_ts or None,
                "disk_io": self._external_disk_ts or self._last_disk_ts or None,
                "network_flows": self._external_flows_ts or self._flow_cache.get("ts") or None,
                "firewall_state": self._external_snapshot_ts or self._firewall_rules_ts,
            }

    def get_external_provenance(self) -> Optional[Dict]:
        with self._lock:
            return dict(self._external_provenance) if self._external_provenance else None

    def external_age_seconds(self) -> Optional[float]:
        with self._lock:
            if not self._external_snapshot_ts:
                return None
            return time.time() - self._external_snapshot_ts

    def external_fresh(self) -> bool:
        with self._lock:
            return self._external_fresh(self._external_snapshot_ts)

    def get_external_unavailable(self) -> List[Dict]:
        with self._lock:
            return list(self._external_unavailable)

    def get_external_platform(self) -> Optional[str]:
        with self._lock:
            return self._external_platform

    def get_external_firewall(self) -> Optional[Dict]:
        with self._lock:
            return dict(self._external_firewall) if isinstance(self._external_firewall, dict) else None

    def _collect_metrics_locked(self) -> Optional[Dict]:
        if not psutil:
            return None
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()._asdict()
        disk = psutil.disk_usage("/")._asdict()
        now = time.time()
        self._latest_detail = {"cpu": cpu, "memory": mem, "disk": disk, "source": "local"}
        self._latest_metrics_ts = now
        self._metrics_history.append({
            "ts": now,
            "cpu": cpu,
            "mem": mem.get("percent"),
            "disk": disk.get("percent"),
        })
        cutoff = now - self.history_seconds
        self._metrics_history = [p for p in self._metrics_history if p["ts"] >= cutoff]
        return self._latest_detail

    def _collect_network_flows(self, firewall_rules: List[Dict]) -> List[Dict]:
        if not psutil:
            return []
        now = time.time()
        bytes_in, bytes_out = self._estimate_network_bytes(now)
        try:
            conns = psutil.net_connections(kind="inet")
        except Exception:
            return []
        rules_by_ip = {}
        for rule in firewall_rules:
            ip = rule.get("source")
            if not ip:
                continue
            rules_by_ip.setdefault(ip, []).append(rule)
        flows: Dict[str, Dict] = {}
        for conn in conns:
            if not conn.raddr:
                continue
            remote_ip = getattr(conn.raddr, "ip", None) or conn.raddr[0]
            remote_port = getattr(conn.raddr, "port", None) or conn.raddr[1]
            local_ip = getattr(conn.laddr, "ip", None) if conn.laddr else None
            local_port = getattr(conn.laddr, "port", None) if conn.laddr else None
            flow = flows.get(remote_ip)
            if not flow:
                allowed = self._ip_allowed(remote_ip, rules_by_ip)
                threat = self._threat_score(remote_ip, allowed)
                flow = {
                    "remote": remote_ip,
                    "bytes_in": 0,
                    "bytes_out": 0,
                    "allowed": allowed,
                    "threat_score": threat,
                    "connections": 0,
                    "remote_ports": set(),
                    "local_ports": set(),
                    "last_seen": time.time(),
                }
                flows[remote_ip] = flow
            flow["connections"] += 1
            if remote_port is not None:
                flow["remote_ports"].add(remote_port)
            if local_port is not None:
                flow["local_ports"].add(local_port)
            flow["last_seen"] = time.time()
        result = []
        total_connections = sum(f["connections"] for f in flows.values()) or 0
        if total_connections > 0:
            for flow in flows.values():
                weight = flow["connections"] / total_connections
                flow["bytes_in"] = int(bytes_in * weight)
                flow["bytes_out"] = int(bytes_out * weight)
        for flow in flows.values():
            flow["remote_ports"] = sorted(flow["remote_ports"])
            flow["local_ports"] = sorted(flow["local_ports"])
            result.append(flow)
        return result

    def _collect_disk_io_locked(self) -> Dict:
        now = time.time()
        if not psutil:
            point = {"ts": now, "iops": None, "throughput_mb": None, "pressure": "unknown", "note": "psutil not installed"}
            self._disk_io_history.append(point)
            self._disk_io_history = self._disk_io_history[-self.disk_history_limit :]
            return point
        counters = psutil.disk_io_counters()
        if not counters:
            point = {"ts": now, "iops": None, "throughput_mb": None, "pressure": "unknown"}
            self._disk_io_history.append(point)
            self._disk_io_history = self._disk_io_history[-self.disk_history_limit :]
            return point
        if self._last_disk_counters and self._last_disk_ts:
            elapsed = max(now - self._last_disk_ts, 0.1)
            read_bytes = counters.read_bytes - self._last_disk_counters.read_bytes
            write_bytes = counters.write_bytes - self._last_disk_counters.write_bytes
            read_count = counters.read_count - self._last_disk_counters.read_count
            write_count = counters.write_count - self._last_disk_counters.write_count
            throughput_mb = (read_bytes + write_bytes) / (1024 * 1024) / elapsed
            iops = (read_count + write_count) / elapsed
        else:
            throughput_mb = 0.0
            iops = 0.0
        pressure = "low"
        if throughput_mb > 200 or iops > 2000:
            pressure = "high"
        elif throughput_mb > 80 or iops > 800:
            pressure = "medium"
        point = {
            "ts": now,
            "iops": round(iops, 2),
            "throughput_mb": round(throughput_mb, 2),
            "pressure": pressure,
        }
        self._last_disk_counters = counters
        self._last_disk_ts = now
        self._disk_io_history.append(point)
        self._disk_io_history = self._disk_io_history[-self.disk_history_limit :]
        return point

    def _ingest_firewall_log_locked(self) -> None:
        path = self.firewall_log_path
        if not path or not os.path.exists(path):
            return
        try:
            stat = os.stat(path)
            inode = stat.st_ino
            if self._firewall_log_inode is None or inode != self._firewall_log_inode:
                self._firewall_log_pos = 0
                self._firewall_log_inode = inode
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(self._firewall_log_pos)
                for line in handle:
                    line_lower = line.lower()
                    action = None
                    if "deny" in line_lower or "block" in line_lower or "drop" in line_lower:
                        action = "deny"
                    elif "allow" in line_lower or "accept" in line_lower or "pass" in line_lower:
                        action = "allow"
                    if not action:
                        continue
                    ip = self._extract_ip(line)
                    event = {"ts": time.time(), "ip": ip, "action": action, "source": "log"}
                    self._firewall_events.append(event)
                self._firewall_log_pos = handle.tell()
            self._firewall_events = self._firewall_events[-500:]
        except Exception:
            return

    def _extract_ip(self, line: str) -> Optional[str]:
        parts = line.split()
        for part in parts:
            candidate = part.strip("()[],:;")
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except Exception:
                continue
        return None

    def _estimate_network_bytes(self, now: float) -> tuple[int, int]:
        if not psutil:
            return (0, 0)
        counters = psutil.net_io_counters()
        if not counters:
            return (0, 0)
        if self._last_net_counters and self._last_net_ts:
            elapsed = max(now - self._last_net_ts, 0.1)
            bytes_in = counters.bytes_recv - self._last_net_counters.bytes_recv
            bytes_out = counters.bytes_sent - self._last_net_counters.bytes_sent
            # Normalize to per-sample window
            bytes_in = max(int(bytes_in), 0)
            bytes_out = max(int(bytes_out), 0)
        else:
            bytes_in = 0
            bytes_out = 0
        self._last_net_counters = counters
        self._last_net_ts = now
        return (bytes_in, bytes_out)

    def _ip_allowed(self, ip: str, rules_by_ip: Dict[str, List[Dict]]) -> Optional[bool]:
        if not rules_by_ip:
            return None
        rules = rules_by_ip.get(ip, [])
        for rule in rules:
            if rule.get("action") == "deny":
                return False
        return True

    def _threat_score(self, ip: str, allowed: Optional[bool]) -> int:
        try:
            addr = ipaddress.ip_address(ip)
            if addr.is_loopback:
                base = 0
            elif addr.is_private:
                base = 5
            else:
                base = 30
        except Exception:
            base = 20
        if allowed is False:
            base = max(base, 80)
        return base

    def _firewall_rules_linux(self) -> List[Dict]:
        rules = []
        for cmd in (["nft", "list", "ruleset"], ["iptables", "-S"]):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            except Exception:
                continue
            lines = result.stdout.splitlines()
            for line in lines:
                entry = self._parse_firewall_rule_line(line)
                if entry:
                    rules.append(entry)
            if rules:
                break
        return rules

    def _firewall_rules_macos(self) -> List[Dict]:
        rules = []
        try:
            result = subprocess.run(["pfctl", "-t", "flightctrl_block", "-T", "show"], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                ip = self._extract_ip(line)
                if ip:
                    rules.append({
                        "id": f"pf-block-{ip}",
                        "source": ip,
                        "dest": "host",
                        "action": "deny",
                        "created_at": time.time(),
                    })
        except Exception:
            pass
        try:
            result = subprocess.run(["pfctl", "-sr"], capture_output=True, text=True, check=True)
        except Exception:
            return rules
        for line in result.stdout.splitlines():
            entry = self._parse_firewall_rule_line(line)
            if entry:
                rules.append(entry)
        return rules

    def _firewall_rules_windows(self) -> List[Dict]:
        rules = []
        try:
            result = subprocess.run(
                ["netsh", "advfirewall", "firewall", "show", "rule", "name=all"],
                capture_output=True,
                text=True,
                check=True,
            )
        except Exception:
            return rules
        for line in result.stdout.splitlines():
            entry = self._parse_firewall_rule_line(line)
            if entry:
                rules.append(entry)
        return rules

    def _parse_firewall_rule_line(self, line: str) -> Optional[Dict]:
        lower = line.lower()
        action = None
        if "deny" in lower or "drop" in lower or "block" in lower:
            action = "deny"
        elif "allow" in lower or "accept" in lower or "pass" in lower:
            action = "allow"
        if not action:
            return None
        ip = self._extract_ip(line) or "any"
        return {
            "id": f"sys-{abs(hash(line))}",
            "source": ip,
            "dest": "host",
            "action": action,
            "created_at": time.time(),
        }
