defmodule Mana.RepoCompassTest do
  use ExUnit.Case, async: false

  alias Mana.Callbacks.Registry
  alias Mana.Config.Store
  alias Mana.RepoCompass

  setup do
    # Start a fresh registry and config store for each test
    start_supervised!({Registry, max_backlog_size: 10, backlog_ttl: 1_000})
    start_supervised!(Store)

    # Create a temporary project directory
    temp_dir = System.tmp_dir!()
    test_project = Path.join(temp_dir, "test_project_#{:erlang.unique_integer([:positive])}")

    File.mkdir_p!(test_project)
    File.mkdir_p!(Path.join(test_project, "lib"))

    # Create a simple Elixir file
    elixir_content = """
    defmodule TestProject.Main do
      def start do
        :ok
      end
    end
    """

    File.write!(Path.join([test_project, "lib", "main.ex"]), elixir_content)

    on_exit(fn ->
      File.rm_rf!(test_project)
    end)

    {:ok, project_dir: test_project}
  end

  describe "behaviour compliance" do
    test "implements Mana.Plugin.Behaviour" do
      behaviours = RepoCompass.__info__(:attributes)[:behaviour] || []
      assert Mana.Plugin.Behaviour in behaviours
    end

    test "has required callbacks" do
      assert function_exported?(RepoCompass, :name, 0)
      assert function_exported?(RepoCompass, :init, 1)
      assert function_exported?(RepoCompass, :hooks, 0)
      assert function_exported?(RepoCompass, :terminate, 0)
    end
  end

  describe "name/0" do
    test "returns correct plugin name" do
      assert RepoCompass.name() == "repo_compass"
    end
  end

  describe "init/1" do
    test "initializes with config" do
      assert {:ok, state} = RepoCompass.init(%{})
      assert is_map(state)
      assert Map.has_key?(state, :enabled)
    end
  end

  describe "hooks/0" do
    test "returns expected hooks" do
      hooks = RepoCompass.hooks()
      assert is_list(hooks)

      hook_names = Enum.map(hooks, fn {name, _func} -> name end)
      assert :get_model_system_prompt in hook_names
    end
  end

  describe "on_get_model_system_prompt/2" do
    test "returns compass prompt when enabled", %{project_dir: project_dir} do
      # Set config
      Mana.Config.put(:repo_compass, %{enabled: true, max_files: 10, max_symbols_per_file: 5})
      Mana.Config.put(:project_dir, project_dir)

      result = RepoCompass.on_get_model_system_prompt("test-model", "default prompt")

      assert result != nil
      assert is_map(result)
      assert Map.has_key?(result, :prompt)

      prompt = result.prompt
      assert prompt =~ "## Repo Compass"
      assert prompt =~ Path.basename(project_dir)
      assert prompt =~ "lib/main.ex"
    end

    test "returns nil when disabled", %{project_dir: project_dir} do
      Mana.Config.put(:repo_compass, %{enabled: false})
      Mana.Config.put(:project_dir, project_dir)

      result = RepoCompass.on_get_model_system_prompt("test-model", "default prompt")

      assert result == nil
    end

    test "returns nil when no repo_compass config exists", %{project_dir: project_dir} do
      # Clear any existing config
      Mana.Config.put(:repo_compass, nil)
      Mana.Config.put(:project_dir, project_dir)

      # Should default to enabled
      result = RepoCompass.on_get_model_system_prompt("test-model", "default prompt")

      assert result != nil
      assert is_map(result)
      assert Map.has_key?(result, :prompt)
    end
  end

  describe "terminate/0" do
    test "returns :ok" do
      assert RepoCompass.terminate() == :ok
    end
  end
end
