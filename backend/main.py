"""
FlightCtrl Backend Entrypoint
- FastAPI app for agent orchestration and real-time API
- WebSocket endpoint for agent/user chat
- REST endpoint for agent status
- Ollama integration placeholder
- Agent lifecycle management placeholder
- CORS enabled for frontend
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import List, Optional, Dict
import asyncio
import contextlib
from pydantic import BaseModel
import os
import httpx
import uuid
import json
import redis
from urllib.parse import urlparse
from threading import Lock
import contextlib
try:
    import psutil
except ImportError:
    psutil = None
import platform
import time
import importlib.util
import glob
from contextlib import asynccontextmanager

# Configure CORS early (cannot add middleware after startup)
raw_origins = os.getenv("FRONTEND_ORIGINS", "")
allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
if not allowed_origins:
    allowed_origins = ["http://localhost:5173"]

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

redis_client: Optional[redis.Redis] = None
CARETAKER_API_KEY: Optional[str] = None
latest_metrics: Dict = {"cpu": None, "mem": None, "disk": None}
event_log_store: Dict[str, list] = {}
network_flow_cache: List[Dict] = []
disk_io_history: List[Dict] = []
firewall_rules: List[Dict] = []
firewall_events: List[Dict] = []
timeline_events: List[Dict] = []
personality_map: Dict[str, str] = {
    "orchestrator": "Calm coordinator synthesizing inputs and directing specialists.",
    "loadwatch": "Performance hawk, loves load shedding and tuning.",
    "netseer": "Network seer, watches flows and anomalies.",
    "taskwarden": "Planner and task router, prioritizes ruthlessly.",
    "sentinel": "Security-first, suspicious by default.",
    "ioguard": "IO guardian, tracks disk and throughput pressures.",
    "memsmith": "Memory artisan, hunts leaks and fragmentation.",
    "firebreak": "Firewall enforcer, blocks threats without hesitation.",
    "caretaker": "Self-modifier and maintainer of the codebase.",
}

def require_caretaker_key(request: Request):
    if CARETAKER_API_KEY:
        supplied = request.headers.get("x-api-key")
        if supplied != CARETAKER_API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Redis Setup ---
    global redis_client
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    parsed_redis = urlparse(REDIS_URL)
    if parsed_redis.scheme not in {"redis", "rediss"}:
        raise ValueError("REDIS_URL must start with redis:// or rediss://")
    try:
        redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
        print(f"[Redis] Connected to {REDIS_URL}")
    except Exception as e:
        redis_client = None
        print(f"[Redis] Connection failed: {e}. Will use file-based fallback.")

    # Caretaker auth (optional API key)
    global CARETAKER_API_KEY
    CARETAKER_API_KEY = os.getenv("CARETAKER_API_KEY")

    # Hand redis to task store if available
    task_store.redis = redis_client

    # Start Ollama client
    await ollama_client.startup()
    # Kick off telemetry chatter
    global metrics_broadcaster_task, automation_runner_task
    metrics_broadcaster_task = asyncio.create_task(background_chatter())
    automation_runner_task = asyncio.create_task(automation_runner())
    yield
    # Shutdown Ollama client
    await ollama_client.shutdown()
    if metrics_broadcaster_task:
        metrics_broadcaster_task.cancel()
        with contextlib.suppress(Exception):
            await metrics_broadcaster_task
    if automation_runner_task:
        automation_runner_task.cancel()
        with contextlib.suppress(Exception):
            await automation_runner_task

app.router.lifespan_context = lifespan

# --- Agent System ---
class Agent:
    def __init__(self, agent_id: str, role: str = "standard"):
        self.agent_id = agent_id
        self.role = role  # 'standard' or 'caretaker'
        self.status = "idle"
        self.task: Optional[str] = None
        self.last_ollama_response: Optional[str] = None
        self.learning_state: Dict = {}
        self.logs = []

    def start(self):
        self.status = "running"

    def stop(self):
        self.status = "idle"
        self.task = None

    def assign_task(self, task: str):
        if self.status != "running":
            raise Exception("Agent must be running to assign a task")
        self.task = task

    def learn(self, data):
        # Update learning_state with new data
        if not isinstance(data, dict):
            raise ValueError("Learning data must be a dictionary.")
        if data == {}:
            self.learning_state = {}
        else:
            # Track notes for transparency
            notes = self.learning_state.get("notes", [])
            summary = data.get("summary") or f"Observed: {list(data.keys())}"
            usage = data.get("usage") or "Use to refine monitoring/decisions."
            notes.append({"ts": time.time(), "summary": summary, "usage": usage})
            self.learning_state["notes"] = notes[-50:]  # cap history
            self.learning_state.update({k: v for k, v in data.items() if k not in {"summary", "usage"}})
        add_agent_event(self.agent_id, "info", f"Learning updated: {data.get('summary', 'n/a')}")
        print(f"[Agent:{self.agent_id}] Learning state updated")

    def persist_state(self):
        # Persist agent state to Redis if available, else to a JSON file
        try:
            state_json = json.dumps(self.learning_state)
            if redis_client:
                redis_client.set(f"agent:{self.agent_id}:state", state_json)
                print(f"[Agent:{self.agent_id}] State persisted to Redis.")
            else:
                filename = f"agent_state_{self.agent_id}.json"
                with open(filename, "w") as f:
                    f.write(state_json)
                print(f"[Agent:{self.agent_id}] State persisted to {filename}")
        except Exception as e:
            print(f"[Agent:{self.agent_id}] Persist error: {e}")
            raise

    def load_state(self):
        # Load agent state from Redis if available, else from a JSON file
        try:
            if redis_client:
                state_json = redis_client.get(f"agent:{self.agent_id}:state")
                if state_json:
                    self.learning_state = json.loads(state_json)
                    print(f"[Agent:{self.agent_id}] State loaded from Redis.")
                else:
                    print(f"[Agent:{self.agent_id}] No persisted state in Redis, starting fresh.")
                    self.learning_state = {}
            else:
                filename = f"agent_state_{self.agent_id}.json"
                with open(filename, "r") as f:
                    self.learning_state = json.load(f)
                print(f"[Agent:{self.agent_id}] State loaded from {filename}")
        except FileNotFoundError:
            print(f"[Agent:{self.agent_id}] No persisted state found, starting fresh.")
            self.learning_state = {}
        except Exception as e:
            print(f"[Agent:{self.agent_id}] Load error: {e}")
            raise

    def to_dict(self):
        notes = self.learning_state.get("notes", [])
        mood = compute_mood(latest_metrics)
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "status": self.status,
            "task": self.task,
            "last_ollama_response": self.last_ollama_response,
            "learning_state": self.learning_state,
            "mood": mood,
            "last_notes": notes[-5:] if isinstance(notes, list) else [],
            "personality": personality_map.get(self.agent_id, ""),
        }

# Caretaker agent with code modification hooks
PLUGIN_DIR = os.path.join(os.path.dirname(__file__), "plugins")

class CaretakerAgent(Agent):
    def __init__(self, agent_id: str):
        super().__init__(agent_id, role="caretaker")
        self.change_log = []  # Track all proposals and applications
        self.plugins = self.load_plugins()

    def load_plugins(self):
        plugins = {}
        for path in glob.glob(os.path.join(PLUGIN_DIR, "*.py")):
            name = os.path.splitext(os.path.basename(path))[0]
            spec = importlib.util.spec_from_file_location(name, path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                plugins[name] = mod
        return plugins

    def run_plugin(self, plugin_name, *args, **kwargs):
        plugin = self.plugins.get(plugin_name)
        if plugin and hasattr(plugin, "run"):
            return plugin.run(*args, **kwargs)
        raise ValueError(f"Plugin {plugin_name} not found or missing 'run' function.")

    def propose_code_change(self, change_request: str):
        # Log the proposal
        entry = {"action": "propose", "request": change_request}
        self.change_log.append(entry)
        print(f"[Caretaker] Proposed change: {change_request}")
        return f"[Caretaker] Proposed change: {change_request}"

    def apply_code_change(self, change_request: str):
        # Log the application (actual code change logic would be more complex)
        entry = {"action": "apply", "request": change_request}
        self.change_log.append(entry)
        print(f"[Caretaker] Applied change: {change_request}")
        return f"[Caretaker] Applied change: {change_request}"

    def get_change_log(self):
        return self.change_log

# --- Agent Registry ---
class AgentRegistry:
    def __init__(self):
        self.agents: Dict[str, Agent] = {}
        self._init_default_agents()

    def _init_default_agents(self):
        profiles = [
            ("agent-1", "standard"),
            ("agent-2", "standard"),
            ("agent-3", "standard"),
            ("orchestrator", "orchestrator"),
            ("loadwatch", "performance"),
            ("netseer", "network"),
            ("taskwarden", "tasks"),
            ("sentinel", "security"),
            ("ioguard", "io"),
            ("memsmith", "memory"),
            ("firebreak", "firewall"),
            ("caretaker", "caretaker"),
        ]
        self.agents = {aid: (CaretakerAgent(aid) if role == "caretaker" else Agent(aid, role=role)) for aid, role in profiles}

    def get(self, agent_id: str) -> Agent:
        if agent_id not in self.agents:
            raise HTTPException(status_code=404, detail="Agent not found")
        return self.agents[agent_id]

    def all(self):
        return [agent.to_dict() for agent in self.agents.values()]

agent_registry = AgentRegistry()

# --- Task System ---
TASKS_FILE = os.path.join(os.path.dirname(__file__), "tasks.json")

class StatusEntry(BaseModel):
    status: str
    ts: float
    note: str | None = None


class Task(BaseModel):
    id: str
    agent_id: str
    description: str
    status: str  # pending | in_progress | completed | failed
    priority: str = "normal"  # low | normal | high | critical
    status_history: List[StatusEntry] = []
    messages: List[Dict] = []
    created_at: float
    updated_at: float

class TaskCreateRequest(BaseModel):
    agent_id: str
    description: str
    priority: str = "normal"


class TaskUpdateRequest(BaseModel):
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    note: Optional[str] = None

class TaskStore:
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.lock = Lock()

    def _load_tasks_file(self) -> Dict[str, dict]:
        if not os.path.exists(TASKS_FILE):
            return {}
        try:
            with open(TASKS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_tasks_file(self, data: Dict[str, dict]):
        with open(TASKS_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def _load_all(self) -> Dict[str, dict]:
        if self.redis:
            try:
                entries = self.redis.hgetall("tasks")
                return {k: json.loads(v) for k, v in entries.items()}
            except Exception:
                pass
        return self._load_tasks_file()

    def _persist_all(self, data: Dict[str, dict]):
        if self.redis:
            try:
                # Replace entire hash for simplicity
                pipe = self.redis.pipeline()
                pipe.delete("tasks")
                if data:
                    pipe.hset("tasks", mapping={k: json.dumps(v) for k, v in data.items()})
                pipe.execute()
                return
            except Exception:
                pass
        self._save_tasks_file(data)

    def create(self, agent_id: str, description: str, priority: str = "normal") -> Task:
        with self.lock:
            tasks = self._load_all()
            task_id = str(uuid.uuid4())
            now = time.time()
            task = Task(
                id=task_id,
                agent_id=agent_id,
                description=description,
                status="pending",
                priority=priority if priority in {"low", "normal", "high", "critical"} else "normal",
                status_history=[StatusEntry(status="pending", ts=now)],
                messages=[],
                created_at=now,
                updated_at=now,
            )
            tasks[task_id] = task.model_dump()
            self._persist_all(tasks)
            return task

    def all(self) -> List[Task]:
        with self.lock:
            tasks = self._load_all()
            return [Task(**t) for t in tasks.values()]

    def get(self, task_id: str) -> Task:
        with self.lock:
            tasks = self._load_all()
            if task_id not in tasks:
                raise HTTPException(status_code=404, detail="Task not found")
            return Task(**tasks[task_id])

    def update(self, task_id: str, description: Optional[str], status: Optional[str], priority: Optional[str], note: Optional[str]) -> Task:
        with self.lock:
            tasks = self._load_all()
            if task_id not in tasks:
                raise HTTPException(status_code=404, detail="Task not found")
            task_data = tasks[task_id]
            if description is not None:
                task_data["description"] = description
            if priority is not None:
                if priority not in {"low", "normal", "high", "critical"}:
                    raise HTTPException(status_code=400, detail="Invalid priority")
                task_data["priority"] = priority
            if status is not None:
                if status not in {"pending", "in_progress", "completed", "failed"}:
                    raise HTTPException(status_code=400, detail="Invalid status")
                task_data["status"] = status
                history = task_data.get("status_history") or []
                history.append(StatusEntry(status=status, ts=time.time(), note=note).model_dump())
                task_data["status_history"] = history[-20:]
            task_data["updated_at"] = time.time()
            tasks[task_id] = task_data
            self._persist_all(tasks)
            return Task(**task_data)

    def add_message(self, task_id: str, role: str, content: str):
        with self.lock:
            tasks = self._load_all()
            if task_id not in tasks:
                raise HTTPException(status_code=404, detail="Task not found")
            task_data = tasks[task_id]
            messages = task_data.get("messages") or []
            msg = {"id": str(uuid.uuid4()), "role": role, "content": content, "ts": time.time()}
            messages.append(msg)
            task_data["messages"] = messages[-100:]
            task_data["updated_at"] = time.time()
            tasks[task_id] = task_data
            self._persist_all(tasks)
            return msg

task_store = TaskStore(redis_client)

# --- Automations ---
AUTOMATIONS_FILE = os.path.join(os.path.dirname(__file__), "automations.json")


class Automation(BaseModel):
    id: str
    name: str
    trigger: Dict
    action: Dict
    enabled: bool = True
    last_run: Optional[float] = None
    error: Optional[str] = None


class AutomationStore:
    def __init__(self):
        self.lock = Lock()

    def _load(self) -> Dict[str, dict]:
        if not os.path.exists(AUTOMATIONS_FILE):
            return {}
        with open(AUTOMATIONS_FILE, "r") as f:
            try:
                return json.load(f)
            except Exception:
                return {}

    def _save(self, data: Dict[str, dict]):
        with open(AUTOMATIONS_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def list(self) -> List[Automation]:
        with self.lock:
            data = self._load()
            return [Automation(**v) for v in data.values()]

    def create(self, name: str, trigger: Dict, action: Dict) -> Automation:
        with self.lock:
            data = self._load()
            auto_id = str(uuid.uuid4())
            auto = Automation(id=auto_id, name=name, trigger=trigger, action=action)
            data[auto_id] = auto.model_dump()
            self._save(data)
            return auto

    def update(self, auto_id: str, **fields) -> Automation:
        with self.lock:
            data = self._load()
            if auto_id not in data:
                raise HTTPException(status_code=404, detail="Automation not found")
            obj = data[auto_id]
            obj.update({k: v for k, v in fields.items() if v is not None})
            data[auto_id] = obj
            self._save(data)
            return Automation(**obj)

    def set_enabled(self, auto_id: str, enabled: bool) -> Automation:
        return self.update(auto_id, enabled=enabled)


automation_store = AutomationStore()

# Evaluate and run automations in background
def _metric_value(metric_key: str):
    if metric_key == "cpu":
        return latest_metrics.get("cpu")
    if metric_key == "mem":
        return latest_metrics.get("mem")
    if metric_key == "disk":
        return latest_metrics.get("disk")
    if metric_key == "iops":
        disk = latest_metrics.get("disk") or {}
        return disk.get("iops") if isinstance(disk, dict) else None
    return None


async def run_automation_action(auto: Automation):
    action = auto.action or {}
    kind = action.get("type")
    if kind == "notify":
        agent_id = action.get("agent_id", "orchestrator")
        message = action.get("message", f"Automation {auto.name} fired")
        add_agent_event(agent_id, "info", message)
    elif kind == "create_task":
        agent_id = action.get("agent_id", "taskwarden")
        description = action.get("description", f"Automation task from {auto.name}")
        priority = action.get("priority", "normal")
        task_store.create(agent_id, description, priority=priority)
    elif kind == "restart_agent":
        agent_id = action.get("agent_id")
        if agent_id:
            agent = agent_registry.get(agent_id)
            with contextlib.suppress(Exception):
                agent.stop()
            with contextlib.suppress(Exception):
                agent.start()
            add_agent_event(agent_id, "info", f"Automation restarted {agent_id}")


async def automation_runner():
    while True:
        await asyncio.sleep(5)
        for auto in automation_store.list():
            if not auto.enabled:
                continue
            should_fire = False
            trg = auto.trigger or {}
            t_type = trg.get("type")
            now = time.time()
            if t_type == "interval":
                interval = float(trg.get("seconds", 60))
                if auto.last_run is None or now - auto.last_run >= interval:
                    should_fire = True
            elif t_type == "metric_threshold":
                metric_key = trg.get("metric")
                threshold = trg.get("gt") or trg.get("gte")
                value = _metric_value(metric_key)
                if value is not None and threshold is not None and value >= float(threshold):
                    # simple cooldown of 60s
                    if auto.last_run is None or now - auto.last_run >= float(trg.get("cooldown", 60)):
                        should_fire = True
            if should_fire:
                try:
                    await run_automation_action(auto)
                    automation_store.update(auto.id, last_run=now, error=None)
                except Exception as e:
                    automation_store.update(auto.id, last_run=now, error=str(e))

# WebSocket manager for real-time chat
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        stale = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.disconnect(connection)

manager = ConnectionManager()

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type in {"agent_typing", "agent_thinking"}:
                await manager.broadcast(data)
                continue
            # Route message to agent if agent_id is present
            agent_id = data.get("agent_id")
            prompt = data.get("prompt")
            model = data.get("model", "llama3")
            if agent_id and prompt:
                agent = agent_registry.get(agent_id)
                # Use Ollama LLM for agent response
                result = await ollama_client.chat(prompt, model)
                agent.last_ollama_response = result
                response = {
                    "role": "agent",
                    "agent_id": agent_id,
                    "response": result,
                    "messageId": str(uuid.uuid4()),
                    "parentId": data.get("parentId"),
                    "incidentId": data.get("incidentId"),
                }
                await manager.broadcast(response)
                # Relay to other agents to simulate agent-to-agent chatter
                for other_id in agent_registry.agents.keys():
                    if other_id == agent_id:
                        continue
                    relay = {
                        "role": "agent",
                        "agent_id": other_id,
                        "response": f"[from {agent_id}] {result}",
                    }
                    await manager.broadcast(relay)
            else:
                # Broadcast as-is if not agent-specific
                await manager.broadcast(data)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/api/agents")
def get_agents():
    """Return status of all agents."""
    return JSONResponse(content={a["agent_id"]: a for a in agent_registry.all()})

class AgentCommand(BaseModel):
    task: str = None

@app.post("/api/agents/{agent_id}/start")
def start_agent(agent_id: str):
    agent = agent_registry.get(agent_id)
    agent.start()
    return {"message": f"{agent_id} started", "status": agent.to_dict()}

@app.post("/api/agents/{agent_id}/stop")
def stop_agent(agent_id: str):
    agent = agent_registry.get(agent_id)
    agent.stop()
    return {"message": f"{agent_id} stopped", "status": agent.to_dict()}

@app.post("/api/agents/{agent_id}/assign")
def assign_task(agent_id: str, command: AgentCommand):
    agent = agent_registry.get(agent_id)
    try:
        agent.assign_task(command.task)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": f"Task assigned to {agent_id}", "status": agent.to_dict()}

@app.get("/api/agents/{agent_id}")
def get_agent(agent_id: str):
    agent = agent_registry.get(agent_id)
    return agent.to_dict()

# --- Task endpoints ---
@app.get("/api/tasks")
def list_tasks():
    tasks = task_store.all()
    return [t.model_dump() for t in tasks]

@app.post("/api/tasks")
def create_task(request: TaskCreateRequest):
    # Ensure agent exists
    agent_registry.get(request.agent_id)
    task = task_store.create(request.agent_id, request.description, priority=request.priority)
    add_agent_event(request.agent_id, "task", f"Task created: {request.description}")
    return task.model_dump()

@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    task = task_store.get(task_id)
    return task.model_dump()

@app.put("/api/tasks/{task_id}")
def update_task(task_id: str, request: TaskUpdateRequest):
    task = task_store.update(task_id, request.description, request.status, request.priority, request.note)
    add_agent_event(task.agent_id, "task", f"Task updated: {task.status}")
    return task.model_dump()

class TaskMessageRequest(BaseModel):
    role: str
    content: str


@app.get("/api/tasks/{task_id}/messages")
def list_task_messages(task_id: str):
    task = task_store.get(task_id)
    return task.messages


@app.post("/api/tasks/{task_id}/messages")
async def add_task_message(task_id: str, req: TaskMessageRequest):
    msg = task_store.add_message(task_id, req.role, req.content)
    # also broadcast to chat stream to mirror in main chat
    await manager.broadcast({
        "role": req.role,
        "agent_id": None,
        "response": f"[task {task_id}] {req.content}",
        "incidentId": task_id,
        "messageId": msg["id"],
    })
    return msg

# --- Automation endpoints ---
class AutomationCreateRequest(BaseModel):
    name: str
    trigger: Dict
    action: Dict


@app.get("/api/automations")
def list_automations():
    return [a.model_dump() for a in automation_store.list()]


@app.post("/api/automations")
def create_automation(req: AutomationCreateRequest):
    auto = automation_store.create(req.name, req.trigger, req.action)
    return auto.model_dump()


@app.post("/api/automations/{auto_id}/toggle")
def toggle_automation(auto_id: str, enabled: bool = True):
    auto = automation_store.set_enabled(auto_id, enabled)
    return auto.model_dump()


@app.post("/api/automations/{auto_id}/run")
async def run_automation_now(auto_id: str):
    auto = automation_store.update(auto_id, last_run=time.time())
    await run_automation_action(auto)
    return {"status": "triggered"}

# --- Background targeted chatter ---
async def background_chatter():
    """Simulate targeted agent-to-agent optimization dialogue with role-specific questions."""
    while True:
        try:
            metric_payload = system_metrics()
            cpu = metric_payload.get("cpu")
            mem = metric_payload.get("memory", {}).get("percent")
            disk = metric_payload.get("disk", {}).get("percent")
            agent_ids = list(agent_registry.agents.keys())
            ts = time.time()
            # Agents learn current system snapshot for continuous documentation
            tasks_snapshot = [t.model_dump() for t in task_store.all()]
            snapshot = {
                "timestamp": ts,
                "metrics": {"cpu": cpu, "mem": mem, "disk": disk},
                "tasks_count": len(tasks_snapshot),
                "tasks_sample": tasks_snapshot[:3],
            }
            for agent in agent_registry.agents.values():
                agent.learn({
                    "observations": snapshot,
                    "summary": f"Metrics cpu={cpu} mem={mem} disk={disk}, tasks={len(tasks_snapshot)}",
                    "usage": "Improve coordination and resource decisions."
                })
                with contextlib.suppress(Exception):
                    agent.persist_state()
            add_agent_event("orchestrator", "metric", "System snapshot captured", snapshot["metrics"])

            if len(agent_ids) < 2:
                # Single agent, still emit a pulse
                await manager.broadcast({
                    "role": "agent",
                    "agent_id": agent_ids[0] if agent_ids else "agent-1",
                    "response": f"[self-check] monitoring cpu={cpu} mem={mem} disk={disk} ts={ts}",
                })
            else:
                # Orchestrator asks, specialists respond
                if "orchestrator" in agent_ids:
                    await manager.broadcast({
                        "role": "agent",
                        "agent_id": "orchestrator",
                        "target": "loadwatch",
                        "response": f"[to loadwatch] CPU {cpu}%, mem {mem}% — propose load shedding plan? ts={ts}"
                    })
                    await manager.broadcast({
                        "role": "agent",
                        "agent_id": "orchestrator",
                        "target": "netseer",
                        "response": f"[to netseer] Any network anomalies detected? ts={ts}"
                    })
                    await manager.broadcast({
                        "role": "agent",
                        "agent_id": "orchestrator",
                        "target": "taskwarden",
                        "response": f"[to taskwarden] Prioritize pending tasks if load > {cpu}% ts={ts}"
                    })
                    await manager.broadcast({
                        "role": "agent",
                        "agent_id": "orchestrator",
                        "target": "sentinel",
                        "response": f"[to sentinel] Confirm no security alerts; disk={disk}% ts={ts}"
                    })
                    await manager.broadcast({
                        "role": "agent",
                        "agent_id": "orchestrator",
                        "target": "ioguard",
                        "response": f"[to ioguard] Check I/O saturation; disk={disk}% ts={ts}"
                    })
                    await manager.broadcast({
                        "role": "agent",
                        "agent_id": "orchestrator",
                        "target": "memsmith",
                        "response": f"[to memsmith] Validate memory pressure trends; mem={mem}% ts={ts}"
                    })
                    await manager.broadcast({
                        "role": "agent",
                        "agent_id": "orchestrator",
                        "target": "firebreak",
                        "response": f"[to firebreak] Review ingress/egress rules and anomalies; ts={ts}"
                    })
                # Specialists acknowledge to orchestrator
                for agent_id in agent_ids:
                    if agent_id == "orchestrator":
                        continue
                    await manager.broadcast({
                        "role": "agent",
                        "agent_id": agent_id,
                        "target": "orchestrator",
                        "response": f"[to orchestrator] {agent_id} ready; cpu={cpu}% mem={mem}% disk={disk}% ts={ts}"
                    })
        except Exception as e:
            print(f"[Chatter] Error broadcasting targeted dialogue: {e}")
        await asyncio.sleep(10)

# --- LLM Integration (provider switch) ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")

class LLMClient:
    def __init__(self):
        self.session: Optional[httpx.AsyncClient] = None

    async def startup(self):
        if self.session is None:
            self.session = httpx.AsyncClient(timeout=30)

    async def shutdown(self):
        if self.session:
            await self.session.aclose()
            self.session = None

    async def chat_openai(self, prompt: str, model: str = OPENAI_MODEL):
        if not OPENAI_API_KEY:
            return "[openai not configured: set OPENAI_API_KEY]"
        if self.session is None:
            await self.startup()
        try:
            resp = await self.session.post(
                f"{OPENAI_API_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices") or []
            if choices and choices[0].get("message"):
                return choices[0]["message"].get("content", "")
            return "[openai: no content]"
        except Exception as e:
            print(f"[OpenAIClient] Error: {e}")
            return f"[openai error: {str(e)}]"

    async def chat_ollama(self, prompt: str, model: str = "mistral"):
        parsed = urlparse(OLLAMA_ENDPOINT)
        if parsed.scheme not in {"http", "https"}:
            return "[ollama endpoint invalid]"
        if self.session is None:
            await self.startup()
        try:
            resp = await self.session.post(
                f"{OLLAMA_ENDPOINT}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")
        except Exception as e:
            print(f"[OllamaClient] Error: {e}")
            return f"[ollama error: {str(e)}]"

    async def chat(self, prompt: str, model: str = "mistral"):
        if LLM_PROVIDER == "openai":
            return await self.chat_openai(prompt, model)
        elif LLM_PROVIDER == "ollama":
            return await self.chat_ollama(prompt, model)
        elif LLM_PROVIDER == "mock":
            return "[mock llm] " + prompt
        return "[llm provider not configured]"

ollama_client = LLMClient()
metrics_broadcaster_task: Optional[asyncio.Task] = None
automation_runner_task: Optional[asyncio.Task] = None

class OllamaChatRequest(BaseModel):
    prompt: str
    model: str = "llama3"

@app.post("/api/ollama/chat")
async def ollama_chat(request: OllamaChatRequest):
    """Proxy chat request to Ollama LLM."""
    result = await ollama_client.chat(request.prompt, request.model)
    return {"response": result}

@app.post("/api/agents/{agent_id}/ask")
async def agent_ask_ollama(agent_id: str, request: OllamaChatRequest):
    agent = agent_registry.get(agent_id)
    result = await ollama_client.chat(request.prompt, request.model)
    agent.last_ollama_response = result
    return {"agent_id": agent_id, "response": result}

# --- Council mode ---
class CouncilQuery(BaseModel):
    prompt: str


@app.post("/api/council/query")
async def council_query(req: CouncilQuery):
    import random
    base_metrics = {k: v for k, v in latest_metrics.items()}
    responses = []
    votes = {"most_likely_cause": {}, "best_fix": {}}
    for aid, _ in list(agent_registry.agents.items())[:5]:
        angle = random.uniform(-5, 5)
        content = f"{aid} sees load={base_metrics.get('cpu')} mem={base_metrics.get('mem')} disk={base_metrics.get('disk')} | delta={angle:.1f}%"
        mood = compute_mood(base_metrics)
        responses.append({"agent": aid, "mood": mood, "content": content})
        cause = "high load" if (base_metrics.get("cpu") or 0) > 70 else "nominal"
        fix = "shed load" if (base_metrics.get("cpu") or 0) > 70 else "monitor"
        votes["most_likely_cause"][cause] = votes["most_likely_cause"].get(cause, 0) + 1
        votes["best_fix"][fix] = votes["best_fix"].get(fix, 0) + 1
    leader_summary = max(votes["best_fix"], key=votes["best_fix"].get, default="monitor")
    summary = f"Consensus: {leader_summary}. Causes: {votes['most_likely_cause']}"
    return {"question": req.prompt, "responses": responses, "summary": summary, "votes": votes}

# --- Caretaker agent endpoint ---
class CaretakerRequest(BaseModel):
    change_request: str

@app.post("/api/caretaker/propose")
def caretaker_propose(request: CaretakerRequest, http_request: Request):
    require_caretaker_key(http_request)
    caretaker = agent_registry.get("caretaker")
    result = caretaker.propose_code_change(request.change_request)
    return {"caretaker": caretaker.agent_id, "result": result}

@app.post("/api/caretaker/apply")
def caretaker_apply(request: CaretakerRequest, http_request: Request):
    require_caretaker_key(http_request)
    caretaker = agent_registry.get("caretaker")
    try:
        result = caretaker.apply_code_change(request.change_request)
        return {"caretaker": caretaker.agent_id, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/caretaker/log")
def caretaker_log():
    caretaker = agent_registry.get("caretaker")
    return {"caretaker": caretaker.agent_id, "log": caretaker.get_change_log()}

class AgentLearnRequest(BaseModel):
    data: dict

class AgentPersistRequest(BaseModel):
    action: str  # 'save' or 'load'

@app.post("/api/agents/{agent_id}/learn")
def agent_learn(agent_id: str, request: AgentLearnRequest):
    agent = agent_registry.get(agent_id)
    try:
        agent.learn(request.data)
        return {"message": f"Agent {agent_id} learning updated.", "status": agent.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/agents/{agent_id}/persist")
def agent_persist(agent_id: str, request: AgentPersistRequest):
    agent = agent_registry.get(agent_id)
    try:
        if request.action == "save":
            agent.persist_state()
            return {"message": f"Agent {agent_id} state persisted."}
        elif request.action == "load":
            agent.load_state()
            return {"message": f"Agent {agent_id} state loaded.", "status": agent.to_dict()}
        else:
            raise ValueError("Invalid action. Use 'save' or 'load'.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/agents/{agent_id}/reload")
def agent_reload(agent_id: str):
    """Explicitly reload agent state from persistence and return updated state."""
    agent = agent_registry.get(agent_id)
    try:
        agent.load_state()
        return {"message": f"Agent {agent_id} state reloaded.", "status": agent.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/agents/{agent_id}/profile")
def agent_profile(agent_id: str):
    agent = agent_registry.get(agent_id)
    last_notes = agent.learning_state.get("notes", [])[-5:] if isinstance(agent.learning_state.get("notes"), list) else []
    profile = {
        "agent": agent.to_dict(),
        "personality": personality_map.get(agent_id, ""),
        "last_notes": last_notes,
        "state": agent.status,
    }
    return profile

@app.get("/api/agents/{agent_id}/events")
def agent_events(agent_id: str, limit: int = 50):
    agent_registry.get(agent_id)
    events = []
    if redis_client:
        try:
            data = redis_client.xrevrange(f"agent:{agent_id}:events", max="+", min="-", count=limit)
            events = [dict(id=e[0], **{k: v for k, v in e[1].items()}) for e in data]
        except Exception:
            pass
    if not events:
        events = list(reversed(event_log_store.get(agent_id, [])[-limit:]))
    return events

@app.post("/api/caretaker/plugin/{plugin_name}")
def caretaker_run_plugin(plugin_name: str, http_request: Request, payload: dict = {}):
    require_caretaker_key(http_request)
    caretaker = agent_registry.get("caretaker")
    allowed_plugins = set(os.getenv("ALLOWED_PLUGINS", "example_plugin").split(","))
    if plugin_name not in {p.strip() for p in allowed_plugins if p.strip()}:
        raise HTTPException(status_code=403, detail="Plugin not allowed")
    try:
        result = caretaker.run_plugin(plugin_name, **payload)
        return {"plugin": plugin_name, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
def health_check():
    return {"status": "ok", "timestamp": time.time(), "system": platform.system(), "release": platform.release()}

@app.get("/api/metrics")
def system_metrics():
    if psutil:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()._asdict()
        disk = psutil.disk_usage("/")._asdict()
        latest_metrics.update({"cpu": cpu, "mem": mem.get("percent"), "disk": disk.get("percent")})
        return {"cpu": cpu, "memory": mem, "disk": disk}
    else:
        return {"cpu": None, "memory": None, "disk": None, "note": "psutil not installed"}

@app.get("/api/metrics/history")
def metrics_history(from_ts: Optional[float] = None, to_ts: Optional[float] = None, resolution: int = 60):
    """Return synthetic historical metrics bucketed by resolution seconds."""
    now = time.time() if to_ts is None else to_ts
    start = from_ts or now - 3600
    points = []
    t = start
    import math
    while t <= now:
        cpu = 40 + 20 * math.sin(t / 180)
        mem = 55 + 10 * math.cos(t / 300)
        disk = 50 + 5 * math.sin(t / 240)
        points.append({"ts": t, "cpu": round(cpu, 2), "mem": round(mem, 2), "disk": round(disk, 2)})
        t += max(resolution, 15)
    return points


def generate_network_flows():
    import random
    hosts = ["203.0.113.5", "198.51.100.42", "192.0.2.99", "8.8.8.8", "1.1.1.1"]
    flows = []
    for h in hosts:
        flows.append({
            "remote": h,
            "bytes_in": random.randint(5_000, 200_000),
            "bytes_out": random.randint(5_000, 200_000),
            "allowed": random.choice([True, True, False]),
            "threat_score": random.randint(1, 95)
        })
    return flows


@app.get("/api/network/flows")
def network_flows():
    global network_flow_cache
    if not network_flow_cache:
        network_flow_cache = generate_network_flows()
    return {"host": platform.node(), "flows": network_flow_cache}


def generate_disk_io():
    import random
    return {
        "ts": time.time(),
        "iops": random.randint(100, 2000),
        "throughput_mb": random.uniform(10, 250),
        "pressure": random.choice(["low", "medium", "high"]),
    }


@app.get("/api/disk/io")
def disk_io():
    global disk_io_history
    point = generate_disk_io()
    disk_io_history.append(point)
    disk_io_history = disk_io_history[-200:]
    return {"latest": point, "history": disk_io_history}


@app.get("/api/firewall/events")
def firewall_events_feed(limit: int = 50):
    return list(reversed(firewall_events[-limit:]))


@app.get("/api/firewall/rules")
def firewall_rule_list():
    return firewall_rules


@app.post("/api/firewall/rules")
def create_firewall_rule(rule: Dict):
    rule_entry = {
        "id": str(uuid.uuid4()),
        "source": rule.get("source", "any"),
        "dest": rule.get("dest", "host"),
        "action": rule.get("action", "allow"),
        "created_at": time.time(),
    }
    firewall_rules.append(rule_entry)
    firewall_events.append({"ts": time.time(), "ip": rule_entry["source"], "action": rule_entry["action"], "threat": "policy"})
    return rule_entry


@app.post("/api/firewall/allow")
def firewall_allow(ip: str):
    return create_firewall_rule({"source": ip, "action": "allow"})


@app.post("/api/firewall/deny")
def firewall_deny(ip: str):
    return create_firewall_rule({"source": ip, "action": "deny"})


@app.get("/api/incidents/search")
def incident_search(keyword: Optional[str] = None, agent: Optional[str] = None):
    """Search chat/messages by keyword. Currently reuses agent event logs."""
    results = []
    for aid, events in event_log_store.items():
        if agent and aid != agent:
            continue
        for ev in events:
            text = ev.get("message", "")
            if (not keyword) or (keyword.lower() in text.lower()):
                results.append({"agent": aid, **ev})
    return results[-100:]


@app.get("/api/timeline")
def timeline():
    # combine firewall + agent events + tasks
    combined = []
    for aid, events in event_log_store.items():
        for ev in events[-50:]:
            combined.append({"ts": ev.get("ts"), "type": ev.get("type"), "agent": aid, "message": ev.get("message")})
    for ev in firewall_events[-50:]:
        combined.append({"ts": ev.get("ts"), "type": "firewall", **ev})
    combined.extend(timeline_events[-50:])
    combined.sort(key=lambda x: x.get("ts", 0))
    return combined[-200:]


@app.get("/api/replay/snapshots")
def replay_snapshots():
    """Return coarse snapshots to drive replay mode."""
    snapshots = []
    now = time.time()
    for offset in range(0, 900, 60):
        ts = now - offset
        snapshots.append({
            "ts": ts,
            "metrics": {"cpu": 30 + offset % 40, "mem": 50 + (offset % 20), "disk": 40 + (offset % 10)},
            "mood": compute_mood({"cpu": 30 + offset % 40, "mem": 50, "disk": 40}),
            "tasks": len(task_store.all())
        })
    snapshots.sort(key=lambda x: x["ts"])
    return snapshots


def compute_mood(metrics: Dict) -> str:
    cpu = metrics.get("cpu") or 0
    mem = metrics.get("mem") or 0
    disk = metrics.get("disk") or 0
    backlog = len(task_store.all())
    # error frequency (last 50 per agent)
    recent_errors = 0
    for events in event_log_store.values():
        recent_errors += len([e for e in events[-50:] if e.get("type") == "error"])
    score = cpu * 0.35 + mem * 0.25 + disk * 0.15 + backlog * 2 + recent_errors * 3
    if score > 120:
        return "stressed"
    if score > 80:
        return "concerned"
    if score < 35:
        return "calm"
    return "focused"

def add_agent_event(agent_id: str, event_type: str, message: str, metrics_snapshot: Optional[Dict] = None):
    event = {
        "ts": time.time(),
        "type": event_type,
        "message": message,
        "metrics": metrics_snapshot or latest_metrics,
        "mood": compute_mood(latest_metrics),
    }
    # store in redis stream if available
    if redis_client:
        try:
            redis_client.xadd(f"agent:{agent_id}:events", event, maxlen=500)
            return
        except Exception:
            pass
    lst = event_log_store.setdefault(agent_id, [])
    lst.append(event)
    if len(lst) > 500:
        del lst[0:len(lst)-500]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
