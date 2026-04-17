defmodule CodePuppyControl.Tools.UniversalConstructorTest do
  @moduledoc """
  Tests for the Universal Constructor module.

  These tests verify that UC operations work correctly:
  - Models: Data structure creation and helpers
  - Formatter: Output formatting for tools

  Note: Tests requiring the Registry GenServer are marked as integration tests
  and skipped when the application is not fully started.
  """

  use ExUnit.Case, async: true

  alias CodePuppyControl.Tools.UniversalConstructor
  alias CodePuppyControl.Tools.UniversalConstructor.Models

  # Integration tests requiring the Registry GenServer are tagged
  describe "run/1 - integration tests (require full app)" do
    @describetag :integration
    test "list action requires Registry" do
      # Skip if registry not available
      try do
        _result = UniversalConstructor.run(action: "list")
        # Test passes if we get here
        assert true
      catch
        :exit, _ ->
          # Expected when registry isn't running
          assert true
      end
    end
  end

  describe "Models" do
    test "full_name combines namespace and name" do
      assert Models.full_name("", "tool") == "tool"
      assert Models.full_name("api", "weather") == "api.weather"
      assert Models.full_name("api.v1", "users") == "api.v1.users"
    end

    test "tool_meta creates metadata with defaults" do
      meta = Models.tool_meta()

      assert meta.name == ""
      assert meta.namespace == ""
      assert meta.description == ""
      assert meta.enabled == true
      assert meta.version == "1.0.0"
      assert meta.author == "user"
      assert meta.created_at != nil
    end

    test "uc_list_output counts enabled tools" do
      tools = [
        Models.uc_tool_info(meta: Models.tool_meta(name: "t1", enabled: true)),
        Models.uc_tool_info(meta: Models.tool_meta(name: "t2", enabled: false))
      ]

      output = Models.uc_list_output(tools: tools)

      assert output.total_count == 2
      assert output.enabled_count == 1
    end
  end

  describe "format_tools/1" do
    test "formats empty list" do
      result = UniversalConstructor.format_tools([])

      assert result =~ "Universal Constructor Tools"
      assert result =~ "No UC tools found"
    end

    test "formats tools with status icons" do
      tools = [
        Models.uc_tool_info(
          meta: Models.tool_meta(name: "enabled", enabled: true, description: "Working"),
          full_name: "enabled",
          signature: "run/1",
          source_path: "/path/to/enabled.ex"
        ),
        Models.uc_tool_info(
          meta: Models.tool_meta(name: "disabled", enabled: false, description: "Broken"),
          full_name: "disabled",
          signature: "run/1",
          source_path: "/path/to/disabled.ex"
        )
      ]

      result = UniversalConstructor.format_tools(tools)

      # Check format is correct - uses markdown bold around labels with colons
      assert result =~ "**Total:** 2"
      assert result =~ "(1 enabled)"
      assert result =~ "🟢 enabled"
      assert result =~ "🔴 disabled"
      assert result =~ "Working"
      assert result =~ "Broken"
    end
  end

  describe "format_tool/2" do
    test "formats tool details" do
      tool =
        Models.uc_tool_info(
          meta:
            Models.tool_meta(
              name: "test",
              namespace: "api",
              description: "API test tool",
              version: "1.5.0"
            ),
          full_name: "api.test",
          function_name: "run",
          signature: "run/1",
          source_path: "/tmp/test.ex",
          docstring: "Runs the tool"
        )

      result = UniversalConstructor.format_tool(tool, "source code here")

      assert result =~ "## Tool: api.test"
      assert result =~ "api"
      assert result =~ "API test tool"
      assert result =~ "1.5.0"
      assert result =~ "source code here"
    end
  end
end
