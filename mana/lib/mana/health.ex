defmodule Mana.Health do
  @moduledoc """
  Shared system health introspection.

  Used by both the `/api/health` HTTP endpoint and the
  `synthetic_status` plugin to introspect the running system.

  ## Usage

      # Programmatic map
      Mana.Health.check()
      #=> %{status: "healthy", children: 12, version: "0.1.0"}

      # Terminal-formatted string
      Mana.Health.format_status()
      #=> "System Status\n─────────────\nStatus:   healthy\n..."

  """

  require Logger

  @min_expected_children 3

  @type health_info :: %{
          status: String.t(),
          children: non_neg_integer(),
          version: String.t()
        }

  @doc """
  Returns a health information map by inspecting the supervisor tree.

  Fields:
  - `status` — `"healthy"` or `"degraded"`
  - `children` — count of live processes under `Mana.Supervisor`
  - `version` — current Mana version string
  """
  @spec check() :: health_info()
  def check do
    version = Mana.version()
    supervisor_children = get_supervisor_children_count()
    status = determine_health_status(supervisor_children)

    %{
      status: status,
      children: supervisor_children,
      version: version
    }
  end

  @doc """
  Returns a terminal-friendly formatted status string.

  ## Example

      iex> Mana.Health.format_status()
      "System Status\\n─────────────\\nStatus:   healthy\\nChildren: 12\\nVersion:  0.1.0"

  """
  @spec format_status() :: String.t()
  def format_status do
    %{status: status, children: children, version: version} = check()

    "System Status\n" <>
      "─────────────\n" <>
      "Status:   #{status}\n" <>
      "Children: #{children}\n" <>
      "Version:  #{version}"
  end

  # ── Private helpers ──────────────────────────────────────────────────────

  @doc false
  @spec get_supervisor_children_count() :: non_neg_integer()
  def get_supervisor_children_count do
    case Process.whereis(Mana.Supervisor) do
      nil ->
        Logger.warning("Health check: Mana.Supervisor is not registered")
        0

      pid ->
        try do
          %{active: active} = Supervisor.count_children(pid)
          active
        catch
          :exit, _ ->
            Logger.warning("Health check: Failed to count children on Mana.Supervisor")
            0
        end
    end
  end

  @doc false
  @spec determine_health_status(non_neg_integer()) :: String.t()
  def determine_health_status(0), do: "degraded"

  def determine_health_status(count) when is_integer(count) and count > 0 do
    if count >= @min_expected_children do
      "healthy"
    else
      "degraded"
    end
  end

  def determine_health_status(_), do: "degraded"
end
