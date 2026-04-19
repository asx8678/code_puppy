defmodule CodePuppyControl.Plugins.PluginBehaviour do
  @moduledoc """
  Behaviour definition for Code Puppy plugins.

  Plugins implement this behaviour to register callbacks, provide metadata,
  and participate in the plugin lifecycle (startup/shutdown).

  ## Example

      defmodule MyPlugin do
        @behaviour CodePuppyControl.Plugins.PluginBehaviour

        @impl true
        def name, do: :my_plugin

        @impl true
        def register_callbacks do
          [
            {:startup, fn -> IO.puts("MyPlugin loaded!") end},
            {:load_prompt, fn -> "## My Plugin Instructions" end}
          ]
        end

        @impl true
        def startup, do: :ok

        @impl true
        def shutdown, do: :ok
      end

  ## Using the `use` Macro

  You can `use` this module to get default implementations for optional
  callbacks:

      defmodule MyPlugin do
        use CodePuppyControl.Plugins.PluginBehaviour

        @impl true
        def name, do: :my_plugin

        @impl true
        def register_callbacks do
          [{:startup, fn -> :ok end}]
        end
      end
  """

  @doc """
  Returns the unique name/identifier for this plugin (an atom).
  """
  @callback name() :: atom()

  @doc """
  Returns a list of `{hook_name, callback_fn}` tuples to register.

  Each `hook_name` must be a valid hook from `CodePuppyControl.Callbacks.Hooks`.
  Each `callback_fn` is a function matching the hook's expected arity.
  """
  @callback register_callbacks() :: [{atom(), function()}]

  @doc """
  Called when the plugin system starts up. Optional — defaults to `:ok`.
  """
  @callback startup() :: :ok

  @doc """
  Called when the plugin system shuts down. Optional — defaults to `:ok`.
  """
  @callback shutdown() :: :ok

  @doc """
  Returns a description of the plugin. Optional — defaults to `""`.
  """
  @callback description() :: String.t()

  @optional_callbacks [startup: 0, shutdown: 0, description: 0]

  defmacro __using__(_opts) do
    quote do
      @behaviour CodePuppyControl.Plugins.PluginBehaviour

      @impl true
      def startup, do: :ok

      @impl true
      def shutdown, do: :ok

      @impl true
      def description, do: ""

      defoverridable startup: 0, shutdown: 0, description: 0
    end
  end
end
