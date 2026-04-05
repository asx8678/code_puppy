defmodule Mana.Plugins.OllamaSetupTest do
  use ExUnit.Case

  alias Mana.Plugins.OllamaSetup

  describe "behaviour compliance" do
    test "implements Mana.Plugin.Behaviour" do
      behaviours = OllamaSetup.__info__(:attributes)[:behaviour] || []
      assert Mana.Plugin.Behaviour in behaviours
    end

    test "has required callbacks" do
      assert function_exported?(OllamaSetup, :name, 0)
      assert function_exported?(OllamaSetup, :init, 1)
      assert function_exported?(OllamaSetup, :hooks, 0)
      assert function_exported?(OllamaSetup, :terminate, 0)
    end
  end

  describe "name/0" do
    test "returns correct plugin name" do
      assert OllamaSetup.name() == "ollama_setup"
    end
  end

  describe "init/1" do
    test "initializes with default config" do
      assert {:ok, state} = OllamaSetup.init(%{})
      assert state.host == "http://localhost:11434"
      assert state.auto_register == true
    end

    test "initializes with custom host" do
      assert {:ok, state} = OllamaSetup.init(%{ollama_host: "http://ollama.local:11434"})
      assert state.host == "http://ollama.local:11434"
    end

    test "initializes with auto_register disabled" do
      assert {:ok, state} = OllamaSetup.init(%{auto_register: false})
      assert state.auto_register == false
    end
  end

  describe "hooks/0" do
    test "returns expected hooks" do
      hooks = OllamaSetup.hooks()
      hook_names = Enum.map(hooks, fn {name, _func} -> name end)
      assert :startup in hook_names
      assert :custom_command in hook_names
      assert :custom_command_help in hook_names
    end
  end

  describe "command_help/0" do
    test "returns help entries" do
      entries = OllamaSetup.command_help()
      assert is_list(entries)
      assert length(entries) >= 1

      names = Enum.map(entries, fn {name, _desc} -> name end)
      assert "ollama-setup" in names
    end
  end

  describe "handle_command/2" do
    test "returns nil for unknown commands" do
      assert nil == OllamaSetup.handle_command("/foo", "foo")
    end

    test "handles /ollama-setup command" do
      result = OllamaSetup.handle_command("/ollama-setup", "ollama-setup")
      assert {:ok, _text} = result
    end

    test "handles /ollama-setup list (no args)" do
      {:ok, text} = OllamaSetup.handle_command("/ollama-setup", "ollama-setup")
      assert is_binary(text)
    end
  end

  describe "on_startup/0" do
    test "returns :ok even when Ollama not available" do
      assert :ok == OllamaSetup.on_startup()
    end
  end

  describe "fetch_ollama_models/0" do
    test "returns error when Ollama is not running" do
      # In test environment Ollama is likely not running
      result = OllamaSetup.fetch_ollama_models()
      # Either :not_available or an error
      assert match?({:error, _}, result)
    end
  end

  describe "terminate/0" do
    test "returns :ok" do
      assert OllamaSetup.terminate() == :ok
    end
  end
end
