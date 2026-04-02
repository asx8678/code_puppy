# Mana Bridge

The **Mana Bridge** connects Code Puppy (Python) to [Mana](../mana) — a Phoenix LiveView dashboard — over a TCP socket. When enabled, every agent lifecycle event, streaming token, and tool call is forwarded in real time so Mana can render a live chat interface.

---

## How to Enable

### CLI flag

```bash
code_puppy --bridge-mode
```

### Environment variable

```bash
export CODE_PUPPY_BRIDGE=1
code_puppy
```

Both are equivalent — the `--bridge-mode` flag simply sets `CODE_PUPPY_BRIDGE=1` internally before plugins load.

---

## Architecture

```text
Code Puppy (Python)                    Mana (Elixir / Phoenix LiveView)
┌──────────────────────┐              ┌──────────────────────────────┐
│  mana_bridge plugin  │              │  Bridge TCP listener         │
│  register_callbacks  │   TCP:9847   │  (Socket accept loop)        │
│        │             │─────────────▶│        │                     │
│  stream_event        │   msgpack    │  Decode frame                │
│  agent_run_start/end │   frames     │  Publish via PubSub           │
│  pre/post_tool_call  │              │        │                     │
│  startup / shutdown  │              │  LiveView subscribes          │
└──────────────────────┘              │  → renders chat UI           │
                                      └──────────────────────────────┘
```

### Flow

1. **Code Puppy starts** → `startup` callback opens a TCP connection to `127.0.0.1:9847`.
2. **Hello handshake** → sends a `{"name": "hello", "data": {"version": "...", "bridge_type": "code_puppy"}}` event.
3. **During an agent run** → every `stream_event`, `agent_run_start/end`, `pre_tool_call`, and `post_tool_call` callback enqueues a message.
4. **Background sender thread** → drains the queue, serialises each message with **msgpack**, and writes a length-prefixed frame to the socket.
5. **Mana** → receives the frame, decodes it, and broadcasts via Phoenix PubSub to the LiveView process.
6. **On shutdown** → sends a `goodbye` event and closes the socket.

---

## Wire Protocol

Each message on the wire is:

```text
[4 bytes: big-endian uint32 payload length][msgpack-encoded payload]
```

The msgpack payload is a map with this schema:

```json
{
  "id": "uuid4-string",
  "type": "event",
  "name": "event_name",
  "data": { ... }
}
```

For the full protocol specification (including Mana-side handling), see [../mana/docs/bridge_protocol.md](../mana/docs/bridge_protocol.md).

---

## Events Sent

| Event Name | Trigger | Payload |
|---|---|---|
| `hello` | Startup handshake | `{"version", "bridge_type": "code_puppy"}` |
| `goodbye` | Shutdown | `{"reason": "shutdown"}` |
| `token` | Streaming token (`stream_event` with `event_type="token"`) | `{"event_type", "agent_session_id", "data"}` |
| `part_start` | Part start (`stream_event` with `event_type="part_start"`) | `{"event_type", "agent_session_id", "data"}` |
| `part_delta` | Part delta (`stream_event` with `event_type="part_delta"`) | `{"event_type", "agent_session_id", "data"}` |
| `part_end` | Part end (`stream_event` with `event_type="part_end"`) | `{"event_type", "agent_session_id", "data"}` |
| `stream_event` | Any other stream event (passthrough) | `{"event_type", "agent_session_id", "data"}` |
| `agent_run_start` | Agent begins a run | `{"agent_name", "model_name", "session_id", "timestamp"}` |
| `agent_run_end` | Agent finishes a run | `{"agent_name", "model_name", "session_id", "success", "timestamp", "error?", "response_preview?", "metadata?"}` |
| `tool_call_start` | Before a tool executes | `{"tool_name", "tool_args", "start_time"}` |
| `tool_call_end` | After a tool returns | `{"tool_name", "tool_args", "duration_ms", "success", "result_summary"}` |

All string fields are truncated to 500 characters and complex values are summarised to keep payloads small and msgpack-safe.

---

## Configuration

| Env Variable | Default | Description |
|---|---|---|
| `CODE_PUPPY_BRIDGE` | _(unset)_ | Set to `1` to enable the bridge |
| `CODE_PUPPY_BRIDGE_HOST` | `127.0.0.1` | TCP host of the Mana bridge listener |
| `CODE_PUPPY_BRIDGE_PORT` | `9847` | TCP port of the Mana bridge listener |

---

## Requirements

1. **msgpack** — the `msgpack` Python package must be installed:

   ```bash
   pip install msgpack
   ```

   If it's missing the bridge logs a warning and disables itself silently.

2. **Mana Phoenix project** — the Elixir/Phoenix LiveView app must be running with its bridge TCP listener on the configured host and port. See [../mana/](../mana) for setup instructions.

---

## Reconnection

If the TCP connection drops (e.g., Mana is restarted), the bridge automatically reconnects with **exponential backoff**:

- Initial delay: **0.5 s**
- Multiplier: **2×** (0.5 → 1 → 2 → 4 → …)
- Max delay: **30 s**

Events generated while disconnected are buffered in a send queue (capacity: 10 000 messages). If the queue fills, oldest events are silently dropped.

---

## Troubleshooting

### Connection refused / nothing appears in Mana

**Cause:** Mana is not running or not listening on the expected port.

**Fix:**
1. Make sure the Mana Phoenix server is started (`mix phx.server` in the Mana project).
2. Verify the port matches: default is `9847` — override with `CODE_PUPPY_BRIDGE_PORT`.
3. Check the Code Puppy logs for a warning like `Mana bridge failed to connect to 127.0.0.1:9847`.

### `msgpack is not installed — Mana bridge disabled`

**Cause:** The `msgpack` Python package is not installed.

**Fix:**
```bash
pip install msgpack
```
Or with uv:
```bash
uv pip install msgpack
```

### Events are missing or delayed

**Cause:** The send queue (10 000 capacity) may be full under heavy load, causing events to be dropped.

**Fix:**
- Check logs for `Mana bridge send queue full — dropping` messages.
- Reduce event volume or increase processing capacity on the Mana side.

### Bridge not activating even with `--bridge-mode`

**Cause:** Plugin not loading, or `CODE_PUPPY_BRIDGE` being overridden.

**Fix:**
1. Run `code_puppy --bridge-mode` and check for `Mana bridge disabled` or `Mana bridge connected` in the logs.
2. Ensure the `mana_bridge` plugin directory exists under `code_puppy/plugins/mana_bridge/`.
3. Verify no other process sets `CODE_PUPPY_BRIDGE=0`.

---

## Implementation

The bridge is implemented as a Code Puppy **plugin** at `code_puppy/plugins/mana_bridge/`:

- **`register_callbacks.py`** — hooks into `startup`, `shutdown`, `stream_event`, `agent_run_start/end`, `pre_tool_call`, and `post_tool_call` callbacks.
- **`tcp_client.py`** — `BridgeClient` class managing the TCP connection, msgpack framing, sender thread, and reconnect logic.

Tests live in `tests/test_mana_bridge.py`.
