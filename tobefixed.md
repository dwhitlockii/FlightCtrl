# Ascension Backlog

## Phase 1: Critical Stabilization
- [x] Close the shared `httpx.AsyncClient` on shutdown to prevent connection/file descriptor leaks (backend/main.py:286).
- [x] Guard WebSocket broadcasts so one dead client cannot crash the loop; prune broken connections (backend/main.py:213).

## Phase 2: Core Matrix
- [x] Baseline agent lifecycle, learning, and persistence endpoints are online (backend/main.py).
- [x] Expose a real task model/storage via REST and wire the UI store to it instead of a placeholder (frontend/src/store.ts).
- [x] Parameterize the WebSocket URL instead of hard-coding `ws://localhost:8000` (frontend/src/App.tsx:63).

## Phase 3: Wards & Security
- [x] Replace wildcard CORS when `allow_credentials=True` with an explicit allowlist (backend/main.py:35).
- [x] Add auth/role checks and a plugin allowlist around the caretaker plugin executor (backend/main.py:385). (Allowlist added; API key optional.)
- [x] Move service endpoints (Ollama, Redis) to env-configured secrets and validate them at startup (backend/main.py:43,274).

## Phase 4: Efficiency & Flow
- [x] Reduce the 5s polling storm for health/metrics; move to push or cached polling with backoff (frontend/src/App.tsx:42-53). (Backoff added.)

## Phase 5: Higher Functions
- [x] Bind the metrics/health widgets to real data instead of placeholders (frontend/src/App.tsx:189-221).
- [x] Implement the “New Task” action so agents can be assigned work from the UI (frontend/src/App.tsx:118,174).

## Phase 6: The Grimoire (Docs)
- [x] Replace the template Vite README with product-specific setup, scripts, and troubleshooting (frontend/README.md).
- [x] Add backend API, config, and security expectations to the root README (README.md).

## Phase 7: Future Ascension
- [x] Add integration tests (REST + WebSocket) and UI smoke/e2e coverage; current `npm test`/Jest setup is non-functional (frontend/package.json, frontend/src).
- [x] Provide a containerized compose stack (backend + frontend + Redis + Ollama stub) for reproducible spins.
