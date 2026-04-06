defmodule Mana.Plugins.SyntheticStatus do
  @moduledoc """
  Plugin that exposes system health status via a slash command.

  Provides the `/synthetic_status` command (aliased as `/status`) to show
  the same health information as the `/api/health` HTTP endpoint, but
  formatted for terminal/chat output.

  ## Commands

  - `/synthetic_status` — Show system health status
  - `/status` — Alias for `/synthetic_status`

  ## Output

      System Status
      ─────────────
      Status:   healthy
      Children: 17
      Version:  0.1.0

  ## Hooks Registered

  - `:custom_command` — Handle `/synthetic_status` and `/status` slash commands
  - `:custom_command_help` — Advertise in `/help` menu

  ## Example

      /synthetic_status    # Show health status
      /status              # Same, shorter alias
  """

  @behaviour Mana.Plugin.Behaviour

  alias Mana.Health

  @command_name "synthetic_status"
  @aliases ["status"]

  # ── Plugin Behaviour ──────────────────────────────────────────────────────

  @impl true
  def name, do: "synthetic_status"

  @impl true
  def init(config) do
    {:ok, %{config: config}}
  end

  @impl true
  def hooks do
    [
      {:custom_command, &__MODULE__.handle_command/2},
      {:custom_command_help, &__MODULE__.command_help/0}
    ]
  end

  @impl true
  def terminate, do: :ok

  # ── Custom Command Help ───────────────────────────────────────────────────

  @doc """
  Returns help entries for the `/synthetic_status` command.
  """
  @spec command_help() :: [{String.t(), String.t()}]
  def command_help do
    [
      {"synthetic_status", "Show system health status (same data as /api/health)"},
      {"status", "Alias for /synthetic_status — show health status"}
    ]
  end

  # ── Command Handler ─────────────────────────────────────────────────────────

  @doc """
  Handles `/synthetic_status` and `/status` slash commands.

  Returns formatted health status string.
  """
  @spec handle_command(String.t(), String.t()) :: {:ok, String.t()} | nil
  def handle_command(_command, name) when name in [@command_name | @aliases] do
    {:ok, Health.format_status()}
  end

  def handle_command(_command, _name), do: nil

  @doc """
  Formats a health info map into a terminal-friendly string.

  Used internally and exposed for testing.
  """
  @spec format_status(%{status: String.t(), children: non_neg_integer(), version: String.t()}) :: String.t()
  def format_status(%{status: status, children: children, version: version}) do
    "System Status\n" <>
      "─────────────\n" <>
      "Status:   #{status}\n" <>
      "Children: #{children}\n" <>
      "Version:  #{version}"
  end
end
