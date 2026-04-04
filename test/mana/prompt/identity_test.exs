defmodule Mana.Prompt.IdentityTest do
  use ExUnit.Case, async: true

  alias Mana.Prompt.Identity

  describe "block/0" do
    test "returns identity block" do
      block = Identity.block()

      assert block =~ "## Identity"
      assert block =~ "Mana"
    end

    test "describes Mana capabilities" do
      block = Identity.block()

      assert block =~ "AI assistant"
      assert block =~ "Elixir/OTP"
      assert block =~ "file operations"
      assert block =~ "shell commands"
    end

    test "format is consistent" do
      block = Identity.block()

      expected = """
      ## Identity
      You are Mana, an AI assistant powered by an Elixir/OTP agent orchestration system.
      You have access to file operations, shell commands, and various tools.
      """

      assert block == expected
    end
  end
end
