# Test fixture: string_interpolation.ex
# Purpose: Test string interpolation - KNOWN GAP for complex cases
#
# Basic interpolation like "Hello #{name}" should work,
# but complex nested interpolations may not parse correctly.
# 
# Expected symbols: 1 module (StringInterpolation), test functions

defmodule StringInterpolation do
  @moduledoc """
  Module testing string interpolation patterns.
  Some complex interpolations may not be fully parsed.
  """

  # Basic interpolation (BASIC - should work)
  def basic_interpolation(name) do
    "Hello, #{name}!"
  end

  # Interpolation with expression (BASIC - should work)
  def expression_interpolation(a, b) do
    "The sum is #{a + b}"
  end

  # Interpolation with function call (BASIC - should work)
  def function_call_interpolation(value) do
    "Result: #{inspect(value)}"
  end

  # Interpolation with module function (BASIC - should work)
  def module_function_interpolation do
    "Now: #{DateTime.utc_now()}"
  end

  # Multiple interpolations (MODERATE - should work)
  def multiple_interpolations(first, last) do
    "First: #{first}, Last: #{last}"
  end

  # Nested string in interpolation (POTENTIAL GAP)
  def nested_string_interpolation do
    "Outer #{"inner #{value}"}"
  end

  # Interpolation with heredoc (POTENTIAL GAP)
  def heredoc_interpolation do
    """
    Hello, #{name}!
    Welcome to #{place}.
    """
  end

  # Interpolation in sigil (POTENTIAL GAP)
  def sigil_interpolation do
    ~s(Welcome #{user.name}!)
  end

  # Interpolation with escape sequences (POTENTIAL GAP)
  def escape_interpolation do
    "Line 1\nLine 2: #{value}\nLine 3"
  end

  # Interpolation inside pattern matching (SYNTAX EDGE CASE)
  def pattern_match_interpolation do
    "prefix_#{suffix}" = some_string
  end
end
