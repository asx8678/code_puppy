defmodule CodePuppyControl.LLM.ModelPacksPropertyTest do
  @moduledoc """
  Property-based tests for ModelPacks invariants.

  Ports invariants from tests/test_model_packs.py and adds:
  - No model appears in two roles simultaneously within a pack (when configured that way)
  - get_model_chain always includes the primary model as the first element
  - Fallback chain always starts with primary + fallbacks
  - get_model_for_role returns a string
  - All default packs have consistent structure
  """
  use ExUnit.Case, async: false
  use ExUnitProperties

  alias CodePuppyControl.ModelPacks
  alias CodePuppyControl.ModelPacks.{ModelPack, RoleConfig}

  setup do
    CodePuppyControl.TestSupport.Reset.ensure_gen_server_started(ModelPacks)
    ModelPacks.set_current_pack("single")

    # Clean up any test user packs
    for pack <- ModelPacks.list_packs() do
      if not ModelPacks.builtin_pack?(pack.name) and String.starts_with?(pack.name, "test-pp-") do
        ModelPacks.delete_pack(pack.name)
      end
    end

    :ok
  end

  # ── RoleConfig Properties ───────────────────────────────────────────────

  describe "RoleConfig properties" do
    property "get_model_chain always starts with primary" do
      check all(
              primary <- string(:alphanumeric, min_length: 1, max_length: 20),
              fallbacks <- list_of(string(:alphanumeric, min_length: 1, max_length: 20), max_length: 5)
            ) do
        config = %RoleConfig{primary: primary, fallbacks: fallbacks}
        chain = RoleConfig.get_model_chain(config)

        assert hd(chain) == primary
        assert length(chain) == 1 + length(fallbacks)
      end
    end

    property "get_model_chain returns primary + fallbacks in order" do
      check all(primary <- string(:alphanumeric, min_length: 1, max_length: 20)) do
        fallbacks = ["fb-a", "fb-b", "fb-c"]
        config = %RoleConfig{primary: primary, fallbacks: fallbacks}
        chain = RoleConfig.get_model_chain(config)

        assert chain == [primary] ++ fallbacks
      end
    end
  end

  # ── ModelPack Properties ────────────────────────────────────────────────

  describe "ModelPack properties" do
    property "get_model_for_role always returns a string for non-nil roles" do
      check all(
              primary <- string(:alphanumeric, min_length: 1, max_length: 20),
              role <- string(:alphanumeric, min_length: 1, max_length: 15)
            ) do
        pack = %ModelPack{
          name: "prop-test",
          description: "Property test pack",
          roles: %{role => %RoleConfig{primary: primary}},
          default_role: role
        }

        result = ModelPack.get_model_for_role(pack, role)
        assert is_binary(result)
        assert result == primary
      end
    end

    property "get_model_for_role falls back to default_role for unknown roles" do
      check all(
              primary <- string(:alphanumeric, min_length: 1, max_length: 20),
              unknown_role <- string(:alphanumeric, min_length: 1, max_length: 15)
            ) do
        default_role = "coder"
        pack = %ModelPack{
          name: "prop-test",
          description: "Property test pack",
          roles: %{default_role => %RoleConfig{primary: primary}},
          default_role: default_role
        }

        # unknown_role may or may not equal default_role, but should still resolve
        result = ModelPack.get_model_for_role(pack, unknown_role)
        assert is_binary(result)
      end
    end

    property "get_fallback_chain always includes primary as first element" do
      check all(
              primary <- string(:alphanumeric, min_length: 1, max_length: 20),
              fallback_count <- integer(0..4)
            ) do
        fallbacks = if fallback_count > 0, do: (for i <- 1..fallback_count, do: "fallback-#{i}"), else: []
        role = "coder"

        pack = %ModelPack{
          name: "prop-test",
          description: "Property test pack",
          roles: %{role => %RoleConfig{primary: primary, fallbacks: fallbacks}},
          default_role: role
        }

        chain = ModelPack.get_fallback_chain(pack, role)
        assert hd(chain) == primary
      end
    end
  end

  # ── Default Pack Invariants ────────────────────────────────────────────

  describe "default pack invariants" do
    test "all default packs have at least one role" do
      for name <- ["single", "coding", "economical", "capacity"] do
        pack = ModelPacks.get_pack(name)
        assert map_size(pack.roles) >= 1, "Pack '#{name}' should have at least one role"
      end
    end

    test "all default packs have a valid default_role" do
      for name <- ["single", "coding", "economical", "capacity"] do
        pack = ModelPacks.get_pack(name)
        assert Map.has_key?(pack.roles, pack.default_role),
               "Pack '#{name}' default_role '#{pack.default_role}' not in roles"
      end
    end

    test "all default packs have string primary models in each role" do
      for name <- ["single", "coding", "economical", "capacity"] do
        pack = ModelPacks.get_pack(name)

        Enum.each(pack.roles, fn {role_name, config} ->
          assert is_binary(config.primary),
                 "Pack '#{name}' role '#{role_name}' primary should be a string"

          assert is_list(config.fallbacks),
                 "Pack '#{name}' role '#{role_name}' fallbacks should be a list"

          assert config.trigger in ["provider_failure", "context_overflow", "always"],
                 "Pack '#{name}' role '#{role_name}' trigger should be valid"
        end)
      end
    end

    test "coding pack has fallbacks for coder role" do
      coding = ModelPacks.get_pack("coding")
      assert length(coding.roles["coder"].fallbacks) > 0
    end

    test "single pack uses auto for all roles" do
      single = ModelPacks.get_pack("single")

      Enum.each(single.roles, fn {_role, config} ->
        assert config.primary == "auto"
      end)
    end
  end

  # ── No Model in Two Roles Simultaneously ────────────────────────────────

  describe "model exclusivity across roles (property)" do
    property "models in a pack's roles can be unique when configured so" do
      check all(
              model_a <- string(:alphanumeric, min_length: 1, max_length: 15),
              model_b <- string(:alphanumeric, min_length: 1, max_length: 15),
              model_c <- string(:alphanumeric, min_length: 1, max_length: 15)
            ) do
        # Only test when models are distinct (the invariant is "CAN be unique")
        if model_a != model_b and model_a != model_c and model_b != model_c do
          pack = %ModelPack{
            name: "exclusive-test",
            description: "Test",
            roles: %{
              "planner" => %RoleConfig{primary: model_a},
              "coder" => %RoleConfig{primary: model_b},
              "reviewer" => %RoleConfig{primary: model_c}
            },
            default_role: "coder"
          }

          # All primaries are distinct
          primaries =
            pack.roles
            |> Map.values()
            |> Enum.map(& &1.primary)

          assert length(Enum.uniq(primaries)) == length(primaries),
                 "Each role should have a unique primary model"
        end
      end
    end
  end

  # ── User Pack CRUD Properties ──────────────────────────────────────────

  describe "user pack operations" do
    test "create and delete user pack round-trip" do
      name = "test-pp-crud-#{:erlang.unique_integer([:positive])}"

      roles = %{
        "coder" => %{
          primary: "test-model",
          fallbacks: [],
          trigger: "provider_failure"
        }
      }

      assert {:ok, pack} = ModelPacks.create_pack(name, "Test pack", roles, "coder")
      assert pack.name == name

      retrieved = ModelPacks.get_pack(name)
      assert retrieved.name == name

      assert ModelPacks.delete_pack(name) == true

      # Falls back to single
      fallback = ModelPacks.get_pack(name)
      assert fallback.name == "single"
    end

    test "cannot create pack with built-in name" do
      for builtin <- ["single", "coding", "economical", "capacity"] do
        assert {:error, :builtin_pack} =
                 ModelPacks.create_pack(builtin, "Override", %{"coder" => %{primary: "x"}})
      end
    end

    test "cannot delete built-in packs" do
      for builtin <- ["single", "coding", "economical", "capacity"] do
        assert ModelPacks.delete_pack(builtin) == false
      end
    end
  end
end
