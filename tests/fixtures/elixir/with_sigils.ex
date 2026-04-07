# Test fixture: with_sigils.ex
# Purpose: Test Elixir sigils - KNOWN GAP for some complex sigils
# 
# Sigils are a core Elixir feature for working with literals.
# Basic sigils (~s, ~w, ~r) should parse, but complex sigils with
# modifiers and custom sigils may have gaps.
# 
# Expected symbols: 1 module (WithSigils), test functions for each sigil type

defmodule WithSigils do
  @moduledoc """
  Module demonstrating various Elixir sigils.
  Some sigils are complex and may not be fully parsed.
  """

  # ~s - String sigil (BASIC - should work)
  def string_sigil do
    ~s(This is a string with "quotes" inside)
  end

  # ~S - String sigil without interpolation (BASIC - should work)
  def raw_string_sigil do
    ~S(No #{interpolation} here)
  end

  # ~w - Word list sigil (BASIC - should work)
  def word_list_sigil do
    ~w(foo bar baz)
  end

  # ~W - Word list without interpolation (BASIC - should work)
  def raw_word_list_sigil do
    ~W(#{not_interpolated})
  end

  # ~r - Regex sigil (BASIC - should work)
  def regex_sigil do
    ~r/\d{3}-\d{4}/
  end

  # ~R - Regex without interpolation (BASIC - should work)
  def raw_regex_sigil do
    ~R/.*#{not_interpolated}.*/
  end

  # ~D - Date sigil (MODERATE - may work)
  def date_sigil do
    ~D[2024-01-15]
  end

  # ~T - Time sigil (MODERATE - may work)
  def time_sigil do
    ~T[14:30:00]
  end

  # ~N - NaiveDateTime sigil (MODERATE - may work)
  def naive_datetime_sigil do
    ~N[2024-01-15 14:30:00]
  end

  # ~U - UTC DateTime sigil (MODERATE - may work)
  def utc_datetime_sigil do
    ~U[2024-01-15 14:30:00Z]
  end

  # Sigils with modifiers (POTENTIAL GAP)
  def regex_with_modifiers do
    ~r/pattern/im  # case-insensitive, multiline
  end

  # Sigils with custom delimiters (POTENTIAL GAP)
  def sigil_delimiters do
    ~s{curly braces}
    ~s[brackets]
    ~s<angles>
    ~s|pipes|
    ~s"double quotes"
  end

  # Heredoc-style sigils (POTENTIAL GAP)
  def heredoc_sigil do
    ~s'''
    This is a
    multi-line
    string
    '''
  end

  # Custom sigil (KNOWN GAP - requires custom sigil definition)
  def custom_sigil_usage do
    ~x/custom pattern/
  end

  # HEEx sigil (KNOWN GAP - HTML+EEx, often in .heex files)
  def heex_sigil do
    ~H"""
    <div class="container">
      <p>Hello, <%= @name %>!</p>
    </div>
    """
  end
end
