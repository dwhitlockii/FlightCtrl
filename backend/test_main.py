import os
import tempfile
import uuid
import time
from typing import Optional

from fastapi.testclient import TestClient

_temp_dir = tempfile.mkdtemp(prefix="flightctrl-test-")
os.environ["AUTH_REQUIRED"] = "true"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "adminpass"
os.environ["USERS_FILE"] = os.path.join(_temp_dir, "users.json")
os.environ["AUDIT_LOG_PATH"] = os.path.join(_temp_dir, "audit.log")
os.environ["RATE_LIMIT_PER_MINUTE"] = "10000"
os.environ["RATE_LIMIT_LOGIN_PER_MINUTE"] = "10000"

from main import app, caretaker_change_store  # noqa: E402
import main as app_main  # noqa: E402

caretaker_change_store.path = os.path.join(_temp_dir, "caretaker_changes.json")
app_main.user_store.ensure_bootstrap()

client = TestClient(app)
_auth_headers: Optional[dict] = None


def auth_headers() -> dict:
    global _auth_headers
    if _auth_headers is None:
        res = client.post("/api/auth/login", json={
            "username": os.environ["ADMIN_USERNAME"],
            "password": os.environ["ADMIN_PASSWORD"],
        })
        assert res.status_code == 200
        token = res.json()["access_token"]
        _auth_headers = {"Authorization": f"Bearer {token}"}
    return dict(_auth_headers)

def test_get_agents():
    response = client.get("/api/agents", headers=auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert "agent-1" in data
    assert data["agent-1"]["status"] == "idle"

def test_start_agent():
    response = client.post("/api/agents/agent-1/start", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["status"]["status"] == "running"

def test_assign_task_to_running_agent():
    # Ensure agent is running
    client.post("/api/agents/agent-1/start", headers=auth_headers())
    response = client.post("/api/agents/agent-1/assign", json={"task": "test-task"}, headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["status"]["task"] == "test-task"

def test_assign_task_to_idle_agent():
    client.post("/api/agents/agent-2/stop", headers=auth_headers())
    response = client.post("/api/agents/agent-2/assign", json={"task": "should-fail"}, headers=auth_headers())
    assert response.status_code == 400
    assert response.json()["detail"] == "Agent must be running to assign a task"

def test_stop_agent():
    client.post("/api/agents/agent-1/start", headers=auth_headers())
    response = client.post("/api/agents/agent-1/stop", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["status"]["status"] == "idle"
    assert response.json()["status"]["task"] is None

def test_get_individual_agent():
    response = client.get("/api/agents/agent-1", headers=auth_headers())
    assert response.status_code == 200
    assert "status" in response.json()

def test_agent_not_found():
    response = client.get("/api/agents/nonexistent", headers=auth_headers())
    assert response.status_code == 404
    assert response.json()["detail"] == "Agent not found"

def test_agent_learning_and_persistence():
    """Test agent learning, persistence, and reload (Redis or file fallback)."""
    agent_id = "agent-1"
    # Learn new data
    learn_data = {"foo": "bar", "count": 42}
    response = client.post(f"/api/agents/{agent_id}/learn", json={"data": learn_data}, headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["status"]["learning_state"]["foo"] == "bar"
    assert response.json()["status"]["learning_state"]["count"] == 42

    # Persist state
    response = client.post(f"/api/agents/{agent_id}/persist", json={"action": "save"}, headers=auth_headers())
    assert response.status_code == 200
    assert "persisted" in response.json()["message"]

    # Overwrite local state to test reload
    response = client.post(f"/api/agents/{agent_id}/learn", json={"data": {"foo": "baz"}}, headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["status"]["learning_state"]["foo"] == "baz"

    # Explicitly reset state to empty before reload (simulate restart)
    response = client.post(f"/api/agents/{agent_id}/learn", json={"data": {}}, headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["status"]["learning_state"] == {}

    # Reload state using new endpoint
    response = client.post(f"/api/agents/{agent_id}/reload", headers=auth_headers())
    assert response.status_code == 200
    # Should restore to previous persisted state
    assert response.json()["status"]["learning_state"]["foo"] == "bar"
    assert response.json()["status"]["learning_state"]["count"] == 42

    # Clean up: reset state
    client.post(f"/api/agents/{agent_id}/learn", json={"data": {}}, headers=auth_headers())
    client.post(f"/api/agents/{agent_id}/persist", json={"action": "save"}, headers=auth_headers())

def test_caretaker_propose_and_apply():
    """Test caretaker agent's propose and apply code change endpoints and log."""
    import main as app_main
    app_main.CARETAKER_API_KEY = None
    # Propose a change
    proposal = {"change_request": "Refactor agent learning logic"}
    response = client.post("/api/caretaker/propose", json=proposal, headers=auth_headers())
    assert response.status_code == 200
    assert "Proposed change" in response.json()["result"]
    change_id = response.json()["change"]["id"]

    approve_res = client.post(
        f"/api/caretaker/proposals/{change_id}/approve",
        json={"note": "ok"},
        headers=auth_headers(),
    )
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "approved"

    # Apply approved change
    response = client.post("/api/caretaker/apply", json={"change_id": change_id}, headers=auth_headers())
    assert response.status_code == 200
    assert "Applied change" in response.json()["result"]

    # Check log
    response = client.get("/api/caretaker/log", headers=auth_headers())
    assert response.status_code == 200
    log = response.json()["log"]
    assert log[-2]["action"] == "propose"
    assert log[-1]["action"] == "apply"
    assert log[-2]["request"] == "Refactor agent learning logic"
    assert log[-1]["request"] == "Refactor agent learning logic" 
    app_main.CARETAKER_API_KEY = None


def test_task_crud():
    """Ensure task lifecycle works end-to-end."""
    create_resp = client.post("/api/tasks", json={"agent_id": "agent-1", "description": "test task"}, headers=auth_headers())
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["status"] == "pending"

    list_resp = client.get("/api/tasks", headers=auth_headers())
    assert list_resp.status_code == 200
    tasks = list_resp.json()
    assert any(t["id"] == created["id"] for t in tasks)

    update_resp = client.put(f"/api/tasks/{created['id']}", json={"status": "in_progress"}, headers=auth_headers())
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["status"] == "in_progress"


def test_caretaker_requires_key_when_configured():
    import main as app_main
    app_main.CARETAKER_API_KEY = "secret"
    res = client.post("/api/caretaker/propose", json={"change_request": "x"}, headers=auth_headers())
    assert res.status_code == 401
    res2 = client.post(
        "/api/caretaker/propose",
        json={"change_request": "x"},
        headers={**auth_headers(), "x-api-key": "secret"},
    )
    assert res2.status_code == 200
    app_main.CARETAKER_API_KEY = None


def test_auth_login_and_refresh():
    res = client.post("/api/auth/login", json={
        "username": os.environ["ADMIN_USERNAME"],
        "password": os.environ["ADMIN_PASSWORD"],
    })
    assert res.status_code == 200
    data = res.json()
    assert data["access_token"]
    refresh_res = client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert refresh_res.status_code == 200
    refreshed = refresh_res.json()
    assert refreshed["access_token"]


def test_role_gating_for_operator_endpoints():
    username = f"viewer-{uuid.uuid4().hex[:8]}"
    create_res = client.post(
        "/api/auth/users",
        json={"username": username, "password": "viewerpass", "role": "viewer"},
        headers=auth_headers(),
    )
    assert create_res.status_code == 200
    login_res = client.post("/api/auth/login", json={"username": username, "password": "viewerpass"})
    assert login_res.status_code == 200
    viewer_headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}
    deny_res = client.post("/api/agents/agent-1/start", headers=viewer_headers)
    assert deny_res.status_code == 403
    allow_res = client.get("/api/agents", headers=viewer_headers)
    assert allow_res.status_code == 200


def test_capabilities_schema():
    res = client.get("/api/capabilities", headers=auth_headers())
    assert res.status_code == 200
    data = res.json()
    assert data.get("platform") in {"windows", "linux", "macos", "unknown"}
    matrix = data.get("matrix")
    assert isinstance(matrix, dict)
    for platform_key in ("windows", "linux", "macos"):
        assert platform_key in matrix
        caps = matrix[platform_key]
        for cap in ("cpu", "memory", "disk_io", "network_flows", "firewall_state", "firewall_enforcement"):
            assert cap in caps
            status = caps[cap].get("status")
            assert status in {"AVAILABLE", "PARTIAL", "UNAVAILABLE"}


def test_provenance_shape_metrics():
    res = client.get("/api/metrics", headers=auth_headers())
    assert res.status_code == 200
    data = res.json()
    assert "platform" in data
    assert "source_type" in data
    assert "freshness_seconds" in data
    provenance = data.get("provenance")
    assert isinstance(provenance, dict)
    assert provenance.get("source_type") in {"external_agent", "local_fallback"}
    assert isinstance(provenance.get("collectors", []), list)
    assert provenance.get("privilege_level") in {"user", "elevated", "unknown"}
    assert isinstance(provenance.get("last_success_at"), dict)


def _sample_ingest_payload() -> dict:
    now = time.time()
    return {
        "timestamp": now,
        "platform": "linux",
        "host_id": "test-host",
        "source": "external",
        "cpu": {
            "usage_percent": 42.5,
            "per_core_percent": [40.0, 45.0],
            "load_avg": [0.1, 0.2, 0.3],
            "top_processes": [
                {"pid": 100, "name": "python", "cpu_percent": 12.5},
            ],
        },
        "memory": {
            "total": 1024,
            "used": 512,
            "available": 512,
            "free": 256,
            "percent": 50.0,
            "swap_total": 256,
            "swap_used": 10,
            "swap_free": 246,
            "swap_percent": 3.9,
            "top_processes": [
                {"pid": 200, "name": "worker", "rss": 2048},
            ],
        },
        "disk": {
            "usage": {"total": 2048, "used": 1024, "free": 1024, "percent": 50.0},
            "io": {"iops": 10.0, "throughput_mb": 1.2},
        },
        "network": {
            "flows": [
                {
                    "remote": "1.2.3.4",
                    "connections": 2,
                    "remote_ports": [443],
                    "local_ports": [51515],
                    "last_seen": now,
                }
            ],
            "listeners": [
                {"local_address": "0.0.0.0", "local_port": 8000, "protocol": "tcp"}
            ],
            "summary": {
                "total_connections": 2,
                "total_listeners": 1,
                "tcp_connections": 2,
                "udp_connections": 0,
            },
        },
        "firewall": {"enabled": True, "backend": "ufw", "rule_count": 3, "raw": "ok"},
        "provenance": {
            "platform": "linux",
            "host_id": "test-host",
            "privilege_level": "user",
            "collectors": ["psutil"],
            "collectors_by_subsystem": {"cpu": ["psutil"]},
            "last_success_at": {"cpu": now},
        },
        "unavailable": [
            {
                "metric": "cpu_load_avg",
                "reason": "not supported",
                "remediation": "use per-core CPU usage",
            }
        ],
    }


def test_telemetry_ingest_external_fresh():
    payload = _sample_ingest_payload()
    res = client.post("/api/telemetry/ingest", json=payload, headers=auth_headers())
    assert res.status_code == 200
    metrics = client.get("/api/metrics", headers=auth_headers())
    assert metrics.status_code == 200
    data = metrics.json()
    assert data["source_type"] == "external_agent"
    assert data["cpu"] == payload["cpu"]["usage_percent"]
    assert any(item["metric"] == "cpu_load_avg" for item in data.get("unavailable", []))


def test_telemetry_fallback_when_external_stale():
    payload = _sample_ingest_payload()
    client.post("/api/telemetry/ingest", json=payload, headers=auth_headers())
    import main as app_main
    app_main.telemetry_store._external_snapshot_ts = time.time() - 999
    metrics = client.get("/api/metrics", headers=auth_headers())
    assert metrics.status_code == 200
    assert metrics.json()["source_type"] == "local_fallback"


def test_diagnostics_reports_external_age():
    payload = _sample_ingest_payload()
    client.post("/api/telemetry/ingest", json=payload, headers=auth_headers())
    diag = client.get("/api/diagnostics", headers=auth_headers())
    assert diag.status_code == 200
    body = diag.json()
    assert body["source_type"] in {"external_agent", "local_fallback"}
    assert body["freshness_threshold_seconds"] is not None
