defmodule CodePuppyControl.Tool do
  @moduledoc """
  Behaviour and `use` macro for tool modules.

  When you `use CodePuppyControl.Tool`, your module must implement:
  - `name/0`          — atom identifier for the tool
  - `description/0`   — human-readable description
  - `parameters/0`    — JSON-schema-style parameter map
  - `invoke/2`        — execution entry point `invoke(args, context)`
  """

  @callback name() :: atom()
  @callback description() :: String.t()
  @callback parameters() :: map()
  @callback permission_check(args :: map(), context :: map()) :: :ok | {:deny, String.t()}
  @callback invoke(args :: map(), context :: map()) :: {:ok, any()} | {:error, String.t()}

  defmacro __using__(_opts) do
    quote do
      @behaviour CodePuppyControl.Tool

      @impl true
      def permission_check(_args, _context), do: :ok
    end
  end
end
