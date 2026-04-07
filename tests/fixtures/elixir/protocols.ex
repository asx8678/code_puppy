# Test fixture: protocols.ex
# Purpose: Test protocol definitions - MODERATE complexity
#
# Protocols define polymorphic behavior. Basic defprotocol/defimpl
# should parse, but some complex cases may have gaps.
# 
# Expected symbols: 2 protocols (Stringifiable, Enumerable), 
#                   multiple implementations

defmodule Protocols do
  @moduledoc """
  Module demonstrating protocol definitions and implementations.
  Tests parsing of Elixir's polymorphism mechanism.
  """

  # Define a simple protocol (BASIC - should work)
  defprotocol Stringifiable do
    @doc "Converts the data structure to a string representation"
    def to_string(data)
  end

  # Define another protocol with multiple functions (BASIC - should work)
  defprotocol Measurable do
    @doc "Returns the size of the data structure"
    def size(data)

    @doc "Checks if the data structure is empty"
    def empty?(data)
  end

  # Protocol implementation for Map (BASIC - should work)
  defimpl Stringifiable, for: Map do
    def to_string(map) do
      map
      |> Enum.map(fn {k, v} -> "#{k}: #{v}" end)
      |> Enum.join(", ")
      |> then(&"%{#{&1}}")
    end
  end

  # Protocol implementation for List (BASIC - should work)
  defimpl Stringifiable, for: List do
    def to_string(list) do
      list
      |> Enum.map(&Kernel.to_string/1)
      |> Enum.join(", ")
      |> then(&"[#{&1}]")
    end
  end

  # Protocol implementation for custom struct (MODERATE)
  defimpl Stringifiable, for: Protocols.User do
    def to_string(%Protocols.User{name: name, age: age}) do
      "User(#{name}, #{age})"
    end
  end

  # Multiple implementations in one block (MODERATE)
  defimpl Measurable, for: List do
    def size(list), do: length(list)
    def empty?([]), do: true
    def empty?(_), do: false
  end

  defimpl Measurable, for: Map do
    def size(map), do: map_size(map)
    def empty?(map), do: map_size(map) == 0
  end

  # Protocol implementation for BitString (POTENTIAL GAP)
  defimpl Stringifiable, for: BitString do
    def to_string(binary) when is_binary(binary), do: binary
    def to_string(_), do: "<bitstring>"
  end

  # Protocol with guards (POTENTIAL GAP)
  defprotocol Collection do
    @fallback_to_any true
    def count(collection)
  end

  defimpl Collection, for: Any do
    def count(_), do: 0
  end

  # Struct definition for protocol demo
  defmodule User do
    defstruct [:name, :age, :email]
  end

  # Using a protocol (BASIC)
  def demo_protocols do
    user = %Protocols.User{name: "Alice", age: 30, email: "alice@example.com"}
    Stringifiable.to_string(user)
  end
end
