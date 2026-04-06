defmodule Mana.Prompt.RulesTest do
  use ExUnit.Case, async: true

  alias Mana.Prompt.Rules

  describe "load/1" do
    test "returns rules block when AGENTS.md exists" do
      # The test runs in the project root where AGENTS.md exists
      result = Rules.load()

      assert result =~ "## Rules"
      assert result =~ "Contributing to Code Puppy"
    end

    test "returns empty string when AGENTS.md does not exist" do
      result = Rules.load(cwd: "/nonexistent/directory")

      assert result == ""
    end

    test "reads from specified working directory" do
      # Create a temp directory with a custom AGENTS.md
      tmp_dir = System.tmp_dir!()
      test_file = Path.join(tmp_dir, "AGENTS.md")

      File.write!(test_file, "Test rules content.")

      try do
        result = Rules.load(cwd: tmp_dir)

        assert result =~ "## Rules"
        assert result =~ "Test rules content"
      after
        File.rm(test_file)
      end
    end

    test "handles relative paths" do
      # Use the current directory (project root)
      result = Rules.load(cwd: ".")

      assert result =~ "## Rules"
    end
  end
end
