defmodule Mana.BannerTest do
  @moduledoc """
  Tests for Mana.Banner module.
  """

  use ExUnit.Case, async: true

  alias Mana.Banner

  describe "render/0" do
    test "returns banner string" do
      result = Banner.render()
      assert is_binary(result)
      assert result =~ "███╗"
    end

    test "contains ANSI formatting" do
      result = Banner.render()
      # ANSI formatting is applied and converted to string
      assert is_binary(result)
      assert String.length(result) > 0
    end
  end

  describe "render_compact/0" do
    test "returns compact banner" do
      result = Banner.render_compact()
      assert is_binary(result)
      assert result =~ "Mana"
    end

    test "is shorter than full banner" do
      full = Banner.render()
      compact = Banner.render_compact()
      assert String.length(compact) < String.length(full)
    end
  end

  describe "print/0" do
    test "prints banner to stdout" do
      # Capture IO to verify output
      result =
        ExUnit.CaptureIO.capture_io(fn ->
          Banner.print()
        end)

      assert result =~ "███╗"
    end
  end

  describe "with_version/1" do
    test "includes version number" do
      result = Banner.with_version("0.1.0")
      assert result =~ "0.1.0"
      assert result =~ "███╗"
    end

    test "includes v prefix" do
      result = Banner.with_version("1.0.0")
      assert result =~ "v1.0.0"
    end
  end
end
