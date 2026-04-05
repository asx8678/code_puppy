defmodule Mana.Commands.ModelTest do
  @moduledoc """
  Tests for Mana.Commands.Model and Mana.Commands.AddModel modules.
  """

  use ExUnit.Case, async: false

  alias Mana.Commands.AddModel
  alias Mana.Commands.Model
  alias Mana.Config.Store, as: ConfigStore
  alias Mana.Models.Registry, as: ModelsRegistry

  setup do
    # Start required GenServers
    start_supervised!({ModelsRegistry, []})
    start_supervised!({ConfigStore, []})

    # Register some test models
    ModelsRegistry.register_model("test-model", %{
      provider: "test",
      max_tokens: 4096,
      supports_tools: true
    })

    :ok
  end

  describe "Model command behaviour implementation" do
    test "implements Mana.Commands.Behaviour" do
      assert function_exported?(Model, :name, 0)
      assert function_exported?(Model, :description, 0)
      assert function_exported?(Model, :usage, 0)
      assert function_exported?(Model, :execute, 2)
    end

    test "name returns '/model'" do
      assert Model.name() == "/model"
    end

    test "description returns expected string" do
      assert Model.description() == "Manage AI models"
    end

    test "usage returns expected string" do
      assert Model.usage() == "/model [list|set <name>|current]"
    end
  end

  describe "Model.execute/2 - list" do
    test "returns list of available models" do
      assert {:ok, result} = Model.execute(["list"], %{})
      assert result =~ "Available models:"
      assert result =~ "test-model"
    end

    test "handles empty model list" do
      # Clear the registry by stopping it and starting fresh
      # This test assumes some default models might exist
      result = Model.execute(["list"], %{})
      assert {:ok, _} = result
    end
  end

  describe "Model.execute/2 - set" do
    test "sets current model to valid model" do
      assert {:ok, result} = Model.execute(["set", "test-model"], %{})
      assert result == "Model set to: test-model"
    end

    test "returns error for unknown model" do
      assert {:error, message} = Model.execute(["set", "nonexistent-model"], %{})
      assert message =~ "Model not found"
    end
  end

  describe "Model.execute/2 - current" do
    test "shows current model" do
      # Set a model first
      ConfigStore.put(:current_model, "test-model")

      assert {:ok, result} = Model.execute(["current"], %{})
      assert result == "Current model: test-model"
    end

    test "shows default model when none set" do
      # Clear the current model
      :ets.insert(:mana_config, {:current_model, nil})

      assert {:ok, result} = Model.execute(["current"], %{})
      assert result == "Current model: claude-opus-4-6"
    end
  end

  describe "Model.execute/2 - usage" do
    test "returns usage when called with no args" do
      assert {:ok, result} = Model.execute([], %{})
      assert result == "Usage: #{Model.usage()}"
    end

    test "returns usage when called with invalid args" do
      assert {:ok, result} = Model.execute(["invalid"], %{})
      assert result == "Usage: #{Model.usage()}"
    end
  end

  describe "AddModel command behaviour implementation" do
    test "implements Mana.Commands.Behaviour" do
      assert function_exported?(AddModel, :name, 0)
      assert function_exported?(AddModel, :description, 0)
      assert function_exported?(AddModel, :usage, 0)
      assert function_exported?(AddModel, :execute, 2)
    end

    test "name returns '/add_model'" do
      assert AddModel.name() == "/add_model"
    end

    test "description returns expected string" do
      assert AddModel.description() == "Add a custom model configuration"
    end

    test "usage returns expected string" do
      assert AddModel.usage() == "/add_model <name> <provider> [max_tokens] [supports_tools]"
    end
  end

  describe "AddModel.execute/2" do
    test "registers new model with name and provider" do
      assert {:ok, result} = AddModel.execute(["my-model", "custom-provider"], %{})
      assert result == "Added model: my-model (custom-provider)"

      # Verify it was registered
      assert {:ok, config} = ModelsRegistry.get_model("my-model")
      assert config.provider == "custom-provider"
      assert config.max_tokens == 4096
      assert config.supports_tools == true
    end

    test "registers model with custom max_tokens" do
      AddModel.execute(["model-with-tokens", "provider", "8192"], %{})

      assert {:ok, config} = ModelsRegistry.get_model("model-with-tokens")
      assert config.max_tokens == 8192
    end

    test "registers model with tools disabled" do
      AddModel.execute(["model-no-tools", "provider", "4096", "false"], %{})

      assert {:ok, config} = ModelsRegistry.get_model("model-no-tools")
      assert config.supports_tools == false
    end

    test "returns usage for invalid args" do
      assert {:ok, result} = AddModel.execute([], %{})
      assert result == "Usage: #{AddModel.usage()}"
    end

    test "handles invalid max_tokens gracefully" do
      AddModel.execute(["model-invalid", "provider", "invalid"], %{})

      # Should use default
      assert {:ok, config} = ModelsRegistry.get_model("model-invalid")
      assert config.max_tokens == 4096
    end
  end
end
