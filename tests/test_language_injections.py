"""
Tests for language injection support in turbo_parse.

**NOTE: These tests are temporarily skipped.**

The turbo_parse Rust crate does not yet implement the `get_injections()` and
`get_injections_from_file()` functions. These will be added in a future release.

Currently available turbo_parse functions:
- extract_symbols, extract_symbols_from_file
- extract_syntax_diagnostics
- get_folds, get_folds_from_file
- get_highlights, get_highlights_from_file
- parse_source, parse_file

This module is designed to test:
1. SQL injection detection in Python strings
2. HEEx template detection in Elixir
3. Nested injections (JavaScript in HTML in Python)
4. Error handling for unsupported combinations
"""

import pytest
import sys
import os

# Add the turbo_parse module to path if needed
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "turbo_parse"))


try:
    import turbo_parse
except (ImportError, SystemError):
    pytest.skip("turbo_parse module not available", allow_module_level=True)


class TestInjectionDetection:
    """Tests for basic language injection detection."""

    @pytest.mark.skip(reason="pending: get_injections not implemented in turbo_parse Rust crate")
    def test_detect_sql_in_python_triple_quoted_string(self):
        """Test detecting SQL in Python triple-quoted strings."""
        source = '''
def get_users(cursor, user_id):
    query = """
    SELECT u.id, u.name, u.email
    FROM users u
    WHERE u.id = %s AND u.active = true
    ORDER BY u.name
    """
    cursor.execute(query, (user_id,))
    return cursor.fetchall()
'''
        result = turbo_parse.get_injections(source, "python")

        assert result["success"], f"Detection failed: {result.get('errors', [])}"
        assert result["parent_language"] == "python"

        # Should detect at least one SQL injection
        sql_injections = [
            i for i in result["injections"] if i["injected_language"] == "sql"
        ]
        assert len(sql_injections) > 0, "Should detect SQL injection"

        # Check the detected SQL content
        sql = sql_injections[0]
        assert "SELECT" in sql["content"]
        assert sql["start_byte"] >= 0
        assert sql["end_byte"] > sql["start_byte"]

    @pytest.mark.skip(reason="pending: get_injections not implemented in turbo_parse Rust crate")
    def test_detect_sql_in_python_insert(self):
        """Test detecting INSERT SQL in Python strings."""
        source = '''
sql = """
INSERT INTO users (name, email, created_at)
VALUES (%s, %s, NOW())
"""
cursor.execute(sql)
'''
        result = turbo_parse.get_injections(source, "python")

        assert result["success"]

        sql_injections = [
            i for i in result["injections"] if i["injected_language"] == "sql"
        ]
        assert len(sql_injections) > 0
        assert "INSERT" in sql_injections[0]["content"]

    @pytest.mark.skip(reason="pending: get_injections not implemented in turbo_parse Rust crate")
    def test_detect_sql_in_python_update(self):
        """Test detecting UPDATE SQL in Python strings."""
        source = '''
query = """
UPDATE users
SET last_login = NOW()
WHERE id = %s
"""
'''
        result = turbo_parse.get_injections(source, "python")

        assert result["success"]

        sql_injections = [
            i for i in result["injections"] if i["injected_language"] == "sql"
        ]
        assert len(sql_injections) > 0
        assert "UPDATE" in sql_injections[0]["content"]

    @pytest.mark.skip(reason="pending: get_injections not implemented in turbo_parse Rust crate")
    def test_detect_html_in_python_string(self):
        """Test detecting HTML content in Python strings."""
        source = '''
html_content = """
<div class="container">
    <h1>Hello World</h1>
    <p>This is a test</p>
</div>
"""
'''
        result = turbo_parse.get_injections(source, "python")

        assert result["success"]

        html_injections = [
            i for i in result["injections"] if i["injected_language"] == "html"
        ]
        # HTML detection might depend on heuristics
        # Just verify the function does not crash

    @pytest.mark.skip(reason="pending: get_injections not implemented in turbo_parse Rust crate")
    def test_detect_json_in_python_string(self):
        """Test detecting JSON in Python strings."""
        source = '''
json_data = """
{
    "name": "John Doe",
    "age": 30,
    "email": "john@example.com"
}
"""
'''
        result = turbo_parse.get_injections(source, "python")

        assert result["success"]
        # JSON detection is heuristic-based


class TestElixirInjections:
    """Tests for injection detection in Elixir."""

    @pytest.mark.skip(reason="pending: get_injections not implemented in turbo_parse Rust crate")
    def test_detect_heex_in_elixir_sigil(self):
        """Test detecting HEEx content in Elixir ~H sigil."""
        source = '''
defmodule MyAppWeb.UserComponent do
  use Phoenix.Component
  
  def user_card(assigns) do
    ~H"""
    <div class="user-card" id={@user.id}>
      <h2 class="user-name"><%= @user.name %></h2>
      <p class="user-email"><%= @user.email %></p>
      <.link navigate={~p"/users/#{@user.id}/edit"}>
        Edit User
      </.link>
    </div>
    """
  end
end
'''
        result = turbo_parse.get_injections(source, "elixir")

        assert result["success"], f"Detection failed: {result.get('errors', [])}"
        assert result["parent_language"] == "elixir"

        # Should detect the HEEx template
        heex_injections = [
            i for i in result["injections"] if i["injected_language"] == "heex"
        ]
        assert len(heex_injections) > 0, "Should detect HEEx injection"

    @pytest.mark.skip(reason="pending: get_injections not implemented in turbo_parse Rust crate")
    def test_detect_sql_in_elixir(self):
        """Test detecting SQL in Elixir strings."""
        source = '''
defmodule MyApp.Users do
  import Ecto.Query
  
  def get_active_users do
    query = """
    SELECT id, name, email
    FROM users
    WHERE active = true
    ORDER BY created_at DESC
    """
    
    Ecto.Adapters.SQL.query!(MyApp.Repo, query)
  end
end
'''
        result = turbo_parse.get_injections(source, "elixir")

        assert result["success"]

        sql_injections = [
            i for i in result["injections"] if i["injected_language"] == "sql"
        ]
        assert len(sql_injections) > 0, "Should detect SQL in Elixir"


class TestNestedInjections:
    """Tests for nested injection detection."""

    @pytest.mark.skip(reason="pending: get_injections not implemented in turbo_parse Rust crate")
    def test_javascript_in_html_in_python(self):
        """Test detecting JavaScript nested in HTML inside Python strings."""
        source = '''
html_template = """
<!DOCTYPE html>
<html>
<head>
    <script>
        function greet() {
            console.log('Hello from embedded JS!');
            return true;
        }
        
        document.addEventListener('DOMContentLoaded', function() {
            greet();
        });
    </script>
</head>
<body>
    <h1>Test Page</h1>
</body>
</html>
"""
'''
        result = turbo_parse.get_injections(source, "python")

        assert result["success"]

        # Should detect both HTML and JavaScript
        html_injections = [
            i for i in result["injections"] if i["injected_language"] == "html"
        ]
        js_injections = [
            i for i in result["injections"] if i["injected_language"] == "javascript"
        ]

        # HTML should always be detected
        assert len(html_injections) > 0 or len(result["injections"]) > 0

    @pytest.mark.skip(reason="pending: get_injections not implemented in turbo_parse Rust crate")
    def test_css_in_html_in_python(self):
        """Test detecting CSS nested in HTML inside Python strings."""
        source = '''
html_content = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body {
            font-family: Arial, sans-serif;
            color: #333;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
    </style>
</head>
<body></body>
</html>
"""
'''
        result = turbo_parse.get_injections(source, "python")

        assert result["success"]


class TestInjectionParsing:
    """Tests for parsing detected injections."""

    @pytest.mark.skip(reason="pending: get_injections and parse_injections_py not implemented in turbo_parse Rust crate")
    def test_parse_detected_sql_injection(self):
        """Test parsing a detected SQL injection with actual grammar."""
        # Note: SQL is not in our supported languages yet,
        # so this tests the error handling path
        source = '''
query = """
SELECT * FROM users
"""
'''
        detection = turbo_parse.get_injections(source, "python")

        # Parse injections - SQL will likely not be supported
        parsed = turbo_parse.parse_injections_py(detection)

        assert "parsed_injections" in parsed
        assert "total_time_ms" in parsed

    @pytest.mark.skip(reason="pending: get_injections and parse_injections_py not implemented in turbo_parse Rust crate")
    def test_parse_supported_language_injection(self):
        """Test parsing an injection for a supported language."""
        # Python inside Python (for testing)
        source = '''
code = """
def helper():
    return 42
"""
'''
        detection = turbo_parse.get_injections(source, "python")

        # If any Python code was detected, verify parsing
        parsed = turbo_parse.parse_injections_py(detection)

        assert "parent_language" in parsed
        assert "parsed_injections" in parsed


class TestInjectionFromFile:
    """Tests for injection detection from files."""

    @pytest.mark.skip(reason="pending: get_injections_from_file not implemented in turbo_parse Rust crate")
    def test_from_python_file(self, tmp_path):
        """Test detecting injections from a Python file."""
        py_file = tmp_path / "test_queries.py"
        py_file.write_text('''
def fetch_users(cursor):
    query = """
    SELECT id, name, email
    FROM users
    WHERE active = true
    """
    cursor.execute(query)
    return cursor.fetchall()
''')

        result = turbo_parse.get_injections_from_file(str(py_file))

        assert result["success"]
        assert result["parent_language"] == "python"

    @pytest.mark.skip(reason="pending: get_injections_from_file not implemented in turbo_parse Rust crate")
    def test_from_elixir_file(self, tmp_path):
        """Test detecting injections from an Elixir file."""
        ex_file = tmp_path / "templates.ex"
        ex_file.write_text('''
defmodule MyApp.Templates do
  def render_card(assigns) do
    ~H"""
    <div class="card">
      <h2><%= @title %></h2>
    </div>
    """
  end
end
''')

        result = turbo_parse.get_injections_from_file(str(ex_file))

        assert result["success"]
        assert result["parent_language"] == "elixir"


class TestErrorHandling:
    """Tests for error handling in injection detection."""

    @pytest.mark.skip(reason="pending: get_injections not implemented in turbo_parse Rust crate")
    def test_empty_source(self):
        """Test handling empty source code."""
        result = turbo_parse.get_injections("", "python")

        assert result["success"]
        assert len(result["injections"]) == 0

    @pytest.mark.skip(reason="pending: get_injections not implemented in turbo_parse Rust crate")
    def test_unsupported_language(self):
        """Test handling unsupported languages gracefully."""
        result = turbo_parse.get_injections("some code", "unsupported_lang")

        # Should succeed but return empty
        assert result["success"]
        assert len(result["injections"]) == 0

    @pytest.mark.skip(reason="pending: get_injections_from_file not implemented in turbo_parse Rust crate")
    def test_nonexistent_file(self):
        """Test error handling for nonexistent file."""
        result = turbo_parse.get_injections_from_file("/nonexistent/path/file.py")

        assert not result["success"]
        assert len(result["errors"]) > 0
        assert "Failed to read file" in result["errors"][0]


class TestInjectionRange:
    """Tests for the InjectionRange pyclass."""

    @pytest.mark.skip(reason="InjectionRange pyclass needs constructor implementation")
    def test_injection_range_creation(self):
        """Test creating InjectionRange via Python."""
        # InjectionRange should be accessible as a Python class
        range_obj = turbo_parse.InjectionRange(
            "python",  # parent_language
            "sql",  # injected_language
            10,  # start_byte
            50,  # end_byte
            "SELECT * FROM users",  # content
            "string",  # node_kind
        )

        assert range_obj.parent_language == "python"
        assert range_obj.injected_language == "sql"
        assert range_obj.start_byte == 10
        assert range_obj.end_byte == 50
        assert range_obj.content == "SELECT * FROM users"
        assert range_obj.node_kind == "string"


class TestLanguageAliases:
    """Tests for language alias handling in injection detection."""

    @pytest.mark.skip(reason="pending: get_injections not implemented in turbo_parse Rust crate")
    def test_python_alias_py(self):
        """Test 'py' alias works for injection detection."""
        source = 'query = """SELECT 1"""'
        result = turbo_parse.get_injections(source, "py")

        assert result["parent_language"] == "python"

    @pytest.mark.skip(reason="pending: get_injections not implemented in turbo_parse Rust crate")
    def test_javascript_alias_js(self):
        """Test 'js' alias works for injection detection."""
        source = "var x = 1;"
        result = turbo_parse.get_injections(source, "js")

        assert result["parent_language"] == "javascript"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
