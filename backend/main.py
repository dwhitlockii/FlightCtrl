"""
FlightCtrl Backend Entrypoint
- FastAPI app for agent orchestration and real-time API
- WebSocket endpoint for agent/user chat
- REST endpoint for agent status
- CORS enabled for frontend
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, BackgroundTasks, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import List, Optional, Dict, Any, Union
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
from datetime import datetime, timedelta
from jose import jwt, JWTError
from passlib.context import CryptContext
try:
    import psutil
except ImportError:
    psutil = None
import platform
import time
import importlib.util
import glob
import subprocess
import shutil
from contextlib import asynccontextmanager
from telemetry import TelemetryStore


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default

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
firewall_rules: List[Dict] = []
firewall_events: List[Dict] = []
telemetry_store = TelemetryStore(
    sample_interval=_int_env("TELEMETRY_SAMPLE_INTERVAL", 5),
    history_seconds=_int_env("TELEMETRY_HISTORY_SECONDS", 3600),
    flow_ttl=_int_env("TELEMETRY_FLOW_TTL", 5),
    disk_history_limit=_int_env("TELEMETRY_DISK_HISTORY", 200),
    external_ttl=_int_env("FRESHNESS_SECONDS", _int_env("TELEMETRY_EXTERNAL_TTL", 5)),
)
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

def _platform_key() -> str:
    system = platform.system().lower()
    if system.startswith("darwin"):
        return "macos"
    if system.startswith("windows"):
        return "windows"
    if system.startswith("linux"):
        return "linux"
    return system or "unknown"


def _privilege_level() -> str:
    if os.name != "nt":
        try:
            return "elevated" if os.geteuid() == 0 else "user"
        except AttributeError:
            return "unknown"
    return "unknown"


def _source_type_from(source: Optional[str]) -> str:
    return "external_agent" if source == "external" else "local_fallback"


def _unavailable_entry(metric: str, reason: str, remediation: str) -> Dict[str, str]:
    return {"metric": metric, "reason": reason, "remediation": remediation}


def _confidence_score(expected: List[str], unavailable: List[Dict[str, str]]) -> float:
    if not expected:
        return 0.0
    unavailable_set = {entry.get("metric") for entry in unavailable}
    available = len([item for item in expected if item not in unavailable_set])
    return round(available / len(expected), 2)


def _collectors_for(subsystem: str, source_type: str) -> List[str]:
    if source_type == "external_agent":
        external = telemetry_store.get_external_provenance() or {}
        collectors = external.get("collectors")
        if isinstance(collectors, list) and collectors:
            return collectors
        return ["external_agent"]
    collectors = []
    if subsystem in {"cpu", "memory", "disk", "disk_io", "network_flows"}:
        if psutil:
            collectors.append("psutil")
    if subsystem == "network_flows":
        if shutil.which("netstat"):
            collectors.append("netstat")
    if subsystem == "firewall_state":
        if shutil.which("pfctl"):
            collectors.append("pfctl")
        if shutil.which("nft"):
            collectors.append("nft")
        if shutil.which("iptables"):
            collectors.append("iptables")
        if shutil.which("ufw"):
            collectors.append("ufw")
        if shutil.which("netsh"):
            collectors.append("netsh")
    return collectors


def _last_success_times() -> Dict[str, Optional[float]]:
    return telemetry_store.get_last_success_times()


def _freshness_seconds(last_ts: Optional[float]) -> Optional[float]:
    if not last_ts:
        return None
    return round(time.time() - last_ts, 2)


def _parse_timestamp(value: Optional[Union[float, str]]) -> float:
    if value is None:
        return time.time()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return time.time()
    return time.time()


def _provenance(subsystem: str, source_type: str) -> Dict[str, Any]:
    if source_type == "external_agent":
        external = telemetry_store.get_external_provenance()
        if isinstance(external, dict):
            external.setdefault("source_type", source_type)
            external.setdefault("privilege_level", _privilege_level())
            external.setdefault("collectors", _collectors_for(subsystem, source_type))
            external.setdefault("last_success_at", _last_success_times())
            return external
    return {
        "source_type": source_type,
        "collectors": _collectors_for(subsystem, source_type),
        "privilege_level": _privilege_level(),
        "last_success_at": _last_success_times(),
    }


def _capability_entry(status: str, reason: Optional[str] = None, remediation: Optional[str] = None) -> Dict[str, Any]:
    entry = {"status": status}
    if status != "AVAILABLE":
        entry["reason"] = reason or "insufficient capability"
        entry["remediation"] = remediation or "check platform support"
    return entry

# --- Security and Auth ---
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "true").lower() in {"1", "true", "yes"}
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_TTL = _int_env("ACCESS_TOKEN_TTL", 3600)
REFRESH_TOKEN_TTL = _int_env("REFRESH_TOKEN_TTL", 604800)
USERS_FILE = os.getenv("USERS_FILE", os.path.join(os.path.dirname(__file__), "users.json"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH")
AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", os.path.join(os.path.dirname(__file__), "audit.log"))
RATE_LIMIT_PER_MINUTE = _int_env("RATE_LIMIT_PER_MINUTE", 120)
RATE_LIMIT_LOGIN_PER_MINUTE = _int_env("RATE_LIMIT_LOGIN_PER_MINUTE", 10)
RATE_LIMIT_WS_PER_MINUTE = _int_env("RATE_LIMIT_WS_PER_MINUTE", 240)
TELEMETRY_API_KEY = os.getenv("TELEMETRY_API_KEY")
ROLE_ORDER = {"viewer": 0, "operator": 1, "admin": 2}
ALLOWED_ROLES = set(ROLE_ORDER.keys())
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security_scheme = HTTPBearer(auto_error=False)
CARETAKER_CHANGES_FILE = os.path.join(os.path.dirname(__file__), "caretaker_changes.json")


class UserStore:
    def __init__(self, path: str):
        self.path = path
        self.lock = Lock()

    def _load_all(self) -> Dict[str, dict]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _save_all(self, data: Dict[str, dict]) -> None:
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def list_users(self) -> List[dict]:
        with self.lock:
            data = self._load_all()
            return [
                {k: v for k, v in user.items() if k not in {"password_hash"}}
                for user in data.values()
            ]

    def get_user(self, username: str) -> Optional[dict]:
        with self.lock:
            data = self._load_all()
            user = data.get(username)
            if not user:
                return None
            return dict(user)

    def verify_password(self, plain: str, hashed: str) -> bool:
        try:
            return pwd_context.verify(plain, hashed)
        except Exception:
            return False

    def create_user(self, username: str, password: str, role: str) -> dict:
        if role not in ALLOWED_ROLES:
            raise ValueError("Invalid role")
        with self.lock:
            data = self._load_all()
            if username in data:
                raise ValueError("User already exists")
            user = {
                "id": str(uuid.uuid4()),
                "username": username,
                "password_hash": pwd_context.hash(password),
                "role": role,
                "disabled": False,
                "created_at": time.time(),
            }
            data[username] = user
            self._save_all(data)
            return {k: v for k, v in user.items() if k != "password_hash"}

    def ensure_bootstrap(self) -> None:
        with self.lock:
            data = self._load_all()
            if data:
                return
            if not AUTH_REQUIRED:
                return
            if not ADMIN_USERNAME or not (ADMIN_PASSWORD or ADMIN_PASSWORD_HASH):
                raise RuntimeError("Missing ADMIN_USERNAME/ADMIN_PASSWORD for auth bootstrap")
            password_hash = ADMIN_PASSWORD_HASH or pwd_context.hash(ADMIN_PASSWORD)
            user = {
                "id": str(uuid.uuid4()),
                "username": ADMIN_USERNAME,
                "password_hash": password_hash,
                "role": "admin",
                "disabled": False,
                "created_at": time.time(),
            }
            data[ADMIN_USERNAME] = user
            self._save_all(data)


class CaretakerChangeStore:
    def __init__(self, path: str):
        self.path = path
        self.lock = Lock()

    def _load(self) -> Dict[str, dict]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _save(self, data: Dict[str, dict]) -> None:
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def list(self) -> List[dict]:
        with self.lock:
            data = self._load()
            return list(data.values())

    def get(self, change_id: str) -> dict:
        with self.lock:
            data = self._load()
            if change_id not in data:
                raise HTTPException(status_code=404, detail="Change request not found")
            return dict(data[change_id])

    def create(self, change_request: str, requested_by: str) -> dict:
        with self.lock:
            data = self._load()
            change_id = str(uuid.uuid4())
            now = time.time()
            entry = {
                "id": change_id,
                "request": change_request,
                "status": "pending",
                "requested_by": requested_by,
                "approved_by": None,
                "applied_by": None,
                "created_at": now,
                "updated_at": now,
            }
            data[change_id] = entry
            self._save(data)
            return dict(entry)

    def update_status(self, change_id: str, status: str, actor: str) -> dict:
        with self.lock:
            data = self._load()
            if change_id not in data:
                raise HTTPException(status_code=404, detail="Change request not found")
            entry = data[change_id]
            entry["status"] = status
            entry["updated_at"] = time.time()
            if status == "approved":
                entry["approved_by"] = actor
            elif status == "applied":
                entry["applied_by"] = actor
            data[change_id] = entry
            self._save(data)
            return dict(entry)


class AuditLogger:
    def __init__(self, path: str):
        self.path = path
        self.lock = Lock()

    def log(self, action: str, actor: Optional[dict], status: str, request: Optional[Request], detail: Optional[dict] = None):
        entry = {
            "ts": time.time(),
            "action": action,
            "status": status,
            "actor": actor.get("username") if actor else None,
            "role": actor.get("role") if actor else None,
            "ip": _client_ip(request) if request else None,
            "user_agent": request.headers.get("user-agent") if request else None,
            "detail": detail or {},
        }
        with self.lock:
            with open(self.path, "a") as f:
                f.write(json.dumps(entry) + "\n")


class RateLimiter:
    def __init__(self):
        self.redis = None
        self.lock = Lock()
        self._memory: Dict[str, dict] = {}

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        if limit <= 0:
            return True
        window_id = int(time.time() // window_seconds)
        if self.redis:
            redis_key = f"rl:{key}:{window_id}"
            try:
                count = self.redis.incr(redis_key)
                if count == 1:
                    self.redis.expire(redis_key, window_seconds)
                return count <= limit
            except Exception:
                pass
        with self.lock:
            state = self._memory.get(key)
            if not state or state["window"] != window_id:
                self._memory[key] = {"window": window_id, "count": 1}
                return True
            state["count"] += 1
            return state["count"] <= limit


user_store = UserStore(USERS_FILE)
caretaker_change_store = CaretakerChangeStore(CARETAKER_CHANGES_FILE)
audit_logger = AuditLogger(AUDIT_LOG_PATH)
rate_limiter = RateLimiter()


def _client_ip(request: Optional[Request]) -> Optional[str]:
    if not request:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _validate_security_config() -> None:
    if not AUTH_REQUIRED:
        return
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET is required when AUTH_REQUIRED=true")
    if ACCESS_TOKEN_TTL <= 0 or REFRESH_TOKEN_TTL <= 0:
        raise RuntimeError("Token TTL values must be positive")


def _create_token(user: dict, token_type: str, ttl_seconds: int) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": user["username"],
        "role": user["role"],
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_token(token: str, token_type: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("type") != token_type:
        raise HTTPException(status_code=401, detail="Invalid token type")
    return payload


def _extract_subject_from_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None
    return payload.get("sub")


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security_scheme)) -> dict:
    if not AUTH_REQUIRED:
        return {"id": "anon", "username": "anonymous", "role": "admin"}
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authorization")
    payload = _decode_token(credentials.credentials, "access")
    user = user_store.get_user(payload.get("sub", ""))
    if not user or user.get("disabled"):
        raise HTTPException(status_code=401, detail="Invalid user")
    return user


def require_min_role(role: str):
    def _dep(user: dict = Depends(get_current_user)) -> dict:
        if ROLE_ORDER.get(user.get("role", "viewer"), -1) < ROLE_ORDER.get(role, 99):
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user
    return _dep


async def authenticate_ws(websocket: WebSocket) -> Optional[dict]:
    if not AUTH_REQUIRED:
        return {"id": "anon", "username": "anonymous", "role": "admin"}
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)
        return None
    try:
        payload = _decode_token(token, "access")
    except HTTPException:
        await websocket.close(code=1008)
        return None
    user = user_store.get_user(payload.get("sub", ""))
    if not user or user.get("disabled"):
        await websocket.close(code=1008)
        return None
    return user

def require_caretaker_key(request: Request):
    if CARETAKER_API_KEY:
        supplied = request.headers.get("x-api-key")
        if supplied != CARETAKER_API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")


def authorize_telemetry_ingest(request: Request) -> None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        try:
            payload = _decode_token(token, "access")
        except HTTPException:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = user_store.get_user(payload.get("sub", ""))
        if not user or user.get("disabled") or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin role required")
        return
    if TELEMETRY_API_KEY:
        supplied = request.headers.get("x-telemetry-key")
        if supplied != TELEMETRY_API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return
    if AUTH_REQUIRED:
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
    rate_limiter.redis = redis_client

    _validate_security_config()
    user_store.ensure_bootstrap()

    # Start Ollama client
    await ollama_client.startup()
    # Kick off telemetry sampler (simulated chatter is optional)
    global metrics_broadcaster_task, automation_runner_task, telemetry_sampler_task, braintrust_task
    telemetry_sampler_task = asyncio.create_task(telemetry_sampler())
    if ENABLE_SIMULATED_CHATTER:
        metrics_broadcaster_task = asyncio.create_task(background_chatter())
    if ENABLE_BRAINTRUST_CHATTER:
        braintrust_task = asyncio.create_task(braintrust_chatter())
    automation_runner_task = asyncio.create_task(automation_runner())
    yield
    # Shutdown Ollama client
    await ollama_client.shutdown()
    if metrics_broadcaster_task:
        metrics_broadcaster_task.cancel()
        with contextlib.suppress(Exception):
            await metrics_broadcaster_task
    if braintrust_task:
        braintrust_task.cancel()
        with contextlib.suppress(Exception):
            await braintrust_task
    if telemetry_sampler_task:
        telemetry_sampler_task.cancel()
        with contextlib.suppress(Exception):
            await telemetry_sampler_task
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
    note: Optional[str] = None


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


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    limit = RATE_LIMIT_PER_MINUTE
    if request.url.path == "/api/auth/login":
        limit = RATE_LIMIT_LOGIN_PER_MINUTE
    subject = None
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
        subject = _extract_subject_from_token(token)
    if not subject:
        subject = _client_ip(request) or "anon"
    key = f"{subject}:{request.url.path}"
    if not rate_limiter.allow(key, limit, 60):
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
    return await call_next(request)


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"


def _public_user(user: dict) -> dict:
    return {k: v for k, v in user.items() if k != "password_hash"}


@app.post("/api/auth/login")
def auth_login(req: LoginRequest, request: Request):
    user = user_store.get_user(req.username)
    if not user or not user_store.verify_password(req.password, user.get("password_hash", "")):
        audit_logger.log("auth.login", None, "fail", request, {"username": req.username})
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.get("disabled"):
        audit_logger.log("auth.login", user, "fail", request, {"reason": "disabled"})
        raise HTTPException(status_code=401, detail="User disabled")
    access_token = _create_token(user, "access", ACCESS_TOKEN_TTL)
    refresh_token = _create_token(user, "refresh", REFRESH_TOKEN_TTL)
    audit_logger.log("auth.login", user, "ok", request)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_TTL,
        "role": user.get("role"),
    }


@app.post("/api/auth/refresh")
def auth_refresh(req: RefreshRequest, request: Request):
    payload = _decode_token(req.refresh_token, "refresh")
    user = user_store.get_user(payload.get("sub", ""))
    if not user or user.get("disabled"):
        audit_logger.log("auth.refresh", None, "fail", request, {"username": payload.get("sub")})
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    access_token = _create_token(user, "access", ACCESS_TOKEN_TTL)
    refresh_token = _create_token(user, "refresh", REFRESH_TOKEN_TTL)
    audit_logger.log("auth.refresh", user, "ok", request)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_TTL,
        "role": user.get("role"),
    }


@app.get("/api/auth/me", dependencies=[Depends(require_min_role("viewer"))])
def auth_me(current_user: dict = Depends(get_current_user)):
    return _public_user(current_user)


@app.get("/api/auth/users", dependencies=[Depends(require_min_role("admin"))])
def list_users():
    return user_store.list_users()


@app.post("/api/auth/users", dependencies=[Depends(require_min_role("admin"))])
def create_user(req: UserCreateRequest, request: Request, current_user: dict = Depends(get_current_user)):
    if req.role not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    try:
        user = user_store.create_user(req.username, req.password, req.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit_logger.log("auth.create_user", current_user, "ok", request, {"username": req.username, "role": req.role})
    return user


@app.get("/api/audit", dependencies=[Depends(require_min_role("admin"))])
def get_audit_log(limit: int = 200):
    if not os.path.exists(AUDIT_LOG_PATH):
        return {"events": []}
    events = []
    with open(AUDIT_LOG_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    if limit and len(events) > limit:
        events = events[-limit:]
    return {"events": events}

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    ws_user = await authenticate_ws(websocket)
    if not ws_user:
        return
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if not rate_limiter.allow(f"ws:{ws_user.get('username', 'anon')}", RATE_LIMIT_WS_PER_MINUTE, 60):
                await websocket.send_json({"type": "error", "message": "rate_limit"})
                await websocket.close(code=1008)
                return
            msg_type = data.get("type")
            if msg_type in {"agent_typing", "agent_thinking"}:
                await manager.broadcast(data)
                continue
            # Route message to agent if agent_id is present
            agent_id = data.get("agent_id")
            prompt = data.get("prompt")
            model = data.get("model", OLLAMA_MODEL)
            if agent_id and prompt:
                if ws_user.get("role") not in {"operator", "admin"}:
                    await websocket.send_json({"type": "error", "message": "insufficient_role"})
                    continue
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
                # Relay to other agents only when simulated chatter is enabled
                if ENABLE_SIMULATED_CHATTER:
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

@app.get("/api/agents", dependencies=[Depends(require_min_role("viewer"))])
def get_agents():
    """Return status of all agents."""
    return JSONResponse(content={a["agent_id"]: a for a in agent_registry.all()})

class AgentCommand(BaseModel):
    task: str = None

@app.post("/api/agents/{agent_id}/start", dependencies=[Depends(require_min_role("operator"))])
def start_agent(agent_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    agent = agent_registry.get(agent_id)
    agent.start()
    audit_logger.log("agent.start", current_user, "ok", request, {"agent_id": agent_id})
    return {"message": f"{agent_id} started", "status": agent.to_dict()}

@app.post("/api/agents/{agent_id}/stop", dependencies=[Depends(require_min_role("operator"))])
def stop_agent(agent_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    agent = agent_registry.get(agent_id)
    agent.stop()
    audit_logger.log("agent.stop", current_user, "ok", request, {"agent_id": agent_id})
    return {"message": f"{agent_id} stopped", "status": agent.to_dict()}

@app.post("/api/agents/{agent_id}/assign", dependencies=[Depends(require_min_role("operator"))])
def assign_task(agent_id: str, command: AgentCommand, request: Request, current_user: dict = Depends(get_current_user)):
    agent = agent_registry.get(agent_id)
    try:
        agent.assign_task(command.task)
    except Exception as e:
        audit_logger.log("agent.assign", current_user, "fail", request, {"agent_id": agent_id, "error": str(e)})
        raise HTTPException(status_code=400, detail=str(e))
    audit_logger.log("agent.assign", current_user, "ok", request, {"agent_id": agent_id, "task": command.task})
    return {"message": f"Task assigned to {agent_id}", "status": agent.to_dict()}

@app.get("/api/agents/{agent_id}", dependencies=[Depends(require_min_role("viewer"))])
def get_agent(agent_id: str):
    agent = agent_registry.get(agent_id)
    return agent.to_dict()

# --- Task endpoints ---
@app.get("/api/tasks", dependencies=[Depends(require_min_role("viewer"))])
def list_tasks():
    tasks = task_store.all()
    return [t.model_dump() for t in tasks]

@app.post("/api/tasks", dependencies=[Depends(require_min_role("operator"))])
def create_task(request: TaskCreateRequest, http_request: Request, current_user: dict = Depends(get_current_user)):
    # Ensure agent exists
    agent_registry.get(request.agent_id)
    task = task_store.create(request.agent_id, request.description, priority=request.priority)
    add_agent_event(request.agent_id, "task", f"Task created: {request.description}")
    audit_logger.log("task.create", current_user, "ok", http_request, {"task_id": task.id, "agent_id": request.agent_id})
    return task.model_dump()

@app.get("/api/tasks/{task_id}", dependencies=[Depends(require_min_role("viewer"))])
def get_task(task_id: str):
    task = task_store.get(task_id)
    return task.model_dump()

@app.put("/api/tasks/{task_id}", dependencies=[Depends(require_min_role("operator"))])
def update_task(task_id: str, request: TaskUpdateRequest, http_request: Request, current_user: dict = Depends(get_current_user)):
    task = task_store.update(task_id, request.description, request.status, request.priority, request.note)
    add_agent_event(task.agent_id, "task", f"Task updated: {task.status}")
    audit_logger.log("task.update", current_user, "ok", http_request, {"task_id": task_id, "status": task.status})
    return task.model_dump()

class TaskMessageRequest(BaseModel):
    role: str
    content: str


@app.get("/api/tasks/{task_id}/messages", dependencies=[Depends(require_min_role("viewer"))])
def list_task_messages(task_id: str):
    task = task_store.get(task_id)
    return task.messages


@app.post("/api/tasks/{task_id}/messages", dependencies=[Depends(require_min_role("operator"))])
async def add_task_message(task_id: str, req: TaskMessageRequest, http_request: Request, current_user: dict = Depends(get_current_user)):
    msg = task_store.add_message(task_id, req.role, req.content)
    # also broadcast to chat stream to mirror in main chat
    await manager.broadcast({
        "role": req.role,
        "agent_id": None,
        "response": f"[task {task_id}] {req.content}",
        "incidentId": task_id,
        "messageId": msg["id"],
    })
    audit_logger.log("task.message", current_user, "ok", http_request, {"task_id": task_id, "message_id": msg["id"]})
    return msg

# --- Automation endpoints ---
class AutomationCreateRequest(BaseModel):
    name: str
    trigger: Dict
    action: Dict


@app.get("/api/automations", dependencies=[Depends(require_min_role("viewer"))])
def list_automations():
    return [a.model_dump() for a in automation_store.list()]


@app.post("/api/automations", dependencies=[Depends(require_min_role("operator"))])
def create_automation(req: AutomationCreateRequest, http_request: Request, current_user: dict = Depends(get_current_user)):
    auto = automation_store.create(req.name, req.trigger, req.action)
    audit_logger.log("automation.create", current_user, "ok", http_request, {"automation_id": auto.id})
    return auto.model_dump()


@app.post("/api/automations/{auto_id}/toggle", dependencies=[Depends(require_min_role("operator"))])
def toggle_automation(auto_id: str, http_request: Request, enabled: bool = True, current_user: dict = Depends(get_current_user)):
    auto = automation_store.set_enabled(auto_id, enabled)
    audit_logger.log("automation.toggle", current_user, "ok", http_request, {"automation_id": auto_id, "enabled": enabled})
    return auto.model_dump()


@app.post("/api/automations/{auto_id}/run", dependencies=[Depends(require_min_role("operator"))])
async def run_automation_now(auto_id: str, http_request: Request, current_user: dict = Depends(get_current_user)):
    auto = automation_store.update(auto_id, last_run=time.time())
    await run_automation_action(auto)
    audit_logger.log("automation.run", current_user, "ok", http_request, {"automation_id": auto_id})
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
            if cpu is None and metric_payload.get("note"):
                await asyncio.sleep(10)
                continue
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

def _llm_response_ok(text: Optional[str]) -> bool:
    if not text:
        return False
    lowered = text.strip().lower()
    if lowered.startswith(("[openai", "[ollama", "[llm")):
        return False
    if lowered.startswith("[") and "error" in lowered:
        return False
    return True


def _truncate(text: str, limit: int = 140) -> str:
    clean = (text or "").strip()
    if len(clean) <= limit:
        return clean
    return f"{clean[: max(limit - 3, 0)]}..."


def _summarize_tasks(tasks: List["Task"], limit: int = 6) -> str:
    if not tasks:
        return "none"
    tasks_sorted = sorted(tasks, key=lambda t: t.updated_at, reverse=True)
    lines = []
    for task in tasks_sorted[:limit]:
        desc = _truncate(task.description, 120)
        lines.append(f"{task.id} {task.agent_id} {task.status}/{task.priority}: {desc}")
    return "\n".join(lines)


def _summarize_flows(flows: List[Dict[str, Any]], limit: int = 5) -> str:
    if not flows:
        return "none"
    flows_sorted = sorted(flows, key=lambda f: (f.get("threat_score") or 0, f.get("connections") or 0), reverse=True)
    lines = []
    for flow in flows_sorted[:limit]:
        remote = flow.get("remote", "unknown")
        allowed = "allow" if flow.get("allowed") else "blocked"
        threat = flow.get("threat_score")
        conns = flow.get("connections")
        lines.append(f"{remote} {allowed} threat={threat} conns={conns}")
    return "\n".join(lines)


def _summarize_firewall_events(events: List[Dict[str, Any]], limit: int = 5) -> str:
    if not events:
        return "none"
    lines = []
    for event in events[:limit]:
        action = event.get("action", "event")
        source = event.get("source", "unknown")
        note = _truncate(event.get("note", ""), 80)
        lines.append(f"{action} {source} {note}".strip())
    return "\n".join(lines)


def _flow_stats(flows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_flows = len(flows)
    blocked = 0
    allowed = 0
    unknown = 0
    total_connections = 0
    top_threat = 0
    top_remote = None
    for flow in flows:
        allowed_flag = flow.get("allowed")
        if allowed_flag is True:
            allowed += 1
        elif allowed_flag is False:
            blocked += 1
        else:
            unknown += 1
        conns = flow.get("connections") or 0
        total_connections += conns
        threat = flow.get("threat_score") or 0
        if threat > top_threat:
            top_threat = threat
            top_remote = flow.get("remote")
    return {
        "total_flows": total_flows,
        "allowed": allowed,
        "blocked": blocked,
        "unknown": unknown,
        "total_connections": total_connections,
        "top_threat": top_threat,
        "top_remote": top_remote,
    }


def _task_stats(tasks: List["Task"]) -> Dict[str, int]:
    counts = {"pending": 0, "in_progress": 0, "completed": 0, "failed": 0}
    for task in tasks:
        status = task.status
        if status in counts:
            counts[status] += 1
    counts["total"] = len(tasks)
    return counts


def _detect_issues(
    cpu: Optional[float],
    mem: Optional[float],
    disk: Optional[float],
    disk_pressure: Optional[str],
    flow_stats: Dict[str, Any],
    task_stats: Dict[str, int],
    firewall_events: List[Dict[str, Any]],
) -> List[str]:
    issues = []
    if cpu is not None and cpu >= 80:
        issues.append(f"cpu_high={cpu}%")
    if mem is not None and mem >= 80:
        issues.append(f"memory_high={mem}%")
    if disk is not None and disk >= 85:
        issues.append(f"disk_high={disk}%")
    if disk_pressure in {"medium", "high"}:
        issues.append(f"disk_pressure={disk_pressure}")
    if flow_stats.get("blocked", 0) > 0:
        issues.append(f"blocked_flows={flow_stats.get('blocked')}")
    if flow_stats.get("top_threat", 0) >= 20:
        issues.append(f"network_threat={flow_stats.get('top_threat')}")
    if task_stats.get("failed", 0) > 0:
        issues.append(f"tasks_failed={task_stats.get('failed')}")
    if task_stats.get("pending", 0) >= 5:
        issues.append(f"tasks_backlog={task_stats.get('pending')}")
    if firewall_events:
        issues.append(f"firewall_events={len(firewall_events)}")
    return issues


def _fallback_agent_report(
    agent_id: str,
    focus: str,
    cpu: Optional[float],
    mem: Optional[float],
    disk: Optional[float],
    disk_io: Dict[str, Any],
    flow_stats: Dict[str, Any],
    task_stats: Dict[str, int],
    firewall_events: List[Dict[str, Any]],
    issues: List[str],
) -> str:
    if agent_id == "loadwatch":
        stats = f"cpu={cpu}% mem={mem}%"
        fix = "Reduce workload, scale workers, or defer non-critical tasks."
    elif agent_id == "memsmith":
        stats = f"mem={mem}% cpu={cpu}%"
        fix = "Identify high-memory processes; trim caches or restart offenders."
    elif agent_id == "netseer":
        stats = f"flows={flow_stats.get('total_flows')} blocked={flow_stats.get('blocked')} top_threat={flow_stats.get('top_threat')}"
        fix = "Inspect top remote and block anomalies; verify host telemetry permissions."
    elif agent_id == "ioguard":
        stats = f"disk={disk}% iops={disk_io.get('iops')} thr={disk_io.get('throughput_mb')}MB"
        fix = "Reduce heavy IO; move logs/tmp to faster storage."
    elif agent_id == "firebreak":
        stats = f"events={len(firewall_events)} blocked={flow_stats.get('blocked')}"
        fix = "Review recent events; tighten rules for suspicious sources."
    elif agent_id == "taskwarden":
        stats = f"tasks total={task_stats.get('total')} pending={task_stats.get('pending')} failed={task_stats.get('failed')}"
        fix = "Reprioritize backlog; address failed tasks first."
    elif agent_id == "sentinel":
        stats = f"top_threat={flow_stats.get('top_threat')} blocked={flow_stats.get('blocked')}"
        fix = "Investigate suspicious IPs and validate access controls."
    else:
        stats = f"cpu={cpu}% mem={mem}% disk={disk}%"
        fix = "Review system metrics and coordinate next actions."
    issue_line = f"Issues: {', '.join(issues)}." if issues else "No critical issues."
    return f"{focus} | {stats}. {issue_line} Fix: {fix}"


async def braintrust_chatter():
    """LLM-backed agent roundtable based on live telemetry and tasks."""
    semaphore = asyncio.Semaphore(max(COUNCIL_CONCURRENCY, 1))
    while True:
        try:
            if not manager.active_connections:
                await asyncio.sleep(BRAINTRUST_INTERVAL)
                continue

            metrics = telemetry_store.get_metrics_detail() or {}
            cpu = metrics.get("cpu")
            mem = metrics.get("memory", {}).get("percent") if isinstance(metrics.get("memory"), dict) else None
            disk = metrics.get("disk", {}).get("percent") if isinstance(metrics.get("disk"), dict) else None
            mood = compute_mood({"cpu": cpu, "mem": mem, "disk": disk})
            disk_io = telemetry_store.get_disk_io().get("latest", {})
            flows_payload = telemetry_store.get_network_flows(firewall_rules)
            flows = flows_payload.get("flows", [])
            firewall_recent = telemetry_store.get_firewall_events(firewall_events, limit=5)
            tasks = task_store.all()
            flow_stats = _flow_stats(flows)
            task_stats = _task_stats(tasks)
            issues = _detect_issues(
                cpu,
                mem,
                disk,
                disk_io.get("pressure"),
                flow_stats,
                task_stats,
                firewall_recent,
            )

            context = (
                f"Metrics: cpu={cpu} mem={mem} disk={disk} mood={mood}\n"
                f"Disk IO: iops={disk_io.get('iops')} throughput_mb={disk_io.get('throughput_mb')} pressure={disk_io.get('pressure')}\n"
                f"Flows (total={flow_stats.get('total_flows')} blocked={flow_stats.get('blocked')} top_threat={flow_stats.get('top_threat')}):\n{_summarize_flows(flows)}\n"
                f"Firewall events:\n{_summarize_firewall_events(firewall_recent)}\n"
                f"Tasks (total={task_stats.get('total')} pending={task_stats.get('pending')} failed={task_stats.get('failed')}):\n{_summarize_tasks(tasks)}\n"
            )
            issue_context = f"Issues detected: {', '.join(issues)}." if issues else "Issues detected: none."

            async def ask_agent(agent_id: str, role: str, prompt: str) -> str:
                async with semaphore:
                    await manager.broadcast({"type": "agent_thinking", "agent_id": agent_id})
                    try:
                        return await asyncio.wait_for(
                            ollama_client.chat(prompt, BRAINTRUST_MODEL),
                            timeout=COUNCIL_TIMEOUT,
                        )
                    except Exception as e:
                        return f"[braintrust error: {e or 'timeout'}]"

            orchestrator_prompt = (
                f"You are {agent_registry.get('orchestrator').agent_id} (orchestrator). "
                f"Personality: {personality_map.get('orchestrator', '')}\n"
                f"{BRAINTRUST_PROMPT}\n"
                f"{issue_context}\n"
                f"{context}\n"
                "Respond in 1-2 sentences. Frame the top concern and ask one question for specialists."
            )
            orchestrator_response = await ask_agent("orchestrator", "orchestrator", orchestrator_prompt)
            orchestrator_id = str(uuid.uuid4())
            if _llm_response_ok(orchestrator_response):
                agent_registry.get("orchestrator").last_ollama_response = orchestrator_response
                await manager.broadcast({
                    "role": "agent",
                    "agent_id": "orchestrator",
                    "response": orchestrator_response,
                    "messageId": orchestrator_id,
                })
            orchestrator_context = orchestrator_response if _llm_response_ok(orchestrator_response) else "No orchestrator response available."

            focus_map = {
                "loadwatch": "CPU focus",
                "memsmith": "Memory focus",
                "netseer": "Network focus",
                "ioguard": "Disk IO focus",
                "firebreak": "Firewall focus",
                "taskwarden": "Task ops focus",
                "sentinel": "Security focus",
            }
            agent_items = [(aid, agent.role) for aid, agent in agent_registry.agents.items() if aid != "orchestrator"]
            prompts = []
            for agent_id, role in agent_items:
                personality = personality_map.get(agent_id, "")
                focus = focus_map.get(agent_id, "System focus")
                prompt = (
                    f"You are {agent_id} ({role}). Personality: {personality}\n"
                    f"Orchestrator prompt: {orchestrator_context}\n"
                    f"Focus area: {focus}. {issue_context}\n"
                    f"{BRAINTRUST_PROMPT}\n"
                    f"{context}\n"
                    "Respond in 1-2 short sentences. Report your focus stats and one concrete action or check."
                )
                prompts.append(prompt)

            responses = await asyncio.gather(*[
                ask_agent(agent_id, role, prompt) for (agent_id, role), prompt in zip(agent_items, prompts)
            ])

            for (agent_id, _), response in zip(agent_items, responses):
                focus = focus_map.get(agent_id, "System focus")
                final_response = response if _llm_response_ok(response) else _fallback_agent_report(
                    agent_id,
                    focus,
                    cpu,
                    mem,
                    disk,
                    disk_io,
                    flow_stats,
                    task_stats,
                    firewall_recent,
                    issues,
                )
                agent_registry.get(agent_id).last_ollama_response = final_response
                payload = {
                    "role": "agent",
                    "agent_id": agent_id,
                    "response": final_response,
                    "messageId": str(uuid.uuid4()),
                }
                if _llm_response_ok(orchestrator_response):
                    payload["parentId"] = orchestrator_id
                await manager.broadcast(payload)
        except Exception as e:
            print(f"[Braintrust] Error broadcasting roundtable: {e}")
        await asyncio.sleep(BRAINTRUST_INTERVAL)


async def telemetry_sampler():
    while True:
        try:
            metrics = telemetry_store.sample()
            if metrics:
                latest_metrics.update({
                    "cpu": metrics.get("cpu"),
                    "mem": metrics.get("memory", {}).get("percent"),
                    "disk": metrics.get("disk", {}).get("percent"),
                })
        except Exception as e:
            print(f"[Telemetry] Sample error: {e}")
        await asyncio.sleep(_int_env("TELEMETRY_SAMPLE_INTERVAL", 5))

# --- LLM Integration (provider switch) ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
COUNCIL_MODEL = os.getenv("COUNCIL_MODEL", OLLAMA_MODEL)
COUNCIL_TIMEOUT = _int_env("COUNCIL_TIMEOUT", 25)
COUNCIL_CONCURRENCY = _int_env("COUNCIL_CONCURRENCY", 2)
LLM_TIMEOUT = _int_env("LLM_TIMEOUT", max(COUNCIL_TIMEOUT, 60))
FIREWALL_CONTROL = os.getenv("FIREWALL_CONTROL", "false").lower() in {"1", "true", "yes"}
BRAINTRUST_MODEL = os.getenv("BRAINTRUST_MODEL", COUNCIL_MODEL)
BRAINTRUST_PROMPT = os.getenv(
    "BRAINTRUST_PROMPT",
    "Review current system metrics and tasks. Identify top risks, explain why, and propose concrete actions.",
)
ENABLE_SIMULATED_CHATTER = os.getenv("ENABLE_SIMULATED_CHATTER", "false").lower() in {"1", "true", "yes"}
ENABLE_BRAINTRUST_CHATTER = os.getenv("ENABLE_BRAINTRUST_CHATTER", "false").lower() in {"1", "true", "yes"}
BRAINTRUST_INTERVAL = _int_env("BRAINTRUST_INTERVAL", 60)

class LLMClient:
    def __init__(self):
        self.session: Optional[httpx.AsyncClient] = None

    async def startup(self):
        if self.session is None:
            self.session = httpx.AsyncClient(timeout=httpx.Timeout(LLM_TIMEOUT))

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

    async def chat_ollama(self, prompt: str, model: str = OLLAMA_MODEL):
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
        return "[llm provider not configured]"

ollama_client = LLMClient()
metrics_broadcaster_task: Optional[asyncio.Task] = None
automation_runner_task: Optional[asyncio.Task] = None
telemetry_sampler_task: Optional[asyncio.Task] = None
braintrust_task: Optional[asyncio.Task] = None

class OllamaChatRequest(BaseModel):
    prompt: str
    model: str = OLLAMA_MODEL

@app.post("/api/ollama/chat", dependencies=[Depends(require_min_role("operator"))])
async def ollama_chat(request: OllamaChatRequest):
    """Proxy chat request to Ollama LLM."""
    result = await ollama_client.chat(request.prompt, request.model)
    return {"response": result}

@app.post("/api/agents/{agent_id}/ask", dependencies=[Depends(require_min_role("operator"))])
async def agent_ask_ollama(agent_id: str, request: OllamaChatRequest):
    agent = agent_registry.get(agent_id)
    result = await ollama_client.chat(request.prompt, request.model)
    agent.last_ollama_response = result
    return {"agent_id": agent_id, "response": result}

# --- Council mode ---
class CouncilQuery(BaseModel):
    prompt: str


@app.post("/api/council/query", dependencies=[Depends(require_min_role("operator"))])
async def council_query(req: CouncilQuery):
    base_metrics = {k: v for k, v in latest_metrics.items()}
    responses = []
    votes = {"most_likely_cause": {}, "best_fix": {}}
    semaphore = asyncio.Semaphore(max(COUNCIL_CONCURRENCY, 1))

    async def ask_agent(agent_id: str, role: str):
        personality = personality_map.get(agent_id, "")
        prompt = (
            f"You are {agent_id} ({role}). Personality: {personality}\n"
            f"System metrics: cpu={base_metrics.get('cpu')} mem={base_metrics.get('mem')} disk={base_metrics.get('disk')}\n"
            f"Question: {req.prompt}\n"
            "Respond with three lines:\n"
            "Cause: <most likely cause>\n"
            "Fix: <best fix>\n"
            "Summary: <one-sentence summary>\n"
        )
        try:
            async with semaphore:
                content = await asyncio.wait_for(
                    ollama_client.chat(prompt, COUNCIL_MODEL),
                    timeout=COUNCIL_TIMEOUT,
                )
        except Exception as e:
            content = f"Cause: unknown\nFix: investigate\nSummary: error: {e or 'timeout'}"

        cause = "unspecified"
        fix = "unspecified"
        summary_line = ""
        for line in content.splitlines():
            lower = line.lower().strip()
            if lower.startswith("cause:"):
                cause = line.split(":", 1)[1].strip() or "unspecified"
            elif lower.startswith("fix:"):
                fix = line.split(":", 1)[1].strip() or "unspecified"
            elif lower.startswith("summary:"):
                summary_line = line.split(":", 1)[1].strip()
        summary_text = summary_line or content.strip()[:200]
        mood = compute_mood(base_metrics)
        responses.append({"agent": agent_id, "mood": mood, "content": content, "summary": summary_text})
        votes["most_likely_cause"][cause] = votes["most_likely_cause"].get(cause, 0) + 1
        votes["best_fix"][fix] = votes["best_fix"].get(fix, 0) + 1

    targets = list(agent_registry.agents.items())[:5]
    await asyncio.gather(*(ask_agent(aid, role) for aid, role in targets))
    leader_fix = max(votes["best_fix"], key=votes["best_fix"].get, default="unspecified")
    summary = f"Consensus: {leader_fix}. Causes: {votes['most_likely_cause']}"
    return {"question": req.prompt, "responses": responses, "summary": summary, "votes": votes}

# --- Caretaker agent endpoint ---
class CaretakerProposeRequest(BaseModel):
    change_request: str


class CaretakerApplyRequest(BaseModel):
    change_id: str


class CaretakerReviewRequest(BaseModel):
    note: Optional[str] = None


@app.get("/api/caretaker/proposals", dependencies=[Depends(require_min_role("admin"))])
def caretaker_list_proposals():
    return caretaker_change_store.list()


@app.get("/api/caretaker/proposals/{change_id}", dependencies=[Depends(require_min_role("admin"))])
def caretaker_get_proposal(change_id: str):
    return caretaker_change_store.get(change_id)


@app.post("/api/caretaker/propose", dependencies=[Depends(require_min_role("admin"))])
def caretaker_propose(request: CaretakerProposeRequest, http_request: Request, current_user: dict = Depends(get_current_user)):
    require_caretaker_key(http_request)
    caretaker = agent_registry.get("caretaker")
    change = caretaker_change_store.create(request.change_request, current_user["username"])
    result = caretaker.propose_code_change(request.change_request)
    audit_logger.log("caretaker.propose", current_user, "ok", http_request, {"change_id": change["id"]})
    return {"caretaker": caretaker.agent_id, "change": change, "result": result}


@app.post("/api/caretaker/proposals/{change_id}/approve", dependencies=[Depends(require_min_role("admin"))])
def caretaker_approve(change_id: str, request: CaretakerReviewRequest, http_request: Request, current_user: dict = Depends(get_current_user)):
    require_caretaker_key(http_request)
    change = caretaker_change_store.update_status(change_id, "approved", current_user["username"])
    audit_logger.log("caretaker.approve", current_user, "ok", http_request, {"change_id": change_id, "note": request.note})
    return change


@app.post("/api/caretaker/proposals/{change_id}/reject", dependencies=[Depends(require_min_role("admin"))])
def caretaker_reject(change_id: str, request: CaretakerReviewRequest, http_request: Request, current_user: dict = Depends(get_current_user)):
    require_caretaker_key(http_request)
    change = caretaker_change_store.update_status(change_id, "rejected", current_user["username"])
    audit_logger.log("caretaker.reject", current_user, "ok", http_request, {"change_id": change_id, "note": request.note})
    return change


@app.post("/api/caretaker/apply", dependencies=[Depends(require_min_role("admin"))])
def caretaker_apply(request: CaretakerApplyRequest, http_request: Request, current_user: dict = Depends(get_current_user)):
    require_caretaker_key(http_request)
    caretaker = agent_registry.get("caretaker")
    change = caretaker_change_store.get(request.change_id)
    if change.get("status") != "approved":
        raise HTTPException(status_code=400, detail="Change request must be approved before apply")
    try:
        result = caretaker.apply_code_change(change["request"])
        caretaker_change_store.update_status(request.change_id, "applied", current_user["username"])
        audit_logger.log("caretaker.apply", current_user, "ok", http_request, {"change_id": request.change_id})
        return {"caretaker": caretaker.agent_id, "result": result}
    except Exception as e:
        audit_logger.log("caretaker.apply", current_user, "fail", http_request, {"change_id": request.change_id, "error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/caretaker/log", dependencies=[Depends(require_min_role("admin"))])
def caretaker_log():
    caretaker = agent_registry.get("caretaker")
    return {"caretaker": caretaker.agent_id, "log": caretaker.get_change_log()}

class AgentLearnRequest(BaseModel):
    data: dict

class AgentPersistRequest(BaseModel):
    action: str  # 'save' or 'load'

@app.post("/api/agents/{agent_id}/learn", dependencies=[Depends(require_min_role("operator"))])
def agent_learn(agent_id: str, request: AgentLearnRequest, http_request: Request, current_user: dict = Depends(get_current_user)):
    agent = agent_registry.get(agent_id)
    try:
        agent.learn(request.data)
        audit_logger.log("agent.learn", current_user, "ok", http_request, {"agent_id": agent_id})
        return {"message": f"Agent {agent_id} learning updated.", "status": agent.to_dict()}
    except Exception as e:
        audit_logger.log("agent.learn", current_user, "fail", http_request, {"agent_id": agent_id, "error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/agents/{agent_id}/persist", dependencies=[Depends(require_min_role("operator"))])
def agent_persist(agent_id: str, request: AgentPersistRequest, http_request: Request, current_user: dict = Depends(get_current_user)):
    agent = agent_registry.get(agent_id)
    try:
        if request.action == "save":
            agent.persist_state()
            audit_logger.log("agent.persist", current_user, "ok", http_request, {"agent_id": agent_id, "action": "save"})
            return {"message": f"Agent {agent_id} state persisted."}
        elif request.action == "load":
            agent.load_state()
            audit_logger.log("agent.persist", current_user, "ok", http_request, {"agent_id": agent_id, "action": "load"})
            return {"message": f"Agent {agent_id} state loaded.", "status": agent.to_dict()}
        else:
            raise ValueError("Invalid action. Use 'save' or 'load'.")
    except Exception as e:
        audit_logger.log("agent.persist", current_user, "fail", http_request, {"agent_id": agent_id, "error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/agents/{agent_id}/reload", dependencies=[Depends(require_min_role("operator"))])
def agent_reload(agent_id: str, http_request: Request, current_user: dict = Depends(get_current_user)):
    """Explicitly reload agent state from persistence and return updated state."""
    agent = agent_registry.get(agent_id)
    try:
        agent.load_state()
        audit_logger.log("agent.reload", current_user, "ok", http_request, {"agent_id": agent_id})
        return {"message": f"Agent {agent_id} state reloaded.", "status": agent.to_dict()}
    except Exception as e:
        audit_logger.log("agent.reload", current_user, "fail", http_request, {"agent_id": agent_id, "error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/agents/{agent_id}/profile", dependencies=[Depends(require_min_role("viewer"))])
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

@app.get("/api/agents/{agent_id}/events", dependencies=[Depends(require_min_role("viewer"))])
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

@app.post("/api/caretaker/plugin/{plugin_name}", dependencies=[Depends(require_min_role("admin"))])
def caretaker_run_plugin(plugin_name: str, http_request: Request, payload: dict = {}, current_user: dict = Depends(get_current_user)):
    require_caretaker_key(http_request)
    caretaker = agent_registry.get("caretaker")
    allowed_raw = os.getenv("ALLOWED_PLUGINS", "")
    allowed_plugins = {p.strip() for p in allowed_raw.split(",") if p.strip()}
    if plugin_name not in allowed_plugins:
        raise HTTPException(status_code=403, detail="Plugin not allowed")
    try:
        result = caretaker.run_plugin(plugin_name, **payload)
        audit_logger.log("caretaker.plugin", current_user, "ok", http_request, {"plugin": plugin_name})
        return {"plugin": plugin_name, "result": result}
    except Exception as e:
        audit_logger.log("caretaker.plugin", current_user, "fail", http_request, {"plugin": plugin_name, "error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health", dependencies=[Depends(require_min_role("viewer"))])
def health_check():
    return {"status": "ok", "timestamp": time.time(), "system": platform.system(), "release": platform.release()}

@app.get("/api/diagnostics", dependencies=[Depends(require_min_role("viewer"))])
def diagnostics():
    external_age = telemetry_store.external_age_seconds()
    freshness_threshold = telemetry_store.external_ttl
    external_fresh = telemetry_store.external_fresh()
    source_type = "external_agent" if external_fresh else "local_fallback"
    remediation = None
    if not external_fresh:
        remediation = (
            "Host telemetry unavailable. Run the agent: "
            "python -m flightctrl_agent --backend http://127.0.0.1:8000 --interval 2"
        )
    return {
        "platform": _platform_key(),
        "source_type": source_type,
        "external_age_seconds": round(external_age, 2) if external_age is not None else None,
        "freshness_threshold_seconds": freshness_threshold,
        "ws_active": len(manager.active_connections) > 0,
        "remediation": remediation,
    }

@app.get("/api/metrics", dependencies=[Depends(require_min_role("viewer"))])
def system_metrics():
    metrics = telemetry_store.get_metrics_detail()
    unavailable: List[Dict[str, str]] = []
    if not metrics:
        metrics = {"cpu": None, "memory": None, "disk": None, "note": "psutil not installed"}
        for key in ("cpu", "memory", "disk"):
            unavailable.append(_unavailable_entry(
                key,
                "psutil not installed or telemetry unavailable",
                "Install psutil or run the host telemetry agent.",
                ))
    else:
        for key in ("cpu", "memory", "disk"):
            if metrics.get(key) is None:
                unavailable.append(_unavailable_entry(
                    key,
                    "telemetry missing",
                    "Ensure the host telemetry agent is running with required privileges.",
                ))
    source_type = _source_type_from(metrics.get("source"))
    if source_type == "local_fallback":
        if metrics.get("cpu_per_core") is None:
            unavailable.append(_unavailable_entry(
                "cpu_per_core",
                "Per-core CPU usage unavailable",
                "Run the host telemetry agent with required privileges.",
            ))
        if metrics.get("load_avg") is None:
            unavailable.append(_unavailable_entry(
                "cpu_load_avg",
                "Load average unavailable",
                "Run the host telemetry agent or use a platform that reports load average.",
            ))
    if source_type == "external_agent":
        external_unavailable = telemetry_store.get_external_unavailable()
        unavailable.extend([entry for entry in external_unavailable if entry.get("metric") in {"cpu", "memory", "disk", "cpu_load_avg", "cpu_per_core"}])
    latest_metrics.update({
        "cpu": metrics.get("cpu"),
        "mem": metrics.get("memory", {}).get("percent"),
        "disk": metrics.get("disk", {}).get("percent"),
    })
    return {
        "cpu": metrics.get("cpu"),
        "memory": metrics.get("memory"),
        "disk": metrics.get("disk"),
        "cpu_per_core": metrics.get("cpu_per_core"),
        "load_avg": metrics.get("load_avg"),
        "note": metrics.get("note"),
        "platform": _platform_key(),
        "source_type": source_type,
        "freshness_seconds": _freshness_seconds(_last_success_times().get("cpu")),
        "provenance": _provenance("cpu", source_type),
        "unavailable": unavailable,
        "confidence": _confidence_score(["cpu", "memory", "disk", "cpu_per_core", "cpu_load_avg"], unavailable),
    }

@app.get("/api/metrics/history", dependencies=[Depends(require_min_role("viewer"))])
def metrics_history(from_ts: Optional[float] = None, to_ts: Optional[float] = None, resolution: int = 60):
    """Return historical metrics bucketed by resolution seconds."""
    return telemetry_store.get_metrics_history(from_ts, to_ts, resolution)

@app.get("/api/capabilities", dependencies=[Depends(require_min_role("viewer"))])
def capabilities():
    matrix = {
        "windows": {
            "cpu": _capability_entry("AVAILABLE"),
            "memory": _capability_entry("AVAILABLE"),
            "disk_io": _capability_entry("AVAILABLE"),
            "network_flows": _capability_entry(
                "PARTIAL",
                "Network connections may require Administrator privileges.",
                "Run the host agent as Administrator to capture full flows.",
            ),
            "firewall_state": _capability_entry(
                "PARTIAL",
                "Firewall rules require Administrator access via netsh.",
                "Run with elevated privileges and ensure netsh is available.",
            ),
            "firewall_enforcement": _capability_entry(
                "UNAVAILABLE",
                "Firewall enforcement not implemented yet.",
                "Enable enforcement in Phase 6 with Administrator privileges.",
            ),
        },
        "linux": {
            "cpu": _capability_entry("AVAILABLE"),
            "memory": _capability_entry("AVAILABLE"),
            "disk_io": _capability_entry("AVAILABLE"),
            "network_flows": _capability_entry(
                "PARTIAL",
                "Full socket visibility may require sudo.",
                "Run the host agent with sudo for full flow visibility.",
            ),
            "firewall_state": _capability_entry(
                "PARTIAL",
                "Requires nftables/iptables/ufw tooling and privileges.",
                "Install nftables/iptables/ufw and run with sudo.",
            ),
            "firewall_enforcement": _capability_entry(
                "UNAVAILABLE",
                "Firewall enforcement not implemented yet.",
                "Enable enforcement in Phase 6 with sudo privileges.",
            ),
        },
        "macos": {
            "cpu": _capability_entry("AVAILABLE"),
            "memory": _capability_entry("AVAILABLE"),
            "disk_io": _capability_entry("AVAILABLE"),
            "network_flows": _capability_entry(
                "PARTIAL",
                "macOS requires elevated privileges for net connections.",
                "Run the host agent with sudo for full flows.",
            ),
            "firewall_state": _capability_entry(
                "PARTIAL",
                "pfctl requires sudo and firewall logging must be enabled.",
                "Run with sudo and enable pf logging.",
            ),
            "firewall_enforcement": _capability_entry(
                "UNAVAILABLE",
                "Firewall enforcement not implemented yet.",
                "Enable enforcement in Phase 6 with sudo privileges.",
            ),
        },
    }
    platform_key = _platform_key()
    return {
        "platform": platform_key,
        "capabilities": matrix.get(platform_key, {}),
        "matrix": matrix,
    }


class UnavailableMetric(BaseModel):
    metric: str
    reason: str
    remediation: str


class ProcessStat(BaseModel):
    pid: Optional[int] = None
    name: Optional[str] = None
    cpu_percent: Optional[float] = None
    rss: Optional[int] = None


class CPUData(BaseModel):
    usage_percent: Optional[float] = None
    per_core_percent: Optional[List[float]] = None
    load_avg: Optional[List[float]] = None
    top_processes: Optional[List[ProcessStat]] = None


class MemoryData(BaseModel):
    total: Optional[int] = None
    used: Optional[int] = None
    available: Optional[int] = None
    free: Optional[int] = None
    percent: Optional[float] = None
    swap_total: Optional[int] = None
    swap_used: Optional[int] = None
    swap_free: Optional[int] = None
    swap_percent: Optional[float] = None
    top_processes: Optional[List[ProcessStat]] = None


class DiskUsage(BaseModel):
    total: Optional[int] = None
    used: Optional[int] = None
    free: Optional[int] = None
    percent: Optional[float] = None


class DiskIO(BaseModel):
    read_bytes_total: Optional[int] = None
    write_bytes_total: Optional[int] = None
    read_ops_total: Optional[int] = None
    write_ops_total: Optional[int] = None
    read_bytes_delta: Optional[int] = None
    write_bytes_delta: Optional[int] = None
    read_ops_delta: Optional[int] = None
    write_ops_delta: Optional[int] = None
    read_bytes_per_sec: Optional[float] = None
    write_bytes_per_sec: Optional[float] = None
    read_ops_per_sec: Optional[float] = None
    write_ops_per_sec: Optional[float] = None
    iops: Optional[float] = None
    throughput_bytes_per_sec: Optional[float] = None
    throughput_mb: Optional[float] = None
    note: Optional[str] = None


class DiskData(BaseModel):
    usage: Optional[DiskUsage] = None
    io: Optional[DiskIO] = None


class NetworkFlow(BaseModel):
    remote: str
    connections: int
    remote_ports: List[int] = []
    local_ports: List[int] = []
    bytes_in: Optional[int] = None
    bytes_out: Optional[int] = None
    threat_score: Optional[int] = None
    allowed: Optional[bool] = None
    last_seen: Optional[float] = None


class NetworkListener(BaseModel):
    local_address: Optional[str] = None
    local_port: Optional[int] = None
    protocol: Optional[str] = None


class NetworkSummary(BaseModel):
    total_connections: Optional[int] = None
    total_listeners: Optional[int] = None
    tcp_connections: Optional[int] = None
    udp_connections: Optional[int] = None


class NetworkData(BaseModel):
    flows: Optional[List[NetworkFlow]] = None
    listeners: Optional[List[NetworkListener]] = None
    summary: Optional[NetworkSummary] = None


class FirewallData(BaseModel):
    enabled: Optional[bool] = None
    backend: Optional[str] = None
    rule_count: Optional[int] = None
    raw: Optional[str] = None


class ProvenanceData(BaseModel):
    platform: Optional[str] = None
    host_id: Optional[str] = None
    privilege_level: Optional[str] = None
    collectors: Optional[List[str]] = None
    collectors_by_subsystem: Optional[Dict[str, List[str]]] = None
    last_success_at: Optional[Dict[str, float]] = None


class TelemetryIngestRequest(BaseModel):
    timestamp: Optional[Union[float, str]] = None
    platform: Optional[str] = None
    host_id: Optional[str] = None
    source: Optional[str] = None
    cpu: Optional[CPUData] = None
    memory: Optional[MemoryData] = None
    disk: Optional[DiskData] = None
    network: Optional[NetworkData] = None
    firewall: Optional[FirewallData] = None
    provenance: Optional[ProvenanceData] = None
    unavailable: Optional[List[UnavailableMetric]] = None
    # Legacy fields (deprecated)
    ts: Optional[float] = None
    host: Optional[str] = None
    host_ip: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    disk_io: Optional[Dict[str, Any]] = None
    flows: Optional[List[Dict[str, Any]]] = None


@app.post("/api/telemetry/ingest")
def telemetry_ingest(req: TelemetryIngestRequest, request: Request):
    authorize_telemetry_ingest(request)
    payload = req.model_dump(exclude_none=True)
    if req.cpu or req.memory or req.disk or req.network or req.firewall:
        ts_value = req.timestamp or req.ts
        timestamp = _parse_timestamp(ts_value)
        normalized = {
            "timestamp": timestamp,
            "platform": req.platform,
            "host_id": req.host_id or req.host,
            "source": req.source,
            "cpu": req.cpu.model_dump(exclude_none=True) if req.cpu else None,
            "memory": req.memory.model_dump(exclude_none=True) if req.memory else None,
            "disk": req.disk.model_dump(exclude_none=True) if req.disk else None,
            "network": req.network.model_dump(exclude_none=True) if req.network else None,
            "firewall": req.firewall.model_dump(exclude_none=True) if req.firewall else None,
            "provenance": req.provenance.model_dump(exclude_none=True) if req.provenance else None,
            "unavailable": [u.model_dump() for u in (req.unavailable or [])],
        }
        telemetry_store.ingest_external_snapshot(normalized)
    else:
        if "ts" not in payload and req.timestamp:
            payload["ts"] = _parse_timestamp(req.timestamp)
        telemetry_store.ingest_external(payload)
    return {"status": "ok"}


@app.get("/api/network/flows", dependencies=[Depends(require_min_role("viewer"))])
def network_flows():
    system_rules = telemetry_store.get_firewall_rules()
    payload = telemetry_store.get_network_flows(system_rules)
    source_type = _source_type_from(payload.get("source"))
    unavailable: List[Dict[str, str]] = []
    if payload.get("note"):
        unavailable.append(_unavailable_entry(
            "network_flows",
            payload.get("note", "network flows unavailable"),
            "Run the host telemetry agent with elevated privileges.",
        ))
    if source_type == "external_agent":
        external_unavailable = telemetry_store.get_external_unavailable()
        unavailable.extend([entry for entry in external_unavailable if entry.get("metric") in {"network_flows", "network_listeners"}])
    return {
        **payload,
        "platform": _platform_key(),
        "source_type": source_type,
        "freshness_seconds": _freshness_seconds(_last_success_times().get("network_flows")),
        "provenance": _provenance("network_flows", source_type),
        "unavailable": unavailable,
        "confidence": _confidence_score(["network_flows", "network_listeners"], unavailable),
    }


@app.get("/api/disk/io", dependencies=[Depends(require_min_role("viewer"))])
def disk_io():
    payload = telemetry_store.get_disk_io()
    source_type = _source_type_from(payload.get("source"))
    unavailable: List[Dict[str, str]] = []
    latest = payload.get("latest") or {}
    if latest.get("iops") is None:
        unavailable.append(_unavailable_entry(
            "disk_iops",
            latest.get("note", "disk I/O stats unavailable"),
            "Install psutil or run the host telemetry agent.",
        ))
    if latest.get("throughput_mb") is None:
        unavailable.append(_unavailable_entry(
            "disk_throughput",
            latest.get("note", "disk I/O stats unavailable"),
            "Install psutil or run the host telemetry agent.",
        ))
    if source_type == "external_agent":
        external_unavailable = telemetry_store.get_external_unavailable()
        unavailable.extend([entry for entry in external_unavailable if entry.get("metric") in {"disk_iops", "disk_throughput"}])
    return {
        **payload,
        "platform": _platform_key(),
        "source_type": source_type,
        "freshness_seconds": _freshness_seconds(_last_success_times().get("disk_io")),
        "provenance": _provenance("disk_io", source_type),
        "unavailable": unavailable,
        "confidence": _confidence_score(["disk_iops", "disk_throughput"], unavailable),
    }


@app.get("/api/firewall/events", dependencies=[Depends(require_min_role("viewer"))])
def firewall_events_feed(limit: int = 50):
    events = telemetry_store.get_firewall_events(firewall_events, limit=limit)
    unavailable: List[Dict[str, str]] = []
    external_fresh = telemetry_store.external_fresh()
    source_type = "external_agent" if external_fresh else "local_fallback"
    snapshot = telemetry_store.get_external_firewall() if external_fresh else None
    if source_type == "external_agent":
        external_unavailable = telemetry_store.get_external_unavailable()
        unavailable.extend([entry for entry in external_unavailable if entry.get("metric") in {"firewall_state", "firewall_rules", "firewall_events"}])
    if source_type == "local_fallback" and not os.getenv("FIREWALL_LOG_PATH"):
        unavailable.append(_unavailable_entry(
            "firewall_events",
            "FIREWALL_LOG_PATH not configured",
            "Set FIREWALL_LOG_PATH to a readable firewall log.",
        ))
    return {
        "events": events,
        "snapshot": snapshot,
        "platform": _platform_key(),
        "source_type": source_type,
        "freshness_seconds": _freshness_seconds(_last_success_times().get("firewall_state")),
        "provenance": _provenance("firewall_state", source_type),
        "unavailable": unavailable,
        "confidence": _confidence_score(["firewall_state", "firewall_events"], unavailable),
    }


@app.get("/api/firewall/rules", dependencies=[Depends(require_min_role("viewer"))])
def firewall_rule_list():
    external_fresh = telemetry_store.external_fresh()
    source_type = "external_agent" if external_fresh else "local_fallback"
    rules = telemetry_store.get_firewall_rules() if not external_fresh else []
    snapshot = telemetry_store.get_external_firewall() if external_fresh else None
    unavailable: List[Dict[str, str]] = []
    if source_type == "external_agent":
        external_unavailable = telemetry_store.get_external_unavailable()
        unavailable.extend([entry for entry in external_unavailable if entry.get("metric") in {"firewall_rules"}])
    return {
        "rules": rules,
        "snapshot": snapshot,
        "platform": _platform_key(),
        "source_type": source_type,
        "freshness_seconds": _freshness_seconds(_last_success_times().get("firewall_state")),
        "provenance": _provenance("firewall_state", source_type),
        "unavailable": unavailable,
        "confidence": _confidence_score(["firewall_state", "firewall_rules"], unavailable),
    }


def _apply_firewall_rule_cmd(rule_entry: Dict):
    system = platform.system().lower()
    ip = rule_entry.get("source")
    action = rule_entry.get("action")
    if not ip or ip == "any":
        raise HTTPException(status_code=400, detail="IP required for firewall rule")
    if system == "linux":
        target = "DROP" if action == "deny" else "ACCEPT"
        cmd = ["iptables", "-I", "INPUT", "-s", ip, "-j", target]
    elif system == "darwin":
        if action == "deny":
            cmd = ["pfctl", "-t", "flightctrl_block", "-T", "add", ip]
        else:
            cmd = ["pfctl", "-t", "flightctrl_block", "-T", "delete", ip]
    elif system == "windows":
        rule_name = f"FlightCtrl {action} {ip}"
        cmd = [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={rule_name}",
            "dir=in",
            f"action={action}",
            f"remoteip={ip}",
        ]
    else:
        raise HTTPException(status_code=501, detail="Firewall control not supported on this OS")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise HTTPException(status_code=501, detail="Firewall command not available")
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.stderr.strip() or "Firewall command failed")


def create_firewall_rule(rule: Dict):
    if not FIREWALL_CONTROL:
        raise HTTPException(status_code=501, detail="Firewall control disabled")
    rule_entry = {
        "id": str(uuid.uuid4()),
        "source": rule.get("source", "any"),
        "dest": rule.get("dest", "host"),
        "action": rule.get("action", "allow"),
        "created_at": time.time(),
    }
    _apply_firewall_rule_cmd(rule_entry)
    firewall_rules.append(rule_entry)
    firewall_events.append({"ts": time.time(), "ip": rule_entry["source"], "action": rule_entry["action"], "threat": "policy"})
    return rule_entry


@app.post("/api/firewall/rules", dependencies=[Depends(require_min_role("admin"))])
def apply_firewall_rule(rule_entry: Dict, http_request: Request, current_user: dict = Depends(get_current_user)):
    result = create_firewall_rule(rule_entry)
    audit_logger.log("firewall.rule.apply", current_user, "ok", http_request, {"source": rule_entry.get("source"), "action": rule_entry.get("action")})
    return result


@app.post("/api/firewall/allow", dependencies=[Depends(require_min_role("admin"))])
def firewall_allow(ip: str, http_request: Request, current_user: dict = Depends(get_current_user)):
    audit_logger.log("firewall.allow", current_user, "ok", http_request, {"ip": ip})
    return create_firewall_rule({"source": ip, "action": "allow"})


@app.post("/api/firewall/deny", dependencies=[Depends(require_min_role("admin"))])
def firewall_deny(ip: str, http_request: Request, current_user: dict = Depends(get_current_user)):
    audit_logger.log("firewall.deny", current_user, "ok", http_request, {"ip": ip})
    return create_firewall_rule({"source": ip, "action": "deny"})


@app.get("/api/incidents/search", dependencies=[Depends(require_min_role("viewer"))])
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


@app.get("/api/timeline", dependencies=[Depends(require_min_role("viewer"))])
def timeline():
    # combine firewall + agent events + tasks
    combined = []
    for aid, events in event_log_store.items():
        for ev in events[-50:]:
            combined.append({"ts": ev.get("ts"), "type": ev.get("type"), "agent": aid, "message": ev.get("message")})
    for ev in telemetry_store.get_firewall_events(firewall_events, limit=50):
        combined.append({"ts": ev.get("ts"), "type": "firewall", **ev})
    for task in task_store.all():
        for entry in task.status_history:
            combined.append({
                "ts": entry.ts,
                "type": "task",
                "agent": task.agent_id,
                "message": f"Task {task.id} -> {entry.status}",
            })
    combined.sort(key=lambda x: x.get("ts", 0))
    return combined[-200:]


@app.get("/api/replay/snapshots", dependencies=[Depends(require_min_role("viewer"))])
def replay_snapshots():
    """Return snapshots derived from sampled metrics history."""
    snapshots = []
    samples = telemetry_store.get_metrics_samples()
    tasks = task_store.all()
    for point in samples:
        ts = point.get("ts")
        if ts is None:
            continue
        task_count = len([t for t in tasks if t.created_at <= ts])
        metrics = {"cpu": point.get("cpu"), "mem": point.get("mem"), "disk": point.get("disk")}
        snapshots.append({
            "ts": ts,
            "metrics": metrics,
            "mood": compute_mood(metrics),
            "tasks": task_count,
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
