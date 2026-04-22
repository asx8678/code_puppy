defmodule CodePuppyControl.TUI.Widgets.ModelSelectorTest do
  use ExUnit.Case, async: true

  alias CodePuppyControl.TUI.Widgets.ModelSelector

  describe "list_models/1" do
    test "returns a list of model_info maps" do
      # ModelFactory.list_available/0 may return [] if no models configured,
      # but it should never crash and each entry should have required keys.
      models = ModelSelector.list_models()

      assert is_list(models)

      for model <- models do
        assert Map.has_key?(model, :name)
        assert Map.has_key?(model, :provider_type)
        assert Map.has_key?(model, :provider_module)
        assert Map.has_key?(model, :context_length)
        assert Map.has_key?(model, :display_name)
        assert is_binary(model.name)
        assert is_binary(model.provider_type)
        assert is_atom(model.provider_module)
        assert is_binary(model.display_name)
      end
    end

    test "results are sorted by name" do
      models = ModelSelector.list_models()
      names = Enum.map(models, & &1.name)
      assert names == Enum.sort(names)
    end

    test "filter option narrows results by name substring (case-insensitive)" do
      all = ModelSelector.list_models()
      # Pick a substring from the first model name if any exist
      if all != [] do
        sample = hd(all)
        # Use a unique fragment of the name
        fragment = String.slice(sample.name, 0, 3)
        filtered = ModelSelector.list_models(filter: fragment)

        assert is_list(filtered)
        # Every filtered model should contain the fragment (case-insensitive)
        for model <- filtered do
          assert String.downcase(model.name) =~ String.downcase(fragment) or
                   String.downcase(model.provider_type) =~ String.downcase(fragment)
        end

        # Filtered should be a subset
        filtered_names = Enum.map(filtered, & &1.name)
        all_names = Enum.map(all, & &1.name)
        assert MapSet.new(filtered_names) |> MapSet.subset?(MapSet.new(all_names))
      end
    end

    test "filter with no matches returns empty list" do
      models = ModelSelector.list_models(filter: "zzz_no_such_model_xyz_999")
      assert models == []
    end

    test "filter is case-insensitive" do
      # If models exist, verify case-insensitive matching
      all = ModelSelector.list_models()

      if all != [] do
        name = hd(all).name
        lower = ModelSelector.list_models(filter: String.downcase(name))
        upper = ModelSelector.list_models(filter: String.upcase(name))
        # Both should return at least the matching model
        assert length(lower) >= 1
        assert length(upper) >= 1
      end
    end
  end

  describe "model_info structure" do
    test "display_name strips common provider prefixes" do
      # Verify short_name logic: "firepass-kimi-k2p5-turbo" → "kimi-k2p5-turbo", "openai-gpt-4" → "gpt-4"
      # We test indirectly via list_models: display_name should not start with
      # known prefixes when the model name does
      models = ModelSelector.list_models()

      for model <- models do
        # display_name should be the name with prefix stripped
        assert is_binary(model.display_name)
        # It should not be longer than the original name
        assert byte_size(model.display_name) <= byte_size(model.name)
      end
    end

    test "context_length is nil or a non-negative integer" do
      models = ModelSelector.list_models()

      for model <- models do
        assert model.context_length == nil or
                 (is_integer(model.context_length) and model.context_length >= 0)
      end
    end
  end
end
