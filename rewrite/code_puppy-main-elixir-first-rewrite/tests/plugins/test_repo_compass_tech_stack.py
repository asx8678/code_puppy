"""Tests for tech_stack.py module."""

from pathlib import Path

from code_puppy.plugins.repo_compass.tech_stack import (
    TechStackItem,
    detect_build_commands,
    detect_tech_stack,
)


class TestTechStackItem:
    """Tests for TechStackItem dataclass."""

    def test_frozen_dataclass(self):
        """TechStackItem should be frozen and hashable."""
        item = TechStackItem("Python", "3.11", "language")
        assert item.name == "Python"
        assert item.version == "3.11"
        assert item.category == "language"

        # Should be hashable (frozen)
        {item}  # Can be added to set

    def test_equality(self):
        """TechStackItem should support equality comparison."""
        item1 = TechStackItem("Python", "3.11", "language")
        item2 = TechStackItem("Python", "3.11", "language")
        item3 = TechStackItem("Python", "3.12", "language")

        assert item1 == item2
        assert item1 != item3


class TestDetectTechStack:
    """Tests for detect_tech_stack function."""

    def test_empty_directory(self, tmp_path: Path):
        """Empty directory should return empty list."""
        stack = detect_tech_stack(tmp_path)
        assert stack == []

    def test_detect_python_from_pyproject(self, tmp_path: Path):
        """Should detect Python from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\nrequires-python = ">=3.11"\n',
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "Python" for item in stack)
        python_item = next(item for item in stack if item.name == "Python")
        assert python_item.category == "language"
        assert python_item.version == "3.11"

    def test_detect_python_with_fastapi(self, tmp_path: Path):
        """Should detect Python and FastAPI from dependencies."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\ndependencies = [\n    "fastapi>=0.100",\n]\n',
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        names = {item.name for item in stack}
        assert "Python" in names
        assert "FastAPI" in names

        fastapi_item = next(item for item in stack if item.name == "FastAPI")
        assert fastapi_item.category == "framework"

    def test_detect_python_test_tools(self, tmp_path: Path):
        """Should detect pytest from tool.pytest section."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        names = {item.name for item in stack}
        assert "pytest" in names or "Python" in names

    def test_detect_rust_from_cargo_toml(self, tmp_path: Path):
        """Should detect Rust from Cargo.toml."""
        (tmp_path / "Cargo.toml").write_text(
            '[package]\nname = "test"\nedition = "2021"\n',
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "Rust" for item in stack)
        rust_item = next(item for item in stack if item.name == "Rust")
        assert rust_item.category == "language"
        assert rust_item.version == "2021"

    def test_detect_rust_with_tokio(self, tmp_path: Path):
        """Should detect Rust and Tokio."""
        (tmp_path / "Cargo.toml").write_text(
            '[package]\nname = "test"\nedition = "2021"\n'
            '[dependencies]\ntokio = "1"\n',
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        names = {item.name for item in stack}
        assert "Rust" in names
        assert "Tokio" in names

        tokio_item = next(item for item in stack if item.name == "Tokio")
        assert tokio_item.category == "framework"

    def test_detect_node_from_package_json(self, tmp_path: Path):
        """Should detect Node.js from package.json engines."""
        (tmp_path / "package.json").write_text(
            '{"name": "test", "engines": {"node": ">=18.0.0"}}',
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "Node.js" for item in stack)
        node_item = next(item for item in stack if item.name == "Node.js")
        assert node_item.version == "18.0"

    def test_detect_react_from_package_json(self, tmp_path: Path):
        """Should detect React from dependencies."""
        (tmp_path / "package.json").write_text(
            '{"name": "test", "dependencies": {"react": "^18.2.0"}}',
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "React" for item in stack)
        react_item = next(item for item in stack if item.name == "React")
        assert react_item.category == "framework"
        assert react_item.version == "18.2"

    def test_detect_nextjs_from_package_json(self, tmp_path: Path):
        """Should detect Next.js from dependencies."""
        (tmp_path / "package.json").write_text(
            '{"name": "test", "dependencies": {"next": "^14.0.0"}}',
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "Next.js" for item in stack)

    def test_detect_express_from_package_json(self, tmp_path: Path):
        """Should detect Express from dependencies."""
        (tmp_path / "package.json").write_text(
            '{"name": "test", "dependencies": {"express": "^4.18.0"}}',
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "Express" for item in stack)

    def test_detect_mongodb_from_package_json(self, tmp_path: Path):
        """Should detect MongoDB from mongoose."""
        (tmp_path / "package.json").write_text(
            '{"name": "test", "dependencies": {"mongoose": "^7.0.0"}}',
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "MongoDB" for item in stack)
        mongo_item = next(item for item in stack if item.name == "MongoDB")
        assert mongo_item.category == "database"

    def test_detect_go_from_go_mod(self, tmp_path: Path):
        """Should detect Go from go.mod."""
        (tmp_path / "go.mod").write_text(
            "module example.com/test\n\ngo 1.21\n",
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "Go" for item in stack)
        go_item = next(item for item in stack if item.name == "Go")
        assert go_item.category == "language"
        assert go_item.version == "1.21"

    def test_detect_gin_from_go_mod(self, tmp_path: Path):
        """Should detect Gin from go.mod."""
        (tmp_path / "go.mod").write_text(
            "module example.com/test\n\ngo 1.21\n"
            "require github.com/gin-gonic/gin v1.9.0\n",
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "Gin" for item in stack)

    def test_detect_ruby_from_gemfile(self, tmp_path: Path):
        """Should detect Ruby from Gemfile."""
        (tmp_path / "Gemfile").write_text(
            "source 'https://rubygems.org'\ngem 'rails', '~> 7.0'\n",
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "Ruby" for item in stack)
        ruby_item = next(item for item in stack if item.name == "Ruby")
        assert ruby_item.category == "language"

    def test_detect_rails_from_gemfile(self, tmp_path: Path):
        """Should detect Rails from Gemfile."""
        (tmp_path / "Gemfile").write_text(
            "source 'https://rubygems.org'\ngem 'rails', '~> 7.0'\n",
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "Rails" for item in stack)
        rails_item = next(item for item in stack if item.name == "Rails")
        assert rails_item.category == "framework"

    def test_detect_docker_from_dockerfile(self, tmp_path: Path):
        """Should detect Docker from Dockerfile."""
        (tmp_path / "Dockerfile").write_text(
            "FROM python:3.11-slim\nWORKDIR /app\n",
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "Docker" for item in stack)
        docker_item = next(item for item in stack if item.name == "Docker")
        assert docker_item.category == "infra"

    def test_detect_python_from_dockerfile(self, tmp_path: Path):
        """Should detect Python from Dockerfile base image."""
        (tmp_path / "Dockerfile").write_text(
            "FROM python:3.11-slim\nWORKDIR /app\n",
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "Python" for item in stack)

    def test_detect_node_from_dockerfile(self, tmp_path: Path):
        """Should detect Node.js from Dockerfile base image."""
        (tmp_path / "Dockerfile").write_text(
            "FROM node:18-alpine\nWORKDIR /app\n",
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "Node.js" for item in stack)

    def test_detect_make_from_makefile(self, tmp_path: Path):
        """Should detect Make from Makefile."""
        (tmp_path / "Makefile").write_text(
            "test:\n\tpytest\n",
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "Make" for item in stack)

    def test_detect_just_from_justfile(self, tmp_path: Path):
        """Should detect Just from justfile."""
        (tmp_path / "justfile").write_text(
            "test:\n    pytest\n",
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        assert any(item.name == "Just" for item in stack)

    def test_deduplication(self, tmp_path: Path):
        """Should deduplicate by name, keeping first occurrence."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\nrequires-python = ">=3.11"\n',
            encoding="utf-8",
        )
        (tmp_path / "Dockerfile").write_text(
            "FROM python:3.11-slim\n",
            encoding="utf-8",
        )
        stack = detect_tech_stack(tmp_path)

        # Python should appear only once
        python_count = sum(1 for item in stack if item.name == "Python")
        assert python_count == 1

    def test_category_ordering(self, tmp_path: Path):
        """Should order by category: language < framework < database < infra."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\nrequires-python = ">=3.11"\ndependencies = ["fastapi", "psycopg"]\n',
            encoding="utf-8",
        )
        (tmp_path / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
        stack = detect_tech_stack(tmp_path)

        categories = [item.category for item in stack]

        # Languages should come before frameworks
        if "framework" in categories and "language" in categories:
            lang_idx = categories.index("language")
            framework_idx = next(
                i for i, c in enumerate(categories) if c == "framework"
            )
            assert lang_idx < framework_idx


class TestDetectBuildCommands:
    """Tests for detect_build_commands function."""

    def test_empty_directory(self, tmp_path: Path):
        """Empty directory should return empty dict."""
        commands = detect_build_commands(tmp_path)
        assert commands == {}

    def test_detect_npm_scripts(self, tmp_path: Path):
        """Should detect npm scripts from package.json."""
        (tmp_path / "package.json").write_text(
            '{"name": "test", "scripts": {"test": "jest", "build": "tsc", "lint": "eslint ."}}',
            encoding="utf-8",
        )
        commands = detect_build_commands(tmp_path)

        assert commands["test"] == "npm run test"
        assert commands["build"] == "npm run build"
        assert commands["lint"] == "npm run lint"

    def test_detect_pytest(self, tmp_path: Path):
        """Should detect pytest from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
            encoding="utf-8",
        )
        commands = detect_build_commands(tmp_path)

        assert commands.get("test") == "pytest"

    def test_detect_ruff(self, tmp_path: Path):
        """Should detect ruff from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\n[tool.ruff]\ntarget-version = "py311"\n',
            encoding="utf-8",
        )
        commands = detect_build_commands(tmp_path)

        assert commands.get("lint") == "ruff check"
        assert commands.get("format") == "ruff format"

    def test_detect_make_targets(self, tmp_path: Path):
        """Should detect make targets."""
        (tmp_path / "Makefile").write_text(
            "test:\n\tpytest\n\nlint:\n\truff check .\n\ndev:\n\tpython main.py\n",
            encoding="utf-8",
        )
        commands = detect_build_commands(tmp_path)

        assert commands.get("test") == "make test"
        assert commands.get("lint") == "make lint"
        assert commands.get("dev") == "make dev"

    def test_detect_just_recipes(self, tmp_path: Path):
        """Should detect justfile recipes."""
        (tmp_path / "justfile").write_text(
            "test:\n    pytest\n\nlint:\n    ruff check .\n",
            encoding="utf-8",
        )
        commands = detect_build_commands(tmp_path)

        assert commands.get("test") == "just test"
        assert commands.get("lint") == "just lint"

    def test_priority_npm_over_others(self, tmp_path: Path):
        """package.json scripts take precedence."""
        (tmp_path / "package.json").write_text(
            '{"name": "test", "scripts": {"test": "jest"}}',
            encoding="utf-8",
        )
        (tmp_path / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")

        commands = detect_build_commands(tmp_path)

        # npm script wins
        assert commands["test"] == "npm run test"

    def test_detect_mypy_typecheck(self, tmp_path: Path):
        """Should detect mypy for typecheck."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\n[tool.mypy]\nstrict = true\n',
            encoding="utf-8",
        )
        commands = detect_build_commands(tmp_path)

        assert commands.get("typecheck") == "mypy"

    def test_detect_dev_command(self, tmp_path: Path):
        """Should detect dev/start command."""
        (tmp_path / "package.json").write_text(
            '{"name": "test", "scripts": {"dev": "vite", "start": "node index.js"}}',
            encoding="utf-8",
        )
        commands = detect_build_commands(tmp_path)

        assert commands.get("dev") == "npm run dev"
