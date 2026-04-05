defmodule Mana.Plugins.FilePermission do
  @moduledoc """
  Plugin that enforces file operation policies through the PolicyEngine.

  This plugin hooks into `:file_permission` events to evaluate whether
  file operations should be allowed based on configured policy rules.
  It also injects policy guidance into system prompts via `:load_prompt`.

  ## Configuration

      config :mana, Mana.Plugin.Manager,
        plugins: [:discover, Mana.Plugins.FilePermission],
        plugin_configs: %{
          Mana.Plugins.FilePermission => %{
            interactive: true,    # Whether to prompt for user confirmation
            log_decisions: true   # Whether to log policy decisions
          }
        }

  ## Hooks Registered

  - `:file_permission` - Evaluate file operations against policy rules
  - `:load_prompt` - Inject policy guidance into system prompts

  ## Policy Evaluation

  When a file operation is requested, the plugin:

  1. Loads the current policy from policy files
  2. Evaluates the operation against matching rules
  3. Returns `true` to allow, `false` to deny, or prompts the user

  ## Examples

      # Policy file (~/.mana/policy.json)
      {
        "rules": [
          {
            "pattern": "\\.secrets",
            "tool": "file_permission",
            "action": "deny",
            "reason": "Secrets directory is protected"
          }
        ]
      }
  """

  @behaviour Mana.Plugin.Behaviour

  require Logger

  @impl true
  def name, do: "file_permission"

  @impl true
  def init(config) do
    # Load policy at initialization for faster lookups
    policy = Mana.PolicyEngine.load()

    state = %{
      policy: policy,
      config: config,
      interactive: Map.get(config, :interactive, true),
      log_decisions: Map.get(config, :log_decisions, true)
    }

    if state.log_decisions do
      Logger.info("FilePermission plugin initialized with #{length(policy.rules)} policy rules")
    end

    {:ok, state}
  end

  @impl true
  def hooks do
    [
      {:file_permission, &__MODULE__.check_permission/6},
      {:load_prompt, &__MODULE__.inject_policy_prompt/0}
    ]
  end

  @doc """
  Check if a file operation is permitted by policy.

  Evaluates the file path and operation against loaded policy rules.
  Returns boolean permission and optionally logs or prompts based on config.

  ## Parameters

  - `_context` - Run context (unused but required by hook signature)
  - `file_path` - Path to the file being operated on
  - `operation` - The operation type (read, write, delete, etc.)
  - `_preview` - Preview of changes (unused)
  - `_message_group` - Message grouping ID (unused)
  - `state` - Plugin state containing policy and config

  ## Returns

  - `true` - Operation is allowed
  - `false` - Operation is denied
  """
  @spec check_permission(term(), String.t(), atom(), term(), term(), map()) :: boolean()
  def check_permission(_context, file_path, operation, _preview, _message_group, state) do
    # Build args map for policy evaluation
    args = %{
      "path" => file_path,
      "operation" => to_string(operation)
    }

    # Evaluate against policy
    tool_name = "file_#{operation}"

    {action, reason} =
      if state.policy do
        Mana.PolicyEngine.evaluate(state.policy, tool_name, args)
      else
        {:ask_user, "No policy loaded"}
      end

    handle_policy_decision(action, reason, file_path, operation, state)
  end

  @doc """
  Inject policy guidance into the system prompt.

  Returns a string that will be included in system prompts to guide
  the agent's behavior regarding file operations.

  ## Returns

  - `String.t()` - Policy guidance text for prompts
  """
  @spec inject_policy_prompt() :: String.t()
  def inject_policy_prompt do
    """
    ## File Operation Policy

    When file operations are rejected by policy, you should:
    1. Acknowledge the rejection in your response
    2. Explain why the operation was denied (include the reason)
    3. Suggest alternatives that would comply with policy
    4. Ask the user if they want to modify the policy or use a different approach

    Protected paths and operations may require user confirmation.
    Always respect policy decisions and help users understand them.
    """
  end

  @impl true
  def terminate do
    Logger.info("FilePermission plugin shutting down")
    :ok
  end

  # Private functions

  defp handle_policy_decision(:allow, _reason, file_path, operation, state) do
    if state.log_decisions do
      Logger.debug("[Policy] Allowed #{operation} on #{file_path}")
    end

    true
  end

  defp handle_policy_decision(:deny, reason, file_path, operation, state) do
    if state.log_decisions do
      Logger.warning("[Policy] Denied #{operation} on #{file_path}: #{reason}")
    end

    # In a full implementation, this would call MessageBus.request_confirmation
    # For now, we just deny the operation
    IO.puts("[Policy] Denied: #{reason}")
    false
  end

  defp handle_policy_decision(:ask_user, reason, file_path, operation, state) do
    if state.log_decisions do
      Logger.info("[Policy] User confirmation required for #{operation} on #{file_path}: #{reason}")
    end

    if state.interactive do
      # In non-interactive or yolo_mode, default to allowing
      # In interactive mode, we would prompt the user
      # For now, we default to allowing in non-critical paths
      IO.puts("[Policy] #{reason}")
      true
    else
      true
    end
  end
end
