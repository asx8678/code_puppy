# Test fixture: with_macros.ex
# Purpose: Test macro definitions and usage
# Expected symbols: 1 module (WithMacros), 2 macros (unless/2, debug/1), 1 function

defmodule WithMacros do
  @moduledoc """
  Module demonstrating macro definitions.
  Tests that the parser handles defmacro and quote/unquote correctly.
  """

  # Define a simple control flow macro
  defmacro unless(condition, do: block) do
    quote do
      if !unquote(condition), do: unquote(block)
    end
  end

  # Define a debugging macro that prints expression and result
  defmacro debug(expr) do
    quote bind_quoted: [expr: expr] do
      result = expr
      IO.puts("#{Macro.to_string(expr)} = #{inspect(result)}")
      result
    end
  end

  # Using __using__ macro to define module behavior
  defmacro __using__(opts) do
    quote location: :keep, bind_quoted: [opts: opts] do
      @behaviour WithMacros.Behaviour

      def init(state) do
        {:ok, state}
      end

      defoverridable init: 1
    end
  end

  # Regular function using macros
  def test_macros do
    unless false do
      "This should execute"
    end
  end
end
