defmodule CodePuppyControl.LLM.ProviderTest do
  @moduledoc """
  Tests for Provider behaviour compliance.

  Verifies that OpenAI and Anthropic providers implement all required callbacks
  and conform to the expected interface.
  """
  use ExUnit.Case, async: true

  alias CodePuppyControl.LLM.Provider
  alias CodePuppyControl.LLM.Providers.{OpenAI, Anthropic}

  describe "behaviour callbacks" do
    test "OpenAI implements all Provider callbacks" do
      assert {:module, OpenAI} = Code.ensure_loaded(OpenAI)
      assert function_exported?(OpenAI, :chat, 3)
      assert function_exported?(OpenAI, :stream_chat, 4)
      assert function_exported?(OpenAI, :supports_tools?, 0)
      assert function_exported?(OpenAI, :supports_vision?, 0)
    end

    test "Anthropic implements all Provider callbacks" do
      assert {:module, Anthropic} = Code.ensure_loaded(Anthropic)
      assert function_exported?(Anthropic, :chat, 3)
      assert function_exported?(Anthropic, :stream_chat, 4)
      assert function_exported?(Anthropic, :supports_tools?, 0)
      assert function_exported?(Anthropic, :supports_vision?, 0)
    end

    test "both providers declare @behaviour Provider" do
      # Check that the modules have the behaviour attribute
      openai_behaviours =
        OpenAI.__info__(:attributes)
        |> Keyword.get_values(:behaviour)
        |> List.flatten()

      assert Provider in openai_behaviours

      anthropic_behaviours =
        Anthropic.__info__(:attributes)
        |> Keyword.get_values(:behaviour)
        |> List.flatten()

      assert Provider in anthropic_behaviours
    end
  end

  describe "supports_tools?/0" do
    test "OpenAI supports tools" do
      assert OpenAI.supports_tools?() == true
    end

    test "Anthropic supports tools" do
      assert Anthropic.supports_tools?() == true
    end
  end

  describe "supports_vision?/0" do
    test "OpenAI supports vision" do
      assert OpenAI.supports_vision?() == true
    end

    test "Anthropic supports vision" do
      assert Anthropic.supports_vision?() == true
    end
  end

  describe "type specs" do
    test "Provider.message type exists" do
      # Verify the types are defined by checking the module doc
      {:docs_v1, _, _, _, _, _, _} = Code.fetch_docs(Provider)
    end
  end
end
