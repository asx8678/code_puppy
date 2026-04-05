defmodule Mana.Plugins.ShellSafety do
  @moduledoc """
  Plugin that assesses shell command safety and risk levels.

  Analyzes shell commands for dangerous patterns and classifies them by risk
  level. Hooks into `:run_shell_command` events to provide safety assessments
  before command execution.

  ## Risk Levels

  - `:none` - Safe command, no special handling needed
  - `:low` - Low risk, minor warning issued
  - `:medium` - Moderate risk, may require approval (unless yolo_mode enabled)
  - `:high` - High risk, requires explicit approval
  - `:critical` - Dangerous patterns detected, blocked by default

  ## Configuration

      config :mana, Mana.Plugin.Manager,
        plugins: [:discover, Mana.Plugins.ShellSafety],
        plugin_configs: %{
          Mana.Plugins.ShellSafety => %{
            yolo_mode: false,        # Skip medium-risk confirmations
            allow_sudo: false,       # Whether to allow sudo commands
            log_assessments: true    # Log risk assessments
          }
        }

  ## Dangerous Patterns

  The plugin detects patterns such as:
  - `rm -rf /` or similar destructive deletions
  - `dd if=` disk operations
  - `mkfs` filesystem formatting
  - `> /dev/sd*` raw device writes
  - Fork bombs: `:(){ :|:& };:`
  - `curl | sh` and `wget | bash` pipe-to-shell
  - `sudo` escalation attempts
  - `chmod 777` overly permissive changes

  ## Hooks Registered

  - `:run_shell_command` - Assess command risk before execution
  """

  @behaviour Mana.Plugin.Behaviour

  require Logger

  # Dangerous command patterns that indicate critical risk
  @dangerous_patterns [
    # rm -rf / or similar destructive deletions
    ~r/rm\s+-rf\s+\//,
    # Disk operations with dd
    ~r/dd\s+if=/,
    # Filesystem formatting
    ~r/mkfs/,
    # Raw device writes
    ~r/>\s*\/dev\/sd[a-z]/,
    # Fork bomb pattern
    ~r/:\(\)\s*\{[^}]*:\|[^}]*\}/,
    # curl | sh pattern
    ~r/curl.*\|\s*sh/,
    # wget | bash pattern
    ~r/wget.*\|\s*bash/
  ]

  @type risk_level :: :none | :low | :medium | :high | :critical

  @type assessment :: %{
          safe: boolean(),
          risk: risk_level(),
          warning: String.t() | nil,
          reason: String.t() | nil
        }

  @impl true
  def name, do: "shell_safety"

  @impl true
  def init(config) do
    state = %{
      config: config,
      yolo_mode: Map.get(config, :yolo_mode, false),
      allow_sudo: Map.get(config, :allow_sudo, false),
      log_assessments: Map.get(config, :log_assessments, true)
    }

    if state.log_assessments do
      Logger.info("ShellSafety plugin initialized (yolo_mode: #{state.yolo_mode})")
    end

    {:ok, state}
  end

  @impl true
  def hooks do
    [
      {:run_shell_command, &__MODULE__.assess_command/3}
    ]
  end

  @doc """
  Assess the safety of a shell command.

  Analyzes the command string for dangerous patterns and returns
  a risk assessment. The assessment includes whether the command
  should be considered safe and any warnings or reasons.

  ## Parameters

  - `_context` - Run context (unused but required by hook signature)
  - `command` - The shell command string to assess
  - `state` - Plugin state containing configuration

  ## Returns

  - `{:ok, assessment}` - Assessment result map
  - `{:error, reason}` - Error during assessment

  ## Examples

      iex> state = %{config: %{}, yolo_mode: false}
      iex> Mana.Plugins.ShellSafety.assess_command(nil, "ls -la", state)
      {:ok, %{safe: true, risk: :none, warning: nil, reason: nil}}
  """
  @spec assess_command(term(), String.t(), map()) :: {:ok, assessment()} | {:error, String.t()}
  def assess_command(_context, command, state) when is_binary(command) do
    risk = classify_risk(command, state)

    result =
      case risk do
        :none ->
          %{safe: true, risk: :none, warning: nil, reason: nil}

        :low ->
          %{safe: true, risk: :low, warning: "Low risk command", reason: nil}

        :medium ->
          handle_medium_risk(state)

        :high ->
          %{safe: false, risk: :high, warning: nil, reason: "High risk command blocked"}

        :critical ->
          %{safe: false, risk: :critical, warning: nil, reason: "CRITICAL: Dangerous command blocked"}
      end

    if get_in(state, [:config, :log_assessments]) do
      Logger.debug("[ShellSafety] Assessed '#{String.slice(command, 0, 50)}' as #{risk}")
    end

    {:ok, result}
  end

  def assess_command(_context, _command, _state) do
    {:error, "Invalid command format"}
  end

  @doc """
  Classify the risk level of a shell command.

  Analyzes the command for known dangerous patterns and returns
  the appropriate risk level.

  ## Parameters

  - `command` - The shell command to analyze
  - `state` - Plugin state for configuration checks

  ## Returns

  - `risk_level` - One of `:none`, `:low`, `:medium`, `:high`, `:critical`
  """
  @spec classify_risk(String.t(), map()) :: risk_level()
  def classify_risk(command, state \\ %{}) do
    cond do
      # Check for critical patterns first
      matches_dangerous_pattern?(command) ->
        :critical

      # High risk: sudo (unless explicitly allowed)
      String.contains?(command, "sudo") && !allow_sudo?(state) ->
        :high

      # High risk: overly permissive chmod
      String.contains?(command, "chmod 777") ||
          String.contains?(command, "chmod -R 777") ->
        :high

      # Medium risk: command chaining
      String.contains?(command, "&&") ||
        String.contains?(command, "||") ||
          String.contains?(command, ";") ->
        :medium

      # Medium risk: redirects that might be destructive
      String.contains?(command, "> /etc/") ||
          String.contains?(command, "> ~/.") ->
        :medium

      # Low risk: other redirects
      String.contains?(command, ">") ||
          String.contains?(command, ">>") ->
        :low

      # No risk: safe command
      true ->
        :none
    end
  end

  @impl true
  def terminate do
    Logger.info("ShellSafety plugin shutting down")
    :ok
  end

  # Private functions

  defp matches_dangerous_pattern?(command) do
    Enum.any?(@dangerous_patterns, fn pattern ->
      Regex.match?(pattern, command)
    end)
  end

  defp allow_sudo?(state) do
    get_in(state, [:config, :allow_sudo]) || false
  end

  defp handle_medium_risk(state) do
    if get_in(state, [:config, :yolo_mode]) do
      %{
        safe: true,
        risk: :medium,
        warning: "Medium risk command (yolo_mode enabled)",
        reason: nil
      }
    else
      %{
        safe: false,
        risk: :medium,
        warning: nil,
        reason: "Medium risk command requires approval"
      }
    end
  end
end
