# Test fixture: binary_pattern_matching.ex
# Purpose: Test binary pattern matching - KNOWN GAP
#
# Binary pattern matching with <<>> syntax and bitstring modifiers
# may not be fully supported by tree-sitter-elixir.
# 
# Expected symbols: 1 module (BinaryPatternMatching), functions demonstrating binary matching

defmodule BinaryPatternMatching do
  @moduledoc """
  Module demonstrating binary pattern matching.
#<<...>> syntax and bitstring modifiers may have parsing gaps.
  """

  # Basic binary matching (BASIC - should work)
  def basic_binary_match(<<a, b, c>>) do
    {a, b, c}
  end

  # Binary with size specification (MODERATE - may work)
  def sized_binary_match(<<value::size(16)>>) do
    value
  end

  # Binary with bit size (MODERATE - may work)
  def bit_size_match(<<flags::size(4), data::size(4)>>) do
    {flags, data}
  end

  # Binary with byte size (MODERATE - may work)
  def byte_size_match(<<header::bytes-size(2), body::binary>>) do
    {header, body}
  end

  # Rest binary matching (MODERATE - may work)
  def rest_binary_match(<<prefix::size(8), rest::binary>>) do
    {prefix, rest}
  end

  # Integer specification (POTENTIAL GAP)
  def integer_spec(<<count::integer-size(32)>>) do
    count
  end

  # Signed/unsigned specification (POTENTIAL GAP)
  def signed_unsigned(<<signed::integer-signed-size(16), unsigned::integer-unsigned-size(16)>>) do
    {signed, unsigned}
  end

  # Little/big endian (POTENTIAL GAP)
  def endian_spec(<<little::integer-little-size(32), big::integer-big-size(32)>>) do
    {little, big}
  end

  # Float specification (POTENTIAL GAP)
  def float_spec(<<value::float-size(64)>>) do
    value
  end

  # UTF-8 binary (POTENTIAL GAP)
  def utf8_binary(<<string::utf8>>) do
    string
  end

  # Binary comprehension (KNOWN GAP)
  def binary_comprehension do
    for <<byte <- <<1, 2, 3, 4>>>>, into: <<>>, do: <<byte * 2>>
  end

  # Building binaries (MODERATE)
  def build_binary do
    <<1, 2, 3>>
  end

  # Building with variables (MODERATE)
  def build_with_vars(a, b) do
    <<a, b, a + b>>
  end

  # String interpolation with binary (POTENTIAL GAP)
  def string_binary_mix do
    <<"prefix", middle::binary, "suffix">>
  end

  # Network packet parsing example (COMPLEX - likely gap)
  def parse_packet(<<version::size(4), ihl::size(4), tos::size(8), 
                     total_length::size(16), id::size(16), 
                     flags::size(3), frag_offset::size(13),
                     ttl::size(8), protocol::size(8), checksum::size(16),
                     src_ip::size(32), dst_ip::size(32),
                     options_and_data::binary>>) do
    %{version: version, src: src_ip, dst: dst_ip, data: options_and_data}
  end
end
