defmodule Mana.PolicyEngine do
  @moduledoc """
  JSON-based policy evaluation for tool calls.

  Provides a rule-based system for evaluating whether tool calls should be
  allowed, denied, or require user approval. Rules are loaded from JSON policy
  files at both global (~/.mana/policy.json) and local (.mana/policy.json) levels.

  ## Policy File Format

      {
        "rules": [
          {
            "pattern": "rm.*-rf",
            "tool": "run_shell_command",
            "action": "deny",
            "reason": "Deleting files recursively is dangerous"
          }
        ],
        "default_action": "ask_user"
      }

  ## Actions

  - `:allow` - Permit the operation
  - `:deny` - Block the operation
  - `:ask_user` - Request user confirmation

  ## Usage

      policy = Mana.PolicyEngine.load()
      {action, reason} = Mana.PolicyEngine.evaluate(policy, "run_shell_command", %{"command" => "ls -la"})
  """

  alias Mana.Config.Paths

  @policy_file "policy.json"
  @local_policy_dir ".mana"

  defstruct rules: [], default_action: :ask_user

  @typedoc "Policy action types"
  @type action :: :allow | :deny | :ask_user

  @typedoc "A single policy rule"
  @type rule :: %{
          pattern: String.t(),
          tool: String.t() | :any,
          action: action(),
          reason: String.t()
        }

  @typedoc "The policy struct"
  @type t :: %__MODULE__{
          rules: [rule()],
          default_action: action()
        }

  @doc """
  Load policy from both global and local policy files.

  Loads the global policy from `~/.mana/policy.json` and merges it with
  any local policy found at `.mana/policy.json` in the current directory.
  Local rules take precedence over global rules.

  ## Returns

  - `%PolicyEngine{}` - Loaded policy with merged rules

  ## Examples

      iex> policy = Mana.PolicyEngine.load()
      iex> policy.default_action
      :ask_user
  """
  @spec load() :: t()
  def load do
    global = load_policy_file(Path.join(Paths.config_dir(), @policy_file))
    local = load_policy_file(Path.join(@local_policy_dir, @policy_file))

    %__MODULE__{
      rules: global.rules ++ local.rules,
      default_action: local.default_action || global.default_action || :ask_user
    }
  end

  @doc """
  Evaluate a tool call against the loaded policy.

  Checks the tool name and arguments against all policy rules. Returns
  the action and reason from the first matching rule, or the default
  action if no rules match.

  ## Parameters

  - `policy` - The policy struct returned from `load/0`
  - `tool_name` - The name of the tool being called
  - `args` - A map of arguments passed to the tool

  ## Returns

  - `{action, reason}` - Tuple of action atom and reason string

  ## Examples

      iex> policy = %Mana.PolicyEngine{rules: [], default_action: :ask_user}
      iex> Mana.PolicyEngine.evaluate(policy, "run_shell_command", %{"command" => "ls"})
      {:ask_user, "No matching policy rule"}
  """
  @spec evaluate(t(), String.t(), map()) :: {action(), String.t()}
  def evaluate(policy, tool_name, args) do
    args_str = Jason.encode!(args)

    case find_matching_rule(policy, tool_name, args_str) do
      nil -> {policy.default_action, "No matching policy rule"}
      rule -> {rule.action, rule.reason}
    end
  end

  @doc """
  Reload the policy with updated rules.

  Useful for refreshing the policy after file changes without
  restarting the application.

  ## Returns

  - `%PolicyEngine{}` - Freshly loaded policy
  """
  @spec reload(t()) :: t()
  def reload(_policy) do
    load()
  end

  # Private functions

  defp load_policy_file(path) do
    case File.read(path) do
      {:ok, data} ->
        case Jason.decode(data) do
          {:ok, decoded} ->
            rules = Map.get(decoded, "rules", [])
            default = Map.get(decoded, "default_action", "ask_user")

            %__MODULE__{
              rules: Enum.map(rules, &parse_rule/1),
              default_action: parse_action(default)
            }

          {:error, _} ->
            %__MODULE__{}
        end

      {:error, _} ->
        %__MODULE__{}
    end
  end

  defp parse_rule(rule_map) when is_map(rule_map) do
    pattern = Map.get(rule_map, "pattern", "")
    tool = Map.get(rule_map, "tool", :any)
    action = Map.get(rule_map, "action", "ask_user")
    reason = Map.get(rule_map, "reason", "")

    %{
      pattern: pattern,
      tool: parse_tool(tool),
      action: parse_action(action),
      reason: reason
    }
  end

  defp parse_tool("*"), do: :any
  defp parse_tool("any"), do: :any
  defp parse_tool(tool) when is_binary(tool), do: tool
  defp parse_tool(_), do: :any

  defp parse_action("allow"), do: :allow
  defp parse_action("deny"), do: :deny
  defp parse_action("ask_user"), do: :ask_user
  defp parse_action(action) when is_atom(action), do: action
  defp parse_action(_), do: :ask_user

  defp find_matching_rule(policy, tool_name, args_str) do
    Enum.find(policy.rules, fn rule ->
      tool_matches?(rule.tool, tool_name) && pattern_matches?(rule.pattern, args_str)
    end)
  end

  defp tool_matches?(:any, _tool_name), do: true
  defp tool_matches?(rule_tool, tool_name) when is_binary(rule_tool), do: rule_tool == tool_name
  defp tool_matches?(_, _), do: false

  defp pattern_matches?(pattern, args_str) when is_binary(pattern) do
    case Regex.compile(pattern) do
      {:ok, regex} -> Regex.match?(regex, args_str)
      {:error, _} -> false
    end
  end

  defp pattern_matches?(_, _), do: false
end
