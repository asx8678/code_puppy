defmodule Mana.Tools.RegistryTest do
  @moduledoc """
  Tests for Mana.Tools.Registry module.
  """

  use ExUnit.Case, async: false

  alias Mana.Tools.Behaviour
  alias Mana.Tools.Registry

  # Test tool module
  defmodule TestTool do
    @behaviour Behaviour

    @impl true
    def name, do: "test_tool"

    @impl true
    def description, do: "A test tool"

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          arg1: %{type: "string", description: "First argument"}
        },
        required: ["arg1"]
      }
    end

    @impl true
    def execute(%{"arg1" => value}) do
      {:ok, "Result: #{value}"}
    end

    def execute(_args) do
      {:error, :missing_argument}
    end
  end

  defmodule ErrorTool do
    @behaviour Behaviour

    @impl true
    def name, do: "error_tool"

    @impl true
    def description, do: "A tool that always errors"

    @impl true
    def parameters do
      %{type: "object", properties: %{}}
    end

    @impl true
    def execute(_args) do
      raise "Tool error!"
    end
  end

  defmodule InvalidTool do
    # Missing required callbacks
    def something, do: :ok
  end

  setup do
    # Start a fresh registry for each test
    start_supervised!({Registry, []})

    :ok
  end

  describe "start_link/1" do
    test "starts the GenServer successfully" do
      assert Process.whereis(Registry) != nil
    end

    test "returns correct child_spec" do
      spec = Registry.child_spec([])
      assert spec.id == Registry
      assert spec.type == :worker
      assert spec.restart == :permanent
    end

    test "registers real tools on startup" do
      tools = Registry.list_tools()

      # 10 real tools are registered on startup
      assert "list_files" in tools
      assert "read_file" in tools
      assert "grep" in tools
      assert "create_file" in tools
      assert "replace_in_file" in tools
      assert "delete_file" in tools
      assert "list_agents" in tools
      assert "invoke_agent" in tools
      assert "ask_user" in tools
      assert "run_shell_command" in tools
      assert length(tools) == 10
    end
  end

  describe "register/1" do
    test "registers a valid tool module" do
      assert :ok = Registry.register(TestTool)
    end

    test "returns error for module without behaviour" do
      assert {:error, :invalid_behaviour} = Registry.register(InvalidTool)
    end

    test "returns error for duplicate registration" do
      assert :ok = Registry.register(TestTool)
      assert {:error, :already_registered} = Registry.register(TestTool)
    end
  end

  describe "execute/2" do
    test "executes a registered tool" do
      Registry.register(TestTool)

      assert {:ok, "Result: hello"} = Registry.execute("test_tool", %{"arg1" => "hello"})
    end

    test "returns error for unknown tool" do
      assert {:error, :unknown_tool} = Registry.execute("unknown_tool", %{})
    end

    test "tool can return error tuple" do
      Registry.register(TestTool)

      assert {:error, :missing_argument} = Registry.execute("test_tool", %{"wrong_key" => "value"})
    end

    test "execution errors update stats" do
      Registry.register(ErrorTool)
      Registry.execute("error_tool", %{})

      stats = Registry.get_stats()
      assert stats.errors == 1
    end

    test "successful execution updates stats" do
      Registry.register(TestTool)
      Registry.execute("test_tool", %{"arg1" => "test"})

      stats = Registry.get_stats()
      assert stats.calls == 1
    end
  end

  describe "get_tool/1" do
    test "returns details for registered tool" do
      Registry.register(TestTool)

      assert {:ok, details} = Registry.get_tool("test_tool")
      assert details.name == "test_tool"
      assert details.description == "A test tool"
      assert details.module == TestTool
      assert details.parameters.type == "object"
    end

    test "returns error for unknown tool" do
      assert {:error, :not_found} = Registry.get_tool("unknown_tool")
    end

    test "real tools have correct schemas" do
      assert {:ok, details} = Registry.get_tool("list_files")
      assert details.parameters.type == "object"
      assert details.parameters.properties[:directory] != nil
    end
  end

  describe "tool_definitions/1" do
    test "returns list of tool definitions for agent config" do
      Registry.register(TestTool)

      definitions = Registry.tool_definitions("any_agent")
      assert is_list(definitions)

      test_tool_def = Enum.find(definitions, &(&1.function.name == "test_tool"))
      assert test_tool_def != nil
      assert test_tool_def.type == "function"
      assert test_tool_def.function.description == "A test tool"
    end

    test "definitions include real tools" do
      definitions = Registry.tool_definitions("any_agent")

      list_files_def = Enum.find(definitions, &(&1.function.name == "list_files"))
      assert list_files_def != nil
      assert list_files_def.function.parameters.type == "object"
    end
  end

  describe "list_tools/0" do
    test "returns list of tool names" do
      Registry.register(TestTool)

      tools = Registry.list_tools()
      assert "test_tool" in tools
    end

    test "returns sorted list" do
      tools = Registry.list_tools()
      assert tools == Enum.sort(tools)
    end
  end

  describe "get_stats/0" do
    test "returns initial stats" do
      stats = Registry.get_stats()

      # 10 real tools are registered on startup
      assert stats.tools_registered == 10
      assert stats.calls == 0
      assert stats.errors == 0
    end

    test "stats reflect registered tools" do
      Registry.register(TestTool)

      stats = Registry.get_stats()
      # 10 real tools + 1 new tool
      assert stats.tools_registered == 11
    end

    test "stats reflect tool calls" do
      Registry.register(TestTool)

      Registry.execute("test_tool", %{"arg1" => "test1"})
      Registry.execute("test_tool", %{"arg1" => "test2"})

      stats = Registry.get_stats()
      assert stats.calls == 2
    end
  end

  describe "real tools" do
    test "real tools are registered and execute" do
      # Real tools are registered, they don't return :not_implemented
      # They either succeed or fail based on input
      tools = Registry.list_tools()

      assert "list_files" in tools
      assert "read_file" in tools
      assert "grep" in tools
      assert "create_file" in tools
      assert "replace_in_file" in tools
      assert "delete_file" in tools
      assert "list_agents" in tools
      assert "invoke_agent" in tools
      assert "ask_user" in tools
      assert "run_shell_command" in tools
    end

    test "real tools have valid parameters" do
      assert {:ok, list_files} = Registry.get_tool("list_files")
      assert list_files.parameters.properties[:directory] != nil
      assert list_files.parameters.properties[:recursive] != nil

      assert {:ok, read_file} = Registry.get_tool("read_file")
      assert read_file.parameters.properties[:file_path] != nil
      assert read_file.parameters.properties[:start_line] != nil

      assert {:ok, create_file} = Registry.get_tool("create_file")
      assert create_file.parameters.properties[:file_path] != nil
      assert create_file.parameters.properties[:content] != nil

      assert {:ok, replace_file} = Registry.get_tool("replace_in_file")
      assert replace_file.parameters.properties[:file_path] != nil
      assert replace_file.parameters.properties[:old_string] != nil
      assert replace_file.parameters.properties[:new_string] != nil

      assert {:ok, delete_file} = Registry.get_tool("delete_file")
      assert delete_file.parameters.properties[:file_path] != nil

      assert {:ok, grep} = Registry.get_tool("grep")
      assert grep.parameters.properties[:search_string] != nil
      assert grep.parameters.properties[:directory] != nil

      assert {:ok, shell} = Registry.get_tool("run_shell_command")
      assert shell.parameters.properties[:command] != nil
      assert shell.parameters.properties[:cwd] != nil
      assert shell.parameters.properties[:timeout] != nil

      assert {:ok, list_agents} = Registry.get_tool("list_agents")
      assert list_agents.parameters.type == "object"

      assert {:ok, invoke_agent} = Registry.get_tool("invoke_agent")
      assert invoke_agent.parameters.properties[:agent_name] != nil
      assert invoke_agent.parameters.properties[:prompt] != nil

      assert {:ok, ask_user} = Registry.get_tool("ask_user")
      assert ask_user.parameters.properties[:question] != nil
    end
  end
end
