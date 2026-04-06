defmodule Mana.Plugin.Manager do
  @moduledoc """
  GenServer that manages plugin discovery, initialization, and lifecycle.

  The Manager is responsible for:
  - Discovering plugins at startup from configured sources
  - Calling `init/1` on each plugin and tracking their state
  - Registering plugin hooks via the unified Mana.Callbacks system
  - Graceful shutdown coordination

  ## Lifecycle

  1. **Discovery** - At startup, scans configured directories for modules
     implementing `Mana.Plugin.Behaviour`
  2. **Initialization** - Calls `init/1` on each discovered plugin with
     its configuration
  3. **Registration** - Registers plugin hooks via Mana.Callbacks.register/2
  4. **Dispatch** - Hooks are dispatched through Mana.Callbacks (unified system)
  5. **Shutdown** - Calls optional `terminate/0` on plugins

  ## Configuration

  Configure in `config/runtime.exs` or `config/config.exs`:

      config :mana, Mana.Plugin.Manager,
        plugins: [
          # Auto-discovered from lib/mana/plugins/
          :discover,
          # Explicit plugin modules
          MyApp.Plugins.Logger,
          MyApp.Plugins.Analytics
        ]

  ## Usage

  Start the manager in your application supervisor:

      children = [
        Mana.Plugin.Manager
      ]

  Trigger hooks through the unified callbacks system:

      Mana.Callbacks.on_agent_run_start("my_agent", "gpt-4", "session_123")
      Mana.Callbacks.dispatch(:agent_run_start, ["my_agent", "gpt-4", "session_123"])

  ## Migration Note

  Previously, this module had its own `trigger/3` and `trigger_async/2` functions.
  These are now deprecated and delegate to `Mana.Callbacks.dispatch/2`.
  Please use `Mana.Callbacks` directly for all hook operations.
  """

  use GenServer

  require Logger

  alias Mana.Callbacks
  alias Mana.Plugin.Hook

  defstruct [
    :plugins,
    :config,
    :stats
  ]

  @typedoc "Plugin state record"
  @type plugin_state :: %{
          module: module(),
          name: String.t(),
          state: term(),
          hooks: [{Hook.hook_phase(), function()}]
        }

  @typedoc "Manager state"
  @type t :: %__MODULE__{
          plugins: %{String.t() => plugin_state()},
          config: keyword(),
          stats: %{
            plugins_loaded: non_neg_integer()
          }
        }

  # Default configuration
  @default_config [
    plugins: [:discover],
    auto_dismiss_errors: true
  ]

  # Client API

  @doc """
  Starts the Plugin Manager GenServer.

  ## Options

  - `:name` - The name to register the process under (default: `__MODULE__`)
  - `:config` - Override configuration options

  ## Examples

      Mana.Plugin.Manager.start_link([])
      Mana.Plugin.Manager.start_link(name: :custom_manager, config: [backlog_ttl: 60_000])
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    config = Keyword.get(opts, :config, [])
    GenServer.start_link(__MODULE__, config, name: name)
  end

  @doc """
  Returns a child specification for use in supervision trees.
  """
  @spec child_spec(keyword()) :: Supervisor.child_spec()
  def child_spec(opts \\ []) do
    %{
      id: __MODULE__,
      start: {__MODULE__, :start_link, [opts]},
      type: :worker,
      restart: :permanent,
      shutdown: 5000
    }
  end

  @doc """
  Triggers a hook synchronously, calling all registered callbacks.

  ## Deprecated

  This function is deprecated. Use `Mana.Callbacks.dispatch/2` instead.

  ## Parameters

  - `hook` - The hook phase atom (e.g., `:agent_run_start`)
  - `args` - List of arguments to pass to callbacks
  - `opts` - Options (unused, kept for backward compatibility)

  ## Returns

  - `{:ok, results}` - List of results from all callbacks
  - `{:error, reason}` - Failed to trigger hook

  ## Examples

      Mana.Plugin.Manager.trigger(:agent_run_start, ["agent", "model", nil])
      # Prefer: Mana.Callbacks.dispatch(:agent_run_start, ["agent", "model", nil])
  """
  @deprecated "Use Mana.Callbacks.dispatch/2 instead — plugin hooks are now managed through the unified Callbacks system"
  @spec trigger(Hook.hook_phase(), [term()], keyword()) :: {:ok, [term()]} | {:error, term()}
  def trigger(hook, args \\ [], _opts \\ []) do
    Callbacks.dispatch(hook, args)
  end

  @doc """
  Triggers a hook asynchronously.

  ## Deprecated

  This function is deprecated. Use `Mana.Callbacks.dispatch/2` with
  `Task.start/1` if you need async behavior, or use the async hooks
  which are already handled asynchronously by the Callbacks system.

  ## Parameters

  - `hook` - The hook phase atom
  - `args` - List of arguments to pass to callbacks

  ## Returns

  - `:ok` - Always returns immediately
  """
  @deprecated "Async hooks are handled by Mana.Callbacks. Use Task.start/1 with Mana.Callbacks.dispatch/2 if needed"
  @spec trigger_async(Hook.hook_phase(), [term()]) :: :ok
  def trigger_async(hook, args \\ []) do
    # Async hooks are already handled asynchronously by the Callbacks system
    # This just delegates to dispatch and discards the result
    _ = Callbacks.dispatch(hook, args)
    :ok
  end

  @doc """
  Triggers the `:startup` hook for all registered plugins.

  Called automatically by the Manager after initialization.
  Plugins can use this to perform post-load setup.

  ## Returns

  - `{:ok, results}` - Results from all startup hooks
  """
  @spec trigger_startup() :: {:ok, [term()]} | {:error, term()}
  def trigger_startup do
    Callbacks.dispatch(:startup, [])
  end

  @doc """
  Triggers the `:shutdown` hook for all registered plugins.

  Called automatically during graceful shutdown. Plugins should
  clean up resources and prepare for termination.

  ## Returns

  - `{:ok, results}` - Results from all shutdown hooks
  """
  @spec trigger_shutdown() :: {:ok, [term()]} | {:error, term()}
  def trigger_shutdown do
    Callbacks.dispatch(:shutdown, [])
  end

  @doc """
  Manually registers a plugin at runtime.

  ## Parameters

  - `module` - The plugin module implementing `Mana.Plugin.Behaviour`
  - `config` - Configuration map for the plugin (default: `%{}`)

  ## Returns

  - `{:ok, plugin_name}` - Plugin successfully registered
  - `{:error, reason}` - Failed to register plugin

  ## Examples

      Mana.Plugin.Manager.register_plugin(MyApp.Plugins.Logger)
      Mana.Plugin.Manager.register_plugin(MyApp.Plugins.Logger, %{level: :debug})
  """
  @spec register_plugin(module(), map()) :: {:ok, String.t()} | {:error, term()}
  def register_plugin(module, config \\ %{}) do
    GenServer.call(__MODULE__, {:register_plugin, module, config})
  end

  @doc """
  Unregisters a plugin at runtime.

  Calls the plugin's `terminate/0` callback if implemented.

  ## Parameters

  - `plugin_name` - The name of the plugin to unregister

  ## Returns

  - `:ok` - Plugin unregistered
  - `{:error, :not_found}` - Plugin not found
  """
  @spec unregister_plugin(String.t()) :: :ok | {:error, :not_found}
  def unregister_plugin(plugin_name) do
    GenServer.call(__MODULE__, {:unregister_plugin, plugin_name})
  end

  @doc """
  Drains the backlog for a specific hook, replaying buffered events.

  ## Deprecated

  Backlog management is now handled by Mana.Callbacks.Registry.
  Use `Mana.Callbacks.drain_backlog/1` instead.

  ## Parameters

  - `hook` - The hook phase to drain

  ## Returns

  - `{:ok, results}` - Results from replayed events
  """
  @deprecated "Use Mana.Callbacks.drain_backlog/1 instead"
  @spec drain_backlog(Hook.hook_phase()) :: {:ok, [term()]} | {:error, term()}
  def drain_backlog(hook) do
    Callbacks.drain_backlog(hook)
  end

  @doc """
  Drains the backlog for all hooks.

  ## Deprecated

  Backlog management is now handled by Mana.Callbacks.Registry.
  Call `Mana.Callbacks.drain_backlog/1` for each hook you need.

  ## Returns

  - `{:ok, %{hook => results}}` - Map of results per hook
  """
  @deprecated "Use individual Mana.Callbacks.drain_backlog/1 calls instead"
  @spec drain_all_backlogs() :: {:ok, %{Hook.hook_phase() => [term()]}} | {:error, term()}
  def drain_all_backlogs do
    all_hooks = Hook.all_hooks()

    results_map =
      Enum.reduce(all_hooks, %{}, fn hook, acc ->
        {:ok, results} = Callbacks.drain_backlog(hook)
        Map.put(acc, hook, results)
      end)

    {:ok, results_map}
  end

  @doc """
  Returns a list of all loaded plugins.
  """
  @spec list_plugins() :: [%{name: String.t(), module: module(), hook_count: non_neg_integer()}]
  def list_plugins do
    GenServer.call(__MODULE__, :list_plugins)
  end

  @doc """
  Returns statistics about the manager.

  ## Note

  Hook-related statistics now come from Mana.Callbacks.Registry.
  This function returns plugin management stats and delegates
  to Callbacks for hook statistics.
  """
  @spec get_stats() :: %{
          plugins_loaded: non_neg_integer(),
          hooks_registered: non_neg_integer(),
          backlog_size: non_neg_integer(),
          dispatches: non_neg_integer(),
          errors: non_neg_integer()
        }
  def get_stats do
    # Get plugin stats from this GenServer
    %{plugins_loaded: plugin_count} = GenServer.call(__MODULE__, :get_plugin_stats)

    # Get hook stats from Callbacks
    callback_stats = Callbacks.get_stats()

    %{
      plugins_loaded: plugin_count,
      hooks_registered: Map.get(callback_stats, :callbacks_registered, 0),
      backlog_size: Map.get(callback_stats, :backlog_size, 0),
      dispatches: Map.get(callback_stats, :dispatches, 0),
      errors: Map.get(callback_stats, :errors, 0)
    }
  end

  # Server Callbacks

  @impl true
  def init(user_config) do
    config = Keyword.merge(@default_config, user_config)

    state = %__MODULE__{
      plugins: %{},
      config: config,
      stats: %{
        plugins_loaded: 0
      }
    }

    # Defer plugin discovery and loading so init/1 returns quickly
    {:ok, state, {:continue, :initialize}}
  end

  @impl true
  def handle_continue(:initialize, state) do
    case discover_and_load(state) do
      {:ok, loaded_state} ->
        Logger.info("Plugin Manager initialized with #{loaded_state.stats.plugins_loaded} plugins")
        {:noreply, loaded_state}

      {:error, reason} ->
        Logger.error("Plugin Manager failed to initialize: #{inspect(reason)}")
        {:stop, reason, state}
    end
  end

  @impl true
  def handle_call({:register_plugin, module, config}, _from, state) do
    case load_plugin(module, config, state) do
      {:ok, plugin_state, new_state} ->
        {:reply, {:ok, plugin_state.name}, new_state}

      {:error, reason} ->
        {:reply, {:error, reason}, state}
    end
  end

  @impl true
  def handle_call({:unregister_plugin, plugin_name}, _from, state) do
    case Map.pop(state.plugins, plugin_name) do
      {nil, _} ->
        {:reply, {:error, :not_found}, state}

      {plugin, remaining} ->
        # Call terminate if implemented
        if function_exported?(plugin.module, :terminate, 0) do
          try do
            plugin.module.terminate()
          catch
            _kind, _reason ->
              Logger.warning("Plugin #{plugin_name} terminate failed: error during cleanup")
          end
        end

        # Unregister hooks from Callbacks system
        unregister_plugin_hooks(plugin)

        new_state = %{
          state
          | plugins: remaining,
            stats: %{state.stats | plugins_loaded: state.stats.plugins_loaded - 1}
        }

        {:reply, :ok, new_state}
    end
  end

  @impl true
  def handle_call(:list_plugins, _from, state) do
    plugins =
      Enum.map(state.plugins, fn {_name, plugin} ->
        %{
          name: plugin.name,
          module: plugin.module,
          hook_count: length(plugin.hooks)
        }
      end)

    {:reply, plugins, state}
  end

  @impl true
  def handle_call(:get_plugin_stats, _from, state) do
    stats = %{
      plugins_loaded: state.stats.plugins_loaded
    }

    {:reply, stats, state}
  end

  @impl true
  def handle_info(msg, state) do
    Logger.warning("[#{__MODULE__}] Unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  @impl true
  def terminate(_reason, state) do
    # Trigger shutdown hooks via Callbacks system
    _ = Callbacks.dispatch(:shutdown, [])

    # Call terminate on all plugins
    Enum.each(state.plugins, fn {_name, plugin} ->
      # Unregister hooks first
      unregister_plugin_hooks(plugin)

      if function_exported?(plugin.module, :terminate, 0) do
        try do
          plugin.module.terminate()
        catch
          _kind, _reason ->
            Logger.warning("Plugin #{plugin.name} terminate failed during shutdown: error")
        end
      end
    end)

    :ok
  end

  # Private Functions

  defp discover_and_load(state) do
    plugin_specs = Keyword.get(state.config, :plugins, [:discover])

    # Build list of modules to load
    modules =
      Enum.flat_map(plugin_specs, fn
        :discover -> discover_plugins()
        module when is_atom(module) -> [module]
        _ -> []
      end)

    # Load each plugin
    Enum.reduce_while(modules, {:ok, state}, fn module, {:ok, acc_state} ->
      load_plugin_with_error_handling(module, acc_state, state.config)
    end)
  end

  defp load_plugin_with_error_handling(module, acc_state, config) do
    plugin_config = get_plugin_config(module, acc_state.config)

    case load_plugin(module, plugin_config, acc_state) do
      {:ok, _plugin, new_state} ->
        {:cont, {:ok, new_state}}

      {:error, reason} ->
        handle_load_error(module, reason, acc_state, config)
    end
  end

  defp handle_load_error(module, reason, acc_state, config) do
    if Keyword.get(config, :auto_dismiss_errors, true) do
      Logger.error("Failed to load plugin #{inspect(module)}: #{inspect(reason)}")
      {:cont, {:ok, acc_state}}
    else
      {:halt, {:error, {module, reason}}}
    end
  end

  defp discover_plugins do
    # Look for modules in Mana.Plugins namespace
    # and any configured additional namespaces
    apps = Application.get_env(:mana, :plugin_namespaces, [Mana.Plugins])

    Enum.flat_map(apps, fn namespace ->
      # Find all modules in the namespace that implement the behaviour
      case Code.ensure_compiled(namespace) do
        {:module, _} ->
          # Get all modules in this namespace
          find_modules_in_namespace(namespace)

        {:error, _} ->
          []
      end
    end)
  end

  defp find_modules_in_namespace(namespace) do
    # In a real implementation, this would use :code.all_loaded()
    # and filter by module prefix
    all_modules = :code.all_loaded()

    Enum.flat_map(all_modules, fn {module, _} ->
      module_name = Atom.to_string(module)
      namespace_str = Atom.to_string(namespace) <> "."

      if String.starts_with?(module_name, namespace_str) do
        [module]
      else
        []
      end
    end)
    |> Enum.filter(&implements_behaviour?/1)
  end

  defp implements_behaviour?(module) do
    behaviours = module.module_info(:attributes)[:behaviour] || []
    Mana.Plugin.Behaviour in behaviours
  rescue
    _ -> false
  catch
    _, _ -> false
  end

  defp get_plugin_config(module, config) do
    # Try to extract plugin-specific config based on plugin name or module
    plugin_key = module |> Atom.to_string() |> String.split(".") |> List.last() |> Macro.underscore()

    config
    |> Keyword.get(:plugin_configs, %{})
    |> Map.get(module, %{})
    |> Map.merge(
      config
      |> Keyword.get(:plugin_configs, %{})
      |> Map.get(plugin_key, %{})
    )
  end

  defp load_plugin(module, config, state) do
    with {:module, _} <- Code.ensure_compiled(module),
         true <- function_exported?(module, :name, 0),
         true <- function_exported?(module, :init, 1),
         true <- function_exported?(module, :hooks, 0),
         plugin_name = module.name(),
         false <- Map.has_key?(state.plugins, plugin_name),
         {:ok, plugin_state} <- module.init(config) do
      hooks = module.hooks()

      # Validate hooks
      valid_hooks = filter_valid_hooks(hooks, plugin_name)

      plugin_record = %{
        module: module,
        name: plugin_name,
        state: plugin_state,
        hooks: valid_hooks
      }

      # Register hooks via unified Callbacks system
      register_plugin_hooks(valid_hooks)

      new_state = %{
        state
        | plugins: Map.put(state.plugins, plugin_name, plugin_record),
          stats: %{state.stats | plugins_loaded: state.stats.plugins_loaded + 1}
      }

      Logger.info("Loaded plugin: #{plugin_name} (#{length(valid_hooks)} hooks)")
      {:ok, plugin_record, new_state}
    else
      true -> {:error, :already_loaded}
      false -> {:error, :missing_callbacks}
      {:error, reason} -> {:error, reason}
    end
  end

  defp register_plugin_hooks(hooks) do
    Enum.each(hooks, fn {hook, func} ->
      # Register via unified Callbacks system
      case Callbacks.register(hook, func) do
        :ok -> :ok
        # Deduplication is fine
        {:error, :already_registered} -> :ok
        {:error, reason} -> Logger.warning("Failed to register hook #{hook}: #{inspect(reason)}")
      end
    end)
  end

  defp filter_valid_hooks(hooks, plugin_name) do
    Enum.filter(hooks, fn {hook, func} ->
      valid? = Hook.valid?(hook) and is_function(func)
      unless valid?, do: Logger.warning("Invalid hook #{inspect(hook)} from plugin #{plugin_name}")
      valid?
    end)
  end

  defp unregister_plugin_hooks(plugin) do
    Enum.each(plugin.hooks, fn {hook, func} ->
      case Callbacks.unregister(hook, func) do
        :ok -> :ok
        # Ignore errors during unregister
        _ -> :ok
      end
    end)
  end
end
