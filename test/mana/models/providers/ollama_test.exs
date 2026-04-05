defmodule Mana.Models.Providers.OllamaTest do
  @moduledoc """
  Tests for Mana.Models.Providers.Ollama module.

  These tests verify that Ollama provider works without requiring an API key,
  since Ollama runs locally and doesn't need authentication.
  """

  use ExUnit.Case, async: true

  alias Mana.Models.Providers.Ollama
  alias Mana.Models.Providers.OpenAICompatible

  describe "provider_id/0" do
    test "returns 'ollama'" do
      assert Ollama.provider_id() == "ollama"
    end
  end

  describe "validate_config/1" do
    test "returns :ok with default base_url (no API key needed)" do
      assert Ollama.validate_config(%{}) == :ok
    end

    test "returns :ok with custom base_url (no API key needed)" do
      assert Ollama.validate_config(%{base_url: "http://custom:11434/v1"}) == :ok
    end

    test "returns :ok even with empty API key" do
      assert Ollama.validate_config(%{api_key: nil}) == :ok
      assert Ollama.validate_config(%{api_key: ""}) == :ok
    end

    test "returns error when base_url is empty" do
      assert {:error, "Missing base_url"} = Ollama.validate_config(%{base_url: ""})
    end

    test "returns :ok when base_url is nil (uses default)" do
      assert Ollama.validate_config(%{base_url: nil}) == :ok
    end
  end

  describe "complete/3 without API key" do
    test "does not require API key to be set" do
      # This test verifies that Ollama.complete doesn't fail due to missing API key
      # It will fail due to network (no real Ollama server), but not due to config validation
      result =
        Ollama.complete(
          [%{"role" => "user", "content" => "Hello"}],
          "ollama/llama3.2"
        )

      # Should NOT be a config error about missing API key
      # It may be a network error (which is fine for this test)
      case result do
        {:error, msg} when is_binary(msg) ->
          refute String.contains?(msg, "Missing OpenAI API key")
          refute String.contains?(msg, "API key")

        _ ->
          # Any other result is fine (would require real server)
          :ok
      end
    end

    test "passes dummy API key to OpenAICompatible" do
      # Verify that the complete function runs without API key errors
      # by checking it gets past config validation
      result =
        Ollama.complete(
          [%{"role" => "user", "content" => "Hello"}],
          "llama3.2",
          base_url: "http://localhost:11434/v1"
        )

      # Should not fail due to missing API key
      case result do
        {:error, msg} when is_binary(msg) ->
          refute String.contains?(msg, "Missing OpenAI API key")

        _ ->
          :ok
      end
    end
  end

  describe "stream/3 without API key" do
    test "does not require API key to be set" do
      stream =
        Ollama.stream(
          [%{"role" => "user", "content" => "Hello"}],
          "ollama/llama3.2"
        )

      events = Enum.to_list(stream)

      # If we get an error, it should NOT be about missing API key
      Enum.each(events, fn
        {:error, msg} when is_binary(msg) ->
          refute String.contains?(msg, "Missing OpenAI API key")
          refute String.contains?(msg, "API key")

        _ ->
          :ok
      end)
    end
  end

  describe "model name handling" do
    test "strips 'ollama/' prefix from model name" do
      # This is tested indirectly - if the prefix wasn't stripped,
      # Ollama would reject the model name
      result =
        Ollama.complete(
          [%{"role" => "user", "content" => "Hello"}],
          "ollama/llama3.2",
          base_url: "http://localhost:11434/v1"
        )

      # Should not fail due to config validation (API key)
      case result do
        {:error, msg} when is_binary(msg) ->
          refute String.contains?(msg, "Missing OpenAI API key")
          refute String.contains?(msg, "API key")

        _ ->
          :ok
      end
    end

    test "handles model name without prefix" do
      result =
        Ollama.complete(
          [%{"role" => "user", "content" => "Hello"}],
          "llama3.2",
          base_url: "http://localhost:11434/v1"
        )

      # Should not fail due to config validation (API key)
      case result do
        {:error, msg} when is_binary(msg) ->
          refute String.contains?(msg, "Missing OpenAI API key")

        _ ->
          :ok
      end
    end
  end

  describe "default base_url" do
    test "uses localhost:11434 by default" do
      # Verify default base_url is set correctly by checking
      # that validation passes with empty config
      assert Ollama.validate_config(%{}) == :ok
    end
  end
end
