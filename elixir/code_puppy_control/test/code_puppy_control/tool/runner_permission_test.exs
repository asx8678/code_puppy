defmodule CodePuppyControl.Tool.RunnerPermissionTest do
  @moduledoc """
  Tests for Tool.Runner permission integration with FilePermission callback chain.

  Covers:
  - File tools go through FilePermission callback chain
  - Non-file tools skip FilePermission chain
  - FilePermission deny blocks tool invocation
  - FilePermission allow passes through to tool invocation
  - Callback denial produces proper error message
  """

  use CodePuppyControl.StatefulCase

  alias CodePuppyControl.Callbacks
  alias CodePuppyControl.PolicyEngine
  alias CodePuppyControl.PolicyEngine.PolicyRule
  alias CodePuppyControl.Tool.{Registry, Runner}

  # ── Test Tool Modules ─────────────────────────────────────────────────────

  defmodule TestFileTool do
    use CodePuppyControl.Tool

    @impl true
    def name, do: :create_file

    @impl true
    def description, do: "Test file creation tool"

    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "file_path" => %{"type" => "string"},
          "content" => %{"type" => "string"}
        },
        "required" => ["file_path", "content"]
      }
    end

    @impl true
    def permission_check(args, _context) do
      # Basic path validation — always ok in test
      case args do
        %{"file_path" => ""} -> {:deny, "empty path"}
        _ -> :ok
      end
    end

    @impl true
    def invoke(args, _context) do
      {:ok, %{path: args["file_path"], created: true}}
    end
  end

  defmodule TestNonFileTool do
    use CodePuppyControl.Tool

    @impl true
    def name, do: :non_file_tool

    @impl true
    def description, do: "A tool that is not file-related"

    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "message" => %{"type" => "string"}
        },
        "required" => ["message"]
      }
    end

    @impl true
    def invoke(args, _context) do
      {:ok, %{message: args["message"]}}
    end
  end

  # ── Setup ─────────────────────────────────────────────────────────────────

  setup do
    Registry.clear()
    PolicyEngine.reset()
    Callbacks.clear(:file_permission)

    Registry.register(TestFileTool)
    Registry.register(TestNonFileTool)

    on_exit(fn ->
      Registry.clear()
    end)

    :ok
  end

  describe "file tool permission integration" do
    test "file tool goes through FilePermission callback chain" do
      # Allow by policy
      PolicyEngine.add_rule(%PolicyRule{
        tool_name: "create_file",
        decision: :allow,
        priority: 10,
        source: "test"
      })

      # Register a callback that denies
      deny_cb = fn _ctx, _path, _op, _, _, _ -> false end
      Callbacks.register(:file_permission, deny_cb)

      result = Runner.invoke(:create_file, %{"file_path" => "test.txt", "content" => "hi"}, %{})
      assert {:error, reason} = result
      assert reason =~ "permission denied"
      assert reason =~ "blocked by security plugin"

      Callbacks.unregister(:file_permission, deny_cb)
    end

    test "file tool allowed when policy and callbacks both allow" do
      # Allow by policy
      PolicyEngine.add_rule(%PolicyRule{
        tool_name: "create_file",
        decision: :allow,
        priority: 10,
        source: "test"
      })

      # No blocking callbacks → should succeed
      result = Runner.invoke(:create_file, %{"file_path" => "test.txt", "content" => "hi"}, %{})
      assert {:ok, _} = result
    end

    test "PolicyEngine deny blocks file tool regardless of callbacks" do
      # Deny by policy
      PolicyEngine.add_rule(%PolicyRule{
        tool_name: "create_file",
        decision: :deny,
        priority: 10,
        source: "test"
      })

      result = Runner.invoke(:create_file, %{"file_path" => "test.txt", "content" => "hi"}, %{})
      assert {:error, reason} = result
      assert reason =~ "permission denied"
      assert reason =~ "Denied by policy"
    end
  end

  describe "non-file tool permission integration" do
    test "non-file tool skips FilePermission callback chain" do
      # Register a deny callback that would block if called
      deny_cb = fn _ctx, _path, _op, _, _, _ -> false end
      Callbacks.register(:file_permission, deny_cb)

      result = Runner.invoke(:non_file_tool, %{"message" => "hello"}, %{})
      # Should succeed — non-file tools don't go through FilePermission
      assert {:ok, _} = result

      Callbacks.unregister(:file_permission, deny_cb)
    end
  end

  describe "file tool with empty file_path" do
    test "skips FilePermission chain when no file_path in args" do
      # Allow by policy
      PolicyEngine.add_rule(%PolicyRule{
        tool_name: "create_file",
        decision: :allow,
        priority: 10,
        source: "test"
      })

      # Register a deny callback — but it shouldn't be reached (no file_path)
      deny_cb = fn _ctx, _path, _op, _, _, _ -> false end
      Callbacks.register(:file_permission, deny_cb)

      # Tool's own permission_check denies empty path first
      result = Runner.invoke(:create_file, %{"file_path" => "", "content" => "hi"}, %{})
      assert {:error, reason} = result
      assert reason =~ "permission denied"

      Callbacks.unregister(:file_permission, deny_cb)
    end
  end
end
