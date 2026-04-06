defmodule Mana.Plugin.Hook do
  @moduledoc """
  Defines the standard hooks for the Mana plugin system.

  These hooks mirror the callback system from Code Puppy, providing
  extension points for plugins to integrate with the agent lifecycle,
  tool calls, file operations, and more.

  ## Hook Types

  - `:startup` - Application startup
  - `:shutdown` - Graceful application shutdown
  - `:invoke_agent` - When an agent is invoked
  - `:agent_exception` - When an agent encounters an error
  - `:agent_run_start` - When an agent run begins
  - `:agent_run_end` - When an agent run completes
  - `:pre_tool_call` - Before a tool is executed
  - `:post_tool_call` - After a tool completes
  - `:stream_event` - Real-time streaming events
  - `:register_tools` - Custom tool registration
  - `:register_agents` - Custom agent registration
  - `:load_prompt` - System prompt loading
  - `:file_permission` - File operation permission checks
  - `:run_shell_command` - Shell command execution
  - `:custom_command` - Unknown slash command handling
  - `:get_motd` - Message of the day retrieval
  - `:load_model_config` - Model configuration loading
  - `:load_models_config` - Models configuration loading
  - `:register_model_type` - Custom model type registration
  - `:get_model_system_prompt` - Model-specific system prompts
  - `:register_mcp_catalog_servers` - MCP server registration
  - `:register_browser_types` - Custom browser type registration
  - `:register_model_providers` - Model provider registration
  - `:message_history_processor_start` - Message history processing start
  - `:message_history_processor_end` - Message history processing end
  """

  @typedoc "All available hook phases"
  @type hook_phase ::
          :startup
          | :shutdown
          | :invoke_agent
          | :agent_exception
          | :agent_run_start
          | :agent_run_end
          | :pre_tool_call
          | :post_tool_call
          | :stream_event
          | :register_tools
          | :register_agents
          | :load_prompt
          | :edit_file
          | :create_file
          | :replace_in_file
          | :delete_snippet
          | :delete_file
          | :file_permission
          | :run_shell_command
          | :custom_command
          | :custom_command_help
          | :get_motd
          | :load_model_config
          | :load_models_config
          | :register_model_type
          | :get_model_system_prompt
          | :register_mcp_catalog_servers
          | :register_browser_types
          | :register_model_providers
          | :message_history_processor_start
          | :message_history_processor_end
          | :version_check
          | :agent_reload

  @hooks %{
    startup: %{arity: 0, async: true},
    shutdown: %{arity: 0, async: true},
    invoke_agent: %{arity: 2, async: true},
    agent_exception: %{arity: 3, async: true},
    agent_run_start: %{arity: 3, async: true},
    agent_run_end: %{arity: 7, async: true},
    pre_tool_call: %{arity: 3, async: true},
    post_tool_call: %{arity: 5, async: true},
    stream_event: %{arity: 3, async: true},
    register_tools: %{arity: 0, async: false},
    register_agents: %{arity: 0, async: false},
    load_prompt: %{arity: 0, async: false},
    edit_file: %{arity: 3, async: false},
    create_file: %{arity: 2, async: false},
    replace_in_file: %{arity: 3, async: false},
    delete_snippet: %{arity: 2, async: false},
    delete_file: %{arity: 1, async: false},
    file_permission: %{arity: 6, async: false},
    run_shell_command: %{arity: 3, async: true},
    custom_command: %{arity: 2, async: false},
    custom_command_help: %{arity: 0, async: false},
    get_motd: %{arity: 0, async: false},
    load_model_config: %{arity: 2, async: false},
    load_models_config: %{arity: 0, async: false},
    register_model_type: %{arity: 0, async: false},
    get_model_system_prompt: %{arity: 3, async: false},
    register_mcp_catalog_servers: %{arity: 0, async: false},
    register_browser_types: %{arity: 0, async: false},
    register_model_providers: %{arity: 0, async: false},
    message_history_processor_start: %{arity: 4, async: false},
    message_history_processor_end: %{arity: 5, async: false},
    version_check: %{arity: 0, async: false},
    agent_reload: %{arity: 1, async: true}
  }

  @doc """
  Returns the hook metadata map.
  """
  @spec hooks_metadata() :: %{atom() => %{arity: non_neg_integer(), async: boolean()}}
  def hooks_metadata do
    @hooks
  end

  @doc """
  Returns all valid hook phases.
  """
  @spec all_hooks() :: [hook_phase()]
  def all_hooks do
    [
      :startup,
      :shutdown,
      :invoke_agent,
      :agent_exception,
      :agent_run_start,
      :agent_run_end,
      :pre_tool_call,
      :post_tool_call,
      :stream_event,
      :register_tools,
      :register_agents,
      :load_prompt,
      :edit_file,
      :create_file,
      :replace_in_file,
      :delete_snippet,
      :delete_file,
      :file_permission,
      :run_shell_command,
      :custom_command,
      :custom_command_help,
      :get_motd,
      :load_model_config,
      :load_models_config,
      :register_model_type,
      :get_model_system_prompt,
      :register_mcp_catalog_servers,
      :register_browser_types,
      :register_model_providers,
      :message_history_processor_start,
      :message_history_processor_end,
      :version_check,
      :agent_reload
    ]
  end

  @doc """
  Validates if a given atom is a valid hook phase.
  """
  @spec valid?(atom()) :: boolean()
  def valid?(phase) when is_atom(phase) do
    phase in all_hooks()
  end

  def valid?(_), do: false

  @doc """
  Returns true if the hook phase supports async callbacks.
  """
  @spec async?(hook_phase()) :: boolean()
  def async?(:startup), do: true
  def async?(:shutdown), do: true
  def async?(:invoke_agent), do: true
  def async?(:agent_exception), do: true
  def async?(:agent_run_start), do: true
  def async?(:agent_run_end), do: true
  def async?(:pre_tool_call), do: true
  def async?(:post_tool_call), do: true
  def async?(:stream_event), do: true
  def async?(:run_shell_command), do: true
  def async?(_), do: false

  @doc """
  Returns the expected callback signature for a hook phase.
  Used for documentation and validation purposes.
  """
  @spec callback_signature(hook_phase()) :: String.t()
  def callback_signature(:startup), do: "() -> :ok | {:ok, state} | {:error, reason}"
  def callback_signature(:shutdown), do: "() -> :ok"
  def callback_signature(:invoke_agent), do: "(args, kwargs) -> :ok | {:ok, result}"
  def callback_signature(:agent_exception), do: "(exception, args, kwargs) -> :ok"
  def callback_signature(:agent_run_start), do: "(agent_name, model_name, session_id) -> :ok"

  def callback_signature(:agent_run_end),
    do: "(agent_name, model_name, session_id, success, error, response_text, metadata) -> :ok"

  def callback_signature(:pre_tool_call), do: "(tool_name, tool_args, context) -> {:ok, modified_args} | :ok"
  def callback_signature(:post_tool_call), do: "(tool_name, tool_args, result, duration_ms, context) -> :ok"
  def callback_signature(:stream_event), do: "(event_type, event_data, session_id) -> :ok"
  def callback_signature(:register_tools), do: "() -> [{name, register_func}]"
  def callback_signature(:register_agents), do: "() -> [{name, agent_class}]"
  def callback_signature(:load_prompt), do: "() -> prompt_string | nil"

  def callback_signature(:file_permission),
    do: "(context, file_path, operation, preview, message_group, operation_data) -> true | false"

  def callback_signature(:run_shell_command), do: "(command, cwd, timeout) -> {:ok, result} | {:error, reason} | nil"
  def callback_signature(:custom_command), do: "(command, name) -> true | {:input, string} | nil"
  def callback_signature(:custom_command_help), do: "() -> [{name, description}]"
  def callback_signature(:get_motd), do: "() -> {message, version} | nil"
  def callback_signature(:load_model_config), do: "(args, kwargs) -> config | nil"
  def callback_signature(:load_models_config), do: "() -> %{model_name => config} | nil"
  def callback_signature(:register_model_type), do: "() -> [{type, handler}]"

  def callback_signature(:get_model_system_prompt),
    do: "(model_name, default_prompt, user_prompt) -> %{instructions: _, user_prompt: _, handled: _} | nil"

  def callback_signature(:register_mcp_catalog_servers), do: "() -> [server_template]"
  def callback_signature(:register_browser_types), do: "() -> %{type => init_func}"
  def callback_signature(:register_model_providers), do: "() -> %{provider_name => model_class}"

  def callback_signature(:message_history_processor_start),
    do: "(agent_name, session_id, message_history, incoming_messages) -> :ok"

  def callback_signature(:message_history_processor_end),
    do: "(agent_name, session_id, message_history, messages_added, messages_filtered) -> :ok"

  def callback_signature(:version_check), do: "(args, kwargs) -> :ok"
  def callback_signature(:agent_reload), do: "(args, kwargs) -> :ok"
  def callback_signature(:edit_file), do: "(args, kwargs) -> :ok"
  def callback_signature(:create_file), do: "(args, kwargs) -> :ok"
  def callback_signature(:replace_in_file), do: "(args, kwargs) -> :ok"
  def callback_signature(:delete_snippet), do: "(args, kwargs) -> :ok"
  def callback_signature(:delete_file), do: "(args, kwargs) -> :ok"
  def callback_signature(_), do: "() -> any()"
end
