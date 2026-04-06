defmodule Mana.Prompt.EnvironmentTest do
  use ExUnit.Case, async: true

  alias Mana.Prompt.Environment

  describe "block/0" do
    test "returns environment block with platform info" do
      block = Environment.block()

      assert block =~ "## Environment"
      assert block =~ "Platform:"
      assert block =~ "Elixir:"
      assert block =~ "OTP:"
    end

    test "includes actual Elixir version" do
      block = Environment.block()
      elixir_version = System.version()

      assert block =~ "Elixir: #{elixir_version}"
    end

    test "includes architecture information" do
      block = Environment.block()

      assert block =~ "Platform:"
      # Should have some architecture string
      assert String.length(block) > 50
    end
  end

  describe "metadata_block/1" do
    test "returns metadata with current date" do
      meta = Environment.metadata_block()

      today = Date.utc_today() |> Date.to_iso8601()

      assert meta =~ "Current date: #{today}"
    end

    test "returns metadata with working directory" do
      meta = Environment.metadata_block()
      cwd = File.cwd!()

      assert meta =~ "Working directory: #{cwd}"
    end

    test "accepts custom working directory" do
      meta = Environment.metadata_block(cwd: "/custom/path")

      assert meta =~ "Working directory: /custom/path"
    end

    test "accepts custom date" do
      custom_date = ~D[2024-01-15]
      meta = Environment.metadata_block(date: custom_date)

      assert meta =~ "Current date: 2024-01-15"
    end

    test "format is consistent" do
      meta = Environment.metadata_block(cwd: "/test", date: ~D[2024-06-01])

      expected = """
      - Current date: 2024-06-01
      - Working directory: /test
      """

      assert meta == expected
    end
  end
end
