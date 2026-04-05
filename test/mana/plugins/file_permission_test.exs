defmodule Mana.Plugins.FilePermissionTest do
  use ExUnit.Case

  alias Mana.Plugins.FilePermission

  describe "behaviour compliance" do
    test "implements Mana.Plugin.Behaviour" do
      behaviours = FilePermission.__info__(:attributes)[:behaviour] || []
      assert Mana.Plugin.Behaviour in behaviours
    end

    test "has required callbacks" do
      assert function_exported?(FilePermission, :name, 0)
      assert function_exported?(FilePermission, :init, 1)
      assert function_exported?(FilePermission, :hooks, 0)
      assert function_exported?(FilePermission, :terminate, 0)
    end
  end

  describe "name/0" do
    test "returns correct plugin name" do
      assert FilePermission.name() == "file_permission"
    end
  end

  describe "init/1" do
    test "initializes with default config" do
      assert {:ok, state} = FilePermission.init(%{})
      assert state.interactive == true
      assert state.log_decisions == true
    end

    test "initializes with custom config" do
      config = %{interactive: false, log_decisions: false}
      assert {:ok, state} = FilePermission.init(config)
      assert state.interactive == false
      assert state.log_decisions == false
    end

    test "loads policy at initialization" do
      assert {:ok, state} = FilePermission.init(%{})
      assert is_struct(state.policy, Mana.PolicyEngine)
    end
  end

  describe "hooks/0" do
    test "returns expected hooks" do
      hooks = FilePermission.hooks()
      assert is_list(hooks)

      hook_names = Enum.map(hooks, fn {name, _func} -> name end)
      assert :file_permission in hook_names
      assert :load_prompt in hook_names
    end

    test "hooks have callable functions" do
      hooks = FilePermission.hooks()

      Enum.each(hooks, fn {_name, func} ->
        assert is_function(func)
      end)
    end
  end

  describe "check_permission/6" do
    setup do
      state = %{
        policy: %Mana.PolicyEngine{
          rules: [
            %{
              pattern: ".*\\.secret",
              tool: "file_read",
              action: :deny,
              reason: "Secret files are protected"
            },
            %{
              pattern: ".*",
              tool: :any,
              action: :allow,
              reason: "Default allow"
            }
          ],
          default_action: :ask_user
        },
        config: %{},
        interactive: false,
        log_decisions: false
      }

      {:ok, state: state}
    end

    test "allows permitted operations", %{state: state} do
      result = FilePermission.check_permission(nil, "/tmp/test.txt", :read, nil, nil, state)
      assert result == true
    end

    test "denies blocked operations", %{state: state} do
      result = FilePermission.check_permission(nil, "/tmp/config.secret", :read, nil, nil, state)
      assert result == false
    end

    test "denies when no policy loaded in non-interactive mode" do
      state = %{
        policy: nil,
        config: %{},
        interactive: false,
        log_decisions: false
      }

      # No policy + non-interactive = :ask_user -> denied (fail-closed)
      result = FilePermission.check_permission(nil, "/tmp/test.txt", :read, nil, nil, state)
      assert result == false
    end
  end

  describe "inject_policy_prompt/0" do
    test "returns a non-empty string" do
      prompt = FilePermission.inject_policy_prompt()
      assert is_binary(prompt)
      assert String.length(prompt) > 0
    end

    test "includes policy guidance keywords" do
      prompt = FilePermission.inject_policy_prompt()
      assert String.contains?(prompt, "File Operation Policy")
      assert String.contains?(prompt, "rejected")
    end
  end

  describe "terminate/0" do
    test "returns :ok" do
      assert FilePermission.terminate() == :ok
    end
  end
end
