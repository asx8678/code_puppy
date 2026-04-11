"""Tests for code_skeleton plugin (ADOPT from Agentless)."""


from code_puppy.plugins.code_skeleton.skeleton import (
    _skeleton_via_regex,
    get_skeleton,
    get_skeleton_for_file,
)


class TestSkeletonViaRegex:
    """Test regex-based skeleton generation (fallback path)."""

    def test_python_class_with_methods(self):
        """Python class → signatures + ... bodies."""
        code = (
            "class Calculator:\n"
            "    def add(self, a, b):\n"
            "        return a + b\n"
            "\n"
            "    def multiply(self, a, b):\n"
            "        result = a * b\n"
            "        return result\n"
        )
        skeleton = _skeleton_via_regex(code)
        assert "class Calculator:" in skeleton
        assert "def add(self, a, b):" in skeleton
        assert "def multiply(self, a, b):" in skeleton
        assert "..." in skeleton
        assert "return a + b" not in skeleton
        assert "result = a * b" not in skeleton

    def test_python_function(self):
        """Standalone function → signature + ..."""
        code = (
            "def hello(name):\n"
            "    greeting = f'Hello, {name}!'\n"
            "    print(greeting)\n"
            "    return greeting\n"
        )
        skeleton = _skeleton_via_regex(code)
        assert "def hello(name):" in skeleton
        assert "..." in skeleton
        assert "greeting" not in skeleton

    def test_async_function(self):
        """async def detected as scope."""
        code = (
            "async def fetch_data(url):\n"
            "    response = await client.get(url)\n"
            "    return response.json()\n"
        )
        skeleton = _skeleton_via_regex(code)
        assert "async def fetch_data(url):" in skeleton
        assert "..." in skeleton
        assert "await" not in skeleton

    def test_top_level_constants_kept(self):
        """Top-level UPPER_CASE assignments are preserved."""
        code = (
            "MAX_RETRIES = 5\n"
            "DEFAULT_TIMEOUT = 30\n"
            "\n"
            "def process():\n"
            "    return MAX_RETRIES\n"
        )
        skeleton = _skeleton_via_regex(code)
        assert "MAX_RETRIES = 5" in skeleton
        assert "DEFAULT_TIMEOUT = 30" in skeleton
        assert "def process():" in skeleton

    def test_imports_kept(self):
        """Import statements are preserved."""
        code = (
            "import os\n"
            "from pathlib import Path\n"
            "\n"
            "def main():\n"
            "    path = Path('.')\n"
            "    return path\n"
        )
        skeleton = _skeleton_via_regex(code)
        assert "import os" in skeleton
        assert "from pathlib import Path" in skeleton

    def test_nested_class_methods(self):
        """Nested method bodies replaced, class structure kept."""
        code = (
            "class Outer:\n"
            "    class Inner:\n"
            "        def method(self):\n"
            "            x = 1\n"
            "            y = 2\n"
            "            return x + y\n"
        )
        skeleton = _skeleton_via_regex(code)
        assert "class Outer:" in skeleton
        assert "class Inner:" in skeleton
        assert "def method(self):" in skeleton
        assert "x = 1" not in skeleton

    def test_rust_fn_and_impl(self):
        """Rust fn and impl keywords detected."""
        code = (
            "impl MyStruct {\n"
            "    pub fn process(&self) -> Result<()> {\n"
            "        let data = self.load()?;\n"
            "        Ok(data)\n"
            "    }\n"
            "}\n"
        )
        skeleton = _skeleton_via_regex(code)
        assert "impl MyStruct {" in skeleton
        assert "pub fn process" in skeleton

    def test_go_func(self):
        """Go func keyword detected."""
        code = (
            "func main() {\n"
            "    fmt.Println(\"hello\")\n"
            "}\n"
        )
        skeleton = _skeleton_via_regex(code)
        assert "func main() {" in skeleton
        assert "Println" not in skeleton

    def test_empty_content(self):
        """Empty content → empty skeleton."""
        assert _skeleton_via_regex("") == ""
        assert _skeleton_via_regex("   \n  \n") == ""


class TestGetSkeleton:
    """Test the main get_skeleton API."""

    def test_with_path_detection(self):
        """Language detected from file path."""
        code = "def hello():\n    return 1\n"
        skeleton = get_skeleton(code, path="example.py")
        assert "def hello():" in skeleton

    def test_empty_content(self):
        """Empty content returns empty string."""
        assert get_skeleton("") == ""
        assert get_skeleton("   ") == ""

    def test_max_lines_cap(self):
        """max_lines truncates output."""
        code = "\n".join(f"def func_{i}():\n    pass\n" for i in range(20))
        skeleton = get_skeleton(code, path="big.py", max_lines=5)
        lines = skeleton.splitlines()
        assert len(lines) <= 6  # 5 + trailing "..."
        assert lines[-1] == "..."

    def test_explicit_language_override(self):
        """Explicit language overrides path detection."""
        code = "def hello():\n    return 1\n"
        # Even with .txt extension, explicit language works
        skeleton = get_skeleton(code, path="readme.txt", language="python")
        # Falls back to regex since turbo_parse may not be available
        assert "def hello():" in skeleton


class TestGetSkeletonForFile:
    """Test file-based skeleton generation."""

    def test_reads_file_and_generates(self, tmp_path):
        """Reads a file and generates skeleton."""
        test_file = tmp_path / "example.py"
        test_file.write_text(
            "class Greeter:\n"
            "    def greet(self, name):\n"
            "        return f'Hello, {name}!'\n"
        )
        skeleton = get_skeleton_for_file(str(test_file))
        assert "class Greeter:" in skeleton
        assert "def greet" in skeleton

    def test_nonexistent_file(self):
        """Nonexistent file returns empty string (no crash)."""
        result = get_skeleton_for_file("/nonexistent/path/file.py")
        assert result == ""

    def test_binary_file_handled(self, tmp_path):
        """Binary file doesn't crash (errors='replace')."""
        test_file = tmp_path / "binary.py"
        test_file.write_bytes(b"\x00\x01\x02\x03")
        result = get_skeleton_for_file(str(test_file))
        assert isinstance(result, str)  # Should not crash


class TestContextCommand:
    """Test /context command that uses inject_scope_context."""

    def test_context_command_with_python_file(self, tmp_path):
        """Context command shows enclosing scope for a code fragment."""
        test_file = tmp_path / "example.py"
        test_file.write_text(
            "class Calculator:\n"
            "    def add(self, a, b):\n"
            "        return a + b\n"
            "\n"
            "    def multiply(self, a, b):\n"
            "        result = a * b\n"
            "        return result\n"
        )

        from code_puppy.plugins.code_skeleton.register_callbacks import (
            _handle_context_command,
        )

        result = _handle_context_command(f"/context {test_file} 3 3", "context")
        assert result is not None
        assert "Calculator" in result  # scope context
        assert "add" in result  # scope context
        assert "return a + b" in result  # actual line

    def test_context_command_wrong_name(self):
        """Returns None for non-context commands."""
        from code_puppy.plugins.code_skeleton.register_callbacks import (
            _handle_context_command,
        )

        assert _handle_context_command("/other test", "other") is None

    def test_context_command_missing_args(self):
        """Returns usage string when args missing."""
        from code_puppy.plugins.code_skeleton.register_callbacks import (
            _handle_context_command,
        )

        result = _handle_context_command("/context", "context")
        assert "Usage" in result

    def test_context_command_nonexistent_file(self):
        """Returns error for nonexistent file."""
        from code_puppy.plugins.code_skeleton.register_callbacks import (
            _handle_context_command,
        )

        result = _handle_context_command("/context /nonexistent 1 5", "context")
        assert "Error" in result
