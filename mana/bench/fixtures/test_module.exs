defmodule Mana.Fixtures.TestModule do
  @moduledoc "Test script for benchmarking"

  use ExUnit.Case

  describe "basic tests" do
    test "truth is true" do
      assert true
    end

    test "math works" do
      assert 2 + 2 == 4
    end

    test "string operations" do
      assert String.upcase("hello") == "HELLO"
    end
  end

  describe "list operations" do
    test "map works" do
      result = Enum.map([1, 2, 3], &(&1 * 2))
      assert result == [2, 4, 6]
    end

    test "reduce works" do
      result = Enum.reduce([1, 2, 3], 0, &(&1 + &2))
      assert result == 6
    end
  end

  defp helper_function(arg) do
    arg * 2
  end

  defp another_helper(arg1, arg2) do
    arg1 + arg2
  end
end
