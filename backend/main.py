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
from pydantic import BaseModel
import os
import httpx
import uuid
import json
import redis
try:
    import psutil
except ImportError:
    psutil = None
import platform
import time
import importlib.util
import glob

app = FastAPI()

# Allow frontend (adjust origin as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Redis Setup ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
try:
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    print(f"[Redis] Connected to {REDIS_URL}")
except Exception as e:
    redis_client = None
    print(f"[Redis] Connection failed: {e}. Will use file-based fallback.")

# --- Agent System ---
class Agent:
    def __init__(self, agent_id: str, role: str = "standard"):
        self.agent_id = agent_id
        self.role = role  # 'standard' or 'caretaker'
        self.status = "idle"
        self.task: Optional[str] = None
        self.last_ollama_response: Optional[str] = None
        self.learning_state: Dict = {}

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
        # Replace state if data is empty (for test reset), else update
        if data == {}:
            self.learning_state = {}
        else:
            self.learning_state.update(data)
        print(f"[Agent:{self.agent_id}] Learning state updated: {self.learning_state}")

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
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "status": self.status,
            "task": self.task,
            "last_ollama_response": self.last_ollama_response,
            "learning_state": self.learning_state,
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
        self.agents = {
            "agent-1": Agent("agent-1"),
            "agent-2": Agent("agent-2"),
            "agent-3": Agent("agent-3"),
            "caretaker": CaretakerAgent("caretaker"),
        }

    def get(self, agent_id: str) -> Agent:
        if agent_id not in self.agents:
            raise HTTPException(status_code=404, detail="Agent not found")
        return self.agents[agent_id]

    def all(self):
        return [agent.to_dict() for agent in self.agents.values()]

agent_registry = AgentRegistry()

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
        for connection in self.active_connections:
            await connection.send_json(message)

manager = ConnectionManager()

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
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
                    "response": result
                }
                await manager.broadcast(response)
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

# --- Ollama Integration ---
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://192.168.50.200:11434")

class OllamaClient:
    def __init__(self, endpoint: str = OLLAMA_ENDPOINT):
        self.endpoint = endpoint.rstrip("/")
        self.session = httpx.AsyncClient(timeout=30)

    async def chat(self, prompt: str, model: str = "llama3"):  # model can be parameterized
        url = f"{self.endpoint}/api/chat"
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        try:
            resp = await self.session.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")
        except Exception as e:
            # Log error, return safe error message
            print(f"[OllamaClient] Error: {e}")
            return f"[Ollama error: {str(e)}]"

ollama_client = OllamaClient()

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

# --- Caretaker agent endpoint ---
class CaretakerRequest(BaseModel):
    change_request: str

@app.post("/api/caretaker/propose")
def caretaker_propose(request: CaretakerRequest):
    caretaker = agent_registry.get("caretaker")
    result = caretaker.propose_code_change(request.change_request)
    return {"caretaker": caretaker.agent_id, "result": result}

@app.post("/api/caretaker/apply")
def caretaker_apply(request: CaretakerRequest):
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

@app.post("/api/caretaker/plugin/{plugin_name}")
def caretaker_run_plugin(plugin_name: str, payload: dict = {}):
    caretaker = agent_registry.get("caretaker")
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
        return {"cpu": cpu, "memory": mem, "disk": disk}
    else:
        return {"cpu": None, "memory": None, "disk": None, "note": "psutil not installed"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 