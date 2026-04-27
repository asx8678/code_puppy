defmodule CodePuppyControl.Tools.CommandRunner.Security do
  @moduledoc """
  Security boundary integration for shell command execution.

  Provides defense-in-depth security by combining:
  1. **PolicyEngine** - Rule-based permission decisions (allow/deny/ask_user)
  2. **Callback hook** - `run_shell_command` callback for plugin-level filtering
  3. **Validator** - Low-level command validation (length, forbidden chars, patterns)

  This mirrors the Python `SecurityBoundary.check_shell_command()` pattern
  where security decisions flow from PolicyEngine → callbacks → validator.

  ## Fail-closed semantics

  If the PolicyEngine is unavailable or callbacks raise, the command is
  **denied** by default (fail-closed). This prevents accidental execution
  of unsafe commands when security infrastructure is degraded.

  ## Environment variables

  - `PUP_SKIP_SHELL_SAFETY` - Set to "1" to bypass policy/callback checks
    (validator still runs). Only for development/testing.
  - `PUP_YOLO_MODE` - Set to "1" to skip user confirmation prompts
    (policy checks still run).

  Refs: code_puppy-mmk.6 (Phase E port)
  """

  require Logger

  alias CodePuppyControl.PolicyEngine
  alias CodePuppyControl.PolicyEngine.PolicyRule.{Allow, Deny, AskUser}
  alias CodePuppyControl.Callbacks
  alias CodePuppyControl.Tools.CommandRunner.Validator

  # ---------------------------------------------------------------------------
  # Types
  # ---------------------------------------------------------------------------

  @typedoc """
  Security decision for a shell command.

  - `:allowed` - Command is permitted
  - `{:denied, reason}` - Command is blocked
  - `{:ask_user, prompt}` - Decision deferred to user
  """
  @type decision ::
          :allowed
          | {:denied, String.t()}
          | {:ask_user, String.t()}

  @typedoc """
  Full security check result.
  """
  @type check_result :: %{
          allowed: boolean(),
          reason: String.t() | nil,
          decision: decision()
        }

  # ---------------------------------------------------------------------------
  # Public API
  # ---------------------------------------------------------------------------

  @doc """
  Performs the full security check pipeline for a shell command.

  Pipeline order:
  1. Check `PUP_SKIP_SHELL_SAFETY` env var (dev bypass)
  2. Run PolicyEngine `check_shell_command/2`
  3. Trigger `run_shell_command` callback hook
  4. Run Validator validation (always runs, even in skip mode)

  ## Parameters

  - `command` - Shell command string
  - `opts` - Options:
    - `:cwd` - Working directory (for policy context)
    - `:timeout` - Timeout value (for policy context)
    - `:context` - Additional context map for callbacks

  ## Returns

  `%{allowed: bool, reason: string | nil, decision: decision}`
  """
  @spec check(String.t(), keyword()) :: check_result()
  def check(command, opts \\ []) when is_binary(command) do
    cwd = Keyword.get(opts, :cwd)
    context = Keyword.get(opts, :context, %{})

    # Step 1: Always run validator (even in skip mode)
    case Validator.validate(command) do
      {:error, reason} ->
        denied("Command validation failed: #{reason}")

      {:ok, _validated} ->
        # Step 2: Check skip-safety env var (dev/testing only)
        if skip_shell_safety?() do
          Logger.debug("Security: PUP_SKIP_SHELL_SAFETY=1, skipping policy/callbacks")
          allowed()
        else
          # Step 3: PolicyEngine check
          case policy_check(command, cwd) do
            {:denied, reason} ->
              denied(reason)

            {:ask_user, prompt} ->
              # Step 4: Callback hook (plugins can override ask_user → deny)
              case callback_check(command, cwd, context) do
                {:denied, reason} -> denied(reason)
                _ -> %{allowed: false, reason: prompt, decision: {:ask_user, prompt}}
              end

            :allowed ->
              # Step 4: Callback hook for allowed commands
              case callback_check(command, cwd, context) do
                {:denied, reason} -> denied(reason)
                :allowed -> allowed()
              end
          end
        end
    end
  end

  @doc """
  Checks if yolo mode is enabled (skip user confirmation).

  Controlled by `PUP_YOLO_MODE` environment variable.
  """
  @spec yolo_mode?() :: boolean()
  def yolo_mode? do
    System.get_env("PUP_YOLO_MODE") == "1"
  end

  @doc """
  Checks if shell safety checks should be skipped.

  Controlled by `PUP_SKIP_SHELL_SAFETY` environment variable.
  """
  @spec skip_shell_safety?() :: boolean()
  def skip_shell_safety? do
    System.get_env("PUP_SKIP_SHELL_SAFETY") == "1"
  end

  # ---------------------------------------------------------------------------
  # PolicyEngine Integration
  # ---------------------------------------------------------------------------

  @spec policy_check(String.t(), String.t() | nil) :: decision()
  defp policy_check(command, cwd) do
    try do
      case PolicyEngine.check_shell_command(command, cwd) do
        %Allow{} -> :allowed
        %Deny{reason: reason} -> {:denied, reason || "Denied by policy"}
        %AskUser{prompt: prompt} -> {:ask_user, prompt || "Confirm command execution"}
      end
    rescue
      e ->
        Logger.error("Security: PolicyEngine check failed: #{Exception.message(e)}")
        # Fail-closed: deny on error
        {:denied, "Security check failed (fail-closed)"}
    catch
      :exit, reason ->
        Logger.error("Security: PolicyEngine unavailable: #{inspect(reason)}")
        {:denied, "Security check unavailable (fail-closed)"}
    end
  end

  # ---------------------------------------------------------------------------
  # Callback Hook Integration
  # ---------------------------------------------------------------------------

  @spec callback_check(String.t(), String.t() | nil, map()) :: decision()
  defp callback_check(command, cwd, context) do
    try do
      # Trigger the run_shell_command callback hook (arity 3) using
      # trigger_raw to get the unmerged results list. This is critical
      # for fail-closed semantics: the :noop merge used by trigger/2
      # can silently discard :callback_failed sentinels when mixed
      # with nil or %{blocked: false} results (code_puppy-mmk.6).
      #
      # Hook signature: (context, command, cwd) -> %{blocked: true} | nil
      results = Callbacks.trigger_raw(:run_shell_command, [context, command, cwd])

      # Fail-closed: any callback returning :callback_failed or
      # {:callback_failed, _} is treated as a denial — we cannot
      # determine the callback's intent, so we deny to be safe.
      blocked =
        Enum.any?(results, fn
          %{blocked: true} -> true
          :callback_failed -> true
          {:callback_failed, _} -> true
          _ -> false
        end)

      if blocked do
        {:denied, "Command blocked by security plugin"}
      else
        :allowed
      end
    rescue
      e ->
        Logger.warning("Security: callback check raised: #{Exception.message(e)}")
        # Fail-closed: callback errors deny execution
        {:denied, "Security callback failed (fail-closed)"}
    catch
      :exit, reason ->
        Logger.warning("Security: callback check crashed: #{inspect(reason)}")
        # Fail-closed: callback crashes deny execution
        {:denied, "Security callback crashed (fail-closed)"}
    end
  end

  # ---------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------

  defp allowed, do: %{allowed: true, reason: nil, decision: :allowed}
  defp denied(reason), do: %{allowed: false, reason: reason, decision: {:denied, reason}}
end
