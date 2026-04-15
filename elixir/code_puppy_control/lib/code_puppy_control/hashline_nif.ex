defmodule CodePuppyControl.HashlineNif do
  @moduledoc """
  NIF bindings to hashline Rust crate.

  Provides per-line content hashing for file edit anchoring.
  Each line gets a 2-character anchor encoded via NIBBLE_STR
  (ZPMQVRWSNKTXJBYH) so the LLM can reference lines precisely.

  Compatible with oh-my-pi's hashline format and the Python/Rust
  reference implementations in code_puppy_core.

  ## Algorithm

  xxHash32 -> lowest byte -> NIBBLE_STR encoding -> 2 uppercase chars

  ## Format

  `format_hashlines/2` produces lines like: `1#AB:original content`

  Where `1` is the line number, `AB` is the 2-char hash anchor,
  and everything after the colon is the original line content.
  """

  use Rustler,
    otp_app: :code_puppy_control,
    crate: "hashline_nif"

  # NIF stubs - these are replaced by the Rust implementations at load time

  @doc """
  Compute a 2-character hash anchor for a single line.

  Strips trailing whitespace, uses xxHash32 with idx as seed for
  whitespace-only lines, encodes lowest byte via NIBBLE_STR.
  """
  @spec compute_line_hash(non_neg_integer(), String.t()) :: String.t()
  def compute_line_hash(_idx, _line), do: :erlang.nif_error(:nif_not_loaded)

  @doc """
  Format text with hashline prefixes.

  Each line becomes `LINE_NUM#HASH:original_line`.
  `start_line` is 1-based by convention.
  """
  @spec format_hashlines(String.t(), non_neg_integer()) :: String.t()
  def format_hashlines(_text, _start_line), do: :erlang.nif_error(:nif_not_loaded)

  @doc """
  Strip hashline prefixes from text, returning plain content.

  Lines matching the pattern `^\\d+#[A-Z]{2}:` have the prefix removed.
  Other lines pass through unchanged.
  """
  @spec strip_hashline_prefixes(String.t()) :: String.t()
  def strip_hashline_prefixes(_text), do: :erlang.nif_error(:nif_not_loaded)

  @doc """
  Validate that a stored hash anchor still matches the current line content.

  Returns `true` if `compute_line_hash(idx, line)` equals `expected_hash`.
  """
  @spec validate_hashline_anchor(non_neg_integer(), String.t(), String.t()) :: boolean()
  def validate_hashline_anchor(_idx, _line, _expected_hash),
    do: :erlang.nif_error(:nif_not_loaded)
end
