defmodule Mana.Commands.Config do
  @moduledoc """
  Configuration viewing and editing commands.

  Provides commands for viewing and modifying Mana configuration settings.
  Supports both viewing all config and editing specific key-value pairs.

  ## Commands

  - `/config` - Show all configuration values
  - `/config get <key>` - Get a specific config value
  - `/config set <key> <value>` - Set a config value
  - `/config delete <key>` - Remove a config key
  - `/config keys` - List all available config keys

  ## Examples

      /config
      # Shows all current configuration

      /config get current_model
      # Shows: current_model = claude-opus-4-6

      /config set current_model gpt-4
      # Sets: current_model = gpt-4

      /config delete my_setting
      # Removes my_setting from config
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Config.Store, as: ConfigStore

  # Known configuration keys for documentation
  @known_keys [
    :current_model,
    :default_agent,
    :theme,
    :color_scheme,
    :banner_color_thinking,
    :banner_color_shell,
    :banner_color_file,
    :banner_color_agent,
    :banner_color_success,
    :banner_color_error,
    :banner_color_warning,
    :diff_addition_color,
    :diff_deletion_color,
    :max_parallel_agents,
    :auto_confirm_tools,
    :stream_responses,
    :show_token_count,
    :save_history
  ]

  @impl true
  def name, do: "/config"

  @impl true
  def description, do: "View and edit Mana configuration"

  @impl true
  def usage, do: "/config [get <key>|set <key> <value>|delete <key>|keys]"

  @impl true
  def execute([], _context) do
    show_all_config()
  end

  def execute(["get", key], _context) do
    get_config_value(key)
  end

  def execute(["set", key | value_parts], _context) when length(value_parts) > 0 do
    value = Enum.join(value_parts, " ")
    set_config_value(key, value)
  end

  def execute(["set", _key], _context) do
    {:error, "Usage: /config set <key> <value>"}
  end

  def execute(["delete", key], _context) do
    delete_config_value(key)
  end

  def execute(["keys"], _context) do
    list_config_keys()
  end

  def execute([unknown | _], _context) do
    {:error, "Unknown subcommand: #{unknown}. #{usage()}"}
  end

  # Implementation

  defp show_all_config do
    # Read directly from ETS to avoid GenServer call in tests
    config = get_all_config_from_ets()

    if map_size(config) == 0 do
      {:ok, "No configuration set.\n\nUse '/config set <key> <value>' to add settings."}
    else
      lines =
        Enum.sort(config)
        |> Enum.map(fn {key, value} ->
          formatted_value = format_config_value(value)
          "  #{key} = #{formatted_value}"
        end)

      header = "Current configuration:\n"
      footer = "\nUse '/config keys' to see available config keys."

      {:ok, header <> Enum.join(lines, "\n") <> footer}
    end
  end

  defp get_config_value(key) do
    key_atom = safe_to_atom(key)

    if is_nil(key_atom) do
      {:ok, "Unknown key: #{key}\n\nUse '/config keys' to see available config keys."}
    else
      case ConfigStore.get(key_atom, :not_set) do
        :not_set ->
          {:ok, "#{key} is not set"}

        value ->
          formatted_value = format_config_value(value)
          {:ok, "#{key} = #{formatted_value}"}
      end
    end
  end

  defp set_config_value(key, value) do
    key_atom =
      case safe_to_atom(key) do
        nil ->
          # Allow new keys as long as they're valid atom strings
          String.to_atom(key)

        existing_atom ->
          existing_atom
      end

    # Parse the value (try to detect booleans and numbers)
    parsed_value = parse_value(value)

    :ok = ConfigStore.put(key_atom, parsed_value)
    formatted = format_config_value(parsed_value)

    {:ok, "Set #{key} = #{formatted}"}
  rescue
    ArgumentError ->
      {:error, "Invalid key name: #{key}"}
  end

  defp delete_config_value(key) do
    key_atom = safe_to_atom(key)

    if is_nil(key_atom) do
      {:ok, "Key not found: #{key}"}
    else
      # Use put with nil as a deletion marker
      # In real implementation, this would be a delete operation
      :ok = ConfigStore.put(key_atom, nil)
      {:ok, "Deleted: #{key}"}
    end
  end

  defp list_config_keys do
    lines =
      Enum.map(@known_keys, fn key ->
        desc = key_description(key)
        "  • #{key} - #{desc}"
      end)

    header = "Available configuration keys:\n\n"

    footer = """

    Custom keys can also be created with '/config set <key> <value>'.
    Values are automatically parsed (booleans, numbers, strings).
    """

    {:ok, header <> Enum.join(lines, "\n") <> footer}
  end

  # Value parsing and formatting helpers

  defp parse_value("true"), do: true
  defp parse_value("True"), do: true
  defp parse_value("TRUE"), do: true
  defp parse_value("false"), do: false
  defp parse_value("False"), do: false
  defp parse_value("FALSE"), do: false

  defp parse_value(value) do
    # Try integer
    case Integer.parse(value) do
      {int, ""} ->
        int

      _ ->
        # Try float
        case Float.parse(value) do
          {float, ""} -> float
          _ -> value
        end
    end
  end

  defp format_config_value(nil), do: "(not set)"
  defp format_config_value(true), do: "true"
  defp format_config_value(false), do: "false"
  defp format_config_value(value) when is_binary(value), do: "\"#{value}\""
  defp format_config_value(value) when is_number(value), do: to_string(value)
  defp format_config_value(value), do: inspect(value)

  defp safe_to_atom(key) when is_binary(key) do
    try do
      String.to_existing_atom(key)
    rescue
      ArgumentError -> nil
    end
  end

  defp safe_to_atom(key) when is_atom(key), do: key
  defp safe_to_atom(_), do: nil

  # Get all config from ETS directly
  defp get_all_config_from_ets do
    case :ets.whereis(:mana_config) do
      :undefined ->
        %{}

      table ->
        :ets.tab2list(table)
        |> Enum.reject(fn {_, v} -> is_nil(v) end)
        |> Map.new()
    end
  end

  # Key descriptions for documentation

  defp key_description(:current_model), do: "Active AI model (e.g., claude-opus-4-6, gpt-4)"
  defp key_description(:default_agent), do: "Default agent to use for new sessions"
  defp key_description(:theme), do: "UI theme (light, dark, auto)"
  defp key_description(:color_scheme), do: "Color scheme name (default, high-contrast, solarized)"
  defp key_description(:banner_color_thinking), do: "Color for THINKING banner"
  defp key_description(:banner_color_shell), do: "Color for SHELL COMMAND banner"
  defp key_description(:banner_color_file), do: "Color for FILE OPERATION banner"
  defp key_description(:banner_color_agent), do: "Color for AGENT banner"
  defp key_description(:banner_color_success), do: "Color for SUCCESS banner"
  defp key_description(:banner_color_error), do: "Color for ERROR banner"
  defp key_description(:banner_color_warning), do: "Color for WARNING banner"
  defp key_description(:diff_addition_color), do: "Color for diff additions (green, #00ff00)"
  defp key_description(:diff_deletion_color), do: "Color for diff deletions (red, #ff0000)"
  defp key_description(:max_parallel_agents), do: "Maximum number of parallel agents (1-8)"
  defp key_description(:auto_confirm_tools), do: "Auto-confirm tool calls (true/false)"
  defp key_description(:stream_responses), do: "Stream responses (true/false)"
  defp key_description(:show_token_count), do: "Show token usage count (true/false)"
  defp key_description(:save_history), do: "Save conversation history (true/false)"
  defp key_description(_), do: "Custom configuration key"
end
