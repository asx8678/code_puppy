# Test fixture: simple_module.ex
# Purpose: Basic defmodule with functions
# Expected symbols: 1 module (SimpleModule), 2 public functions (hello/0, add/2)

defmodule SimpleModule do
  @moduledoc """
  A simple module for testing basic Elixir parsing.
  Contains public functions with various arities.
  """

  @doc "Returns a greeting string"
  def hello do
    "Hello, World!"
  end

  @doc "Adds two numbers"
  def add(a, b) do
    a + b
  end
end
