# FlightCtrl User Guide

## Authentication
- Sign in with your FlightCtrl credentials when prompted.
- If your session expires, you'll be asked to sign in again.

## Dashboard
- Overview gauges for CPU/mem/disk, network flow graph, disk I/O ripple, firewall threats.
- Timeline & replay slider to scrub recent snapshots.
- Theme switcher (cyber, jet, starship, minimal, hacker) and grid toggle.

## Agents
- Select an agent to see profile, strengths/weaknesses, current task, and last notes.
- Event console shows stream with type coloring; pause/scroll supported in UI.

## Chat & Incidents
- Threaded chat with reply/incident filters and typing/thinking indicators.
- Use incident filter to focus related discussions.

## Tasks & Automations
- Create tasks with priority/assignee; task cards show status history.
- Build automations (interval or metric threshold) with notify/create-task actions.

## Network & War Room
- Network tab lists flows, firewall rules, allow/deny actions.
- War Room shows live connection graph; click nodes for actions and details.

## Council Mode
- Ask multi-agent council; view per-agent reasoning, consensus votes, and export JSON.

## Themes & Branding
- Animated logo and optional splash screen on load.

## Keyboard
- Ctrl/Cmd+K opens command palette.

## Running the Host Telemetry Agent
The backend uses the external agent as the source of truth for host telemetry.

### Windows
```sh
python -m pip install -r agent/requirements.txt
set FLIGHTCTRL_TOKEN=your_admin_jwt
python -m flightctrl_agent --backend http://127.0.0.1:8000 --interval 2
```
Run in an Administrator shell to access full network/firewall metrics.

### Linux
```sh
python -m pip install -r agent/requirements.txt
export FLIGHTCTRL_TOKEN=your_admin_jwt
sudo -E python -m flightctrl_agent --backend http://127.0.0.1:8000 --interval 2
```
Use sudo for full network and firewall visibility.

### macOS
```sh
python -m pip install -r agent/requirements.txt
export FLIGHTCTRL_TOKEN=your_admin_jwt
sudo -E python -m flightctrl_agent --backend http://127.0.0.1:8000 --interval 2
```
Use sudo to access pf firewall state and full socket visibility.
