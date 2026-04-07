# Test fixture: complex_module.ex
# Purpose: Nested modules, guards, multiple function clauses
# Expected symbols: 3 modules (Outer, Outer.Inner, Outer.Inner.Deep), 
#                   4+ functions with guards and multiple clauses

defmodule Outer do
  @moduledoc "Outer module containing nested modules"

  defmacro __using__(_opts) do
    quote do
      import Outer
    end
  end

  # Function with multiple clauses and guards
  def classify_number(n) when is_integer(n) and n > 0 do
    :positive
  end

  def classify_number(n) when is_integer(n) and n < 0 do
    :negative
  end

  def classify_number(0), do: :zero
  def classify_number(_), do: :unknown

  defmodule Inner do
    @moduledoc "Inner nested module"

    # Function with default arguments
    def greet(name \\ "World") do
      "Hello, #{name}!"
    end

    # Function with when guard and pattern matching
    def safe_divide(_numerator, denominator) when denominator == 0 do
      {:error, :division_by_zero}
    end

    def safe_divide(numerator, denominator) do
      {:ok, numerator / denominator}
    end

    defmodule Deep do
      @moduledoc "Deeply nested module"

      @const_value 42

      def get_const, do: @const_value
    end
  end
end
