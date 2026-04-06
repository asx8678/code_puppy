defmodule Mana.Fixtures.Fixture5 do
  @moduledoc "Fixture module 5"

  def function_a(arg), do: arg
  def function_b(arg1, arg2), do: arg1 + arg2
  defp private_helper, do: :ok
end
