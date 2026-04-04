defmodule Mana.Prompt.ModelTransformTest do
  use ExUnit.Case, async: false

  alias Mana.Callbacks.Registry
  alias Mana.Prompt.ModelTransform

  setup do
    # Start a fresh registry for each test
    start_supervised!({Registry, max_backlog_size: 10, backlog_ttl: 1_000})

    :ok
  end

  describe "apply/2" do
    test "joins layers with double newlines" do
      layers = ["Layer 1", "Layer 2"]

      result = ModelTransform.apply(layers, "generic-model")

      assert result == ["Layer 1\n\nLayer 2"]
    end

    test "handles single layer" do
      layers = ["Single layer"]

      result = ModelTransform.apply(layers, "generic-model")

      assert result == ["Single layer"]
    end

    test "claude models receive direct prompt without wrapping" do
      layers = ["Test content"]

      result = ModelTransform.apply(layers, "claude-3-opus")

      assert result == ["Test content"]
      refute result |> hd() =~ "<antigravity>"
    end

    test "claude models are case-insensitive" do
      layers = ["Test content"]

      result_claude = ModelTransform.apply(layers, "CLAUDE-3")
      result_mixed = ModelTransform.apply(layers, "Claude-3-Haiku")

      assert result_claude == ["Test content"]
      assert result_mixed == ["Test content"]
    end

    test "antigravity models receive XML envelope" do
      layers = ["Test content"]

      result = ModelTransform.apply(layers, "antigravity-model")

      assert result |> hd() =~ "<antigravity>"
      assert result |> hd() =~ "</antigravity>"
      assert result |> hd() =~ "Test content"
    end

    test "antigravity models are case-insensitive" do
      layers = ["Test content"]

      result_upper = ModelTransform.apply(layers, "ANTIGRAVITY")
      result_mixed = ModelTransform.apply(layers, "AntiGravity-Pro")

      assert result_upper |> hd() =~ "<antigravity>"
      assert result_mixed |> hd() =~ "<antigravity>"
    end

    test "unknown models receive direct prompt" do
      layers = ["Test content"]

      result = ModelTransform.apply(layers, "unknown-model-v1")

      assert result == ["Test content"]
    end

    test "uses get_model_system_prompt callback when available" do
      callback = fn _model_name, _prompt ->
        %{prompt: "Custom transformed prompt."}
      end

      :ok = Mana.Callbacks.register(:get_model_system_prompt, callback)

      try do
        layers = ["Original content"]
        result = ModelTransform.apply(layers, "custom-model")

        # Should use callback result instead of default
        assert result == ["Custom transformed prompt."]
      after
        Mana.Callbacks.unregister(:get_model_system_prompt, callback)
      end
    end

    test "falls back to default transform when callback returns non-map" do
      callback = fn _model_name, _prompt ->
        "not a map"
      end

      :ok = Mana.Callbacks.register(:get_model_system_prompt, callback)

      try do
        layers = ["Test content"]
        result = ModelTransform.apply(layers, "claude-3")

        # Should fall back to default (claude = no wrapping)
        assert result == ["Test content"]
      after
        Mana.Callbacks.unregister(:get_model_system_prompt, callback)
      end
    end

    test "falls back when callback returns map without prompt key" do
      callback = fn _model_name, _prompt ->
        %{other_key: "value"}
      end

      :ok = Mana.Callbacks.register(:get_model_system_prompt, callback)

      try do
        layers = ["Test content"]
        result = ModelTransform.apply(layers, "claude-3")

        assert result == ["Test content"]
      after
        Mana.Callbacks.unregister(:get_model_system_prompt, callback)
      end
    end

    test "handles multiple callbacks, using first valid one" do
      callback1 = fn _model_name, _prompt ->
        nil
      end

      callback2 = fn _model_name, _prompt ->
        %{prompt: "From second callback."}
      end

      :ok = Mana.Callbacks.register(:get_model_system_prompt, callback1)
      :ok = Mana.Callbacks.register(:get_model_system_prompt, callback2)

      try do
        layers = ["Test content"]
        result = ModelTransform.apply(layers, "any-model")

        assert result == ["From second callback."]
      after
        Mana.Callbacks.unregister(:get_model_system_prompt, callback1)
        Mana.Callbacks.unregister(:get_model_system_prompt, callback2)
      end
    end
  end
end
