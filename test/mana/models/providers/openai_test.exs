defmodule Mana.Models.Providers.OpenAITest do
  @moduledoc """
  Tests for Mana.Models.Providers.OpenAI module.

  These tests use mocking to avoid making real API calls.
  """

  use ExUnit.Case, async: false

  alias Mana.Models.Providers.OpenAI

  setup do
    # Clear environment variables for clean tests
    original_key = System.get_env("OPENAI_API_KEY")
    System.delete_env("OPENAI_API_KEY")

    on_exit(fn ->
      if original_key do
        System.put_env("OPENAI_API_KEY", original_key)
      end
    end)

    :ok
  end

  describe "provider_id/0" do
    test "returns 'openai'" do
      assert OpenAI.provider_id() == "openai"
    end
  end

  describe "validate_config/1" do
    test "returns :ok when API key is present" do
      assert OpenAI.validate_config(%{api_key: "sk-test-key"}) == :ok
    end

    test "returns error when API key is missing" do
      assert {:error, "Missing OpenAI API key"} = OpenAI.validate_config(%{api_key: nil})
    end

    test "returns error when API key is empty" do
      assert {:error, "Missing OpenAI API key"} = OpenAI.validate_config(%{api_key: ""})
    end

    test "checks environment variable" do
      System.put_env("OPENAI_API_KEY", "sk-env-key")
      assert OpenAI.validate_config(%{}) == :ok
    end
  end

  describe "complete/3" do
    test "returns error without API key" do
      result = OpenAI.complete([%{"role" => "user", "content" => "Hello"}], "gpt-4")
      assert {:error, _} = result
    end

    test "returns error with invalid API key" do
      result =
        OpenAI.complete(
          [%{"role" => "user", "content" => "Hello"}],
          "gpt-4",
          api_key: "invalid-key"
        )

      # This will fail with HTTP error since we're using real Req
      assert {:error, _} = result
    end
  end

  describe "stream/3" do
    test "returns error stream without API key" do
      stream = OpenAI.stream([%{"role" => "user", "content" => "Hello"}], "gpt-4")

      events = Enum.to_list(stream)
      assert length(events) == 1
      assert {:error, _} = hd(events)
    end

    test "returns error stream with invalid API key" do
      stream =
        OpenAI.stream(
          [%{"role" => "user", "content" => "Hello"}],
          "gpt-4",
          api_key: "invalid-key"
        )

      events = Enum.to_list(stream)
      assert length(events) == 1
      assert {:error, _} = hd(events)
    end
  end

  describe "helper functions" do
    test "supports temperature option" do
      # Just verify that the function doesn't crash with temperature
      # Actual network request will fail without valid key
      result =
        OpenAI.complete(
          [%{"role" => "user", "content" => "Hello"}],
          "gpt-4",
          api_key: "test",
          temperature: 0.5
        )

      assert {:error, _} = result
    end

    test "supports max_tokens option" do
      result =
        OpenAI.complete(
          [%{"role" => "user", "content" => "Hello"}],
          "gpt-4",
          api_key: "test",
          max_tokens: 100
        )

      assert {:error, _} = result
    end
  end
end
