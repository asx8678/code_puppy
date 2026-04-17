defmodule CodePuppyControl.HashLine do
  @moduledoc """
  Pure Elixir implementation of HashLine algorithm.

  Provides per-line content hashing for file edit anchoring, compatible
  with the Rust NIF implementation (HashlineNif).

  This module uses xxHash32 (via the xxhash package) to compute line
  hashes, producing identical output to the Rust NIF version.

  ## Algorithm

  NIBBLE_STR = "ZPMQVRWSNKTXJBYH"

  1. Strip trailing whitespace (\\r, spaces, tabs, etc.)
  2. Check if cleaned line has alphanumeric characters
  3. If has alnum: seed = 0, else seed = idx
  4. hash = XXHash.xxh32(cleaned, seed)  # returns u32
  5. byte = Bitwise.band(hash, 0xFF)  # lowest byte
  6. hi = String.at(NIBBLE_STR, Bitwise.bsr(byte, 4))
  7. lo = String.at(NIBBLE_STR, Bitwise.band(byte, 0xF))
  8. hi <> lo

  ## Format

  `format_hashlines/2` produces lines like: `1#AB:original content`

  Where `1` is the line number, `AB` is the 2-char hash anchor,
  and everything after the colon is the original line content.

  ## Note on Current Implementation

  This is currently a STUB that delegates to HashlineNif. The pure Elixir
  implementation will be provided by bd-149. These tests ensure parity
  between the two implementations.
  """

  alias CodePuppyControl.HashlineNif

  @doc """
  Returns true if the NIF is loaded and available for delegation.
  """
  @spec nif_loaded?() :: boolean()
  def nif_loaded? do
    # Check if NIF functions are actually loaded (not just stubs)
    try do
      HashlineNif.compute_line_hash(1, "test")
      true
    rescue
      _ -> false
    end
  end

  @doc """
  Compute a 2-character hash anchor for a single line.

  Strips trailing whitespace, uses xxHash32 with idx as seed for
  whitespace-only lines, encodes lowest byte via NIBBLE_STR.

  ## Examples

      iex> HashLine.compute_line_hash(1, "hello world")
      "MM"

      iex> HashLine.compute_line_hash(1, "   ")
      "ZB"

  """
  @spec compute_line_hash(non_neg_integer(), String.t()) :: String.t()
  def compute_line_hash(idx, line) do
    # STUB: Currently delegates to NIF. Pure Elixir implementation coming in bd-149.
    HashlineNif.compute_line_hash(idx, line)
  end

  @doc """
  Format text with hashline prefixes.

  Each line becomes `LINE_NUM#HASH:original_line`.
  `start_line` is 1-based by convention.

  ## Examples

      iex> HashLine.format_hashlines("foo\\nbar", 1)
      "1#PZ:foo\\n2#BE:bar"

  """
  @spec format_hashlines(String.t(), non_neg_integer()) :: String.t()
  def format_hashlines(text, start_line) do
    # STUB: Currently delegates to NIF. Pure Elixir implementation coming in bd-149.
    HashlineNif.format_hashlines(text, start_line)
  end

  @doc """
  Strip hashline prefixes from text, returning plain content.

  Lines matching the pattern `^\\d+#[A-Z]{2}:` have the prefix removed.
  Other lines pass through unchanged.

  ## Examples

      iex> HashLine.strip_hashline_prefixes("1#PZ:foo\\n2#BE:bar")
      "foo\\nbar"

  """
  @spec strip_hashline_prefixes(String.t()) :: String.t()
  def strip_hashline_prefixes(text) do
    # STUB: Currently delegates to NIF. Pure Elixir implementation coming in bd-149.
    HashlineNif.strip_hashline_prefixes(text)
  end

  @doc """
  Validate that a stored hash anchor still matches the current line content.

  Returns `true` if `compute_line_hash(idx, line)` equals `expected_hash`.

  ## Examples

      iex> hash = HashLine.compute_line_hash(5, "some code")
      iex> HashLine.validate_hashline_anchor(5, "some code", hash)
      true

      iex> HashLine.validate_hashline_anchor(5, "different code", hash)
      false

  """
  @spec validate_hashline_anchor(non_neg_integer(), String.t(), String.t()) :: boolean()
  def validate_hashline_anchor(idx, line, expected_hash) do
    # STUB: Currently delegates to NIF. Pure Elixir implementation coming in bd-149.
    HashlineNif.validate_hashline_anchor(idx, line, expected_hash)
  end
end
