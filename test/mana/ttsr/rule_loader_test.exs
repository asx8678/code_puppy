defmodule Mana.TTSR.RuleLoaderTest do
  use ExUnit.Case, async: true

  alias Mana.TTSR.{Rule, RuleLoader}

  defp temp_file do
    Path.join(System.tmp_dir!(), "mana_ttsr_#{System.unique_integer([:positive])}.md")
  end

  defp temp_dir do
    dir = Path.join(System.tmp_dir!(), "mana_ttsr_dir_#{System.unique_integer([:positive])}")
    File.mkdir_p!(dir)
    dir
  end

  describe "parse_file/1" do
    test "parses valid markdown with YAML frontmatter" do
      tmp_path = temp_file()

      content = """
      ---
      name: error-watcher
      trigger: "error|exception"
      scope: text
      repeat: once
      ---

      When you see an error, check the logs for more information.
      """

      File.write!(tmp_path, content)

      try do
        rule = RuleLoader.parse_file(tmp_path)
        assert %Rule{} = rule
        assert rule.name == "error-watcher"
        assert rule.scope == :text
        assert rule.repeat == :once
        assert Regex.match?(rule.trigger, "error")
        assert Regex.match?(rule.trigger, "exception")
        assert rule.content =~ "check the logs"
        assert rule.source == tmp_path
      after
        File.rm(tmp_path)
      end
    end

    test "defaults scope to :text when not specified" do
      tmp_path = temp_file()

      content = """
      ---
      trigger: "test"
      ---

      Test content.
      """

      File.write!(tmp_path, content)

      try do
        rule = RuleLoader.parse_file(tmp_path)
        assert rule.scope == :text
      after
        File.rm(tmp_path)
      end
    end

    test "defaults repeat to :once when not specified" do
      tmp_path = temp_file()

      content = """
      ---
      trigger: "test"
      ---

      Test content.
      """

      File.write!(tmp_path, content)

      try do
        rule = RuleLoader.parse_file(tmp_path)
        assert rule.repeat == :once
      after
        File.rm(tmp_path)
      end
    end

    test "parses different scopes" do
      for {scope_str, scope_atom} <- [{"thinking", :thinking}, {"tool", :tool}, {"all", :all}] do
        tmp_path = temp_file()

        content = """
        ---
        trigger: "test"
        scope: #{scope_str}
        ---

        Test content.
        """

        File.write!(tmp_path, content)

        try do
          rule = RuleLoader.parse_file(tmp_path)
          assert rule.scope == scope_atom
        after
          File.rm(tmp_path)
        end
      end
    end

    test "parses gap repeat format" do
      tmp_path = temp_file()

      content = """
      ---
      trigger: "test"
      repeat: gap:5
      ---

      Test content.
      """

      File.write!(tmp_path, content)

      try do
        rule = RuleLoader.parse_file(tmp_path)
        assert rule.repeat == {:gap, 5}
      after
        File.rm(tmp_path)
      end
    end

    test "parses 'always' as gap:0" do
      tmp_path = temp_file()

      content = """
      ---
      trigger: "test"
      repeat: always
      ---

      Test content.
      """

      File.write!(tmp_path, content)

      try do
        rule = RuleLoader.parse_file(tmp_path)
        assert rule.repeat == {:gap, 0}
      after
        File.rm(tmp_path)
      end
    end

    test "returns nil for file without frontmatter" do
      tmp_path = temp_file()

      content = "Just some content without frontmatter."

      File.write!(tmp_path, content)

      try do
        assert RuleLoader.parse_file(tmp_path) == nil
      after
        File.rm(tmp_path)
      end
    end

    test "returns nil for file without trigger" do
      tmp_path = temp_file()

      content = """
      ---
      name: no-trigger
      ---

      This has no trigger.
      """

      File.write!(tmp_path, content)

      try do
        assert RuleLoader.parse_file(tmp_path) == nil
      after
        File.rm(tmp_path)
      end
    end

    test "returns nil for non-existent file" do
      assert RuleLoader.parse_file("/nonexistent/path/rule.md") == nil
    end

    test "uses filename as name when name not specified" do
      tmp_path = Path.join(System.tmp_dir!(), "my_awesome_rule.md")

      content = """
      ---
      trigger: "test"
      ---

      Test content.
      """

      File.write!(tmp_path, content)

      try do
        rule = RuleLoader.parse_file(tmp_path)
        assert rule.name == "my_awesome_rule"
      after
        File.rm(tmp_path)
      end
    end
  end

  describe "load_from_dir/1" do
    test "loads all .md files from directory" do
      tmp_dir = temp_dir()

      try do
        # Create a couple of rule files
        File.write!(Path.join(tmp_dir, "rule1.md"), """
        ---
        trigger: "one"
        ---
        Content one.
        """)

        File.write!(Path.join(tmp_dir, "rule2.md"), """
        ---
        trigger: "two"
        ---
        Content two.
        """)

        # Create a non-.md file (should be ignored)
        File.write!(Path.join(tmp_dir, "not_a_rule.txt"), "Not a rule.")

        rules = RuleLoader.load_from_dir(tmp_dir)
        assert length(rules) == 2

        triggers = Enum.map(rules, & &1.trigger)
        assert Enum.any?(triggers, &Regex.match?(&1, "one"))
        assert Enum.any?(triggers, &Regex.match?(&1, "two"))
      after
        File.rm_rf(tmp_dir)
      end
    end

    test "returns empty list for non-existent directory" do
      assert RuleLoader.load_from_dir("/nonexistent/dir") == []
    end

    test "returns empty list for empty directory" do
      tmp_dir = temp_dir()

      try do
        assert RuleLoader.load_from_dir(tmp_dir) == []
      after
        File.rm_rf(tmp_dir)
      end
    end
  end
end
