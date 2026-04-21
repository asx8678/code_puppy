defmodule CodePuppyControl.CLI.SlashCommands.Commands.MCP do
  @moduledoc """
  MCP slash command: /mcp [help|list|status [name]].

  Read-only entrypoint for inspecting MCP server configuration and runtime
  status.  Follows the same subcommand routing pattern as /diff and
  /model_settings.

  ## Subcommands

      /mcp              — alias for /mcp list
      /mcp list         — show configured servers and their runtime status
      /mcp help         — show MCP command help
      /mcp status       — status dashboard for all servers
      /mcp status <n>   — detailed status for a single server

  ## Design notes

  - Configured server definitions are read from
    `CodePuppyControl.Config.Paths.mcp_servers_file/0` (safe JSON parse).
  - Runtime status is queried from `CodePuppyControl.MCP.Manager` when the
    MCP supervision tree is running; otherwise we show "not running".
  - This module is intentionally read-only.  Start/stop/install/edit are
    separate issues.
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

    #{IO.ANSI.bright()}Status Indicators:#{IO.ANSI.reset()}
      ✓ Running   ✗ Stopped   ⚠ Error   ⏸ Quarantined

    #{IO.ANSI.faint()}Start/stop/install/edit commands will be added in future releases.#{IO.ANSI.reset()}
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

      lines =
        if cfg do
          lines ++
            [
              "    Command:     #{cfg["command"] || "—"}",
              "    Args:        #{inspect(cfg["args"] || [])}",
              "    Env keys:    #{inspect(map_size(cfg["env"] || %{}))}"
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

  defp read_configured_servers do
    path = Paths.mcp_servers_file()

    case File.read(path) do
      {:ok, content} ->
        case Jason.decode(content) do
          {:ok, %{"mcp_servers" => servers}} when is_map(servers) ->
            # Nested shape: {"mcp_servers": {"fs": {...}, ...}}
            servers_to_list(servers)

          {:ok, flat} when is_map(flat) ->
            # Flat top-level shape: {"fs": {...}, "gh": {...}}
            # Only treat as server defs if values are maps (skip malformed)
            if Enum.any?(flat, fn {_k, v} -> is_map(v) end) do
              servers_to_list(flat)
            else
              []
            end

          {:ok, _other} ->
            []

          {:error, _} ->
            []
        end

      {:error, _} ->
        []
    end
  end

  # Converts a name-keyed map of server defs into a list with "name" injected.
  # Skips entries whose value is not a map (e.g. "broken": true).
  defp servers_to_list(servers_map) do
    servers_map
    |> Enum.filter(fn {_name, cfg} -> is_map(cfg) end)
    |> Enum.map(fn {name, cfg} ->
      Map.put(cfg, "name", name)
    end)
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
