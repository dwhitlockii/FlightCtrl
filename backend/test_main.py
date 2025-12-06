from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_get_agents():
    response = client.get("/api/agents")
    assert response.status_code == 200
    data = response.json()
    assert "agent-1" in data
    assert data["agent-1"]["status"] == "idle"

def test_start_agent():
    response = client.post("/api/agents/agent-1/start")
    assert response.status_code == 200
    assert response.json()["status"]["status"] == "running"

def test_assign_task_to_running_agent():
    # Ensure agent is running
    client.post("/api/agents/agent-1/start")
    response = client.post("/api/agents/agent-1/assign", json={"task": "test-task"})
    assert response.status_code == 200
    assert response.json()["status"]["task"] == "test-task"

def test_assign_task_to_idle_agent():
    client.post("/api/agents/agent-2/stop")
    response = client.post("/api/agents/agent-2/assign", json={"task": "should-fail"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Agent must be running to assign a task"

def test_stop_agent():
    client.post("/api/agents/agent-1/start")
    response = client.post("/api/agents/agent-1/stop")
    assert response.status_code == 200
    assert response.json()["status"]["status"] == "idle"
    assert response.json()["status"]["task"] is None

def test_get_individual_agent():
    response = client.get("/api/agents/agent-1")
    assert response.status_code == 200
    assert "status" in response.json()

def test_agent_not_found():
    response = client.get("/api/agents/nonexistent")
    assert response.status_code == 404
    assert response.json()["detail"] == "Agent not found"

def test_agent_learning_and_persistence():
    """Test agent learning, persistence, and reload (Redis or file fallback)."""
    agent_id = "agent-1"
    # Learn new data
    learn_data = {"foo": "bar", "count": 42}
    response = client.post(f"/api/agents/{agent_id}/learn", json={"data": learn_data})
    assert response.status_code == 200
    assert response.json()["status"]["learning_state"]["foo"] == "bar"
    assert response.json()["status"]["learning_state"]["count"] == 42

    # Persist state
    response = client.post(f"/api/agents/{agent_id}/persist", json={"action": "save"})
    assert response.status_code == 200
    assert "persisted" in response.json()["message"]

    # Overwrite local state to test reload
    response = client.post(f"/api/agents/{agent_id}/learn", json={"data": {"foo": "baz"}})
    assert response.status_code == 200
    assert response.json()["status"]["learning_state"]["foo"] == "baz"

    # Explicitly reset state to empty before reload (simulate restart)
    response = client.post(f"/api/agents/{agent_id}/learn", json={"data": {}})
    assert response.status_code == 200
    assert response.json()["status"]["learning_state"] == {}

    # Reload state using new endpoint
    response = client.post(f"/api/agents/{agent_id}/reload")
    assert response.status_code == 200
    # Should restore to previous persisted state
    assert response.json()["status"]["learning_state"]["foo"] == "bar"
    assert response.json()["status"]["learning_state"]["count"] == 42

    # Clean up: reset state
    client.post(f"/api/agents/{agent_id}/learn", json={"data": {}})
    client.post(f"/api/agents/{agent_id}/persist", json={"action": "save"})

def test_caretaker_propose_and_apply():
    """Test caretaker agent's propose and apply code change endpoints and log."""
    # Ensure no auth required in this test
    import main as app_main
    app_main.CARETAKER_API_KEY = None
    # Propose a change
    proposal = {"change_request": "Refactor agent learning logic"}
    response = client.post("/api/caretaker/propose", json=proposal)
    assert response.status_code == 200
    assert "Proposed change" in response.json()["result"]

    # Apply a change
    apply = {"change_request": "Add monitoring endpoint"}
    response = client.post("/api/caretaker/apply", json=apply)
    assert response.status_code == 200
    assert "Applied change" in response.json()["result"]

    # Check log
    response = client.get("/api/caretaker/log")
    assert response.status_code == 200
    log = response.json()["log"]
    assert log[-2]["action"] == "propose"
    assert log[-1]["action"] == "apply"
    assert log[-2]["request"] == "Refactor agent learning logic"
    assert log[-1]["request"] == "Add monitoring endpoint" 


def test_task_crud():
    """Ensure task lifecycle works end-to-end."""
    create_resp = client.post("/api/tasks", json={"agent_id": "agent-1", "description": "test task"})
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["status"] == "pending"

    list_resp = client.get("/api/tasks")
    assert list_resp.status_code == 200
    tasks = list_resp.json()
    assert any(t["id"] == created["id"] for t in tasks)

    update_resp = client.put(f"/api/tasks/{created['id']}", json={"status": "in_progress"})
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["status"] == "in_progress"


def test_caretaker_requires_key_when_configured():
    import main as app_main
    app_main.CARETAKER_API_KEY = "secret"
    res = client.post("/api/caretaker/propose", json={"change_request": "x"})
    assert res.status_code == 401
    res2 = client.post(
        "/api/caretaker/propose",
        json={"change_request": "x"},
        headers={"x-api-key": "secret"},
    )
    assert res2.status_code == 200
    app_main.CARETAKER_API_KEY = None
