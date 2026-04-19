defmodule CodePuppyControl.Plugins.Loader do
  @moduledoc """
  Discovers and loads plugins from builtin and user directories.

  ## Plugin Types

  ### Builtin Plugins
  Compiled modules that implement `CodePuppyControl.Plugins.PluginBehaviour`.
  These are discovered at compile time by scanning modules in the
  `CodePuppyControl.Plugins.*` namespace that have `@behaviour PluginBehaviour`.

  ### User Plugins
  `.ex` files under `~/.code_puppy/plugins/` that are compiled at runtime
  using `Code.compile_file/1`.

  **SECURITY WARNING**: User plugins execute arbitrary Elixir code with full
  system privileges. A malicious plugin can perform any action the host process
  can perform (delete files, steal credentials, install malware, etc.).
  Only load plugins from trusted sources.

  ## Discovery

  The loader scans for plugin modules and `.ex` files, then registers them
  with the callback system. Discovery is idempotent — calling `discover/0`
  multiple times only discovers plugins once.
  """

  require Logger

  alias CodePuppyControl.Callbacks
  alias CodePuppyControl.Config.Isolation
  alias CodePuppyControl.Config.Paths
  alias CodePuppyControl.Plugins.PluginBehaviour

  # ── Public API ──────────────────────────────────────────────────

  @doc """
  Discovers and loads all plugins (builtin + user).

  Returns a map with `:builtin` and `:user` keys containing lists of
  plugin names that were loaded.

  This function is idempotent — subsequent calls only discover new plugins.
  """
  @spec load_all() :: %{builtin: [atom()], user: [atom()]}
  def load_all do
    builtin = load_builtin_plugins()
    user = load_user_plugins()

    %{builtin: builtin, user: user}
  end

  @doc """
  Loads a single plugin from the given path.

  For `.ex` files: compiles and loads the file, then discovers any modules
  that implement `PluginBehaviour` within the compiled code.

  For module atoms: directly loads the module if it implements `PluginBehaviour`.

  Returns `{:ok, plugin_name}` or `{:error, reason}`.
  """
  @spec load_plugin(String.t() | atom()) :: {:ok, atom()} | {:error, term()}
  def load_plugin(path_or_module)

  def load_plugin(module_name) when is_atom(module_name) do
    if plugin_behaviour?(module_name) do
      register_plugin(module_name)
      {:ok, module_name.name()}
    else
      {:error, {:not_a_plugin, module_name}}
    end
  end

  def load_plugin(file_path) when is_binary(file_path) do
    expanded = Path.expand(file_path)

    if not File.exists?(expanded) do
      {:error, {:file_not_found, expanded}}
    else
      Logger.warning(
        "SECURITY: Loading user plugin from #{expanded} — executes arbitrary Elixir code " <>
          "with full system privileges. Only load plugins from trusted sources!"
      )

      try do
        modules_before = loaded_modules()
        Code.compile_file(expanded)
        modules_after = loaded_modules()
        new_modules = modules_after -- modules_before

        plugin_modules =
          Enum.filter(new_modules, &plugin_behaviour?/1)

        case plugin_modules do
          [] ->
            {:error, {:no_plugins_found, expanded}}

          [mod | _] ->
            register_plugin(mod)
            {:ok, mod.name()}
        end
      rescue
        e ->
          Logger.error("Failed to load plugin from #{expanded}: #{Exception.message(e)}")
          {:error, {:compile_error, Exception.message(e)}}
      end
    end
  end

  @doc """
  Returns the path to the user plugins directory.
  """
  @spec user_plugins_dir() :: String.t()
  def user_plugins_dir, do: Paths.plugins_dir()

  @doc """
  Ensures the user plugins directory exists.

  Returns the path to the directory.
  """
  @spec ensure_user_plugins_dir() :: String.t()
  def ensure_user_plugins_dir do
    dir = Paths.plugins_dir()
    Isolation.safe_mkdir_p!(dir)
    dir
  end

  @doc """
  Lists all currently loaded plugins.

  Returns a list of maps with `:name`, `:module`, and `:type` keys.
  """
  @spec list_loaded() :: [%{name: atom(), module: module(), type: :builtin | :user}]
  def list_loaded do
    case :ets.whereis(__MODULE__) do
      :undefined -> []
      _tab -> __MODULE__ |> :ets.tab2list() |> Enum.map(fn {_k, v} -> v end)
    end
  end

  # ── Builtin Plugin Discovery ────────────────────────────────────

  @doc false
  @spec load_builtin_plugins() :: [atom()]
  defp load_builtin_plugins do
    ensure_ets_table()

    # Find all compiled modules that implement PluginBehaviour
    # and aren't already loaded
    loaded_names = list_loaded() |> Enum.map(& &1.name)

    :code.all_loaded()
    |> Enum.map(fn {mod, _} -> mod end)
    |> Enum.filter(&plugin_behaviour?/1)
    |> Enum.reject(fn mod -> mod.name() in loaded_names end)
    |> Enum.map(fn mod ->
      register_plugin(mod, :builtin)
      mod.name()
    end)
  end

  # ── User Plugin Discovery ───────────────────────────────────────

  @doc false
  @spec load_user_plugins() :: [atom()]
  defp load_user_plugins do
    ensure_ets_table()

    plugins_dir = Paths.plugins_dir()

    unless File.dir?(plugins_dir) do
      []
    else
      loaded_names = list_loaded() |> Enum.map(& &1.name)

      plugins_dir
      |> File.ls!()
      |> Enum.filter(fn name ->
        dir = Path.join(plugins_dir, name)

        File.dir?(dir) and not String.starts_with?(name, "_") and
          not String.starts_with?(name, ".")
      end)
      |> Enum.flat_map(fn plugin_name ->
        if plugin_name in loaded_names do
          []
        else
          load_user_plugin(plugin_name, plugins_dir)
        end
      end)
    end
  end

  @doc false
  @spec load_user_plugin(String.t(), String.t()) :: [atom()]
  defp load_user_plugin(plugin_name, plugins_dir) do
    plugin_dir = Path.join(plugins_dir, plugin_name)

    # SECURITY: Validate no path traversal
    if String.contains?(plugin_name, ["..", "/", "\\", <<0>>]) do
      Logger.warning("SECURITY: Skipping user plugin with suspicious name: #{plugin_name}")
      []
    else
      # Try register_callbacks.ex first, then any .ex file
      ex_files =
        [Path.join(plugin_dir, "register_callbacks.ex")]
        |> Enum.filter(&File.exists?/1)
        |> case do
          [] ->
            plugin_dir
            |> File.ls!()
            |> Enum.filter(&String.ends_with?(&1, ".ex"))
            |> Enum.map(&Path.join(plugin_dir, &1))

          files ->
            files
        end

      case ex_files do
        [] ->
          Logger.warning("No .ex files found in user plugin: #{plugin_name}")
          []

        files ->
          Enum.flat_map(files, fn file ->
            Logger.warning(
              "SECURITY: Loading user plugin '#{plugin_name}' from #{file} — " <>
                "executes arbitrary Elixir code with full system privileges!"
            )

            try do
              modules_before = loaded_modules()
              Code.compile_file(file)
              modules_after = loaded_modules()
              new_modules = modules_after -- modules_before

              plugin_modules = Enum.filter(new_modules, &plugin_behaviour?/1)

              Enum.map(plugin_modules, fn mod ->
                register_plugin(mod, :user)
                mod.name()
              end)
            rescue
              e ->
                Logger.error(
                  "Failed to load user plugin '#{plugin_name}': #{Exception.message(e)}"
                )

                []
            end
          end)
      end
    end
  end

  # ── Plugin Registration ─────────────────────────────────────────

  @doc false
  @spec register_plugin(module(), :builtin | :user) :: :ok
  defp register_plugin(module, type \\ :builtin) do
    ensure_ets_table()

    plugin_info = %{
      name: module.name(),
      module: module,
      type: type
    }

    :ets.insert(__MODULE__, {module.name(), plugin_info})

    # Register callbacks from the plugin
    callbacks = module.register_callbacks()

    Enum.each(callbacks, fn {hook_name, fun} ->
      try do
        Callbacks.register(hook_name, fun)
      rescue
        ArgumentError ->
          Logger.warning(
            "Plugin #{module.name()} registered callback for unknown hook: #{hook_name}"
          )
      end
    end)

    # Call startup
    if function_exported?(module, :startup, 0) do
      module.startup()
    end

    Logger.info("Loaded #{type} plugin: #{module.name()}")
    :ok
  end

  # ── Helpers ─────────────────────────────────────────────────────

  @doc false
  @spec plugin_behaviour?(module()) :: boolean()
  defp plugin_behaviour?(module) do
    behaviours =
      module.module_info(:attributes)
      |> Keyword.get(:behaviour, [])

    PluginBehaviour in behaviours
  rescue
    UndefinedFunctionError -> false
    _ -> false
  end

  @doc false
  @spec loaded_modules() :: [module()]
  defp loaded_modules do
    :code.all_loaded() |> Enum.map(fn {mod, _} -> mod end)
  end

  @doc false
  @spec ensure_ets_table() :: :ok
  defp ensure_ets_table do
    case :ets.whereis(__MODULE__) do
      :undefined ->
        :ets.new(__MODULE__, [:set, :named_table, :public, read_concurrency: true])
        :ok

      _ ->
        :ok
    end
  end
end
