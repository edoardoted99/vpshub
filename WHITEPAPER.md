# VPSHub — Whitepaper

## Abstract

VPSHub is a self-hosted, open-source platform for centralized management of remote servers. It adopts an agent-based architecture: a lightweight agent runs on each target server, while a central hub provides a unified web interface for monitoring, command execution, and administration. The goal is to give individuals and small teams a simple, secure, and real-time control plane for all their infrastructure.

---

## 1. Problem Statement

Managing multiple VPS and remote servers is a fragmented experience. System administrators and developers typically deal with:

- **Scattered access**: SSH configs, IP addresses, credentials, and keys spread across files, password managers, and notes.
- **No unified visibility**: no single pane of glass to see which servers are healthy, which are running out of disk, or which went offline.
- **Repetitive operations**: running the same commands (updates, restarts, log checks) across multiple servers manually.
- **Delayed incident detection**: without active monitoring, a server can go down unnoticed for hours.
- **Context switching**: jumping between terminals, monitoring tools, and documentation to manage infrastructure.

Existing solutions are either enterprise-grade and complex (Ansible Tower, Teleport, Rancher) or limited to monitoring only (Netdata, Uptime Kuma). VPSHub aims to fill the gap: a lightweight, all-in-one tool for personal and small-scale server management.

---

## 2. Architecture Overview

The system is composed of two distinct components that communicate over a persistent, encrypted channel.

```
                        ┌──────────────────────────────┐
                        │           VPSHub Hub         │
                        │                              │
                        │  ┌────────┐  ┌────────────┐  │
                        │  │  Web   │  │  Backend    │  │
                        │  │  UI    │  │  API        │  │
                        │  └───┬────┘  └─────┬──────┘  │
                        │      │             │         │
                        │      └──────┬──────┘         │
                        │             │                │
                        │       ┌─────┴─────┐          │
                        │       │ WebSocket │          │
                        │       │  Server   │          │
                        │       └─────┬─────┘          │
                        │             │                │
                        └─────────────┼────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                  │
              ┌─────┴─────┐    ┌─────┴─────┐     ┌─────┴─────┐
              │  Agent A  │    │  Agent B  │     │  Agent C  │
              │ (server1) │    │ (server2) │     │ (server3) │
              └───────────┘    └───────────┘     └───────────┘
```

### 2.1 Agent (Target Server)

The agent is a single, statically compiled binary that runs as a systemd service on each target server. It is designed to be minimal, secure, and zero-configuration after initial enrollment.

**Responsibilities:**

- **Metrics collection**: periodically samples CPU usage, memory, disk, network I/O, load average, and uptime. Metrics are pushed to the hub, not polled.
- **Heartbeat**: sends a periodic signal to the hub to confirm liveness. If the hub stops receiving heartbeats, the server is marked as unreachable.
- **Command execution**: receives commands from the hub and executes them in a controlled shell environment, streaming stdout/stderr back in real time.
- **Interactive shell**: proxies a PTY session from the hub to allow full terminal access through the web browser.
- **Self-reporting**: reports its own version, OS info, and capabilities upon connection.

**Design constraints:**

- Single binary, no runtime dependencies.
- Minimal resource footprint: < 20 MB RAM, negligible CPU at idle.
- Runs as a dedicated unprivileged user (`vpshub-agent`), with optional sudo escalation for administrative commands.
- Connects outbound to the hub (no inbound ports required on the target server).

### 2.2 Hub (Central Server)

The hub is a web application that serves as the control plane. It manages agent connections, stores server metadata, and provides the user interface.

**Responsibilities:**

- **Agent registry**: tracks all enrolled servers, their metadata, tags, and groupings.
- **Real-time dashboard**: displays live metrics received from agents, connection status, and alerts.
- **Command dispatch**: sends commands to one or more agents simultaneously, aggregating results.
- **Web terminal**: provides an interactive SSH-like terminal session through the browser via xterm.js, proxied through the agent's PTY.
- **Alert engine**: evaluates rules against incoming metrics and triggers notifications when thresholds are breached.
- **User authentication**: protects access to the hub with local authentication (username/password + optional TOTP).

**Components:**

| Component | Role |
|-----------|------|
| Web UI | React + TypeScript SPA, dashboard and terminal interface |
| API Server | REST API for CRUD operations, session management |
| WebSocket Server | Persistent connections with agents, real-time data relay |
| Database | SQLite for server registry, metrics history, alert rules |
| Notification Service | Webhook, email, or Telegram/Discord integration for alerts |

---

## 3. Communication Protocol

### 3.1 Transport

All communication between agent and hub occurs over **WebSocket over TLS (wss://)**. The agent initiates the connection outbound to the hub. This means:

- No inbound firewall rules are required on target servers.
- The connection is persistent and bidirectional.
- Reconnection is automatic with exponential backoff.

### 3.2 Message Format

Messages are JSON-encoded with a simple envelope structure:

```json
{
  "type": "metrics | heartbeat | command_request | command_response | shell_data | error",
  "id": "unique-message-id",
  "timestamp": 1709712000,
  "payload": { ... }
}
```

### 3.3 Message Types

| Type | Direction | Description |
|------|-----------|-------------|
| `heartbeat` | Agent -> Hub | Periodic liveness signal with basic status |
| `metrics` | Agent -> Hub | System metrics snapshot |
| `command_request` | Hub -> Agent | Command to execute on the target |
| `command_response` | Agent -> Hub | Streamed output of an executed command |
| `shell_open` | Hub -> Agent | Request to open an interactive PTY session |
| `shell_data` | Bidirectional | Terminal I/O data for interactive sessions |
| `shell_close` | Either | Close an interactive session |
| `agent_info` | Agent -> Hub | Agent version, OS, capabilities (sent on connect) |
| `error` | Either | Error reporting |

### 3.4 Intervals

| Event | Default Interval |
|-------|-----------------|
| Heartbeat | Every 10 seconds |
| Metrics push | Every 30 seconds |
| Offline detection | After 3 missed heartbeats (30 seconds) |
| Reconnection backoff | 1s, 2s, 4s, 8s, ... up to 60s |

---

## 4. Security Model

### 4.1 Agent Enrollment

Servers are enrolled through a token-based flow:

1. The user adds a new server in the hub UI.
2. The hub generates a unique, time-limited enrollment token.
3. The user runs the install script on the target server, passing the token.
4. The agent presents the token on first connection. The hub validates it and issues a persistent API key for future connections.
5. The enrollment token is invalidated.

```bash
# One-liner installation on target server
curl -sSL https://your-hub-address/install.sh | bash -s -- --token <enrollment-token>
```

### 4.2 Authentication and Encryption

- **Agent <-> Hub**: mutual authentication via API key over TLS. All traffic is encrypted in transit.
- **Hub UI**: username/password authentication with optional TOTP 2FA. Sessions are managed via HTTP-only secure cookies.
- **API keys**: stored hashed (bcrypt) in the database. Can be rotated from the hub.

### 4.3 Command Execution Security

- The agent runs as an unprivileged user by default.
- Commands requiring root must be explicitly allowed via a local allowlist or sudo configuration.
- The hub logs all commands executed on every server for audit purposes.
- Optional: restrict command execution to predefined snippets only (disable arbitrary command execution).

### 4.4 Data at Rest

- The SQLite database stores server metadata, hashed API keys, metrics history, and alert configuration.
- No SSH private keys are stored by the hub — the agent model eliminates the need for key management on the hub side.
- The database file should be protected with filesystem permissions and optionally encrypted (SQLCipher).

---

## 5. Core Features

### 5.1 Server Registry

- Add, edit, remove servers.
- Organize with tags (e.g., `production`, `staging`, `database`) and groups.
- Store notes and custom metadata per server.
- View connection history and enrollment date.

### 5.2 Real-Time Dashboard

- Grid or list view of all servers with live status indicators.
- Per-server detail view with time-series charts for CPU, RAM, disk, and network.
- Quick filters by tag, group, or status (online/offline/degraded).
- Summary cards: total servers, online count, alerts active.

### 5.3 Web Terminal

- Full interactive terminal in the browser via xterm.js.
- Session is proxied through the agent's PTY — no direct SSH connection from the hub.
- Supports window resizing, copy/paste, and standard terminal features.
- Optional session recording for audit/replay.

### 5.4 Command Execution

- Run a command on a single server or broadcast to a group.
- Real-time streaming output.
- Saved snippets: predefined commands with name, description, and optional parameters.
- Execution history with output logs.

### 5.5 Alerts and Notifications

- Configurable rules: e.g., "CPU > 90% for 5 minutes", "disk > 85%", "server offline".
- Notification channels: webhook, email, Telegram, Discord.
- Alert history and acknowledgement.

### 5.6 Agent Management

- View agent version and status from the hub.
- Push agent updates remotely.
- Revoke agent access (invalidate API key).

---

## 6. Technology Stack

### Agent

| Concern | Choice | Rationale |
|---------|--------|-----------|
| Language | Go | Single static binary, cross-compilation for linux/amd64, linux/arm64. Minimal footprint. |
| Metrics | `/proc` filesystem, `gopsutil` | Native Linux metrics without external dependencies. |
| Communication | `gorilla/websocket` or `nhooyr.io/websocket` | Reliable WebSocket client with reconnection logic. |
| Process manager | systemd unit | Standard, automatic restart, logging via journald. |

### Hub

| Concern | Choice | Rationale |
|---------|--------|-----------|
| Language | Python | Mature ecosystem, rapid development, excellent for server-side apps. |
| Framework | Django | Batteries-included: ORM, auth, admin, migrations, sessions. |
| Interactivity | htmx | Reactive UI without JavaScript complexity. Server-rendered HTML partials swapped via AJAX. |
| WebSocket | Django Channels + Daphne | Async WebSocket support within the Django ecosystem. |
| Terminal | xterm.js | Industry-standard terminal emulator for the web. Only JS dependency. |
| Database | SQLite (default) / PostgreSQL | SQLite for single-user, PostgreSQL for production. Django ORM abstracts both. |
| Auth | Django built-in auth | Session-based authentication, CSRF protection, optional TOTP via `django-otp`. |
| Styling | Tailwind CSS | Utility-first, fast UI development. |
| Deployment | Docker Compose | Single `docker compose up` to run the hub. |

---

## 7. Deployment Model

VPSHub is designed to be self-hosted. The hub runs on a single server (or even locally) and agents connect outbound to it.

### Hub Deployment

```yaml
# docker-compose.yml
services:
  vpshub:
    image: vpshub/hub:latest
    ports:
      - "3000:3000"
    volumes:
      - ./data:/app/data    # SQLite database
    environment:
      - VPSHUB_SECRET=<random-secret>
      - VPSHUB_DOMAIN=hub.example.com
```

### Agent Installation

```bash
# On each target server
curl -sSL https://hub.example.com/install.sh | bash -s -- --token <token>
```

The install script:
1. Downloads the correct agent binary for the platform.
2. Creates a `vpshub-agent` system user.
3. Installs a systemd service.
4. Configures the hub URL and enrollment token.
5. Starts the agent.

---

## 8. Roadmap

### Phase 1 — Foundation
- Agent: heartbeat, basic metrics (CPU, RAM, disk), WebSocket connection with auto-reconnect.
- Hub: server registry, enrollment flow, real-time dashboard with status indicators.
- Authentication: single-user login.

### Phase 2 — Interaction
- Web terminal via xterm.js.
- Command execution (single server).
- Command history and output logging.

### Phase 3 — Scale
- Multi-server command broadcast.
- Saved snippets and templates.
- Tag-based server groups.

### Phase 4 — Observability
- Metrics history with time-series charts.
- Alert rules engine.
- Notification integrations (webhook, Telegram, Discord).

### Phase 5 — Polish
- Agent auto-update mechanism.
- Session recording and replay.
- Multi-user support with roles.
- API for external integrations.

---

## 9. Conclusion

VPSHub aims to be the simplest way to manage a personal fleet of servers. By using an agent-based architecture, it eliminates the complexity of SSH key distribution, avoids inbound firewall requirements on targets, and enables real-time monitoring without polling overhead. The project prioritizes simplicity, security, and a smooth self-hosting experience.
