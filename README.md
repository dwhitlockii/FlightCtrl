# FlightCtrl AI Agent System

## Overview
A Windows 11 system performance and health monitoring platform with multi-agent AI (Ollama), a real-time, professional web UI, and self-adaptive capabilities. Features live agent chat, widgets, and a modern dashboard. Protocols and UI layout are locked after signoff.

## Architecture
- **Backend:** Python (FastAPI, WebSockets, Ollama integration, Redis, system monitoring)
- **Frontend:** React (TypeScript, PrimeReact, Tailwind CSS, WebSocket client)
- **Agents:** Ollama LLMs, orchestrated by backend
- **Communication:** WebSockets (real-time), REST (config/logs)
- **Self-adaptive:** Caretaker agent can modify backend/frontend code

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

### Backend
```sh
cd backend
python -m venv venv
venv\Scripts\activate  # On Windows
pip install -r requirements.txt
# Start backend
python main.py
```

### Frontend
```sh
cd frontend
npm install
npm run dev
```

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