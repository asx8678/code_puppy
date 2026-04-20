defmodule CodePuppyControl.Config.RoundTripPropertyTest do
  @moduledoc """
  Property-based round-trip tests for config serialization (bd-184).

  Uses StreamData to verify that Loader and canonical_json are stable
  under re-serialization. These complement the golden-file tests by
  exploring a wider input space.

  **How to run:**
      mix test --only config_compat
      # or specifically:
      mix test --only property
  """

  use ExUnit.Case, async: false
  use ExUnitProperties

  @moduletag :config_compat
  @moduletag :property

  alias CodePuppyControl.Support.ConfigFixtures
  alias CodePuppyControl.Config.Loader

  # ── Local INI Serializer ─────────────────────────────────────────────────
  # Writer's INI serializer is private (encapsulated in the GenServer), so we
  # provide a deterministic equivalent here for property testing. This mirrors
  # the Writer's output format: sorted sections, sorted keys within sections.

  defp serialize_ini(config) do
    config
    |> Enum.sort_by(fn {section, _} -> section end)
    |> Enum.map_join("\n\n", fn {section, kvs} ->
      header = "[#{section}]"

      lines =
        kvs
        |> Enum.sort_by(&elem(&1, 0))
        |> Enum.map_join("\n", fn {k, v} -> "#{k} = #{v}" end)

      header <> "\n" <> lines
    end)
  end

  # ── Shared Generator ─────────────────────────────────────────────────────

  map_of_scalars =
    StreamData.map_of(
      StreamData.string(:ascii, min_length: 1, max_length: 8),
      StreamData.one_of([
        StreamData.string(:ascii),
        StreamData.integer(),
        StreamData.boolean(),
        StreamData.constant(nil)
      ]),
      max_length: 6
    )

  # ===========================================================================
  # INI Round-Trip
  # ===========================================================================

  describe "INI round-trip stability" do
    property "parse(serialize(parse(fixture))) == parse(fixture)" do
      # Pick one of the two real INI fixtures at random
      check all variant <- StreamData.member_of([:minimal, :realistic]),
                max_runs: 20 do
        raw = ConfigFixtures.read_raw(variant, "puppy.cfg")
        parsed = Loader.parse_string(raw)
        reserialized = serialize_ini(parsed)
        reparsed = Loader.parse_string(reserialized)

        assert ConfigFixtures.normalize(reparsed) == ConfigFixtures.normalize(parsed),
               "INI round-trip diverged for #{variant} fixture"
      end
    end
  end

  # ===========================================================================
  # JSON Canonical Serialization
  # ===========================================================================

  describe "canonical_json idempotency" do
    property "canonical_json is idempotent" do
      check all m <- ^map_of_scalars, max_runs: 50 do
        once = ConfigFixtures.canonical_json(m)
        twice = ConfigFixtures.canonical_json(Jason.decode!(once))
        assert once == twice
      end
    end
  end

  # ===========================================================================
  # Normalize Idempotency
  # ===========================================================================

  describe "normalize idempotency" do
    property "normalize is idempotent" do
      check all m <- ^map_of_scalars, max_runs: 50 do
        once = ConfigFixtures.normalize(m)
        twice = m |> ConfigFixtures.normalize() |> ConfigFixtures.normalize()
        assert once == twice
      end
    end
  end
end
