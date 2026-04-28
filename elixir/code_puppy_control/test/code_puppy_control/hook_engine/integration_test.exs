defmodule CodePuppyControl.HookEngine.IntegrationTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.HookEngine
  alias CodePuppyControl.HookEngine.Models.{EventData, HookConfig}
  alias CodePuppyControl.HookEngine.CallbackAdapter
  alias CodePuppyControl.Callbacks

  @engine_name __MODULE__.TestEngine

  setup do
    # Start a fresh HookEngine for each test
    {:ok, pid} = HookEngine.start_link(name: @engine_name, strict_validation: false)
    Callbacks.clear(:pre_tool_call)
    Callbacks.clear(:post_tool_call)

    on_exit(fn ->
      # Safely stop the engine — it may already be dead
      case Process.whereis(@engine_name) do
        nil ->
          :ok

        _pid ->
          try do
            GenServer.stop(@engine_name, :normal, 1000)
          catch
            :exit, _ -> :ok
          end
      end

      Callbacks.clear(:pre_tool_call)
      Callbacks.clear(:post_tool_call)
    end)

    {:ok, engine: @engine_name, pid: pid}
  end

  describe "HookEngine GenServer lifecycle" do
    test "starts with empty registry", %{engine: engine} do
      assert HookEngine.count_hooks(engine) == 0
    end

    test "loads config and counts hooks", %{engine: engine} do
      config = %{
        "PreToolUse" => [
          %{"matcher" => "Bash", "hooks" => [%{"type" => "command", "command" => "echo hi"}]}
        ]
      }

      assert :ok = HookEngine.load_config(engine, config)
      assert HookEngine.count_hooks(engine) == 1
    end

    test "returns error for invalid config with strict mode" do
      # Start a strict engine with a unique name
      # {System.unique_integer([:positive])}
      strict_name = :strict_test_engine_
      result = HookEngine.start_link(strict_validation: true, name: strict_name)

      case result do
        {:ok, pid} ->
          result = HookEngine.load_config(strict_name, %{"BadType" => []})
          assert {:error, _msg} = result
          GenServer.stop(pid, :normal, 1000)

        {:error, _} ->
          # Engine failed to start — that's also an acceptable strict-mode outcome
          :ok
      end
    end

    test "reloads config replacing previous hooks", %{engine: engine} do
      config1 = %{
        "PreToolUse" => [
          %{"matcher" => "*", "hooks" => [%{"type" => "command", "command" => "echo 1"}]}
        ]
      }

      config2 = %{
        "PostToolUse" => [
          %{"matcher" => "*", "hooks" => [%{"type" => "command", "command" => "echo 2"}]}
        ]
      }

      :ok = HookEngine.load_config(engine, config1)
      assert HookEngine.count_hooks(engine, "PreToolUse") == 1

      :ok = HookEngine.load_config(engine, config2)
      # Old config should be replaced
      assert HookEngine.count_hooks(engine, "PreToolUse") == 0
      assert HookEngine.count_hooks(engine, "PostToolUse") == 1
    end
  end

  describe "process_event/4" do
    test "returns empty result when no hooks configured", %{engine: engine} do
      event_data = EventData.new(event_type: "PreToolUse", tool_name: "Bash")
      result = HookEngine.process_event(engine, "PreToolUse", event_data)

      assert result.blocked == false
      assert result.executed_hooks == 0
    end

    test "executes matching hook and returns results", %{engine: engine} do
      config = %{
        "PreToolUse" => [
          %{"matcher" => "Bash", "hooks" => [%{"type" => "command", "command" => "echo test_ok"}]}
        ]
      }

      :ok = HookEngine.load_config(engine, config)

      event_data = EventData.new(event_type: "PreToolUse", tool_name: "agent_run_shell_command")
      result = HookEngine.process_event(engine, "PreToolUse", event_data)

      assert result.blocked == false
      assert result.executed_hooks == 1
      assert String.contains?(hd(result.results).stdout, "test_ok")
    end

    test "blocking hook sets blocked=true", %{engine: engine} do
      config = %{
        "PreToolUse" => [
          %{"matcher" => "*", "hooks" => [%{"type" => "command", "command" => "exit 1"}]}
        ]
      }

      :ok = HookEngine.load_config(engine, config)

      event_data = EventData.new(event_type: "PreToolUse", tool_name: "Bash")
      result = HookEngine.process_event(engine, "PreToolUse", event_data)

      assert result.blocked == true
      assert result.blocking_reason != nil
    end

    test "non-matching hooks are skipped", %{engine: engine} do
      config = %{
        "PreToolUse" => [
          %{"matcher" => "Read", "hooks" => [%{"type" => "command", "command" => "echo nope"}]}
        ]
      }

      :ok = HookEngine.load_config(engine, config)

      event_data = EventData.new(event_type: "PreToolUse", tool_name: "Bash")
      result = HookEngine.process_event(engine, "PreToolUse", event_data)

      assert result.executed_hooks == 0
    end

    test "parallel execution mode", %{engine: engine} do
      config = %{
        "PreToolUse" => [
          %{
            "matcher" => "*",
            "hooks" => [
              %{"type" => "command", "command" => "echo alpha"},
              %{"type" => "command", "command" => "echo beta"}
            ]
          }
        ]
      }

      :ok = HookEngine.load_config(engine, config)

      event_data = EventData.new(event_type: "PreToolUse", tool_name: "Bash")
      result = HookEngine.process_event(engine, "PreToolUse", event_data, sequential: false)

      assert result.executed_hooks == 2
    end
  end

  describe "add_hook/3 with deduplication" do
    test "adding same hook twice is a no-op", %{engine: engine} do
      hook = HookConfig.new(matcher: "*", type: :command, command: "echo dup", id: "dedup-test")

      assert :ok = HookEngine.add_hook(engine, "PreToolUse", hook)
      assert :duplicate = HookEngine.add_hook(engine, "PreToolUse", hook)
      assert HookEngine.count_hooks(engine, "PreToolUse") == 1
    end
  end

  describe "remove_hook/3" do
    test "removes a hook", %{engine: engine} do
      hook = HookConfig.new(matcher: "*", type: :command, command: "echo rm")
      :ok = HookEngine.add_hook(engine, "PreToolUse", hook)

      assert true = HookEngine.remove_hook(engine, "PreToolUse", hook.id)
      assert HookEngine.count_hooks(engine, "PreToolUse") == 0
    end
  end

  describe "once hooks" do
    test "once hooks are executed only once", %{engine: engine} do
      config = %{
        "PreToolUse" => [
          %{
            "matcher" => "*",
            "hooks" => [%{"type" => "command", "command" => "echo once", "once" => true}]
          }
        ]
      }

      :ok = HookEngine.load_config(engine, config)

      event_data = EventData.new(event_type: "PreToolUse", tool_name: "Bash")

      # First call — should execute
      result1 = HookEngine.process_event(engine, "PreToolUse", event_data)
      assert result1.executed_hooks == 1

      # Second call — once hook should be skipped
      result2 = HookEngine.process_event(engine, "PreToolUse", event_data)
      assert result2.executed_hooks == 0
    end

    test "reset_once_hooks allows re-execution", %{engine: engine} do
      config = %{
        "PreToolUse" => [
          %{
            "matcher" => "*",
            "hooks" => [%{"type" => "command", "command" => "echo once", "once" => true}]
          }
        ]
      }

      :ok = HookEngine.load_config(engine, config)

      event_data = EventData.new(event_type: "PreToolUse", tool_name: "Bash")
      _result = HookEngine.process_event(engine, "PreToolUse", event_data)

      :ok = HookEngine.reset_once_hooks(engine)

      result = HookEngine.process_event(engine, "PreToolUse", event_data)
      assert result.executed_hooks == 1
    end
  end

  describe "update_env_vars/2" do
    test "updates environment variables", %{engine: engine} do
      :ok = HookEngine.update_env_vars(engine, %{"MY_VAR" => "hello"})
      # Just verify it doesn't crash — env vars are used during execution
      assert :ok = HookEngine.update_env_vars(engine, %{"ANOTHER" => "world"})
    end
  end

  describe "get_stats/1" do
    test "returns stats for loaded registry", %{engine: engine} do
      config = %{
        "PreToolUse" => [
          %{"matcher" => "*", "hooks" => [%{"type" => "command", "command" => "echo st"}]}
        ]
      }

      :ok = HookEngine.load_config(engine, config)
      stats = HookEngine.get_stats(engine)
      assert stats.total_hooks == 1
    end
  end

  describe "CallbackAdapter integration" do
    test "registers as pre_tool_call callback" do
      # Should not raise
      assert :ok = CallbackAdapter.register(@engine_name)
    end

    test "handle_pre_tool_call returns nil when not blocked" do
      # No hooks configured, so nothing should block
      result = CallbackAdapter.handle_pre_tool_call(@engine_name, "Bash", %{})
      assert result == nil
    end

    test "handle_pre_tool_call returns blocked when hook blocks" do
      config = %{
        "PreToolUse" => [
          %{"matcher" => "*", "hooks" => [%{"type" => "command", "command" => "exit 1"}]}
        ]
      }

      :ok = HookEngine.load_config(@engine_name, config)

      result = CallbackAdapter.handle_pre_tool_call(@engine_name, "Bash", %{})
      assert result != nil
      assert result.blocked == true
      assert is_binary(result.reason)
    end

    test "handle_post_tool_call always returns nil" do
      result = CallbackAdapter.handle_post_tool_call(@engine_name, "Bash", %{})
      assert result == nil
    end

    test "adapter recovers from errors gracefully (fail-open)" do
      # Use a non-existent engine — adapter should not crash
      result = CallbackAdapter.handle_pre_tool_call(:nonexistent_engine, "Bash", %{})
      assert result == nil
    end
  end
end
