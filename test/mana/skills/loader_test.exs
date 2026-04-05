defmodule Mana.Skills.LoaderTest do
  use ExUnit.Case, async: true

  alias Mana.Skills.Loader

  describe "load_from_dir/1" do
    test "returns empty list for non-existent directory" do
      assert Loader.load_from_dir("/nonexistent/path/12345") == []
    end

    test "parses SKILL.md files with YAML frontmatter" do
      # Create a temporary directory with test files
      temp_dir = System.tmp_dir!()
      test_dir = Path.join(temp_dir, "mana_test_skills_#{:erlang.unique_integer([:positive])}")
      File.mkdir_p!(test_dir)

      # Create a test SKILL.md file
      test_skill = """
      ---
      name: test-skill
      description: A test skill for unit testing
      version: 1.0.0
      author: test-author
      tags: elixir, testing
      ---

      # Test Skill

      This is the content of the test skill.
      """

      File.write!(Path.join(test_dir, "test_skill.md"), test_skill)

      # Create another skill without frontmatter (should be skipped)
      File.write!(Path.join(test_dir, "invalid.md"), "No frontmatter here")

      # Create a non-markdown file (should be ignored)
      File.write!(Path.join(test_dir, "readme.txt"), "Not a markdown file")

      # Load and verify
      skills = Loader.load_from_dir(test_dir)

      assert length(skills) == 1

      [skill] = skills
      assert skill.name == "test-skill"
      assert skill.description == "A test skill for unit testing"
      assert skill.version == "1.0.0"
      assert skill.author == "test-author"
      assert skill.tags == ["elixir", "testing"]
      assert skill.content =~ "# Test Skill"
      assert skill.source == Path.join(test_dir, "test_skill.md")

      # Cleanup
      File.rm_rf!(test_dir)
    end

    test "uses filename as name when not specified" do
      temp_dir = System.tmp_dir!()
      test_dir = Path.join(temp_dir, "mana_test_skills_#{:erlang.unique_integer([:positive])}")
      File.mkdir_p!(test_dir)

      test_skill = """
      ---
      description: Skill without explicit name
      ---

      Content here.
      """

      File.write!(Path.join(test_dir, "my_skill.md"), test_skill)

      [skill] = Loader.load_from_dir(test_dir)
      assert skill.name == "my_skill"

      File.rm_rf!(test_dir)
    end

    test "handles empty tags" do
      temp_dir = System.tmp_dir!()
      test_dir = Path.join(temp_dir, "mana_test_skills_#{:erlang.unique_integer([:positive])}")
      File.mkdir_p!(test_dir)

      test_skill = """
      ---
      name: no-tags-skill
      tags:
      ---

      Content here.
      """

      File.write!(Path.join(test_dir, "no_tags.md"), test_skill)

      [skill] = Loader.load_from_dir(test_dir)
      assert skill.tags == []

      File.rm_rf!(test_dir)
    end
  end

  describe "load/0" do
    test "loads from both user and project directories" do
      # This test verifies that load/0 combines both directories
      # In a real scenario, it would check ~/.mana/skills and ./skills
      # For testing, we verify the function runs without error
      skills = Loader.load()
      assert is_list(skills)
    end
  end
end
