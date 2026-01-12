# Codex Handoff — FlightCtrl
STATUS: Phase 4 implemented but NOT VERIFIED. Phase 5 is BLOCKED until Phase 4 tests are green.

## 1. PROJECT STATUS (AUTHORITATIVE)
- Repo URL: https://github.com/dwhitlockii/FlightCtrl
- Working branch: `codex/flightctrl-refactor`
- Status banner:
  - Phase 1: COMPLETE
  - Phase 2: COMPLETE (tests passed)
  - Phase 4: IMPLEMENTED BUT NOT VERIFIED
  - Phase 5: NOT STARTED
  - Phase 6: NOT STARTED
- Phase 5 MUST NOT begin until Phase 4 is verified.
- HARD RULE: "If a feature cannot be implemented on a platform, you must expose it as UNAVAILABLE, explain why, and provide remediation. Silent omission is forbidden."

## 2. HARD RULE (REPEATED)
- "If a feature cannot be implemented on a platform, you must expose it as UNAVAILABLE, explain why, and provide remediation. Silent omission is forbidden."

## 3. KEY DECISIONS THAT MUST NOT BE UNDONE

### Telemetry Truth Model
- `external_agent` vs `local_fallback` are explicit sources.
- Freshness arbitration: fresh external data wins; fallback never overwrites fresh external data.
- Prohibition on simulated or container-only data; all telemetry must reflect real host data.

### Agent Ingest Authentication
- Header: `X-Telemetry-Key`
- Env var: `FLIGHTCTRL_TELEMETRY_KEY`
- Admin JWT is separate: `Authorization: Bearer ...`
- 401/403 remediation: verify the env var and header match and the backend is configured to accept the header.

### Platform Constraints
- Container detection is tri-state: true, false, or unknown.
- Windows and macOS container detection is UNAVAILABLE and must be reported as such.
- Disk I/O rate is UNAVAILABLE until a second sample exists.
- Explicit UNAVAILABLE propagation is required in all responses.
- HARD RULE: "If a feature cannot be implemented on a platform, you must expose it as UNAVAILABLE, explain why, and provide remediation. Silent omission is forbidden."

## 4. EXACT RESUME INSTRUCTIONS (TOMORROW START)

### A. Checkout and Sync
- `git fetch`
- `git checkout codex/flightctrl-refactor`
- `git pull`

### B. Phase 4 VERIFICATION GATE (MANDATORY)
- Install dev deps: `python3 -m pip install -r backend/requirements-dev.txt`
- Run tests (from `backend/`): `python3 -m pytest -q`
- Expected output includes: `N passed`
- If tests fail, STOP. Fix and rerun. Do not start Phase 5.
- After tests are green, print: `PHASE 4 VERIFIED`

### C. Run the System (Dev)
- Backend (from `backend/`): `python3 main.py`
- Frontend (from `frontend/`):
  - `npm install`
  - `npm run dev`
- Agent:
  - `python3 -m pip install -r agent/requirements.txt`
  - `export FLIGHTCTRL_TELEMETRY_KEY=...`
  - `python -m flightctrl_agent`

### D. Confirm External Host Telemetry
- UI indicators: Trust panel shows `external_agent` and the HOST TELEMETRY UNAVAILABLE banner is cleared.
- API check: `GET /api/diagnostics` confirms freshness and source.
- Remediation if unavailable:
  - Ensure the agent is running and the telemetry key is correct.
  - Run the agent elevated if collectors require privileges.
  - Keep the agent running long enough to establish baseline samples.

## 5. GO / NO-GO CHECKLIST BEFORE PHASE 5
- Phase 4 tests are green and `PHASE 4 VERIFIED` was printed.
- External telemetry is active and fresh.
- UNAVAILABLE and constraints are visible and truthful across APIs and UI.
- Baseline bands render only when baseline status is AVAILABLE.
- what_changed shows constraints when evidence is missing.
- HARD RULE: "If a feature cannot be implemented on a platform, you must expose it as UNAVAILABLE, explain why, and provide remediation. Silent omission is forbidden."

## 6. PHASE 5 — FULL, DETAILED SPEC (DO NOT IMPLEMENT YET)

### Objective
Implement Braintrust (rule-based agents + Council) with disagreement surfacing and automation safety modes.

### Backend Responsibilities
- Define agent registry, message schema validation, and rule-based reasoning engine.
- Implement disagreement detection and Council aggregation.
- Enforce automation mode gating with audit logging.

### Frontend Responsibilities
- War Room and Council views with disagreement highlighting.
- Global automation mode indicator and gating UX.
- Display citations, constraints, and automation actions in timeline UI.

### Required Endpoints (explicit list)
- `GET /api/agents`
- `GET /api/agents/{id}/profile`
- `GET /api/agents/{id}/events?limit=...`
- `POST /api/braintrust/cycle`
- `GET /api/council/latest`
- `GET/PUT /api/settings/automation_mode`
- `GET /api/timeline`

### Braintrust Message Schema (required fields)
- `agent_id`, `subsystem`
- `observations` with numeric values and timestamps
- `diagnosis`
- `recommendations` (ranked, risk-labeled)
- `confidence` in [0, 1]
- `citations` with field paths, numeric values, timestamps, and provenance/source_type
- `constraints` listing UNAVAILABLE/PARTIAL items affecting the conclusion

### Disagreement Detection Rules (deterministic)
- Disagree when agents recommend conflicting actions on the same target in the same cycle (allow vs deny, execute vs defer, block vs investigate).
- Disagree when risk labels for the same action are opposite (low vs high) within the same cycle.

### Council Output Requirements
- `consensus_plan` and `confidence_spread` must be present.
- Include `disagreements[]` when detected. Each entry includes:
  - agents involved
  - conflicting actions
  - evidence citations
  - what data would resolve the disagreement with remediation if missing

### Automation Safety Modes
- `observe` (default): timeline notes only
- `recommend`: propose tasks/incidents; requires user approval click
- `execute`: allowlist + explicit opt-in + audit logs; never default
- Execute mode must be blocked in read-only mode (Phase 6 dependency).

### Task / Incident Linking
- Agents must reference relevant open tasks and active incidents.
- Council output links to tasks/incidents and to explain_spike or what_changed evidence windows.

### Tests Required
- Schema validation: citations required and non-empty evidence.
- Disagreement detection logic.
- Automation mode gating.
- `/api/timeline` includes agent messages and automation actions with audit metadata.

### Acceptance Criteria
- Orchestrator speaks first; specialist agents follow.
- Agent messages MUST cite real data paths, numeric values, timestamps, and provenance/source_type.
- Disagreements are visible in UI and Council output.
- Automation defaults to observe and never executes without explicit opt-in.
- Constraints are emitted when evidence is missing.
- HARD RULE: "If a feature cannot be implemented on a platform, you must expose it as UNAVAILABLE, explain why, and provide remediation. Silent omission is forbidden."

## 7. PHASE 6 — FULL, DETAILED SPEC (DO NOT IMPLEMENT YET)

### Firewall Enforcement (truthful, best-effort)
- Endpoints:
  - `POST /api/security/allow` (confirm=true required)
  - `POST /api/security/deny` (confirm=true required)
- Per-OS enforcement methods:
  - Windows: netsh or PowerShell; admin required
  - Linux: nftables or iptables or ufw detection; root required
  - macOS: pfctl tables; sudo required
- Audit logging requirements:
  - requested action
  - enforcement attempted
  - enforced true/false
  - if false: NOT ENFORCED with reason and remediation
- NEVER claim enforcement if it was not applied.
- HARD RULE: "If a feature cannot be implemented on a platform, you must expose it as UNAVAILABLE, explain why, and provide remediation. Silent omission is forbidden."

### Read-Only Viewer Mode
- Environment flag or CLI flag that enables read-only state.
- Disables firewall allow/deny, execute-mode automations, and any other mutating controls.
- UI shows a clear read-only banner and disables buttons with tooltips.

### Validation Pack
- Runbooks: `docs/runbook-windows.md`, `docs/runbook-linux.md`, `docs/runbook-macos.md`
- Validation scripts list:
  - external telemetry freshness
  - induced CPU, disk, and network activity
  - freeze/replay if Phase 3 exists
  - explain_spike if Phase 3 exists
  - baseline/what_changed
  - disagreement surfacing
  - automation gating
  - firewall enforcement truthfulness

### Final Acceptance Checklist
- Include known limitations with explicit UNAVAILABLE + remediation per OS.
- HARD RULE: "If a feature cannot be implemented on a platform, you must expose it as UNAVAILABLE, explain why, and provide remediation. Silent omission is forbidden."

## 8. TROUBLESHOOTING (REALISTIC FAILURES)
- pytest failures: install dev deps and rerun `python3 -m pip install -r backend/requirements-dev.txt` then `python3 -m pytest -q`.
- Agent auth failures (401/403): verify `FLIGHTCTRL_TELEMETRY_KEY` and the `X-Telemetry-Key` header match backend config.
- Host telemetry unavailable: ensure agent is running, key is correct, and check `/api/diagnostics` for freshness and remediation.
- Missing privileges: run the agent elevated and enable platform-specific collectors.
- Baseline never warming: keep the agent running until sufficient samples are collected.
- Disagreement not appearing: create test scenarios with conflicting recommendations and verify detection rules.

## 9. RESUME PROMPT (COPY / PASTE)
```
You are resuming FlightCtrl. Follow docs/codex_handoff.md as the single source of truth. Run the Phase 4 verification gate first, and do not start Phase 5 until tests are green and you have printed PHASE 4 VERIFIED. HARD RULE: If a feature cannot be implemented on a platform, you must expose it as UNAVAILABLE, explain why, and provide remediation. Silent omission is forbidden.
```
