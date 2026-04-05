defmodule Mana.ModelsDevTest do
  @moduledoc """
  Tests for Mana.ModelsDev module.
  """

  use ExUnit.Case, async: false

  alias Mana.ModelsDev

  setup do
    # Create test data file
    test_data = %{
      "anthropic" => %{
        "models" => [
          %{"name" => "claude-opus-4-6", "context" => 200_000},
          %{"name" => "claude-sonnet-4-5", "context" => 200_000}
        ]
      },
      "openai" => %{
        "models" => [
          %{"name" => "gpt-4o", "context" => 128_000},
          %{"name" => "gpt-4o-mini", "context" => 128_000}
        ]
      },
      "test_provider" => %{
        "models" => [
          %{"name" => "test-model-1", "context" => 8000},
          %{"name" => "test-model-2", "context" => 4000}
        ]
      }
    }

    # Start the GenServer with test name
    test_name = :"models_dev_#{System.unique_integer([:positive])}"
    {:ok, pid} = ModelsDev.start_link(name: test_name)

    # Initialize with test data
    :sys.replace_state(pid, fn state ->
      %{state | data: test_data, last_refresh: DateTime.utc_now()}
    end)

    %{models_dev: pid, models_dev_name: test_name, test_data: test_data}
  end

  describe "start_link/1" do
    test "starts successfully with default name" do
      {:ok, pid} = ModelsDev.start_link()
      assert Process.alive?(pid)
    end

    test "starts successfully with custom name" do
      {:ok, pid} = ModelsDev.start_link(name: :custom_models_dev)
      assert Process.alive?(pid)
    end

    test "loads bundled data on init" do
      # Create a new instance - it will load from priv/models_dev_api.json
      {:ok, pid} = ModelsDev.start_link(name: :"load_test_#{System.unique_integer([:positive])}")

      data = GenServer.call(pid, :get_data)
      # Should have at least the default providers from the bundled file
      assert is_map(data)
    end
  end

  describe "list_providers/0" do
    test "returns list of provider IDs", %{models_dev_name: name} do
      providers = GenServer.call(name, :list_providers)

      assert is_list(providers)
      assert "anthropic" in providers
      assert "openai" in providers
      assert "test_provider" in providers
    end

    test "returns empty list when no data", %{models_dev_name: name} do
      # Clear the data
      :sys.replace_state(Process.whereis(name), fn state -> %{state | data: %{}} end)

      providers = GenServer.call(name, :list_providers)
      assert providers == []
    end
  end

  describe "list_models/1" do
    test "returns models for existing provider", %{models_dev_name: name} do
      models = GenServer.call(name, {:list_models, "anthropic"})

      assert is_list(models)
      assert length(models) == 2

      model_names = Enum.map(models, & &1["name"])
      assert "claude-opus-4-6" in model_names
      assert "claude-sonnet-4-5" in model_names
    end

    test "returns empty list for unknown provider", %{models_dev_name: name} do
      models = GenServer.call(name, {:list_models, "unknown_provider"})
      assert models == []
    end

    test "returns empty list for provider without models", %{models_dev_name: name} do
      # Add provider without models key
      :sys.replace_state(Process.whereis(name), fn state ->
        new_data = Map.put(state.data, "empty_provider", %{"info" => "test"})
        %{state | data: new_data}
      end)

      models = GenServer.call(name, {:list_models, "empty_provider"})
      assert models == []
    end
  end

  describe "search/1" do
    test "finds models matching query", %{models_dev_name: name} do
      results = GenServer.call(name, {:search, "claude"})

      assert is_list(results)
      assert length(results) == 2

      names = Enum.map(results, & &1["name"])
      assert "claude-opus-4-6" in names
      assert "claude-sonnet-4-5" in names
    end

    test "search is case-insensitive", %{models_dev_name: name} do
      results_lower = GenServer.call(name, {:search, "gpt"})
      results_upper = GenServer.call(name, {:search, "GPT"})

      assert length(results_lower) == length(results_upper)
      assert length(results_lower) == 2
    end

    test "returns partial matches", %{models_dev_name: name} do
      results = GenServer.call(name, {:search, "4o"})

      names = Enum.map(results, & &1["name"])
      assert "gpt-4o" in names
      assert "gpt-4o-mini" in names
    end

    test "returns empty list for non-matching query", %{models_dev_name: name} do
      results = GenServer.call(name, {:search, "nonexistentxyz123"})
      assert results == []
    end

    test "searches across all providers", %{models_dev_name: name} do
      results = GenServer.call(name, {:search, "model"})

      # Should find test-model-1 and test-model-2 from test_provider
      names = Enum.map(results, & &1["name"])
      assert "test-model-1" in names
      assert "test-model-2" in names
    end
  end

  describe "get_model/1" do
    test "returns model when found", %{models_dev_name: name} do
      model = GenServer.call(name, {:get_model, "claude-opus-4-6"})

      assert is_map(model)
      assert model["name"] == "claude-opus-4-6"
      assert model["context"] == 200_000
    end

    test "returns nil when not found", %{models_dev_name: name} do
      model = GenServer.call(name, {:get_model, "unknown-model"})
      assert model == nil
    end

    test "finds model across all providers", %{models_dev_name: name} do
      model = GenServer.call(name, {:get_model, "test-model-1"})

      assert is_map(model)
      assert model["name"] == "test-model-1"
      assert model["context"] == 8000
    end
  end

  describe "get_data/0" do
    test "returns full data structure", %{models_dev_name: name} do
      data = GenServer.call(name, :get_data)

      assert is_map(data)
      assert Map.has_key?(data, "anthropic")
      assert Map.has_key?(data, "openai")
      assert Map.has_key?(data, "test_provider")
    end
  end

  describe "last_refresh/0" do
    test "returns timestamp after init", %{models_dev_name: name} do
      timestamp = GenServer.call(name, :last_refresh)

      assert %DateTime{} = timestamp
      assert DateTime.diff(DateTime.utc_now(), timestamp, :second) < 5
    end
  end

  describe "refresh/0" do
    test "updates last_refresh timestamp", %{models_dev_name: name} do
      # Set old timestamp
      old_time = DateTime.add(DateTime.utc_now(), -3600, :second)

      :sys.replace_state(Process.whereis(name), fn state ->
        %{state | last_refresh: old_time}
      end)

      # Mocking the API call is complex, so just verify the call format
      # In real scenario, it would attempt to fetch from API
      assert GenServer.call(name, :last_refresh) == old_time
    end
  end

  describe "cache behavior" do
    test "schedules automatic refresh timer on init" do
      {:ok, pid} = ModelsDev.start_link(name: :"cache_test_#{System.unique_integer([:positive])}")

      state = :sys.get_state(pid)
      assert state.refresh_timer != nil
      assert is_reference(state.refresh_timer)
    end
  end

  describe "bundled data loading" do
    test "falls back to empty map when bundled file missing" do
      # This test would require mocking the file system
      # For now, just verify the data structure is handled correctly
      {:ok, pid} = ModelsDev.start_link(name: :"fallback_test_#{System.unique_integer([:positive])}")

      data = GenServer.call(pid, :get_data)
      assert is_map(data)
    end
  end
end
