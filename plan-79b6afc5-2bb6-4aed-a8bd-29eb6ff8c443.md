# FlightCtrl AI Agent System

## Notes
- Initial user request: Launch with 3 AI agents using Ollama at http://192.168.50.200:11434.
- Web-based UI must be cutting-edge, sleek, professional, and display real-time agent chats (agent-to-agent and user-to-agent).
- Only live data is permitted; no test data.
- UI layout and communication protocols are to be locked after signoff.
- Must include widgets and a modern dashboard design.
- Agents must learn and get smarter over time.
- UI must display agent status and current tasks.
- The system must be self-adaptive, with a caretaker agent able to make code changes on the fly.
- Must provide comprehensive system information and diagnostics.
- All code must be production-ready, robust, and fully functional.
- 2024-06-27T14:05-03:00 Plan created and initial requirements logged.
- 2024-06-27T14:15-03:00 User approved architecture, tech stack, protocols, and UI layout. Protocols and UI layout are now locked. Proceeding to implementation.
- 2024-06-27T15:47-03:00 Blocker: Node.js/npm/npx environment is corrupted on Windows, preventing Tailwind CSS CLI from running. User must fully uninstall Node.js, clear npm caches, reboot, and reinstall Node.js LTS. Frontend work is paused until this is resolved. Backend scaffolding will proceed in parallel.
- 2024-06-27T21:00-03:00 Frontend Tailwind CSS + Vite + React integration completed and verified. UI is now ready for live data and agent integration.

## Task List
- [x] Design system architecture and specify all required technologies/frameworks
- [x] Define and document communication protocols between web UI and agents
- [x] Design and lock the final UI layout (dashboard, widgets, chat, agent/task/status panels)
- [ ] Implement backend agent orchestration (Ollama integration, agent lifecycle, learning, caretaker agent)
- [x] Implement real-time web UI (React, widgets, chat, agent/task/status panels)
- [ ] Implement secure, production-grade communication (WebSockets, REST, etc.)
- [ ] Integrate live system performance and health monitoring
- [ ] Implement agent learning and self-adaptation features
- [ ] Implement caretaker agent for self-modifying code
- [ ] Provide comprehensive documentation, changelog, and project overview
- [ ] Repair Node.js/npm/npx environment on Windows (uninstall, clear caches, reboot, reinstall Node.js LTS).
- [ ] Begin backend scaffolding for agent orchestration and real-time API while frontend environment is being repaired.

## Current Goal
Implement backend agent orchestration (Ollama integration, agent lifecycle, learning, caretaker agent) and real-time API. 