# ADR-002: Zig ↔ BEAM Integration Strategy

## Status

**ACCEPTED** (2026-04-14)

## Context

The hybrid architecture requires Zig to handle OS-level process work:
- Subprocess spawning and process groups
- PTY lifecycle (fork, read, resize, kill)
- MCP stdio communication
- Output streaming and kill trees

Current Python implementation (`command_runner.py`, `pty_manager.py`) shows this is:
- IO-heavy and blocking by nature
- Stateful and long-lived (PTY sessions)
- OS-resource sensitive
- Safety-critical to isolate from VM

## Decision

**Use Erlang Ports (external Zig processes), not NIFs.**

### Why Ports

| Factor | Port | NIF |
|--------|------|-----|
| Crash isolation | ✅ Zig crash ≠ BEAM crash | ❌ Can corrupt VM |
| Long-running ops | ✅ Natural fit | ❌ Blocks scheduler |
| OTP supervision | ✅ First-class | ⚠️ Complex |
| Shutdown semantics | ✅ Clean | ⚠️ Fragile |
| Debugging | ✅ Easier | ❌ Harder |

### Rejected Alternatives

**NIF**: Poor fit for blocking subprocess/PTY work. Crash risk unacceptable.

**Port Driver**: Legacy approach, same crash-domain problems as NIF.

## Architecture

### Supervision Model

```
DynamicSupervisor
├── PTYSession GenServer (owns Port → Zig worker)
├── PTYSession GenServer (owns Port → Zig worker)
├── MCPConnection GenServer (owns Port → Zig worker)
└── CommandRunner GenServer (owns Port → Zig worker pool)
```

### Ownership Model

| Elixir Owns | Zig Owns |
|-------------|----------|
| Lifecycle decisions | OS handles (PIDs, FDs, PTYs) |
| Supervision/restart | Kill escalation logic |
| Policy/routing | Stdio pipes |
| Session state | Child process reaping |

### Protocol Messages

| Message | Direction | Purpose |
|---------|-----------|---------|
| `spawn_command` | E→Z | Start subprocess |
| `command_output` | Z→E | Stdout/stderr chunk |
| `command_exit` | Z→E | Process terminated |
| `open_pty` | E→Z | Create PTY session |
| `pty_output` | Z→E | PTY output chunk |
| `pty_input` | E→Z | Send to PTY stdin |
| `resize_pty` | E→Z | Terminal resize |
| `close_pty` | E→Z | Terminate PTY |
| `open_mcp_stdio` | E→Z | Start MCP server |
| `mcp_in` | E→Z | Send to MCP stdin |
| `mcp_out` | Z→E | MCP stdout chunk |
| `shutdown` | E→Z | Graceful shutdown |
| `error` | Z→E | Error report |

### Shutdown Sequence

1. Elixir sends `shutdown` / `close_session`
2. Zig performs graceful termination:
   - Close stdin / EOF
   - SIGTERM (grace period)
   - SIGKILL if needed
   - Reap child
3. Zig replies with exit acknowledgment
4. Elixir closes Port
5. Supervisor marks worker terminated

### Abnormal Termination

If Elixir worker crashes:
- Port owner dies
- Zig detects EOF on port
- Zig cleans up all owned resources
- Zig exits

## Consequences

### Positive
- Strong fault isolation
- Clear OTP ownership boundaries
- Natural restart/recovery
- Cleaner migration from Python subprocess code

### Negative
- Need IPC protocol definition
- More moving parts than NIF
- Per-message overhead (acceptable for IO-bound work)

## Future Exception

If profiling identifies a **small, pure, non-blocking native hot path**, that specific helper could be a NIF. But **subprocess, PTY, and MCP stdio must remain external via Ports**.

## Zig Implementation Sketch

```zig
// zig_src/process_runner/main.zig
const std = @import("std");

pub fn main() !void {
    const stdin = std.io.getStdIn();
    const stdout = std.io.getStdOut();
    
    var sessions = SessionRegistry.init();
    defer sessions.deinit();
    
    while (true) {
        const msg = try readFramedMessage(stdin);
        switch (msg.type) {
            .spawn_command => try handleSpawn(&sessions, msg, stdout),
            .open_pty => try handleOpenPty(&sessions, msg, stdout),
            .pty_input => try handlePtyInput(&sessions, msg),
            .resize_pty => try handleResize(&sessions, msg),
            .close_pty => try handleClosePty(&sessions, msg, stdout),
            .shutdown => break,
        }
    }
    
    sessions.cleanupAll();
}
```

## Elixir GenServer Sketch

```elixir
defmodule CodePuppyControl.PTYSession do
  use GenServer
  
  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts)
  end
  
  def init(opts) do
    port = Port.open({:spawn_executable, zig_runner_path()}, [
      :binary, :exit_status, {:packet, 4}
    ])
    
    send_message(port, %{type: :open_pty, session_id: opts[:session_id]})
    {:ok, %{port: port, session_id: opts[:session_id]}}
  end
  
  def handle_info({port, {:data, data}}, %{port: port} = state) do
    case decode_message(data) do
      %{type: :pty_output, data: output} ->
        Phoenix.PubSub.broadcast(PubSub, "pty:#{state.session_id}", {:output, output})
      %{type: :exit, code: code} ->
        {:stop, :normal, state}
    end
    {:noreply, state}
  end
  
  def handle_info({port, {:exit_status, status}}, %{port: port} = state) do
    {:stop, {:zig_exit, status}, state}
  end
end
```
