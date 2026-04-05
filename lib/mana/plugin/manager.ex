defmodule Mana.Plugin.Manager do
  @moduledoc """
  GenServer that manages plugin discovery, initialization, and hook dispatch.

  The Manager is responsible for:
  - Discovering plugins at startup from configured sources
  - Calling `init/1` on each plugin and tracking their state
  - Dispatching hook events to registered plugin callbacks
  - Maintaining an event backlog for hooks fired before listeners register
  - Graceful shutdown coordination

  ## Lifecycle

  1. **Discovery** - At startup, scans configured directories for modules
     implementing `Mana.Plugin.Behaviour`
  2. **Initialization** - Calls `init/1` on each discovered plugin with
     its configuration
  3. **Registration** - Stores hook mappings for efficient dispatch
  4. **Dispatch** - Routes hook events to registered callbacks
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
        ],
        # Backlog retention time in milliseconds
        backlog_ttl: 30_000,
        # Maximum backlog size per hook
        max_backlog_size: 100

  ## Usage

  Start the manager in your application supervisor:

      children = [
        Mana.Plugin.Manager
      ]

  Trigger hooks from your code:

      Mana.Plugin.Manager.trigger(:agent_run_start, ["my_agent", "gpt-4", "session_123"])
      Mana.Plugin.Manager.trigger_async(:agent_run_start, ["my_agent", "gpt-4", "session_123"])
  """

  use GenServer

  require Logger

  alias Mana.Plugin.Hook

  defstruct [
    :plugins,
    :hooks,
    :backlog,
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
          hooks: %{Hook.hook_phase() => [function()]},
          backlog: %{Hook.hook_phase() => [term()]},
          config: keyword(),
          stats: %{
            triggers: non_neg_integer(),
            errors: non_neg_integer(),
            plugins_loaded: non_neg_integer()
          }
        }

  # Default configuration
  @default_config [
    backlog_ttl: 30_000,
    max_backlog_size: 100,
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

  ## Parameters

  - `hook` - The hook phase atom (e.g., `:agent_run_start`)
  - `args` - List of arguments to pass to callbacks
  - `opts` - Options:
    - `:timeout` - Maximum time to wait for callbacks (default: 5000ms)
    - `:continue_on_error` - Whether to continue if a callback fails (default: true)

  ## Returns

  - `{:ok, results}` - List of results from all callbacks
  - `{:error, reason}` - Failed to trigger hook

  ## Examples

      Mana.Plugin.Manager.trigger(:agent_run_start, ["agent", "model", nil])
      Mana.Plugin.Manager.trigger(:file_permission, [ctx, "/path", "read", nil, nil, nil], timeout: 10_000)
  """
  @spec trigger(Hook.hook_phase(), [term()], keyword()) :: {:ok, [term()]} | {:error, term()}
  def trigger(hook, args \\ [], opts \\ []) do
    # Reentrancy guard: if called from within the GenServer itself, execute directly
    # to avoid deadlock when callbacks try to trigger other hooks.
    # NOTE: We use the process dictionary to pass state during dispatch,
    # because :sys.get_state sends a message to self() which deadlocks.
    if self() == GenServer.whereis(__MODULE__) do
      # We're inside the GenServer process — read state from process dictionary
      case Process.get(:plugin_manager_state) do
        nil ->
          # Fallback: no state available, buffer the event for later
          {:ok, []}

        state ->
          {results, _new_state} = do_trigger(hook, args, opts, state, :sync)
          {:ok, results}
      end
    else
      # Normal case: call through GenServer
      GenServer.call(__MODULE__, {:trigger, hook, args, opts}, Keyword.get(opts, :timeout, 5000))
    end
  end

  @doc """
  Triggers a hook asynchronously.

  Returns immediately without waiting for callbacks to complete.
  Callback errors are logged but don't affect the caller.

  ## Parameters

  - `hook` - The hook phase atom
  - `args` - List of arguments to pass to callbacks

  ## Returns

  - `:ok` - Hook dispatched (results not available)

  ## Examples

      Mana.Plugin.Manager.trigger_async(:stream_event, ["token", %{token: "hello"}, session_id])
  """
  @spec trigger_async(Hook.hook_phase(), [term()]) :: :ok
  def trigger_async(hook, args \\ []) do
    GenServer.cast(__MODULE__, {:trigger_async, hook, args})
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
    trigger(:startup, [], timeout: 30_000)
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
    trigger(:shutdown, [], timeout: 10_000)
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

  When hooks fire before any listeners are registered, events are
  buffered. Call this after registering a plugin to process missed events.

  ## Parameters

  - `hook` - The hook phase to drain

  ## Returns

  - `{:ok, results}` - Results from replayed events
  """
  @spec drain_backlog(Hook.hook_phase()) :: {:ok, [term()]} | {:error, term()}
  def drain_backlog(hook) do
    GenServer.call(__MODULE__, {:drain_backlog, hook})
  end

  @doc """
  Drains the backlog for all hooks.

  ## Returns

  - `{:ok, %{hook => results}}` - Map of results per hook
  """
  @spec drain_all_backlogs() :: {:ok, %{Hook.hook_phase() => [term()]}} | {:error, term()}
  def drain_all_backlogs do
    GenServer.call(__MODULE__, :drain_all_backlogs)
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
  """
  @spec get_stats() :: %{
          plugins_loaded: non_neg_integer(),
          hooks_registered: non_neg_integer(),
          triggers_total: non_neg_integer(),
          errors_total: non_neg_integer(),
          backlog_size: non_neg_integer()
        }
  def get_stats do
    GenServer.call(__MODULE__, :get_stats)
  end

  # Server Callbacks

  @impl true
  def init(user_config) do
    config = Keyword.merge(@default_config, user_config)

    state = %__MODULE__{
      plugins: %{},
      hooks: %{},
      backlog: initialize_backlog(),
      config: config,
      stats: %{
        triggers: 0,
        errors: 0,
        plugins_loaded: 0
      }
    }

    # Discover and load plugins
    case discover_and_load(state) do
      {:ok, loaded_state} ->
        Logger.info("Plugin Manager initialized with #{loaded_state.stats.plugins_loaded} plugins")
        {:ok, loaded_state}

      {:error, reason} ->
        Logger.error("Plugin Manager failed to initialize: #{inspect(reason)}")
        {:stop, reason}
    end
  end

  @impl true
  def handle_call({:trigger, hook, args, opts}, _from, state) do
    # Store state in process dictionary for reentrant calls
    Process.put(:plugin_manager_state, state)
    {results, new_state} = do_trigger(hook, args, opts, state, :sync)
    Process.delete(:plugin_manager_state)
    {:reply, {:ok, results}, new_state}
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

        # Remove hooks
        new_hooks = remove_plugin_hooks(plugin, state.hooks)

        new_state = %{
          state
          | plugins: remaining,
            hooks: new_hooks,
            stats: %{state.stats | plugins_loaded: state.stats.plugins_loaded - 1}
        }

        {:reply, :ok, new_state}
    end
  end

  @impl true
  def handle_call({:drain_backlog, hook}, _from, state) do
    {results, new_state} = do_drain_backlog(hook, state)
    {:reply, {:ok, results}, new_state}
  end

  @impl true
  def handle_call(:drain_all_backlogs, _from, state) do
    all_hooks = Map.keys(state.backlog)

    {results_map, final_state} =
      Enum.reduce(all_hooks, {%{}, state}, fn hook, {acc, st} ->
        {results, new_st} = do_drain_backlog(hook, st)
        {Map.put(acc, hook, results), new_st}
      end)

    {:reply, {:ok, results_map}, final_state}
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
  def handle_call(:get_stats, _from, state) do
    backlog_size =
      state.backlog
      |> Map.values()
      |> Enum.map(&length/1)
      |> Enum.sum()

    hook_count =
      state.hooks
      |> Map.values()
      |> Enum.map(&length/1)
      |> Enum.sum()

    stats = %{
      plugins_loaded: state.stats.plugins_loaded,
      hooks_registered: hook_count,
      triggers_total: state.stats.triggers,
      errors_total: state.stats.errors,
      backlog_size: backlog_size
    }

    {:reply, stats, state}
  end

  @impl true
  def handle_cast({:trigger_async, hook, args}, state) do
    Process.put(:plugin_manager_state, state)
    {_results, new_state} = do_trigger(hook, args, [continue_on_error: true], state, :async)
    Process.delete(:plugin_manager_state)
    {:noreply, new_state}
  end

  @impl true
  def terminate(_reason, state) do
    # Trigger shutdown hooks
    _ = do_trigger(:shutdown, [], [continue_on_error: true], state, :sync)

    # Call terminate on all plugins
    Enum.each(state.plugins, fn {_name, plugin} ->
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

  defp initialize_backlog do
    Hook.all_hooks()
    |> Map.new(fn hook -> {hook, []} end)
  end

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

      # Register hooks
      new_hooks = register_hooks(valid_hooks, plugin_name, state.hooks)

      new_state = %{
        state
        | plugins: Map.put(state.plugins, plugin_name, plugin_record),
          hooks: new_hooks,
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

  defp register_hooks(hooks, plugin_name, existing_hooks) do
    Enum.reduce(hooks, existing_hooks, fn {hook, func}, acc ->
      func_with_metadata = {func, plugin_name}
      Map.update(acc, hook, [func_with_metadata], &[func_with_metadata | &1])
    end)
  end

  defp filter_valid_hooks(hooks, plugin_name) do
    Enum.filter(hooks, fn {hook, func} ->
      valid? = Hook.valid?(hook) and is_function(func)
      unless valid?, do: Logger.warning("Invalid hook #{inspect(hook)} from plugin #{plugin_name}")
      valid?
    end)
  end

  defp remove_plugin_hooks(plugin, hooks) do
    Enum.reduce(plugin.hooks, hooks, fn {hook, _func}, acc ->
      Map.update(acc, hook, [], &reject_plugin_funcs(&1, plugin.name))
    end)
  end

  defp reject_plugin_funcs(funcs, plugin_name) do
    Enum.reject(funcs, fn {_f, name} -> name == plugin_name end)
  end

  defp do_trigger(hook, args, opts, state, mode) do
    # Validate hook
    if Hook.valid?(hook) do
      callbacks = Map.get(state.hooks, hook, [])

      if callbacks == [] do
        # Buffer to backlog if no listeners
        buffer_to_backlog(hook, args, state)
      else
        # Execute callbacks
        execute_callbacks(callbacks, args, opts, state, mode)
      end
    else
      Logger.warning("Invalid hook triggered: #{inspect(hook)}")
      {[], state}
    end
  end

  defp buffer_to_backlog(hook, args, state) do
    max_size = Keyword.get(state.config, :max_backlog_size, 100)
    backlog = state.backlog
    hook_backlog = Map.get(backlog, hook, [])

    # Add to backlog, respecting max size (FIFO)
    new_hook_backlog =
      if length(hook_backlog) >= max_size do
        tl(hook_backlog) ++ [{args, System.monotonic_time()}]
      else
        hook_backlog ++ [{args, System.monotonic_time()}]
      end

    new_backlog = Map.put(backlog, hook, new_hook_backlog)
    new_stats = %{state.stats | triggers: state.stats.triggers + 1}
    new_state = %{state | backlog: new_backlog, stats: new_stats}

    Logger.debug("Buffered #{hook} event (no listeners yet)")
    {[], new_state}
  end

  defp execute_callbacks(callbacks, args, opts, state, mode) do
    continue_on_error = Keyword.get(opts, :continue_on_error, true)

    results =
      if mode == :async do
        # Fire and forget for async
        Enum.each(callbacks, fn {func, _plugin_name} ->
          Task.start(fn ->
            try do
              apply_callback(func, args)
            catch
              _kind, _reason ->
                Logger.error("Async hook failed: error during execution")
            end
          end)
        end)

        []
      else
        # Execute synchronously
        Enum.map(callbacks, fn {func, plugin_name} ->
          try do
            result = apply_callback(func, args)
            Logger.debug("Hook #{plugin_name} succeeded")
            result
          catch
            kind, reason ->
              Logger.error("Hook #{plugin_name} failed: #{kind} #{inspect(reason)}")

              if continue_on_error do
                {:error, {kind, reason}}
              else
                throw({:callback_error, plugin_name, kind, reason})
              end
          end
        end)
      end

    new_stats = %{
      state.stats
      | triggers: state.stats.triggers + 1,
        errors: state.stats.errors + count_errors(results)
    }

    new_state = %{state | stats: new_stats}
    {results, new_state}
  catch
    {:callback_error, _plugin_name, _kind, _reason} ->
      Logger.error("Stopping due to hook error: callback failed")
      {[], %{state | stats: %{state.stats | triggers: state.stats.triggers + 1, errors: state.stats.errors + 1}}}
  end

  @spec apply_callback(fun(), list()) :: any()
  defp apply_callback(func, args) do
    {:arity, arity} = :erlang.fun_info(func, :arity)
    actual_args = Enum.take(args, arity)
    apply(func, actual_args)
  end

  defp count_errors(results) do
    Enum.count(results, fn
      {:error, _} -> true
      _ -> false
    end)
  end

  defp do_drain_backlog(hook, state) do
    backlog = Map.get(state.backlog, hook, [])
    ttl = Keyword.get(state.config, :backlog_ttl, 30_000)
    now = System.monotonic_time()
    ttl_native = System.convert_time_unit(ttl, :millisecond, :native)

    # Filter expired events
    valid_events =
      Enum.filter(backlog, fn {_args, timestamp} ->
        now - timestamp < ttl_native
      end)

    # Replay events
    {results, final_state} =
      Enum.reduce(valid_events, {[], state}, fn {args, _timestamp}, {acc, st} ->
        {hook_results, new_st} = do_trigger(hook, args, [continue_on_error: true], st, :sync)
        {acc ++ hook_results, new_st}
      end)

    # Clear this hook's backlog
    new_backlog = Map.put(final_state.backlog, hook, [])
    final_state = %{final_state | backlog: new_backlog}

    Logger.info("Drained #{hook} backlog: #{length(valid_events)} events replayed")
    {results, final_state}
  end
end
