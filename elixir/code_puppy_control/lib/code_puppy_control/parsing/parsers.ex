defmodule CodePuppyControl.Parsing.Parsers do
  @moduledoc """
  Module for registering built-in language parsers.

  This module provides a child_spec for use in the application supervision tree
  to ensure all built-in parsers are registered on startup.
  """

  alias CodePuppyControl.Parsing.ParserRegistry

  @doc """
  Registers all built-in language parsers with the ParserRegistry.

  Should be called after the ParserRegistry has started.
  """
  @spec register_all() :: :ok
  def register_all do
    parsers = [
      CodePuppyControl.Parsing.Parsers.ElixirParser,
      CodePuppyControl.Parsing.Parsers.PythonParser,
      CodePuppyControl.Parsing.Parsers.JavaScriptParser,
      CodePuppyControl.Parsing.Parsers.TypeScriptParser,
      CodePuppyControl.Parsing.Parsers.RustParser
    ]

    Enum.each(parsers, fn parser ->
      case ParserRegistry.register(parser) do
        :ok -> :ok
        {:error, :unsupported} -> :ok
        {:error, :invalid_module} -> :ok
      end
    end)

    :ok
  end

  @doc """
  Child spec for supervision tree.

  Registers all parsers on startup and returns :ignore so it doesn't
  remain in the supervision tree.
  """
  def child_spec(_opts) do
    %{
      id: __MODULE__,
      start: {__MODULE__, :start_link, []},
      type: :worker
    }
  end

  @doc false
  def start_link do
    register_all()
    # Return :ignore so this doesn't stay in the supervision tree
    :ignore
  end
end
