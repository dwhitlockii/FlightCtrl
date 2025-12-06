# FlightCtrl Frontend (React + Vite + Tailwind)

## Scripts
- `npm run dev` — start Vite dev server.
- `npm run build` — type-check + build for production.
- `npm run preview` — preview built assets.
- `npm run lint` — ESLint.
- `npm run test` — Vitest + RTL.

## Configuration
- `VITE_WS_URL` — WebSocket URL for chat/agent channel. Defaults to current origin (`ws://` or `wss://`).
- API base — proxied via Vite dev server; in production ensure frontend is served behind the backend/API.

## Features
- Live agent chat via WebSocket.
- Agents/task list with creation UI bound to backend tasks API.
- Health/metrics widgets bound to backend endpoints.
- Polling with backoff to reduce load on failures.

## Testing
- Vitest with jsdom and React Testing Library. See `vitest.config.ts` and `src/setupTests.ts`.

## Build & Deploy
For containerized deploy:
```sh
docker build -t flightctrl-frontend .
```
Or via compose (root):
```sh
docker compose up --build
```
