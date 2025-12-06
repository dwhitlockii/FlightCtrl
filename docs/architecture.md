# FlightCtrl Architecture

## System Map
- Frontend (Vite React) consumes REST + WebSocket /ws/chat.
- Backend (FastAPI) orchestrates agents, tasks, metrics, events; optional Redis for persistence and streams.
- LLM provider switch via env (OLLAMA or OpenAI).
- Redis used for tasks hash and agent event streams (agent:{id}:events).
- Automations evaluated server-side; actions notify/create tasks/restart agents.

## Data Flows
- Metrics loop captures psutil metrics and broadcasts chatter over WS.
- Agent events recorded via add_agent_event -> Redis stream or in-memory list.
- Chat WS supports agent_typing/thinking + streamed chunks; frontend threads messages by parentId/incidentId.
- Network/disk/firewall endpoints provide telemetry for dashboard + war room.
- Replay snapshots endpoint returns time-bucketed state for slider.

## Adding a New Agent
1. Register in AgentRegistry profile list with role string.
2. Provide personality text in personality_map.
3. Frontend will show in sidebar/profile automatically after /api/agents.

## Message Contracts (WS)
- agent_typing: {type, agent_id}
- agent_thinking: {type, agent_id}
- message_chunk: {type, messageId, chunk, parentId?, incidentId?, agent_id}
- message_complete: same as chunk with content field.

