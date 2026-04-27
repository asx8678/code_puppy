defmodule CodePuppyControl.Tools.UniversalConstructor.PathTraversalTest do
  @moduledoc """
  Regression tests for code_puppy-mmk.2: path-traversal and atom-safety hardening
  in Universal Constructor CreateAction and Validator.

  These tests verify that:
  1. Path traversal via tool_name, namespace, or metadata is blocked
  2. Absolute paths are rejected
  3. Containment checks prevent escape from UC tools directory
  4. Arbitrary UC tool names do not create atoms
  """

  use ExUnit.Case, async: true

  alias CodePuppyControl.Tools.UniversalConstructor.CreateAction
  alias CodePuppyControl.Tools.UniversalConstructor.Validator

  # ==========================================================================
  # Safe-Identifier Validation (CreateAction.validate_safe_identifier/1)
  # ==========================================================================

  describe "validate_safe_identifier/1 — path-traversal blocking (code_puppy-mmk.2)" do
    test "rejects parent-directory traversal '..'" do
      assert {:error, msg} = CreateAction.validate_safe_identifier("../evil")
      # May be caught by '/' or '..' check — both are path-traversal vectors
      assert msg =~ ".." or msg =~ "/"
    end

    test "rejects double parent-directory traversal" do
      assert {:error, _} = CreateAction.validate_safe_identifier("../../evil")
    end

    test "rejects forward slash" do
      assert {:error, msg} = CreateAction.validate_safe_identifier("namespace/evil")
      assert msg =~ "/"
    end

    test "rejects backslash" do
      assert {:error, msg} = CreateAction.validate_safe_identifier("namespace\\evil")
      assert msg =~ "\\"
    end

    test "rejects absolute Unix path" do
      assert {:error, _} = CreateAction.validate_safe_identifier("/etc/passwd")
    end

    test "rejects empty string" do
      assert {:error, _} = CreateAction.validate_safe_identifier("")
    end

    test "rejects names starting with dot" do
      assert {:error, _} = CreateAction.validate_safe_identifier(".hidden")
    end

    test "rejects names with spaces" do
      assert {:error, _} = CreateAction.validate_safe_identifier("my tool")
    end

    test "rejects names with special shell characters" do
      assert {:error, _} = CreateAction.validate_safe_identifier("tool;rm")
      assert {:error, _} = CreateAction.validate_safe_identifier("tool$(cmd)")
      assert {:error, _} = CreateAction.validate_safe_identifier("tool`whoami`")
    end

    test "accepts simple alphanumeric names" do
      assert :ok = CreateAction.validate_safe_identifier("my_tool")
      assert :ok = CreateAction.validate_safe_identifier("tool123")
      assert :ok = CreateAction.validate_safe_identifier("Tool-Name")
    end

    test "accepts namespaced dot-separated names" do
      assert :ok = CreateAction.validate_safe_identifier("api.weather")
      assert :ok = CreateAction.validate_safe_identifier("ns.sub.tool_name")
    end

    test "accepts names with underscores and hyphens" do
      assert :ok = CreateAction.validate_safe_identifier("my_tool_v2")
      assert :ok = CreateAction.validate_safe_identifier("my-tool-v2")
    end

    test "rejects non-string input" do
      assert {:error, _} = CreateAction.validate_safe_identifier(nil)
      assert {:error, _} = CreateAction.validate_safe_identifier(123)
    end
  end

  # ==========================================================================
  # CreateAction.execute/3 — end-to-end path-traversal rejection
  # ==========================================================================

  describe "CreateAction.execute/3 — path-traversal rejection (code_puppy-mmk.2)" do
    # Code WITHOUT @uc_tool so tool_name is actually used for path construction
    @no_meta_code """
    defmodule PathTestTool do
      def run(_), do: :ok
    end
    """

    test "rejects tool_name with parent-directory traversal" do
      result =
        CreateAction.execute(
          "../evil",
          @no_meta_code,
          "Traversal test"
        )

      assert result.success == false

      assert result.error =~ ".." or result.error =~ "/" or
               result.error =~ "Identifier"
    end

    test "rejects tool_name with forward slash" do
      result =
        CreateAction.execute(
          "namespace/evil",
          @no_meta_code,
          "Traversal test"
        )

      assert result.success == false
      assert result.error =~ "/" or result.error =~ "Identifier"
    end

    test "rejects tool_name that is an absolute path" do
      result =
        CreateAction.execute(
          "/etc/passwd",
          @no_meta_code,
          "Traversal test"
        )

      assert result.success == false
    end

    test "rejects code with @uc_tool name containing traversal" do
      traversal_code = """
      defmodule TraversalTool do
        @uc_tool %{name: "../../evil", description: "Traversal"}
        def run(_), do: :ok
      end
      """

      result =
        CreateAction.execute(
          nil,
          traversal_code,
          "Traversal test"
        )

      assert result.success == false

      assert result.error =~ ".." or result.error =~ "traversal" or
               result.error =~ "Identifier"
    end

    test "rejects code with @uc_tool namespace containing traversal" do
      traversal_ns_code = """
      defmodule TraversalNSTool do
        @uc_tool %{name: "safe_name", namespace: "../evil", description: "Traversal NS"}
        def run(_), do: :ok
      end
      """

      result =
        CreateAction.execute(
          nil,
          traversal_ns_code,
          "Traversal NS test"
        )

      assert result.success == false

      assert result.error =~ ".." or result.error =~ "traversal" or
               result.error =~ "Identifier"
    end

    test "accepts safe tool name" do
      safe_code = """
      defmodule SafeTool do
        @uc_tool %{name: "safe_tool_xyz", description: "Safe"}
        def run(_), do: :ok
      end
      """

      result =
        CreateAction.execute(
          "safe_tool_xyz",
          safe_code,
          "Safe test"
        )

      # May fail due to write permissions in test, but should NOT fail
      # due to identifier validation
      unless result.success do
        # If it fails, it should NOT be about path traversal / identifier
        refute result.error =~ "traversal"
        refute result.error =~ "Identifier"
      end
    end
  end

  # ==========================================================================
  # Atom Safety (Validator.find_main_function/2)
  # ==========================================================================

  describe "Validator.find_main_function/2 — atom safety (code_puppy-mmk.2)" do
    test "arbitrary unique tool names do not create new atoms" do
      # Generate a name guaranteed not to be an atom
      unique_name = "atom_safety_test_#{:erlang.unique_integer([:positive])}"

      # Pre-check: not an atom yet
      assert_raise ArgumentError, fn -> String.to_existing_atom(unique_name) end

      functions = [
        %{name: :run, arity: 1, signature: "run/1", docstring: nil, line_number: 0}
      ]

      # Call find_main_function with the unique name — it should NOT
      # create the atom
      result = Validator.find_main_function(functions, unique_name)

      # Should fall back to :run
      assert result.name == :run

      # Post-check: the atom still doesn't exist
      assert_raise ArgumentError, fn -> String.to_existing_atom(unique_name) end
    end

    test "known existing atoms still match correctly" do
      # :run is always an existing atom
      functions = [
        %{name: :run, arity: 1, signature: "run/1", docstring: nil, line_number: 0}
      ]

      result = Validator.find_main_function(functions, "run")
      assert result.name == :run
    end
  end
end
