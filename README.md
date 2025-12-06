# FlightCtrl AI Agent System

## Overview
A Windows 11 system performance and health monitoring platform with multi-agent AI (Ollama), a real-time, professional web UI, and self-adaptive capabilities. Features live agent chat, widgets, and a modern dashboard. Protocols and UI layout are locked after signoff.

## Architecture
- **Backend:** Python (FastAPI, WebSockets, Ollama integration, Redis, system monitoring)
- **Frontend:** React (TypeScript, PrimeReact, Tailwind CSS, WebSocket client)
- **Agents:** Ollama LLMs, orchestrated by backend
- **Communication:** WebSockets (real-time), REST (config/logs)
- **Self-adaptive:** Caretaker agent can modify backend/frontend code

## FlightCtrl Command Highlights
- Design system primitives (Card/Panel/Button/Badge/Modal/Drawer/Toast/TabBar) with theme tokens and motion presets.
- Agent profiles with moods, notes timeline, and event console backed by Redis streams or in-memory log.
- Threaded chat with incident filters, typing/thinking indicators, and WebSocket streaming.
- Dashboard upgrades: network flow graph, disk I/O ripple, firewall threat feed, historical metrics, global timeline + replay slider.
- Tasks & automations: priorities, status history, automation builder with interval/metric triggers and notify/task actions.
- Network & firewall war room: live flows, allow/deny actions, rule list, recent firewall events.
- Council mode: multi-agent fan-out query with summary and vote hints.
- Theme pack: cyber, jet, starship, minimal white, hacker green.
 - New docs: see `docs/user-guide.md`, `docs/developer-guide.md`, `docs/architecture.md`.

## Directory Structure
- `/backend` — Python backend, agent orchestration, API, system monitoring
- `/frontend` — React web UI, widgets, chat, dashboard

## Setup
### Prerequisites
- Windows 11
- Python 3.11+
- Node.js 18+
- Docker (optional, for containerization)
- Ollama server at http://192.168.50.200:11434

### Configuration
- `REDIS_URL` (redis|rediss): Redis for agent/task state. Falls back to local JSON files if unreachable.
- `OPENAI_API_KEY`: API key for ChatGPT integration (required for chat responses).
- `OPENAI_MODEL`: ChatGPT model name (default `gpt-4o-mini`).
- `LLM_PROVIDER`: `ollama` (default), `openai`, or `mock`.
- `OLLAMA_ENDPOINT`: http(s) endpoint for Ollama (default `http://ollama:11434` in compose).
- `FRONTEND_ORIGINS`: Comma-separated allowed origins for CORS (default `http://localhost:5173`).
- `ALLOWED_PLUGINS`: Comma-separated plugin module names allowed for the caretaker (default `example_plugin`).
- `CARETAKER_API_KEY`: Optional API key required as `X-API-Key` on caretaker propose/apply/plugin endpoints.

### Backend
```sh
cd backend
python -m venv venv
venv\Scripts\activate  # On Windows
pip install -r requirements.txt
# Start backend
python main.py
# Run backend tests
python -m pytest
```

### Frontend
```sh
cd frontend
npm install
npm run dev
```

### Containers (docker-compose)
```sh
docker compose up --build
```
Services: `backend` (FastAPI), `frontend` (Nginx serving built UI), `redis`, `ollama` (LLM runtime). Configure envs as needed in `docker-compose.yml`. Pull a model inside the running Ollama container, e.g.:
```sh
docker exec -it flightctrl-ollama-1 ollama pull mistral
```
The backend defaults to `LLM_PROVIDER=ollama` and model name `mistral`.

### Key Endpoints
- Agents: `GET /api/agents`, `POST /api/agents/{id}/start|stop|assign`, `POST /api/agents/{id}/learn|persist|reload`
- Tasks: `GET /api/tasks`, `POST /api/tasks`, `PUT /api/tasks/{task_id}`
- Ollama proxy: `POST /api/ollama/chat`
- Caretaker: `POST /api/caretaker/propose|apply`, `GET /api/caretaker/log`, `POST /api/caretaker/plugin/{name}` (guarded by allowlist and optional API key)
- System: `GET /api/health`, `GET /api/metrics`

## Development
- All protocols and UI layout are locked after signoff.
- Use only live data (no test data).
- See `plan-*.md` for planning and progress.

## License
Proprietary. See plan for details.

## Troubleshooting: Node.js, npm, and PATH Issues (Windows)

If you encounter errors such as `'npm' is not recognized as an internal or external command` or `'vite' is not recognized as an internal or external command`, follow these steps to resolve them:

### 1. Install Node.js
- Download and install the latest LTS version from [nodejs.org](https://nodejs.org/).
- The installer will add both `node` and `npm` to your system PATH automatically.

### 2. Add Node.js and npm to PATH (if needed)
- Open **Start** > **System** > **Advanced system settings** > **Environment Variables**.
- Under **System variables** or **User variables**, select `Path` and click **Edit**.
- Ensure the following are present (adjust for your install location):
  - `C:\Program Files\nodejs\`
- Click **OK** to save. See [wikiHow: Change the PATH Environment Variable on Windows](https://www.wikihow.com/Change-the-PATH-Environment-Variable-on-Windows) for details.

### 3. Restart Your Terminal
- Close all Command Prompt, PowerShell, and Git Bash windows.
- Open a new **Command Prompt (cmd.exe)** window.
- Run:
  ```
  node -v
  npm -v
  ```
  Both should print version numbers.

### 4. Clean and Reinstall Frontend Dependencies
- In your project root, run:
  ```
  cd frontend
  del /s /q node_modules
  del package-lock.json
  npm install
  npm run dev
  ```
- This will ensure all dependencies (including Vite) are installed and available.

### 5. If You Still Have Issues
- Double-check your PATH and Node.js installation.
- Reboot your computer if changes do not take effect.

---

**References:**
- [How to Change the PATH Environment Variable on Windows (wikiHow)](https://www.wikihow.com/Change-the-PATH-Environment-Variable-on-Windows)
- [Node.js Official Download](https://nodejs.org/)
- [npm run dev missing script error](https://blog.jonrshar.pe/wtf-npm/errors/missing-script/) 
