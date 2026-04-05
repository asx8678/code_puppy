defmodule Mana.Fixtures.Fixture20 do
  @moduledoc "Fixture module 20"

  def function_a(arg), do: arg
  def function_b(arg1, arg2), do: arg1 + arg2
  defp private_helper, do: :ok
end
