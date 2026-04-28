defmodule CodePuppyControl.HookEngine.MatcherTest do
  use ExUnit.Case, async: true

  alias CodePuppyControl.HookEngine.Matcher

  describe "matches/3" do
    test "wildcard matches everything" do
      assert Matcher.matches("*", "any_tool", %{}) == true
    end

    test "exact tool name match" do
      assert Matcher.matches("read_file", "read_file", %{}) == true
    end

    test "case-insensitive match" do
      assert Matcher.matches("Read", "read_file", %{}) == true
    end

    test "alias match: Bash matches agent_run_shell_command" do
      assert Matcher.matches("Bash", "agent_run_shell_command", %{}) == true
    end

    test "alias match: agent_run_shell_command matches Bash" do
      assert Matcher.matches("agent_run_shell_command", "Bash", %{}) == true
    end

    test "non-matching tool name" do
      assert Matcher.matches("Unknown", "agent_run_shell_command", %{}) == false
    end

    test "nil matcher returns false" do
      assert Matcher.matches(nil, "tool", %{}) == false
    end

    test "empty matcher returns false" do
      assert Matcher.matches("", "tool", %{}) == false
    end
  end

  describe "AND (&&) matcher" do
    test "all parts must match" do
      assert Matcher.matches("Bash && .sh", "agent_run_shell_command", %{"command" => "test.sh"}) ==
               true
    end

    test "fails if one part doesn't match" do
      assert Matcher.matches("Bash && .py", "agent_run_shell_command", %{"command" => "test.sh"}) ==
               false
    end
  end

  describe "OR (||) matcher" do
    test "any part matching is enough" do
      assert Matcher.matches("Bash || .py", "read_file", %{"file_path" => "main.py"}) == true
    end

    test "file extension OR match" do
      assert Matcher.matches(".py || .ts", "read_file", %{"file_path" => "main.py"}) == true
      assert Matcher.matches(".py || .ts", "read_file", %{"file_path" => "app.ts"}) == true
      assert Matcher.matches(".py || .ts", "read_file", %{"file_path" => "app.rb"}) == false
    end
  end

  describe "file extension matching" do
    test "matches .py extension" do
      assert Matcher.matches(".py", "read_file", %{"file_path" => "main.py"}) == true
    end

    test "does not match wrong extension" do
      assert Matcher.matches(".py", "read_file", %{"file_path" => "main.ts"}) == false
    end

    test "does not match when no file path" do
      assert Matcher.matches(".py", "agent_run_shell_command", %{"command" => "echo"}) == false
    end
  end

  describe "regex pattern matching (is_regex_pattern? fix)" do
    test "^agent_.* matches tool names starting with agent_" do
      assert Matcher.matches("^agent_.*", "agent_run_shell_command", %{}) == true
    end

    test "^agent_.* does not match non-agent tool names" do
      assert Matcher.matches("^agent_.*", "read_file", %{}) == false
    end

    test ".*\\.py$ matches Python file paths" do
      assert Matcher.matches(".*\\.py$", "read_file", %{"file_path" => "/src/main.py"}) == true
    end

    test ".*\\.py$ does not match non-Python files" do
      assert Matcher.matches(".*\\.py$", "read_file", %{"file_path" => "/src/main.ts"}) == false
    end

    test "read_file|grep matches either tool name (regex OR)" do
      # Single | is regex alternation, NOT the || logical-OR matcher
      assert Matcher.matches("read_file|grep", "read_file", %{}) == true
      assert Matcher.matches("read_file|grep", "grep", %{}) == true
      assert Matcher.matches("read_file|grep", "agent_run_shell_command", %{}) == false
    end

    test "^Bash$ matches exact tool name via regex" do
      assert Matcher.matches("^Bash$", "Bash", %{}) == true
      assert Matcher.matches("^Bash$", "BashScript", %{}) == false
    end

    test "^.+_file$ matches tool names ending with _file" do
      assert Matcher.matches("^.+_file$", "read_file", %{}) == true
      assert Matcher.matches("^.+_file$", "create_file", %{}) == true
      assert Matcher.matches("^.+_file$", "agent_run", %{}) == false
    end

    test "regex with character class [ab] matches a or b" do
      assert Matcher.matches("^[ab]ash$", "Bash", %{}) == true
      assert Matcher.matches("^[ab]ash$", "bash", %{}) == true
      assert Matcher.matches("^[ab]ash$", "dash", %{}) == false
    end

    test "regex with group (read|write) matches alternatives" do
      assert Matcher.matches("^(read|write)_file$", "read_file", %{}) == true
      assert Matcher.matches("^(read|write)_file$", "write_file", %{}) == true
      assert Matcher.matches("^(read|write)_file$", "delete_file", %{}) == false
    end

    test "escaped backslash in regex: \\. matches a literal dot" do
      # \\.py$ in source is the regex \\.py$ which means: literal backslash, any-char, py, end
      # This is an uncommon but valid regex pattern
      assert Matcher.matches("\\\\.py$", "read_file", %{"file_path" => "main\\xpy"}) == true
      assert Matcher.matches("\\\\.py$", "read_file", %{"file_path" => "main.py"}) == false
    end
  end

  describe "glob/wildcard patterns (simple * only)" do
    test "Bash* matches Bash and BashScript (glob semantics)" do
      assert Matcher.matches("Bash*", "Bash", %{}) == true
      assert Matcher.matches("Bash*", "BashScript", %{}) == true
    end

    test "*Bash matches MyBash (prefix glob)" do
      assert Matcher.matches("*Bash", "MyBash", %{}) == true
      assert Matcher.matches("*Bash", "MyShell", %{}) == false
    end

    test "agent_* matches agent_ prefixed tools" do
      assert Matcher.matches("agent_*", "agent_run_shell_command", %{}) == true
      assert Matcher.matches("agent_*", "read_file", %{}) == false
    end
  end

  describe "extract_file_path/1" do
    test "extracts from file_path key" do
      assert Matcher.extract_file_path(%{"file_path" => "/tmp/test.py"}) == "/tmp/test.py"
    end

    test "extracts from path key" do
      assert Matcher.extract_file_path(%{"path" => "/tmp/test.py"}) == "/tmp/test.py"
    end

    test "returns nil for empty map" do
      assert Matcher.extract_file_path(%{}) == nil
    end

    test "falls back to scanning values" do
      assert Matcher.extract_file_path(%{"arg1" => "main.py"}) == "main.py"
    end
  end

  describe "extract_file_extension/1" do
    test "extracts .py extension" do
      assert Matcher.extract_file_extension("main.py") == ".py"
    end

    test "extracts from full path" do
      assert Matcher.extract_file_extension("/path/to/main.ts") == ".ts"
    end

    test "returns nil for no extension" do
      assert Matcher.extract_file_extension("noext") == nil
    end
  end

  describe "ReDoS protection" do
    test "rejects dangerous nested quantifier patterns" do
      # (a+)+ is a classic ReDoS pattern
      assert Matcher.matches_file_pattern(%{"file_path" => "test.py"}, "(a+)+") == false
    end

    test "rejects dangerous overlapping quantifiers" do
      assert Matcher.matches_file_pattern(%{"file_path" => "test.py"}, "(a*)*") == false
    end
  end

  describe "matches_tool/2" do
    test "case-insensitive match against name list" do
      assert Matcher.matches_tool("bash", ["Bash", "Shell"]) == true
      assert Matcher.matches_tool("bash", ["Python", "Ruby"]) == false
    end
  end

  describe "matches_file_extension/2" do
    test "matches known extensions" do
      assert Matcher.matches_file_extension(%{"file_path" => "main.py"}, [".py", ".ts"]) == true
      assert Matcher.matches_file_extension(%{"file_path" => "main.rb"}, [".py", ".ts"]) == false
    end
  end

  describe "matches_file_pattern/2" do
    test "matches file path against regex" do
      assert Matcher.matches_file_pattern(%{"file_path" => "/src/main.py"}, ".*\\.py$") == true
      assert Matcher.matches_file_pattern(%{"file_path" => "/src/main.ts"}, ".*\\.py$") == false
    end
  end
end
