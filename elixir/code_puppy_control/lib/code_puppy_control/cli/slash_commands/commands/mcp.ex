defmodule CodePuppyControl.CLI.SlashCommands.Commands.MCP do
  @moduledoc """
  MCP slash command: /mcp [help|list|status|start|stop|restart|start-all|stop-all].

  Entry point for inspecting MCP server configuration, runtime status,
  and lifecycle management.  Follows the same subcommand routing pattern
  as /diff and /model_settings.

  ## Subcommands

      /mcp                — alias for /mcp list
      /mcp list           — show configured servers and their runtime status
      /mcp help           — show MCP command help
      /mcp status         — status dashboard for all servers
      /mcp status <n>     — detailed status for a single server
      /mcp start <n>      — start a configured server by name
      /mcp stop <n>       — stop a running server by name
      /mcp restart <n>    — restart a server by name (reads fresh config)
      /mcp start-all      — start all configured servers
      /mcp stop-all       — stop all running servers

  ## Design notes

  - Configured server definitions are read from
    `CodePuppyControl.Config.Paths.mcp_servers_file/0` (safe JSON parse).
  - Runtime status is queried from `CodePuppyControl.MCP.Manager` when the
    MCP supervision tree is running; otherwise we show "not running".
  - Lifecycle commands (start/stop/restart/start-all/stop-all) delegate to
    `MCP.Manager` helpers that read config from disk.
  - Pure formatting functions are public for testability.
  """

  alias CodePuppyControl.Config.Paths
  alias CodePuppyControl.MCP.Manager

  # ── Public API ──────────────────────────────────────────────────────────

  @doc """
  Handles `/mcp` — routes to the appropriate subcommand.

  Returns `{:continue, state}` in all cases (read-only, never halts).
  """
  @spec handle_mcp(String.t(), any()) :: {:continue, any()}
  def handle_mcp(line, state) do
    case extract_args(line) do
      "" -> show_list()
      args -> route_subcommand(args)
    end

    {:continue, state}
  end

  # ── Subcommand: help ────────────────────────────────────────────────────

  @doc """
  Formats the help text as a string (pure, no IO — testable).
  """
  @spec format_help() :: String.t()
  def format_help do
    """
    #{IO.ANSI.bright()}MCP Server Management Commands#{IO.ANSI.reset()}

    #{IO.ANSI.bright()}Core Commands:#{IO.ANSI.reset()}
      #{IO.ANSI.cyan()}/mcp#{IO.ANSI.reset()}              Show configured servers and status
      #{IO.ANSI.cyan()}/mcp list#{IO.ANSI.reset()}          Show configured servers and runtime status
      #{IO.ANSI.cyan()}/mcp help#{IO.ANSI.reset()}          Show this help message
      #{IO.ANSI.cyan()}/mcp status#{IO.ANSI.reset()}        Status dashboard for all servers
      #{IO.ANSI.cyan()}/mcp status <name>#{IO.ANSI.reset()} Detailed status for one server

    #{IO.ANSI.bright()}Lifecycle Commands:#{IO.ANSI.reset()}
      #{IO.ANSI.cyan()}/mcp start <name>#{IO.ANSI.reset()}   Start a configured server
      #{IO.ANSI.cyan()}/mcp stop <name>#{IO.ANSI.reset()}    Stop a running server
      #{IO.ANSI.cyan()}/mcp restart <name>#{IO.ANSI.reset()} Restart a server (fresh config)
      #{IO.ANSI.cyan()}/mcp start-all#{IO.ANSI.reset()}      Start all configured servers
      #{IO.ANSI.cyan()}/mcp stop-all#{IO.ANSI.reset()}       Stop all running servers

    #{IO.ANSI.bright()}Status Indicators:#{IO.ANSI.reset()}
      ✓ Running   ✗ Stopped   ⚠ Error   ⏸ Quarantined
    """
  end

  # ── Subcommand: list ────────────────────────────────────────────────────

  @doc """
  Reads configured MCP servers from disk and enriches them with runtime
  status.  Returns `{configured_servers, runtime_servers}` where:

  - `configured_servers` — list of maps parsed from `mcp_servers.json`
  - `runtime_servers`   — list of status maps from `MCP.Manager.list_servers/0`
    (empty when the MCP tree is not running)

  Pure function (no IO) — testable without capturing output.
  """
  @spec fetch_server_data() :: {[map()], [map()]}
  def fetch_server_data do
    configured = read_configured_servers()
    runtime = fetch_runtime_servers()
    {configured, runtime}
  end

  @doc """
  Formats the server list as a string (pure, no IO).
  """
  @spec format_list([map()], [map()]) :: String.t()
  def format_list(configured, runtime) do
    runtime_map = build_runtime_map(runtime)

    if configured == [] do
      "    No MCP servers configured.\n" <>
        "    Add servers to #{Paths.mcp_servers_file()} to get started."
    else
      lines =
        ["    #{IO.ANSI.bright()}MCP Servers#{IO.ANSI.reset()}", ""]
        |> Kernel.++(
          Enum.map(configured, fn server ->
            name = server["name"] || "unknown"
            rt = Map.get(runtime_map, name)
            status_icon = runtime_status_icon(rt)
            health_str = runtime_health_str(rt)
            cmd = server["command"] || "—"

            "    #{status_icon} #{IO.ANSI.cyan()}#{name}#{IO.ANSI.reset()}" <>
              "   #{IO.ANSI.faint()}#{cmd}#{IO.ANSI.reset()}" <>
              "   #{health_str}"
          end)
        )
        |> Kernel.++([""])
        |> Kernel.++([
          "    #{IO.ANSI.faint()}#{length(configured)} configured, #{length(runtime)} running#{IO.ANSI.reset()}"
        ])

      Enum.join(lines, "\n")
    end
  end

  # ── Subcommand: status ─────────────────────────────────────────────────

  @doc """
  Formats the status dashboard for all servers (pure, no IO).
  """
  @spec format_status_dashboard([map()], [map()]) :: String.t()
  def format_status_dashboard(configured, runtime) do
    runtime_map = build_runtime_map(runtime)

    if configured == [] do
      "    No MCP servers configured."
    else
      lines =
        ["    #{IO.ANSI.bright()}MCP Status Dashboard#{IO.ANSI.reset()}", ""]
        |> Kernel.++(
          Enum.map(configured, fn server ->
            name = server["name"] || "unknown"
            rt = Map.get(runtime_map, name)

            status = if rt, do: rt.status, else: "stopped"
            health = if rt, do: rt.health, else: :unknown
            errors = if rt, do: rt.error_count, else: 0
            quarantined = if rt, do: rt.quarantined, else: false

            status_icon = status_to_icon(status)
            health_str = health_to_string(health)

            q_str =
              if quarantined, do: " #{IO.ANSI.yellow()}⏸ Quarantined#{IO.ANSI.reset()}", else: ""

            err_str = if errors > 0, do: " (#{errors} errors)", else: ""

            "    #{status_icon} #{IO.ANSI.cyan()}#{String.pad_trailing(name, 20)}#{IO.ANSI.reset()}" <>
              " #{String.pad_trailing(to_string(status), 10)}" <>
              " #{health_str}#{err_str}#{q_str}"
          end)
        )
        |> Kernel.++([""])

      Enum.join(lines, "\n")
    end
  end

  @doc """
  Formats detailed status for a single server (pure, no IO).
  Returns `{:ok, text}` if found, `{:error, :not_found}` otherwise.
  """
  @spec format_server_status(String.t(), [map()], [map()]) ::
          {:ok, String.t()} | {:error, :not_found}
  def format_server_status(name, configured, runtime) do
    runtime_map = build_runtime_map(runtime)
    cfg = Enum.find(configured, &(&1["name"] == name))

    if cfg == nil and not Map.has_key?(runtime_map, name) do
      {:error, :not_found}
    else
      rt = Map.get(runtime_map, name)

      lines = [
        "    #{IO.ANSI.bright()}Server: #{name}#{IO.ANSI.reset()}",
        ""
      ]

      # Normalize malformed field types so /mcp status never crashes
      # on non-map env or non-list args values (e.g. {"env": "oops"}).
      safe_env = if is_map(cfg["env"]), do: cfg["env"], else: %{}
      safe_args = if is_list(cfg["args"]), do: cfg["args"], else: []

      lines =
        if cfg do
          lines ++
            [
              "    Command:     #{cfg["command"] || "—"}",
              "    Args:        #{inspect(safe_args)}",
              "    Env keys:    #{inspect(map_size(safe_env))}"
            ]
        else
          lines
        end

      lines =
        if rt do
          (lines ++
             [
               "",
               "    Status:      #{rt.status}",
               "    Health:      #{rt.health}",
               "    Errors:      #{rt.error_count}",
               "    Quarantined: #{rt.quarantined}",
               "    Server ID:   #{rt.server_id}"
             ])
          |> Kernel.++(
            if rt.quarantine_until do
              ["    Quarantined until: #{rt.quarantine_until}"]
            else
              []
            end
          )
          |> Kernel.++(
            if rt.last_health_check do
              ["    Last check: #{rt.last_health_check}"]
            else
              []
            end
          )
        else
          lines ++ ["", "    #{IO.ANSI.faint()}Not currently running#{IO.ANSI.reset()}"]
        end

      {:ok, Enum.join(lines, "\n")}
    end
  end

  # ── Private helpers ────────────────────────────────────────────────────

  defp route_subcommand(args) do
    parts = String.split(args, ~r/\s+/, trim: true)

    # Case-insensitive matching on subcommand tokens only —
    # server names must preserve original casing.
    lowered = Enum.map(parts, &String.downcase/1)

    case lowered do
      ["help"] -> show_help()
      ["list"] -> show_list()
      ["status"] -> show_status()
      ["status", _name_lower] -> show_server_status(Enum.at(parts, 1))
      ["start"] -> show_start_usage()
      ["start", _name_lower] -> show_start(Enum.at(parts, 1))
      ["stop"] -> show_stop_usage()
      ["stop", _name_lower] -> show_stop(Enum.at(parts, 1))
      ["restart"] -> show_restart_usage()
      ["restart", _name_lower] -> show_restart(Enum.at(parts, 1))
      ["start-all"] -> show_start_all()
      ["stop-all"] -> show_stop_all()
      _ -> show_unknown(parts)
    end
  end

  defp show_help do
    IO.puts("")
    IO.puts(format_help())
    IO.puts("")
  end

  defp show_list do
    {configured, runtime} = fetch_server_data()

    IO.puts("")
    IO.puts(format_list(configured, runtime))
    IO.puts("")
  end

  defp show_status do
    {configured, runtime} = fetch_server_data()

    IO.puts("")
    IO.puts(format_status_dashboard(configured, runtime))
    IO.puts("")
  end

  defp show_server_status(name) do
    {configured, runtime} = fetch_server_data()

    case format_server_status(name, configured, runtime) do
      {:ok, text} ->
        IO.puts("")
        IO.puts(text)
        IO.puts("")

      {:error, :not_found} ->
        IO.puts("")

        IO.puts(
          IO.ANSI.red() <>
            "    Server '#{name}' not found." <>
            IO.ANSI.reset()
        )

        IO.puts("    Use /mcp list to see configured servers.")
        IO.puts("")
    end
  end

  # ── Subcommand: start ──────────────────────────────────────────────────

  defp show_start_usage do
    IO.puts("")
    IO.puts("    #{IO.ANSI.yellow()}Usage: /mcp start <server_name>#{IO.ANSI.reset()}")
    IO.puts("    Use /mcp list to see configured servers.")
    IO.puts("")
  end

  defp show_start(name) do
    result =
      if mcp_supervisor_running?() do
        try do
          Manager.start_server_by_name(name)
        rescue
          _ -> {:error, :supervisor_error}
        end
      else
        {:error, :supervisor_not_running}
      end

    IO.puts("")
    IO.puts(format_start_result(name, result))
    IO.puts("")
  end

  @doc """
  Formats the result of a start operation (pure, no IO).
  """
  @spec format_start_result(String.t(), {:ok, String.t()} | {:ok, :already_running} | {:error, term()}) ::
          String.t()
  def format_start_result(name, {:ok, :already_running}) do
    "    #{IO.ANSI.yellow()}• #{name} is already running#{IO.ANSI.reset()}"
  end

  def format_start_result(name, {:ok, server_id}) do
    "    #{IO.ANSI.green()}✓ Started server (#{server_id})#{IO.ANSI.reset()}\n" <>
      "    #{IO.ANSI.faint()}Use /mcp status #{name} to check initialization.#{IO.ANSI.reset()}"
  end

  def format_start_result(name, {:error, :not_configured}) do
    "    #{IO.ANSI.red()}✗ Server '#{name}' not found in configuration.#{IO.ANSI.reset()}\n" <>
      "    Use /mcp list to see configured servers."
  end

  def format_start_result(name, {:error, :supervisor_not_running}) do
    "    #{IO.ANSI.red()}✗ Cannot start '#{name}' — MCP supervisor is not running.#{IO.ANSI.reset()}"
  end

  def format_start_result(name, {:error, reason}) do
    "    #{IO.ANSI.red()}✗ Failed to start '#{name}': #{inspect(reason)}#{IO.ANSI.reset()}"
  end

  # ── Subcommand: stop ───────────────────────────────────────────────────

  defp show_stop_usage do
    IO.puts("")
    IO.puts("    #{IO.ANSI.yellow()}Usage: /mcp stop <server_name>#{IO.ANSI.reset()}")
    IO.puts("    Use /mcp status to see running servers.")
    IO.puts("")
  end

  defp show_stop(name) do
    result =
      if mcp_supervisor_running?() do
        try do
          Manager.stop_server_by_name(name)
        rescue
          _ -> {:error, :supervisor_error}
        end
      else
        {:error, :supervisor_not_running}
      end

    IO.puts("")
    IO.puts(format_stop_result(name, result))
    IO.puts("")
  end

  @doc """
  Formats the result of a stop operation (pure, no IO).
  """
  @spec format_stop_result(String.t(), :ok | {:error, term()}) :: String.t()
  def format_stop_result(name, :ok) do
    "    #{IO.ANSI.green()}✓ Stopped server: #{name}#{IO.ANSI.reset()}"
  end

  def format_stop_result(name, {:error, :not_running}) do
    "    #{IO.ANSI.yellow()}• '#{name}' is not currently running#{IO.ANSI.reset()}"
  end

  def format_stop_result(name, {:error, :supervisor_not_running}) do
    "    #{IO.ANSI.red()}✗ Cannot stop '#{name}' — MCP supervisor is not running.#{IO.ANSI.reset()}"
  end

  def format_stop_result(name, {:error, reason}) do
    "    #{IO.ANSI.red()}✗ Failed to stop '#{name}': #{inspect(reason)}#{IO.ANSI.reset()}"
  end

  # ── Subcommand: restart ────────────────────────────────────────────────

  defp show_restart_usage do
    IO.puts("")
    IO.puts("    #{IO.ANSI.yellow()}Usage: /mcp restart <server_name>#{IO.ANSI.reset()}")
    IO.puts("    Use /mcp list to see configured servers.")
    IO.puts("")
  end

  defp show_restart(name) do
    result =
      if mcp_supervisor_running?() do
        try do
          Manager.restart_server_by_name(name)
        rescue
          _ -> {:error, :supervisor_error}
        end
      else
        {:error, :supervisor_not_running}
      end

    IO.puts("")
    IO.puts(format_restart_result(name, result))
    IO.puts("")
  end

  @doc """
  Formats the result of a restart operation (pure, no IO).
  """
  @spec format_restart_result(String.t(), {:ok, String.t()} | {:error, term()}) :: String.t()
  def format_restart_result(name, {:ok, server_id}) do
    "    #{IO.ANSI.green()}✓ Restarted server: #{name} (#{server_id})#{IO.ANSI.reset()}"
  end

  def format_restart_result(name, {:error, :not_configured}) do
    "    #{IO.ANSI.red()}✗ Server '#{name}' not found in configuration.#{IO.ANSI.reset()}\n" <>
      "    Use /mcp list to see configured servers."
  end

  def format_restart_result(name, {:error, :supervisor_not_running}) do
    "    #{IO.ANSI.red()}✗ Cannot restart '#{name}' — MCP supervisor is not running.#{IO.ANSI.reset()}"
  end

  def format_restart_result(name, {:error, reason}) do
    "    #{IO.ANSI.red()}✗ Failed to restart '#{name}': #{inspect(reason)}#{IO.ANSI.reset()}"
  end

  # ── Subcommand: start-all ─────────────────────────────────────────────

  defp show_start_all do
    results =
      if mcp_supervisor_running?() do
        try do
          Manager.start_all_configured()
        rescue
          _ -> []
        end
      else
        []
      end

    IO.puts("")
    IO.puts(format_start_all_result(results))
    IO.puts("")
  end

  @doc """
  Formats the result of a start-all operation (pure, no IO).
  """
  @spec format_start_all_result([{String.t(), atom() | tuple()}]) :: String.t()
  def format_start_all_result([]) do
    "    #{IO.ANSI.faint()}No MCP servers configured.#{IO.ANSI.reset()}"
  end

  def format_start_all_result(results) do
    lines = ["    #{IO.ANSI.bright()}Starting all configured servers#{IO.ANSI.reset()}", ""]

    {started, already, failed} =
      Enum.reduce(results, {0, 0, 0}, fn
        {_name, {:ok, :already_running}}, {s, a, f} -> {s, a + 1, f}
        {_name, {:ok, _sid}}, {s, a, f} -> {s + 1, a, f}
        {_name, {:error, _}}, {s, a, f} -> {s, a, f + 1}
      end)

    per_server =
      Enum.map(results, fn
        {name, {:ok, :already_running}} ->
          "    #{IO.ANSI.yellow()}• #{name}: already running#{IO.ANSI.reset()}"

        {name, {:ok, _sid}} ->
          "    #{IO.ANSI.green()}✓ Started: #{name}#{IO.ANSI.reset()}"

        {name, {:error, reason}} ->
          "    #{IO.ANSI.red()}✗ #{name}: #{format_error_reason(reason)}#{IO.ANSI.reset()}"
      end)

    summary =
      [""] ++
      ["    #{IO.ANSI.faint()}#{started} started, #{already} already running, #{failed} failed#{IO.ANSI.reset()}"]

    Enum.join(lines ++ per_server ++ summary, "\n")
  end

  # ── Subcommand: stop-all ──────────────────────────────────────────────

  defp show_stop_all do
    results =
      if mcp_supervisor_running?() do
        try do
          Manager.stop_all_running()
        rescue
          _ -> []
        end
      else
        []
      end

    IO.puts("")
    IO.puts(format_stop_all_result(results))
    IO.puts("")
  end

  @doc """
  Formats the result of a stop-all operation (pure, no IO).
  """
  @spec format_stop_all_result([{String.t(), :ok | {:error, term()}}]) :: String.t()
  def format_stop_all_result([]) do
    "    #{IO.ANSI.faint()}No MCP servers currently running.#{IO.ANSI.reset()}"
  end

  def format_stop_all_result(results) do
    lines = ["    #{IO.ANSI.bright()}Stopping all running servers#{IO.ANSI.reset()}", ""]

    {stopped, failed} =
      Enum.reduce(results, {0, 0}, fn
        {_name, :ok}, {s, f} -> {s + 1, f}
        {_name, {:error, _}}, {s, f} -> {s, f + 1}
      end)

    per_server =
      Enum.map(results, fn
        {name, :ok} ->
          "    #{IO.ANSI.green()}✓ Stopped: #{name}#{IO.ANSI.reset()}"

        {name, {:error, reason}} ->
          "    #{IO.ANSI.red()}✗ #{name}: #{format_error_reason(reason)}#{IO.ANSI.reset()}"
      end)

    summary =
      [""] ++
      ["    #{IO.ANSI.faint()}#{stopped} stopped, #{failed} failed#{IO.ANSI.reset()}"]

    Enum.join(lines ++ per_server ++ summary, "\n")
  end

  # ── Shared formatting helpers ─────────────────────────────────────────

  defp format_error_reason(:not_configured), do: "not configured"
  defp format_error_reason(:not_running), do: "not running"
  defp format_error_reason(:supervisor_not_running), do: "supervisor not running"
  defp format_error_reason(reason), do: inspect(reason)

  defp show_unknown(parts) do
    subcmd = List.first(parts) || ""

    IO.puts("")

    IO.puts(
      IO.ANSI.red() <>
        "    Unknown MCP subcommand: '#{subcmd}'" <>
        IO.ANSI.reset()
    )

    IO.puts("    Type /mcp help for available commands.")
    IO.puts("")
  end

  # ── Config reading ─────────────────────────────────────────────────────

  # Delegates to Manager.read_configured_servers/0 which reads from
  # mcp_servers.json.  This private wrapper preserves the existing API
  # for the read-only subcommands while keeping config logic in one place.
  defp read_configured_servers do
    Manager.read_configured_servers()
  end

  # ── Runtime queries ────────────────────────────────────────────────────

  defp fetch_runtime_servers do
    if mcp_supervisor_running?() do
      try do
        Manager.list_servers()
      rescue
        _ -> []
      end
    else
      []
    end
  end

  defp mcp_supervisor_running? do
    case Process.whereis(CodePuppyControl.MCP.Supervisor) do
      nil -> false
      _pid -> true
    end
  end

  # ── Formatting helpers ─────────────────────────────────────────────────

  defp build_runtime_map(runtime_servers) do
    runtime_servers
    |> Enum.filter(&is_map/1)
    |> Enum.into(%{}, fn rt ->
      name = Map.get(rt, :name, Map.get(rt, "name", "unknown"))
      {name, rt}
    end)
  end

  defp runtime_status_icon(nil), do: IO.ANSI.faint() <> "✗" <> IO.ANSI.reset()
  defp runtime_status_icon(%{status: :running}), do: IO.ANSI.green() <> "✓" <> IO.ANSI.reset()
  defp runtime_status_icon(%{status: :starting}), do: IO.ANSI.yellow() <> "⏳" <> IO.ANSI.reset()
  defp runtime_status_icon(%{status: :crashed}), do: IO.ANSI.red() <> "⚠" <> IO.ANSI.reset()
  defp runtime_status_icon(%{status: :stopped}), do: IO.ANSI.faint() <> "✗" <> IO.ANSI.reset()
  defp runtime_status_icon(_), do: "?"

  defp runtime_health_str(nil), do: ""

  defp runtime_health_str(%{health: :healthy}),
    do: IO.ANSI.green() <> "healthy" <> IO.ANSI.reset()

  defp runtime_health_str(%{health: :degraded}),
    do: IO.ANSI.yellow() <> "degraded" <> IO.ANSI.reset()

  defp runtime_health_str(%{health: :unhealthy}),
    do: IO.ANSI.red() <> "unhealthy" <> IO.ANSI.reset()

  defp runtime_health_str(%{health: :unknown}),
    do: IO.ANSI.faint() <> "unknown" <> IO.ANSI.reset()

  defp runtime_health_str(_), do: ""

  defp status_to_icon(:running), do: IO.ANSI.green() <> "✓" <> IO.ANSI.reset()
  defp status_to_icon(:starting), do: IO.ANSI.yellow() <> "⏳" <> IO.ANSI.reset()
  defp status_to_icon(:stopped), do: IO.ANSI.faint() <> "✗" <> IO.ANSI.reset()
  defp status_to_icon(:crashed), do: IO.ANSI.red() <> "⚠" <> IO.ANSI.reset()
  # String fallbacks — runtime may return strings instead of atoms
  defp status_to_icon("running"), do: status_to_icon(:running)
  defp status_to_icon("starting"), do: status_to_icon(:starting)
  defp status_to_icon("stopped"), do: status_to_icon(:stopped)
  defp status_to_icon("crashed"), do: status_to_icon(:crashed)
  defp status_to_icon(s), do: to_string(s)

  defp health_to_string(:healthy), do: IO.ANSI.green() <> "healthy" <> IO.ANSI.reset()
  defp health_to_string(:degraded), do: IO.ANSI.yellow() <> "degraded" <> IO.ANSI.reset()
  defp health_to_string(:unhealthy), do: IO.ANSI.red() <> "unhealthy" <> IO.ANSI.reset()
  defp health_to_string(:unknown), do: IO.ANSI.faint() <> "unknown" <> IO.ANSI.reset()
  defp health_to_string(h), do: to_string(h)

  # Extracts the argument portion from a raw slash command line.
  # "/mcp list" → "list"
  # "/mcp"      → ""
  @spec extract_args(String.t()) :: String.t()
  defp extract_args("/" <> rest) do
    case String.split(rest, " ", parts: 2) do
      [_name] -> ""
      [_name, args] -> args
    end
  end

  defp extract_args(_line), do: ""
end
