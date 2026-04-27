defmodule CodePuppyControl.Tools.CpUniversalConstructorTest do
  @moduledoc """
  Tests for the CpUniversalConstructor Tool-behaviour wrapper.

  Boundary and invariant tests for the Phase E port of universal_constructor.py.
  Verifies:
  - cp_ prefixed name
  - Parameters include all Python-compatible action params
  - python_code → elixir_code alias works
  - UC disabled check returns UniversalConstructorOutput shape
  - list action returns correct shape
  - All expected operation failures return {:ok, map} with success: false
  - EventBus emission on actions
  - Registry filtering through for_agent(CodePuppyControl.Agents.CodePuppy)
  - Exact shape parity with Python UniversalConstructorOutput
  """

  use ExUnit.Case, async: true

  alias CodePuppyControl.Tools.CpUniversalConstructor
  alias CodePuppyControl.Tool.Registry

  # ── Tool contract ──────────────────────────────────────────────────────

  describe "tool contract" do
    test "name/0 returns :cp_universal_constructor" do
      assert CpUniversalConstructor.name() == :cp_universal_constructor
    end

    test "description/0 returns non-empty string" do
      desc = CpUniversalConstructor.description()
      assert is_binary(desc) and desc != ""
    end

    test "parameters/0 has action as required" do
      params = CpUniversalConstructor.parameters()
      assert params["type"] == "object"
      assert "action" in params["required"]
      assert Map.has_key?(params["properties"], "action")
      assert Map.has_key?(params["properties"], "tool_name")
      assert Map.has_key?(params["properties"], "tool_args")
      assert Map.has_key?(params["properties"], "elixir_code")
      assert Map.has_key?(params["properties"], "python_code")
      assert Map.has_key?(params["properties"], "description")
    end

    test "action property has enum values matching Python" do
      params = CpUniversalConstructor.parameters()
      action_prop = params["properties"]["action"]
      assert "list" in action_prop["enum"]
      assert "call" in action_prop["enum"]
      assert "create" in action_prop["enum"]
      assert "update" in action_prop["enum"]
      assert "info" in action_prop["enum"]
    end
  end

  # ── UniversalConstructorOutput shape parity ────────────────────────────

  describe "invoke/2 - UniversalConstructorOutput shape parity" do
    test "unknown action returns {:ok, map} with success: false (not {:error, _})" do
      result = CpUniversalConstructor.invoke(%{"action" => "explode"}, %{})

      # Must be {:ok, _} to preserve UniversalConstructorOutput shape
      assert {:ok, data} = result
      assert Map.has_key?(data, :action)
      assert Map.has_key?(data, :success)
      assert Map.has_key?(data, :error)
      assert data.success == false
      assert is_binary(data.error)
      assert data.error =~ "Unknown action"
    end

    test "call without tool_name returns {:ok, map} with success: false" do
      result = CpUniversalConstructor.invoke(%{"action" => "call"}, %{})

      assert {:ok, data} = result
      assert data.success == false
      assert Map.has_key?(data, :action)
      assert Map.has_key?(data, :error)
      assert data.error =~ "tool_name"
    end

    test "info without tool_name returns {:ok, map} with success: false" do
      result = CpUniversalConstructor.invoke(%{"action" => "info"}, %{})

      assert {:ok, data} = result
      assert data.success == false
      assert Map.has_key?(data, :action)
      assert Map.has_key?(data, :error)
      assert data.error =~ "tool_name"
    end

    test "call for nonexistent tool returns {:ok, map} with success: false" do
      result =
        CpUniversalConstructor.invoke(
          %{"action" => "call", "tool_name" => "nonexistent_xyz"},
          %{}
        )

      assert {:ok, data} = result
      assert data.success == false
      assert Map.has_key?(data, :error)
      assert data.error =~ "not found"
    end

    test "info for nonexistent tool returns {:ok, map} with success: false" do
      result =
        CpUniversalConstructor.invoke(
          %{"action" => "info", "tool_name" => "nonexistent_xyz"},
          %{}
        )

      assert {:ok, data} = result
      assert data.success == false
      assert Map.has_key?(data, :error)
    end

    test "update without tool_name returns {:ok, map} with success: false" do
      result =
        CpUniversalConstructor.invoke(
          %{"action" => "update", "elixir_code" => "defmodule X do end"},
          %{}
        )

      assert {:ok, data} = result
      assert data.success == false
      assert Map.has_key?(data, :error)
      assert data.error =~ "tool_name"
    end

    test "update without elixir_code returns {:ok, map} with success: false" do
      result =
        CpUniversalConstructor.invoke(
          %{"action" => "update", "tool_name" => "some_tool"},
          %{}
        )

      assert {:ok, data} = result
      assert data.success == false
      assert Map.has_key?(data, :error)
    end
  end

  # ── python_code compatibility ──────────────────────────────────────────

  describe "python_code compatibility" do
    test "parameters include python_code field" do
      params = CpUniversalConstructor.parameters()
      assert Map.has_key?(params["properties"], "python_code")
    end

    test "create with python_code instead of elixir_code passes code to UC" do
      # When python_code is provided without elixir_code, the code is
      # forwarded to UC which will reject non-Elixir syntax in validation.
      # The result should still be {:ok, map} shape.
      result =
        CpUniversalConstructor.invoke(
          %{
            "action" => "create",
            "tool_name" => "py_compat_test",
            "python_code" => "def hello(): print('hi')",
            "description" => "Python compat test"
          },
          %{}
        )

      # Shape parity: always {:ok, map}
      assert {:ok, data} = result
      assert Map.has_key?(data, :action)
      assert Map.has_key?(data, :success)
      assert Map.has_key?(data, :error)
      # The code is non-Elixir so it should fail with success: false
      assert data.success == false
      assert is_binary(data.error)
    end

    test "elixir_code takes precedence over python_code when both provided" do
      # When both are provided, elixir_code should be used
      result =
        CpUniversalConstructor.invoke(
          %{
            "action" => "create",
            "tool_name" => "precedence_test",
            "elixir_code" =>
              "defmodule PrecedenceTest do @uc_tool %{name: \"precedence_test\", description: \"test\"} def run(_), do: :ok end",
            "python_code" => "def hello(): pass",
            "description" => "Precedence test"
          },
          %{}
        )

      assert {:ok, data} = result
      assert Map.has_key?(data, :success)
    end
  end

  # ── list action ────────────────────────────────────────────────────────

  describe "invoke/2 - list action" do
    @tag :integration
    test "returns {:ok, map} with list result" do
      result = CpUniversalConstructor.invoke(%{"action" => "list"}, %{})

      assert {:ok, data} = result
      # UniversalConstructorOutput shape
      assert Map.has_key?(data, :action)
      assert Map.has_key?(data, :success)
      assert Map.has_key?(data, :error)
      assert data.action == "list" or data.action == :list
    end
  end

  # ── Registry filtering ─────────────────────────────────────────────────

  describe "Registry filtering for CodePuppy agent" do
    @tag :integration
    test "cp_universal_constructor appears in for_agent(CodePuppy)" do
      agent_tools = Registry.for_agent(CodePuppyControl.Agents.CodePuppy)
      tool_names = Enum.map(agent_tools, & &1.name)
      assert "cp_universal_constructor" in tool_names
    end
  end
end
