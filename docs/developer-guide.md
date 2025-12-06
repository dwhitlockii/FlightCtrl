# FlightCtrl Developer Guide

## Backend (FastAPI)
- Entrypoint: backend/main.py uses lifespan to init Redis, LLM client, metrics chatter, automation runner.
- Key endpoints:
  - /api/agents, /api/agents/{id}, start/stop/assign.
  - /api/agents/{id}/profile, /api/agents/{id}/events.
  - /api/tasks CRUD with priority + status_history.
  - /api/automations list/create/toggle/run; automation_runner evaluates interval/threshold triggers.
  - /api/network/flows, /api/disk/io, /api/firewall/events|rules|allow|deny.
  - /api/metrics, /api/metrics/history, /api/timeline, /api/replay/snapshots.
  - /api/council/query fan-outs to agents and returns responses/votes.
  - WebSocket /ws/chat supports agent_typing/agent_thinking + streaming message_chunk/message_complete.
- Mood scoring blends cpu/mem/disk, task backlog, recent errors.
- Storage: Redis if available; falls back to JSON for tasks/events.

## Frontend (React/Vite/TS)
- Global state: see src/store.ts (agents/tasks via REST).
- UI primitives in src/components/ui (Card, Panel, Button, Badge, Modal, Drawer, Toast, TabBar, motionPresets).
- Main shell: src/App.tsx handles tabs, theming, splash, WS chat, overview, tasks, network, war room, council, timeline/replay.
- Styling tokens in src/index.css; themes via data-theme on :root.

## Testing
- Backend: pytest (test_main.py).
- Frontend: npm run build (strict TS) plus Vitest setup present.

## Extending
- Add agents in AgentRegistry (backend/main.py).
- Add automations by extending AutomationStore and action runner.
- For new metrics, extend /api/metrics and propagate to frontend gauges.

## Deployment
- Dockerfiles in frontend/backend, docker-compose.yml wires Redis and Ollama mock.
- Nginx config serves built frontend; configure env vars for CORS/LLM/Redis.

