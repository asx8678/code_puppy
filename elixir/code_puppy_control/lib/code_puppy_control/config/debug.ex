defmodule CodePuppyControl.Config.Debug do
  @moduledoc """
  Feature toggles, debug flags, and environment configuration.

  Centralizes all boolean feature flags and debug-related settings from
  `puppy.cfg`. Each getter has a documented default that matches the
  Python `config.py` behaviour.

  ## Config keys in `puppy.cfg`

  - `yolo_mode` — auto-approve all actions (default `true`)
  - `allow_recursion` — allow recursive agent calls (default `true`)
  - `enable_dbos` — enable DBOS workflow engine (default `true`)
  - `enable_pack_agents` — enable pack agents (default `false`)
  - `enable_universal_constructor` — enable dynamic tool creation (default `true`)
  - `enable_streaming` — enable SSE streaming (default `true`)
  - `enable_gitignore_filtering` — filter gitignored files in list_files (default `false`)
  - `enable_agent_memory` — enable cross-session agent memory (default `false`)
  - `enable_elixir_message_shadow_mode` — shadow mode for Elixir message ops (default `false`)
  - `enable_user_plugins` — allow user plugins (default `true`)
  - `http2` — enable HTTP/2 for httpx clients (default `false`)
  - `subagent_verbose` — verbose output for sub-agents (default `false`)
  - `disable_mcp` — skip MCP server loading (default `false`)
  - `grep_output_verbose` — full grep output (default `false`)
  - `safety_permission_level` — risk threshold (default `\"medium\"`)
  - `cancel_agent_key` — keyboard shortcut for canceling agent (default `\"ctrl-c\"`)
  - `debug` — debug mode flag
  """

  alias CodePuppyControl.Config.Loader

  # ── Core toggles ────────────────────────────────────────────────────────

  @doc "Return `true` if yolo mode is on (default `true`)."
  @spec yolo_mode?() :: boolean()
  def yolo_mode?, do: truthy?("yolo_mode", true)

  @doc "Return `true` if recursion is allowed (default `true`)."
  @spec allow_recursion?() :: boolean()
  def allow_recursion?, do: truthy?("allow_recursion", true)

  @doc "Return `true` if DBOS is enabled (default `true`)."
  @spec dbos_enabled?() :: boolean()
  def dbos_enabled?, do: truthy?("enable_dbos", true)

  @doc "Return `true` if pack agents are enabled (default `false`)."
  @spec pack_agents_enabled?() :: boolean()
  def pack_agents_enabled?, do: truthy?("enable_pack_agents", false)

  @doc "Return `true` if the Universal Constructor is enabled (default `true`)."
  @spec universal_constructor_enabled?() :: boolean()
  def universal_constructor_enabled?, do: truthy?("enable_universal_constructor", true)

  @doc "Return `true` if streaming is enabled (default `true`)."
  @spec streaming_enabled?() :: boolean()
  def streaming_enabled?, do: truthy?("enable_streaming", true)

  @doc "Return `true` if gitignore filtering is enabled (default `false`)."
  @spec gitignore_filtering_enabled?() :: boolean()
  def gitignore_filtering_enabled?, do: truthy?("enable_gitignore_filtering", false)

  @doc "Return `true` if agent memory is enabled (default `false`)."
  @spec agent_memory_enabled?() :: boolean()
  def agent_memory_enabled?, do: truthy?("enable_agent_memory", false)

  @doc "Return `true` if Elixir message shadow mode is enabled (default `false`)."
  @spec elixir_message_shadow_mode?() :: boolean()
  def elixir_message_shadow_mode?, do: truthy?("enable_elixir_message_shadow_mode", false)

  @doc "Return `true` if user plugins are enabled (default `true`)."
  @spec user_plugins_enabled?() :: boolean()
  def user_plugins_enabled?, do: truthy?("enable_user_plugins", true)

  @doc "Return `true` if HTTP/2 is enabled (default `false`)."
  @spec http2_enabled?() :: boolean()
  def http2_enabled?, do: truthy?("http2", false)

  @doc "Return `true` if sub-agent verbose output is enabled (default `false`)."
  @spec subagent_verbose?() :: boolean()
  def subagent_verbose?, do: truthy?("subagent_verbose", false)

  @doc "Return `true` if MCP is disabled (default `false`)."
  @spec mcp_disabled?() :: boolean()
  def mcp_disabled?, do: truthy?("disable_mcp", false)

  @doc """
  Return the cancel agent key binding (default `\"ctrl-c\"`).

  Configurable via `cancel_agent_key` in `puppy.cfg`.
  Common values: `\"ctrl-c\"`, `\"ctrl-d\"`, `\"escape\"`.
  """
  @spec cancel_agent_key() :: String.t()
  def cancel_agent_key do
    Loader.get_value("cancel_agent_key") || "ctrl-c"
  end

  @doc """
  Set the cancel agent key binding.
  """
  @spec set_cancel_agent_key(String.t()) :: :ok
  def set_cancel_agent_key(key) when is_binary(key) do
    CodePuppyControl.Config.Writer.set_value("cancel_agent_key", key)
  end

  @doc """
  Return the list of allowed user plugins.

  If `allowed_user_plugins` is not set or empty, all plugins are allowed
  (when `enable_user_plugins` is true).
  """
  @spec allowed_user_plugins() :: [String.t()]
  def allowed_user_plugins do
    case Loader.get_value("allowed_user_plugins") do
      nil -> []
      "" -> []
      val -> String.split(val, ",", trim: true) |> Enum.map(&String.trim/1)
    end
  end

  @doc """
  Set the list of allowed user plugins.

  Pass a list of plugin names, or `nil` to allow all plugins.
  """
  @spec set_allowed_user_plugins([String.t()] | nil) :: :ok
  def set_allowed_user_plugins(nil),
    do: CodePuppyControl.Config.Writer.set_value("allowed_user_plugins", "")

  def set_allowed_user_plugins(list) when is_list(list) do
    value = Enum.join(list, ", ")
    CodePuppyControl.Config.Writer.set_value("allowed_user_plugins", value)
  end

  @doc """
  Adaptive rendering enabled.
  Env override: PUP_ADAPTIVE_RENDERING
  """
  def adaptive_rendering_enabled? do
    case System.get_env("PUP_ADAPTIVE_RENDERING") do
      nil -> truthy?("adaptive_rendering", true)
      val -> val not in ["0", "false", "no"]
    end
  end

  @doc """
  Post-edit validation enabled.
  Env override: PUP_POST_EDIT_VALIDATION
  """
  def post_edit_validation_enabled? do
    case System.get_env("PUP_POST_EDIT_VALIDATION") do
      nil -> truthy?("post_edit_validation", true)
      val -> val not in ["0", "false", "no"]
    end
  end

  # ── Setters ─────────────────────────────────────────────────────────────

  @doc "Enable or disable the Universal Constructor."
  @spec set_universal_constructor_enabled(boolean()) :: :ok
  def set_universal_constructor_enabled(enabled) do
    CodePuppyControl.Config.Writer.set_value("enable_universal_constructor", bool_str(enabled))
  end

  @doc "Enable or disable DBOS."
  @spec set_dbos_enabled(boolean()) :: :ok
  def set_dbos_enabled(enabled) do
    CodePuppyControl.Config.Writer.set_value("enable_dbos", bool_str(enabled))
  end

  @doc "Enable or disable HTTP/2."
  @spec set_http2_enabled(boolean()) :: :ok
  def set_http2_enabled(enabled) do
    CodePuppyControl.Config.Writer.set_value("http2", bool_str(enabled))
  end

  # ── Safety ──────────────────────────────────────────────────────────────

  @valid_safety_levels MapSet.new(["none", "low", "medium", "high", "critical"])

  @doc """
  Return the safety permission level (default `"medium"`).
  Valid values: `none`, `low`, `medium`, `high`, `critical`.
  """
  @spec safety_permission_level() :: String.t()
  def safety_permission_level do
    case Loader.get_value("safety_permission_level") do
      nil ->
        "medium"

      val ->
        normalized = String.downcase(String.trim(val))
        if normalized in @valid_safety_levels, do: normalized, else: "medium"
    end
  end

  # ── Debug mode ──────────────────────────────────────────────────────────

  @doc """
  Return `true` if debug mode is active.

  Checks `PUP_DEBUG` env var first, then `debug` key in `puppy.cfg`.
  """
  @spec debug?() :: boolean()
  def debug? do
    case System.get_env("PUP_DEBUG") do
      nil -> truthy?("debug", false)
      val -> val != "" and val != "0"
    end
  end

  # ── Token / puppy token ─────────────────────────────────────────────────

  @doc "Return the puppy_token from config, or `nil`."
  @spec puppy_token() :: String.t() | nil
  def puppy_token do
    Loader.get_value("puppy_token")
  end

  @doc "Set the puppy_token in config."
  @spec set_puppy_token(String.t()) :: :ok
  def set_puppy_token(token) when is_binary(token) do
    CodePuppyControl.Config.Writer.set_value("puppy_token", token)
  end

  # ── Memory config ───────────────────────────────────────────────────────

  @doc "Return memory write debounce in seconds (default `30`, range `1–300`)."
  @spec memory_debounce_seconds() :: pos_integer()
  def memory_debounce_seconds do
    case Loader.get_value("memory_debounce_seconds") do
      nil ->
        30

      val ->
        case Integer.parse(val) do
          {n, _} -> n |> max(1) |> min(300)
          :error -> 30
        end
    end
  end

  @doc "Return max facts per agent (default `50`, range `1–1000`)."
  @spec memory_max_facts() :: pos_integer()
  def memory_max_facts do
    case Loader.get_value("memory_max_facts") do
      nil ->
        50

      val ->
        case Integer.parse(val) do
          {n, _} -> n |> max(1) |> min(1000)
          :error -> 50
        end
    end
  end

  @doc "Return token budget for memory injection (default `500`, range `100–2000`)."
  @spec memory_token_budget() :: pos_integer()
  def memory_token_budget do
    case Loader.get_value("memory_token_budget") do
      nil ->
        500

      val ->
        case Integer.parse(val) do
          {n, _} -> n |> max(100) |> min(2000)
          :error -> 500
        end
    end
  end

  # ── API keys ────────────────────────────────────────────────────────────

  @api_key_names [
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CEREBRAS_API_KEY",
    "SYN_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "OPENROUTER_API_KEY",
    "ZAI_API_KEY",
    "WAFER_API_KEY"
  ]

  @doc """
  Load API keys from `puppy.cfg` into environment variables.

  Only sets env vars that are not already present, preserving `.env` and
  shell-level overrides.
  """
  @spec load_api_keys_to_environment() :: :ok
  def load_api_keys_to_environment do
    Enum.each(@api_key_names, fn key ->
      if is_nil(System.get_env(key)) or System.get_env(key) == "" do
        # Config keys are lowercase (e.g., "wafer_api_key")
        config_key = String.downcase(key)

        case Loader.get_value(config_key) do
          nil -> :ok
          "" -> :ok
          value -> System.put_env(key, value)
        end
      end
    end)

    :ok
  end

  # ── Private ─────────────────────────────────────────────────────────────

  @truthy_values MapSet.new(["1", "true", "yes", "on"])

  defp truthy?(key, default) do
    case Loader.get_value(key) do
      nil -> default
      val -> String.downcase(String.trim(val)) in @truthy_values
    end
  end

  defp bool_str(true), do: "true"
  defp bool_str(false), do: "false"
end
